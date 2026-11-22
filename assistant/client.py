"""The assistant's main entry point: events -> actions (plan D1, roluri/P3 step 2).

Core calls (same process)::

    from assistant.client import handle_event
    actions = await handle_event(event, state)

Pipeline for one event:

1. **Policies** (``assistant/policies.py``): safety veto, muted, conversation, rate
   limit. Blocked -> ``[stay_silent(reason)]`` immediately, no LLM call.
2. **Deterministic events**: ``driver_refused`` never goes to the LLM (plan D10).
3. **LLM off?** No key / model, or the director switched it off
   (``safety.llm_enabled = False``, plan C6) -> fixed fallback texts.
4. **LLM call** with the state summary, streamed, under a hard deadline of
   ``llm.timeout_s`` (2.5 s). Each complete ``speak`` / ``ask`` action that arrives
   while streaming is validated and handed to ``on_early_speech`` so TTS can start
   before the answer is finished (plan D1, section 8 rule 7).
   A *transient* error (503 overloaded, 429 rate limit) gets **one retry** through
   ``provider.generate_retry`` (Gemini: the backup model), only if nothing was spoken
   yet and at least ``llm.retry.min_remaining_s`` of the same deadline is left.
5. **Validation** (``assistant/actions.py``). If nothing valid survives, or on
   timeout / error -> fixed fallback texts (plan C9).
6. **YouTube search** (``assistant/media_search.py``, docs/assistant.md 6.1): a
   ``search_media`` action (from the LLM or the fallback) is resolved here into an
   ``ask`` with ``expects="choice"`` listing the results; core never sees ``search_media``.

Every answer is described in :attr:`AssistantClient.last_result` (source LLM/RULE,
latency, rejected actions) so core can show it in the event log (plan H3, J1).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from assistant import actions as actions_mod
from assistant import cabin, fallback, media_search, music, preferences
from assistant.contract import Action, Event, State
from assistant.llm import LLMError, LLMProvider, make_provider
from assistant.memory import ShortMemory
from assistant.policies import Policies
from assistant.settings import cfg, get_texts
from assistant.summary import summarize

log = logging.getLogger("drivemate.assistant.client")

#: Callback for speech that is ready while the LLM is still streaming.
EarlySpeechCallback = Callable[[Action], None]

_PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "system.md"
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_LANGUAGE_NAMES = {"ro": "Romanian", "en": "English"}

#: Events answered without the LLM even when it is available: the refusal (plan D10)
#: and the quiz offer after refused music (plan D8), whose follow-up is driven by
#: ``assistant/dialog.py`` and needs the ``quiz_offer`` marker.
DETERMINISTIC_EVENTS = frozenset({"driver_refused", "media_declined"})

#: Events where a person spoke to the assistant: they always get a spoken answer.
SPEECH_EVENTS = frozenset({"driver_speech", "passenger_speech"})


@lru_cache(maxsize=1)
def system_prompt() -> str:
    """Load ``prompts/system.md``, drop HTML comments and fill the placeholders.

    Returns:
        The system prompt sent with every LLM request.
    """
    text = _HTML_COMMENT.sub("", _PROMPT_FILE.read_text(encoding="utf-8")).strip()
    language = cfg("language", default="ro")
    return (
        text.replace("{language_name}", _LANGUAGE_NAMES.get(language, language))
        .replace("{max_words}", str(cfg("speech", "max_words_to_driver", default=30)))
    )


@dataclass
class AnswerInfo:
    """Description of the last answer, for core's event log and the perf panel.

    Attributes:
        event_type: The event answered.
        source: ``"LLM"`` or ``"RULE"`` (fallback / policy / deterministic).
        reason: Why RULE was used (``"policy:muted"``, ``"timeout"``, ``"no_llm"``,
            ``"llm_disabled"``, ``"all_rejected"``, ``"llm_error"``, ``"invalid_json"``,
            ``"truncated"`` (the JSON was cut at ``llm.max_output_tokens``),
            ``"deterministic"``, ``"silent_on_request"``) or ``"ok"``.
        latency_ms: Total time spent in :meth:`AssistantClient.handle_event`.
        llm_ttft_ms: Time to the first LLM chunk (plan J1 ``llm_ttft_ms``).
        llm_total_ms: Time to the complete LLM answer (``llm_total_ms``).
        rejected: ``(raw_action, reason)`` pairs rejected by validation.
        error: Short description of the LLM failure when ``reason`` is ``llm_error``
            (e.g. ``"429 RESOURCE_EXHAUSTED"`` = free-tier rate limit, ``"503 UNAVAILABLE"``
            = Google overloaded), so it can be shown in the event log.
        retry: Set when a transient error was retried, e.g.
            ``"503 UNAVAILABLE -> gemini-3.1-flash-lite"`` (the answer may still be ``"ok"``).
    """

    event_type: str = ""
    source: str = "RULE"
    reason: str = "ok"
    latency_ms: float = 0.0
    llm_ttft_ms: float | None = None
    llm_total_ms: float | None = None
    rejected: list[tuple[Any, str]] = field(default_factory=list)
    error: str | None = None
    retry: str | None = None


def _short_error(exc: Exception) -> str:
    """Compact form of an LLM error: HTTP code + status, e.g. ``"429 RESOURCE_EXHAUSTED"``."""
    text = str(exc)
    code = re.search(r"\b(4\d\d|5\d\d)\b", text)
    status = re.search(r"\b([A-Z]+_[A-Z_]+|UNAVAILABLE|INTERNAL)\b", text)
    if code or status:
        return " ".join(part.group(1) for part in (code, status) if part)
    return text[:120]


class _StreamWatcher:
    """Finds complete action objects in a partially streamed ``{"actions": [...]}``.

    Each time the accumulated text grows, :meth:`feed` decodes any newly completed
    action object. Valid ``speak`` / ``ask`` actions are passed to the callback
    (at most ``llm.max_actions``, in order) and their indexes remembered.
    """

    def __init__(self, state: State, event: Event, callback: EarlySpeechCallback) -> None:
        self._state = state
        self._event = event
        self._callback = callback
        self._decoder = json.JSONDecoder()
        self._pos: int | None = None  # parse position inside the actions array
        self._index = 0                  # index of the next action object
        self.streamed: set[int] = set()  # indexes already handed to TTS

    def feed(self, text: str) -> None:
        """Process the accumulated text (called after every streamed chunk)."""
        if self._pos is None:
            match = re.search(r'"actions"\s*:\s*\[', text)
            if not match:
                return
            self._pos = match.end()
        max_actions = int(cfg("llm", "max_actions", default=3))
        while self._index < max_actions:
            pos = self._pos
            while pos < len(text) and text[pos] in " \t\r\n,":
                pos += 1
            if pos >= len(text) or text[pos] != "{":
                return
            try:
                obj, end = self._decoder.raw_decode(text, pos)
            except ValueError:
                return  # object not complete yet
            self._pos = end
            index = self._index
            self._index += 1
            if isinstance(obj, dict) and obj.get("type") in ("speak", "ask"):
                checked = actions_mod.validate_actions([obj], self._state, self._event, source="LLM")
                if checked.accepted:
                    self.streamed.add(index)
                    try:
                        self._callback(checked.accepted[0].model_copy(update={"streamed": True}))
                    except Exception:
                        log.exception("on_early_speech callback failed")


class AssistantClient:
    """Stateful assistant: provider, policies and short memory for one trip."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        """Create the client.

        Args:
            provider: LLM provider (tests inject fakes); defaults to
                :func:`assistant.llm.make_provider` (Gemini or offline).
        """
        self.provider: LLMProvider = provider or make_provider()
        self.policies = Policies()
        self.memory = ShortMemory()
        self.last_result = AnswerInfo()

    async def handle_event(
        self,
        event: Event | dict,
        state: State | dict,
        on_early_speech: EarlySpeechCallback | None = None,
        now: float | None = None,
    ) -> list[Action]:
        """Turn one event into validated actions (see module docstring for the pipeline).

        Args:
            event: The event (model or plain dict).
            state: The current state (model or plain dict).
            on_early_speech: Optional callback for ``speak`` / ``ask`` actions that are
                ready while the LLM is still streaming; such actions are returned again
                in the final list with ``streamed=True`` so core does not repeat them.
            now: Current Unix time (tests); defaults to ``time.time()``.

        Returns:
            At most ``llm.max_actions`` validated actions. Never raises.
        """
        started = time.perf_counter()
        now = time.time() if now is None else now
        event = event if isinstance(event, Event) else Event.model_validate(event)
        state = state if isinstance(state, State) else State.model_validate(state)
        info = AnswerInfo(event_type=event.type)

        if event.type in ("driver_speech", "passenger_speech"):
            speaker = "driver" if event.type == "driver_speech" else "passenger"
            self.memory.add(speaker, str(event.data.get("text", "")), now)

        decision = self.policies.check(event, state, now)
        if not decision.allowed:
            info.reason = f"policy:{decision.reason}"
            result = [fallback.silent(decision.reason)]
        elif event.type in DETERMINISTIC_EVENTS or (
            event.type in SPEECH_EVENTS and (fallback.media_command(str(event.data.get("text", "")), state)
                                             or fallback.thanks(str(event.data.get("text", ""))))
        ):
            # Music controls, known preference commands and thanks are answered without the LLM.
            info.reason = "deterministic"
            result = self._fallback(event, state, info)
        elif not self.provider.available:
            info.reason = "no_llm"
            result = self._fallback(event, state, info)
        elif not state.safety.llm_enabled:
            info.reason = "llm_disabled"
            result = self._fallback(event, state, info)
        else:
            result = await self._ask_llm(event, state, info, on_early_speech)

        if any(a.type == "search_media" for a in result):
            result = await self._resolve_media_search(result, event, state, info, on_early_speech)
        result = self._with_follow_up(event, result, state)

        if any(a.type != "stay_silent" for a in result):
            self.policies.record(event, now)
        for action in result:
            spoken = action.text if action.type == "speak" else action.question if action.type == "ask" else None
            if spoken:
                self.memory.add("assistant", spoken, now)

        info.latency_ms = (time.perf_counter() - started) * 1000
        self.last_result = info
        log.info("event=%s source=%s reason=%s latency=%.0fms actions=%s",
                 event.type, info.source, info.reason, info.latency_ms, [a.type for a in result])
        return result

    async def _ask_llm(
        self, event: Event, state: State, info: AnswerInfo, on_early_speech: EarlySpeechCallback | None
    ) -> list[Action]:
        """Call the LLM under the deadline (one retry on a transient error), validate, fall back when needed."""
        watcher = _StreamWatcher(state, event, on_early_speech) if on_early_speech else None
        user = summarize(state, event, self.memory.recent())
        timeout = float(cfg("llm", "timeout_s", default=2.5))
        total = max(timeout, float(cfg("llm", "total_timeout_s", default=timeout)))
        started = time.perf_counter()
        task = asyncio.ensure_future(self.provider.generate(system_prompt(), user, watcher.feed if watcher else None))
        try:
            # llm.timeout_s is the deadline for the FIRST spoken sentence: an answer whose first sentence the
            # driver already hears (streamed, on_early_speech) may go on until llm.total_timeout_s, so a long
            # answer is not cut in the middle and replaced by a fixed text.
            llm = await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except TimeoutError:
            if watcher is not None and watcher.streamed and total > timeout:
                try:
                    log.info("LLM answer on %s goes past %.1fs: its first sentence is out, waiting up to %.1fs.",
                             event.type, timeout, total)
                    llm = await asyncio.wait_for(task, timeout=total - (time.perf_counter() - started))
                except TimeoutError:
                    info.reason = "timeout"
                    log.warning("LLM timeout after %.1fs on %s; using fallback.", total, event.type)
                    return self._fallback(event, state, info, skip_speech=True)
                except LLMError as exc:  # failed after its first sentence: no retry (never say it twice)
                    info.reason, info.error = "llm_error", _short_error(exc)
                    log.warning("LLM error on %s after its first sentence: %s", event.type, exc)
                    return self._fallback(event, state, info, skip_speech=True)
            else:
                task.cancel()
                info.reason = "timeout"
                log.warning("LLM timeout after %.1fs on %s; using fallback.", timeout, event.type)
                return self._fallback(event, state, info, skip_speech=bool(watcher and watcher.streamed))
        except LLMError as exc:
            remaining = timeout - (time.perf_counter() - started)
            if not self._can_retry(exc, watcher, remaining):
                info.reason = "llm_error"
                info.error = _short_error(exc)
                log.warning("LLM error on %s: %s; using fallback.", event.type, exc)
                return self._fallback(event, state, info)
            info.retry = f"{_short_error(exc)} -> {self.provider.retry_label}"
            log.warning("LLM error on %s: %s; retrying with %s (%.1fs left).",
                        event.type, exc, self.provider.retry_label, remaining)
            # Fresh watcher: the retry streams its answer from the start.
            watcher = _StreamWatcher(state, event, on_early_speech) if on_early_speech else None
            try:
                llm = await asyncio.wait_for(
                    self.provider.generate_retry(system_prompt(), user, watcher.feed if watcher else None),
                    timeout=remaining,
                )
            except TimeoutError:
                info.reason = "timeout"
                log.warning("LLM retry timeout on %s; using fallback.", event.type)
                return self._fallback(event, state, info, skip_speech=bool(watcher and watcher.streamed))
            except LLMError as retry_exc:
                info.reason = "llm_error"
                info.error = _short_error(retry_exc)
                log.warning("LLM retry failed on %s: %s; using fallback.", event.type, retry_exc)
                return self._fallback(event, state, info)

        info.llm_ttft_ms, info.llm_total_ms = llm.ttft_ms, llm.total_ms
        try:
            payload = json.loads(llm.text)
            raw_actions = payload.get("actions", []) if isinstance(payload, dict) else []
        except ValueError:
            # MAX_TOKENS = the model ran out of llm.max_output_tokens (its thinking counts too).
            info.reason = "truncated" if llm.finish_reason == "MAX_TOKENS" else "invalid_json"
            log.warning("LLM returned %s JSON on %s: %r", info.reason, event.type, llm.text[:200])
            return self._fallback(event, state, info)

        checked = actions_mod.validate_actions(raw_actions, state, event, source="LLM")
        info.rejected = [(r.raw, r.reason) for r in checked.rejected]
        self._ask_for_held(checked, state, event)
        answers = ("speak", "ask", "search_media")  # a search becomes a spoken question (see _resolve_media_search)
        acted = [a for a in checked.accepted if a.type not in ("stay_silent",) and not a.needs_confirmation]
        if event.type in SPEECH_EVENTS and acted and not any(a.type in answers for a in checked.accepted):
            # The LLM did what was asked (e.g. only stop_media) without a sentence: confirm it with "Ok."
            # instead of throwing the action away.
            ok = Action(type="speak", to="driver", text=get_texts().get("clips", {}).get("confirm_ok", "Ok."),
                        clip_id="confirm_ok", source="RULE")
            checked.accepted.append(ok)
            checked.accepted_indexes.append(-1)
        if event.type in SPEECH_EVENTS and not any(a.type in answers for a in checked.accepted) and not any(
            a.type == "stay_silent" and a.reason == "driver_refused" for a in checked.accepted
        ):
            # Someone spoke TO the assistant: silence is never an acceptable answer
            # (only a refusal is). Use the fixed "n-am înțeles, poți repeta?" instead.
            info.reason = "silent_on_request"
            log.warning("LLM stayed silent on %s %r; using fallback.", event.type, event.data.get("text"))
            return self._fallback(event, state, info)
        if not checked.accepted:
            if raw_actions:  # the LLM wanted to act but nothing was valid
                info.reason = "all_rejected"
                return self._fallback(event, state, info)
            info.source = "LLM"
            return [Action(type="stay_silent", reason="nothing_to_add", source="LLM")]

        info.source = "LLM"
        if watcher and watcher.streamed:
            # Mark the actions already handed to TTS while streaming (same raw index).
            return [
                action.model_copy(update={"streamed": True}) if index in watcher.streamed else action
                for action, index in zip(checked.accepted, checked.accepted_indexes)  # noqa: B905
            ]
        return checked.accepted

    @staticmethod
    def _ask_for_held(checked: actions_mod.ValidationResult, state: State, event: Event) -> None:
        """An action held for a "yes" with no question in the answer gets its confirmation question.

        Without it the action waited for a "yes" nobody asked for, and on a direct request
        the answer counted as silence ("n-am înțeles"): 100% of "Am mesaje noi?" /
        "Citește-mi mesajele" with a passenger on board in the baseline evaluation.
        """
        held = [a for a in checked.accepted if a.needs_confirmation]
        if not held or any(a.type == "ask" for a in checked.accepted):
            return
        raw = {"type": "ask", "to": "driver", "question": fallback.confirmation_question(held[0], state),
               "expects": "yes_no"}
        added = actions_mod.validate_actions([raw], state, event, source="RULE")
        if added.accepted:
            checked.accepted.append(added.accepted[0])
            checked.accepted_indexes.append(-1)
        else:  # never expected (fixed texts); logged so it can be fixed
            log.warning("confirmation question rejected: %s", [r.reason for r in added.rejected])

    @staticmethod
    def _with_follow_up(event: Event, result: list[Action], state: State) -> list[Action]:
        """Add "Te mai ajut cu ceva?" after a statement that answers the driver (``speech.follow_up``).

        Only for ``driver_speech`` (never after proactive interventions such as a cause or
        fatigue), only when the answer contains a ``speak`` to the driver and no question,
        no held action and no ``stay_silent`` (refusal, policy), and only while the driver's
        ``follow_up`` preference is not ``never`` (``assistant/preferences.py``). The question
        is an ``ask`` with ``reason="follow_up"``: core opens the dialog window, and
        :class:`assistant.dialog.DialogManager` handles the "da" / "nu" that follows.
        """
        if event.type != "driver_speech" or not cfg("speech", "follow_up", "enabled", default=True):
            return result
        if not preferences.follow_up_enabled(state):
            return result
        if not any(a.type == "speak" and a.to in (None, "driver", "all") for a in result):
            return result
        if any(a.type in ("ask", "stay_silent") or a.needs_confirmation or a.reason == "closing" for a in result):
            return result  # "closing": the driver ended the exchange ("mulțumesc" -> "Cu plăcere!")
        question = get_texts().get("fallback", {}).get("follow_up") or "Te mai ajut cu ceva?"
        return [*result, Action(type="ask", to="driver", question=question, expects="free",
                                reason="follow_up", source="RULE")]

    @staticmethod
    def _can_retry(exc: LLMError, watcher: _StreamWatcher | None, remaining: float) -> bool:
        """True when a failed LLM call deserves its one retry.

        Only transient errors (overload, rate limit), only if nothing was handed to TTS
        yet (the driver must never hear an answer twice), and only if at least
        ``llm.retry.min_remaining_s`` of the deadline is left.
        """
        if not cfg("llm", "retry", "enabled", default=True) or not exc.transient:
            return False
        if watcher is not None and watcher.streamed:
            return False
        return remaining >= float(cfg("llm", "retry", "min_remaining_s", default=1.0))

    async def _resolve_media_search(
        self, result: list[Action], event: Event, state: State, info: AnswerInfo,
        on_early_speech: EarlySpeechCallback | None,
    ) -> list[Action]:
        """Replace ``search_media`` with the spoken choice of YouTube results (docs/assistant.md 6.1).

        "Caut." is said right away through ``on_early_speech`` (when given) because the search
        takes ~0.5-5 s. Other questions in the same answer are dropped: one question at a time.
        On failure / no results the driver hears why, and the local catalog is offered when
        possible (plan C9: every component has a fallback).
        """
        search = next(a for a in result if a.type == "search_media")
        kept = [a for a in result if a.type in ("speak", "stop_media")]
        texts = get_texts().get("fallback", {})
        if on_early_speech is not None and not any(a.type == "speak" and a.streamed for a in kept):
            searching = Action(type="speak", to="driver", text=texts.get("youtube_searching", "Caut."),
                               source="RULE", streamed=True)
            try:
                on_early_speech(searching)
                kept.append(searching)
            except Exception:
                log.exception("on_early_speech callback failed")
        try:
            found = await media_search.search(search.query or "", search.kind or "music",
                                              kid_safe=cabin.has_child(state))
        except media_search.MediaSearchError as exc:
            info.error = f"media_search {exc}"
            log.warning("YouTube search failed (%s) for %r", exc, search.query)
            return kept + self._media_fallback(state, event, child=str(exc) == "kid_safe_needs_api")
        if not found:
            return kept + [Action(type="speak", to="driver", text=texts.get("youtube_none", ""), source="RULE")]  # noqa: RUF005
        question, options = media_search.build_choice(found, media_search.offer_size(state))
        media_search.prefetch(o["track_id"][len(media_search.TRACK_PREFIX):] for o in options if o["offered"])
        ask = Action(type="ask", to="driver", question=question, expects="choice", options=options,
                     reason="media_choice", source=search.source)
        return kept + [ask]  # noqa: RUF005

    def _media_fallback(self, state: State, event: Event, child: bool) -> list[Action]:
        """Search impossible: offer a catalog track (kid_safe with a child), or just say so."""
        texts = get_texts().get("fallback", {})
        track = music.pick_track(state, "request")
        if track is None:
            raw = [{"type": "speak", "to": "driver", "text": texts.get("youtube_unavailable_no_catalog", "")}]
        else:
            key = "youtube_child_catalog" if child else "youtube_unavailable"
            raw = [{"type": "ask", "to": "driver", "question": texts.get(key, ""), "expects": "yes_no"},
                   {"type": "suggest_media", "track_id": track.id, "reason": "driver_request"}]
        return actions_mod.validate_actions(raw, state, event, source="RULE").accepted

    def _fallback(self, event: Event, state: State, info: AnswerInfo, skip_speech: bool = False) -> list[Action]:
        """Fixed answer for ``event`` (validated, ``source="RULE"``).

        Args:
            skip_speech: True when the LLM already spoke during streaming before the
                timeout; spoken fallback actions are then dropped to avoid repeating.
        """
        info.source = "RULE"
        raw = fallback.build_fallback(event, state, info.reason)
        checked = actions_mod.validate_actions(raw, state, event, source="RULE")
        info.rejected.extend((r.raw, r.reason) for r in checked.rejected)
        result = checked.accepted
        if skip_speech:
            result = [a for a in result if a.type not in ("speak", "ask")]
        return result

    def reset(self) -> None:
        """New trip / director reset: forget memory, the rate-limit clock and preferences changed by voice."""
        self.memory.clear()
        self.policies.reset()
        preferences.store.reset()


_client: AssistantClient | None = None


def get_client() -> AssistantClient:
    """Return the process-wide :class:`AssistantClient` (created on first use)."""
    global _client
    if _client is None:
        _client = AssistantClient()
    return _client


async def handle_event(
    event: Event | dict, state: State | dict, on_early_speech: EarlySpeechCallback | None = None
) -> list[Action]:
    """Interface for core (plan section 13): ``handle_event(event, state) -> list[Action]``.

    Thin wrapper around :meth:`AssistantClient.handle_event` on the shared client.
    """
    return await get_client().handle_event(event, state, on_early_speech)
