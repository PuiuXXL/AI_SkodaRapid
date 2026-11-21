"""C: core <-> P3's assistant. Events go to ``assistant.handle_event``; the actions that come back are checked (C8) and
executed. Safety never waits for any of this (plan section 3: the slow path).

**Events core sends** (``docs/assistant.md`` section 3.2):

* ``trip_start`` once the driver has been seen for ``assistant.greet_after_s`` ("Salut Andrei. Salut Maria.");
* ``driver_speech``: an addressed, final utterance that is neither an answer to the SOS nor to the assistant's
  pending question;
* ``driver_refused``: a refusal ("lasă-mă în pace") while the fatigue dialog is on (C10 follows in step H);
* ``message_received`` / ``safe_contact_reply``: when the F2 rule (``core/messages_timing.py``) allows it;
* ``stop_suggested``: after a KSS answer of ``assistant.kss_break_min`` or more, with the stop the rule picked (K3);
* the follow-ups P3's dialog manager returns (``media_declined``, ``kss_answer``, ``driver_refused``, ...).

Events are processed one at a time by a background task (``run``); an answer can take seconds (LLM, YouTube search).
Sentences that are ready while the LLM streams are spoken at once (``on_early_speech``) and not repeated.

**Answers.** Actions that need a "yes" are held by P3's ``DialogManager``; voice (``speech``), nods
(``driver.head.answer``) and gestures (``driver.gesture``) release or cancel them. When the assistant's question has
been spoken (``speak_done``), core opens the dialog window. The SOS has priority: an input that answered "Ești bine?"
never reaches the assistant, and a safety alert drops the pending question.

**D4, yielding the floor.** While the assistant speaks and the driver looks at a mirror (``assistant.yield_zones``)
the voice pauses (``speak_control: pause``) and resumes with "...cum ziceam" when the gaze is back on the road.
✋ with nothing pending stops the assistant's voice.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from core import messages_timing, validator
from core.reminders import pick_stop
from core.settings import template, th
from shared.contracts import (
    Action,
    Event,
    LastInput,
    PerceptionFrame,
    Reminder,
    SendReply,
    State,
    UiMedia,
    UiSpeakControl,
    UiSpeakDone,
    UiSpeech,
    to_wire,
)

if TYPE_CHECKING:
    from core.engine import Engine

log = logging.getLogger("drivemate.core.assistant")

#: P3's ``AnswerInfo.reason`` -> ``integrations.llm``.
LLM_STATUS = {"no_llm": "off", "llm_disabled": "off", "llm_error": "down", "timeout": "down", "invalid_json": "down"}
GESTURE_STOP = "Open_Palm"
#: Causes answered by delegation / attention to the cabin (D2): their effect is measured (D6).
DELEGATE_CAUSES = frozenset({"passenger_showing_phone", "passenger_talk", "child_activity"})


class AssistantLink:
    def __init__(self, engine: Engine, client: Any = None, clock: Callable[[], float] = time.time) -> None:
        self.engine = engine
        self.clock = clock
        self.available = False
        try:
            from assistant import music, tts
            from assistant.answers import InputEvent
            from assistant.client import get_client
            from assistant.dialog import DialogManager
            from assistant.refusal import is_refusal
        except Exception as exc:  # P3's code or its dependencies missing: core and safety run without the assistant
            log.warning("assistant not available (%s: %s): no LLM, safety unaffected", exc.__class__.__name__, exc)
            self.client = client
            self.dialog: Any = None
        else:
            self.available = True
            self._music, self._tts, self._input, self._is_refusal = music, tts, InputEvent, is_refusal
            self.client = client or get_client()
            self.dialog = DialogManager()
        self.queue: deque[Event] = deque()
        self._wake = asyncio.Event()
        self.processed = 0
        engine.assistant = self
        engine.add_browser_listener(self.on_browser)
        engine.add_frame_listener(self.on_frame)
        engine.add_tick_listener(self.on_tick)
        engine.add_reset_listener(self.reset)
        engine.safety.arbiter.on_interrupt.append(self.on_safety_interrupt)
        self.reset(0.0)

    # --- state of the link ---------------------------------------------------------------------------------------

    def reset(self, now: float) -> None:
        self.queue.clear()
        if self.dialog is not None:
            self.dialog.reset()
        if self.client is not None and hasattr(self.client, "reset"):
            self.client.reset()
        self.utterances: dict[str, dict[str, Any]] = {}  # the assistant's utterances not finished yet
        self.speaking: str | None = None
        self.paused = False
        self.greeted = False
        self.driver_seen_since: float | None = None
        self.offered: set[str] = set()  # messages handed to the assistant
        self.deferred_next: dict[str, float] = {}
        self.deferred_said: set[str] = set()
        self.handled_messages: set[str] = set()  # read or replied hands-free (scorecard)
        self.last_inputs: tuple[Any, ...] = (None, None, None, None)

    def on_safety_interrupt(self) -> None:
        """A safety alert stopped every sound: the question the assistant was waiting on no longer stands."""
        if self.dialog is not None:
            self.dialog.reset()
        self.speaking, self.paused = None, False

    def _sos_active(self, now: float) -> bool:
        sos = self.engine.safety.sos
        return sos.state != "normal" or sos.consumed_at == now

    # --- events --------------------------------------------------------------------------------------------------

    def submit(self, type_: str, now: float, **data: Any) -> None:
        """Queue one event for ``handle_event`` (processed in order by :meth:`run`)."""
        if not self.available:
            return
        self.queue.append(Event(type=type_, ts=now, data=data))
        self._wake.set()

    async def run(self) -> None:
        """The background worker (started by core/main.py)."""
        while True:
            await self._wake.wait()
            self._wake.clear()
            await self.drain()

    async def drain(self) -> None:
        while self.queue:
            event = self.queue.popleft()
            try:
                await self.process(event)
            except Exception:  # one bad answer must not stop the assistant
                log.exception("assistant event %s failed", event.type)

    async def process(self, event: Event) -> list[Action]:
        """Send one event to the assistant and execute what it returns."""
        snapshot = self.engine.state.model_copy(deep=True)  # the state keeps changing while the LLM answers

        def on_early(action: Action) -> None:
            now = self.clock()
            reason = validator.check(action, self.engine.state, confirmed=False)
            if reason is None:
                self._send_speech(action, now)

        actions: list[Action] = await self.client.handle_event(event, snapshot, on_early_speech=on_early)
        now = self.clock()
        self.processed += 1
        self._record(event, now)
        immediate = self.dialog.register(actions, now)
        held = [a for a in actions if a.needs_confirmation]
        if held:
            self.engine.log_event("assistant_action", now, source=held[0].source,
                                  text="Așteaptă confirmarea: " + ", ".join(a.type for a in held),
                                  action_type="held", event_type=event.type)
        executed = [a for a in immediate if self.execute(a, now, confirmed=False, event_type=event.type)]
        if (event.type == "cause_detected" and event.data.get("label") in DELEGATE_CAUSES
                and any(a.type in ("speak", "ask", "delegate") for a in executed)):
            self._intervention("delegate", now)  # D2, D6: did the glances at the passenger fall?
        if event.type == "kss_answer" and int(event.data.get("value", 0)) >= int(th("assistant", "kss_break_min")):
            stop = pick_stop(self.engine.state)
            if stop is not None:
                self.submit("stop_suggested", now, **stop)
        return actions

    def _record(self, event: Event, now: float) -> None:
        """LLM latency for the performance panel (J1) and its status for ``integrations.llm``."""
        info = getattr(self.client, "last_result", None)
        if info is None:
            return
        perf = self.engine.core_perf
        if info.llm_ttft_ms is not None:
            perf["llm_ttft_ms"] = round(info.llm_ttft_ms, 1)
        if info.llm_total_ms is not None:
            perf["llm_total_ms"] = round(info.llm_total_ms, 1)
        if info.reason != "llm_disabled":  # the director's switch is shown by the engine itself
            self.engine.llm_status = LLM_STATUS.get(info.reason, "ok")
        for raw, reason in info.rejected:
            kind = raw.get("type") if isinstance(raw, dict) else getattr(raw, "type", "?")
            self.engine.log_event("action_rejected", now, source="LLM", text=f"{kind} respins de asistent: {reason}",
                                  reason=reason, by="assistant", event_type=event.type)
        if info.error:
            self.engine.log_event("llm_error", now, source="RULE", text=f"LLM: {info.error}; text fix în loc.")

    # --- executing actions ---------------------------------------------------------------------------------------

    def execute(self, action: Action, now: float, *, confirmed: bool, event_type: str = "") -> bool:
        """Run one action after the C8 check. Returns False when it was rejected."""
        reason = validator.check(action, self.engine.state, confirmed=confirmed)
        if reason is not None:
            self.engine.log_event("action_rejected", now, source=action.source, text=f"{action.type}: {reason}",
                                  reason=reason, by="core", action=action.model_dump(mode="json", exclude_none=True))
            return False
        state = self.engine.state
        text: str | None = None
        kind = action.type
        if kind in ("speak", "ask"):
            text = action.text if kind == "speak" else action.question
            if not action.streamed:
                self._send_speech(action, now)
        elif kind == "play_media" and action.track_id:
            text = self._play(action, state, event_type, now)
        elif kind == "stop_media":
            self.engine.hub.broadcast_ui(to_wire(UiMedia(action="stop")))
            state.media.playing = False
            text = "Muzica oprită."
        elif kind == "set_preference":
            text = self._preference(action, state)
        elif kind == "read_message":
            text = self._read(action, state, now)
        elif kind == "reply_message":
            text = self._reply(action, state, now)
        elif kind == "create_reminder" and action.trigger is not None:
            reminder = Reminder(id=f"r{len(state.reminders) + 1}", task=action.task or "", trigger=action.trigger,
                                state="active", created_ts=now)
            state.reminders.append(reminder)
            text = f"Memento: {reminder.task} ({reminder.trigger.category})."
        elif kind == "complete_reminder":
            for reminder in state.reminders:
                if reminder.id == action.reminder_id and reminder.state != "done":
                    reminder.state = "done"
                    state.scorecard.reminders_done += 1
            text = f"Memento bifat: {action.reminder_id}."
        elif kind == "suggest_stop":
            text = f"Oprire acceptată: {action.poi_id}."
        elif kind == "delegate":
            text = f"Delegat lui {action.to_person}: {action.task}."
        elif kind == "show_on_screen":
            self.engine.log_event("show_on_screen", now, source=action.source, text=action.text,
                                  target=action.target or "passenger")
            return True
        elif kind == "stay_silent":
            text = f"Tace: {action.reason}."
        self.engine.log_event("assistant_action", now, source=action.source, text=text, action_type=kind,
                              event_type=event_type)
        return True

    def _send_speech(self, action: Action, now: float) -> None:
        message = self._tts.speak_message(action)
        self.engine.hub.broadcast_ui(message)
        self.utterances[message["id"]] = {"to": action.to or "driver", "is_question": action.type == "ask",
                                          "ts": now}
        self.speaking, self.paused = message["id"], False

    def _intervention(self, kind: str, now: float) -> None:
        scores = self.engine.scores
        if scores is not None:
            scores.intervention.start(kind, now)

    def _play(self, action: Action, state: State, event_type: str, now: float) -> str:
        music = self._music
        track_id = str(action.track_id)
        volume = action.volume if action.volume is not None else music.volume_for(state)
        self.engine.hub.broadcast_ui(to_wire(UiMedia(action="play", url=music.track_url(track_id), volume=volume,
                                                     track_id=track_id, title=action.title,
                                                     loop=music.loops(track_id))))
        media = state.media
        media.playing, media.track_id, media.title, media.volume = True, track_id, action.title, volume
        media.source = "catalog" if music.loops(track_id) else "youtube"
        disengaged = event_type == "disengagement_high" or action.reason == "disengagement"
        media.reason = "disengagement" if disengaged else (action.reason or "driver_request")
        if disengaged:
            self._intervention("music", now)  # D6: does D fall with the music on? (requested music: not measured)
        return f"Muzică: {action.title or track_id}."

    def _preference(self, action: Action, state: State) -> str:
        if action.key == "volume" and isinstance(action.value, (int, float)):
            volume = max(0.0, min(1.0, float(action.value)))
            state.media.volume = volume
            self.engine.hub.broadcast_ui(to_wire(UiMedia(action="volume", volume=volume)))
            return f"Volum {volume:.0%}."
        return f"Preferință: {action.key} = {action.value}."

    def _read(self, action: Action, state: State, now: float) -> str:
        message = next((m for m in state.messages if m.id == action.msg_id), None)
        if message is None or not message.text:
            return f"Mesajul {action.msg_id} nu mai există."
        # Reading a message is not an LLM sentence: no 15-word rule, said as is (docs/assistant.md 3.4).
        self._send_speech(Action(type="speak", to="driver", text=message.text, source="RULE"), now)
        message.state = "read"
        if message.ts:
            self.engine.core_perf["msg_to_voice_ms"] = round((now - message.ts) * 1000.0, 1)
        self._hands_free(message.id, state)
        return f"Mesaj citit: {message.from_}."

    def _reply(self, action: Action, state: State, now: float) -> str:
        message = next((m for m in state.messages if m.id == action.msg_id), None)
        notification = self.engine.notifications.get(str(action.msg_id))
        if message is None or notification is None:
            return f"Răspunsul nu se poate trimite prin telefon (mesaj {action.msg_id} fără notificare)."
        request_id = f"reply-{action.msg_id}-{int(now)}"
        sent = self.engine.hub.send_phone(to_wire(SendReply(request_id=request_id, notification_id=notification,
                                                            text=str(action.text))))
        if not sent:
            return "Puntea cu telefonul nu e conectată: răspunsul nu a plecat."
        message.state = "replied"
        self._hands_free(message.id, state)
        return f"Răspuns trimis lui {message.from_}."

    def _hands_free(self, msg_id: str, state: State) -> None:
        if msg_id not in self.handled_messages:
            self.handled_messages.add(msg_id)
            state.scorecard.hands_free_messages += 1

    # --- answers -------------------------------------------------------------------------------------------------

    def apply(self, result: Any, now: float) -> None:
        """Execute a DialogManager result: confirmed actions, short replies, follow-up events."""
        state = self.engine.state
        if result.channel:
            state.interaction.last_input = LastInput.model_validate(
                {"from": 1, "channel": result.channel, "value": result.answer, "ts": now})
        self.engine.log_event("input", now, source="RULE", channel=result.channel, text=f"Răspuns: {result.answer}",
                              value=result.answer)
        if result.answer == "yes" and result.execute:
            state.scorecard.suggestions_accepted += 1
        elif result.answer in ("no", "silence") and result.cancelled:
            state.scorecard.suggestions_rejected += 1
        for action in result.execute:
            self.execute(action, now, confirmed=True)
        for action in result.speak:
            self.execute(action, now, confirmed=True)
        for follow_up in result.events:
            self.submit(follow_up.type, now, **follow_up.data)

    def _fatigue_dialog(self, state: State) -> bool:
        return state.assessment.fatigue >= float(th("safe_contact", "fatigue_min"))

    def on_browser(self, message: Any, now: float) -> None:
        if not self.available:
            return
        if isinstance(message, UiSpeakDone):
            self._speak_done(message, now)
            return
        if not isinstance(message, UiSpeech) or not message.final:
            return
        if not (message.addressed or self.engine.safety.dialog.is_open(now)) or self._sos_active(now):
            return
        if message.wait_ms is not None:
            self.engine.core_perf["stt_final_ms"] = message.wait_ms
        state = self.engine.state
        if self.dialog.has_pending(now):
            result = self.dialog.handle([self._input("voice", message.text, now)], now, state=state,
                                        fatigue_dialog=self._fatigue_dialog(state))
            if result.handled:
                self.apply(result, now)
                return
        if self._fatigue_dialog(state) and self._is_refusal(message.text):
            self.submit("driver_refused", now, text=message.text)
        else:
            self.submit("driver_speech", now, text=message.text)

    def _speak_done(self, message: UiSpeakDone, now: float) -> None:
        utterance = self.utterances.pop(message.id, None)
        if self.speaking == message.id:
            self.speaking, self.paused = None, False
        if utterance and utterance["is_question"] and not message.interrupted and not self._sos_active(now):
            self.engine.safety.dialog.open(now, float(th("dialog", "window_s")), to=utterance["to"],
                                           reason="assistant")

    def on_frame(self, frame: PerceptionFrame, now: float) -> None:
        """Nods and gestures (rising edges only: P1 holds an answer for about a second)."""
        if not self.available:
            return
        driver, passenger = frame.driver, frame.passenger
        current = (driver.head.answer, driver.gesture, passenger.answer, passenger.gesture)
        new = tuple(value if value != before else None for value, before in zip(current, self.last_inputs,
                                                                                 strict=True))
        self.last_inputs = current
        if not any(new) or self._sos_active(now):
            return
        inputs = []
        for index, value in enumerate(new):
            if value:
                inputs.append(self._input("nod" if index in (0, 2) else "gesture", value, now))
        if self.dialog.has_pending(now):
            result = self.dialog.handle(inputs, now, state=self.engine.state,
                                        fatigue_dialog=self._fatigue_dialog(self.engine.state))
            if result.handled:
                self.apply(result, now)
            return
        if GESTURE_STOP in (new[1], new[3]) and self.speaking is not None:  # ✋ = silence (E3)
            self.engine.hub.broadcast_ui(to_wire(UiSpeakControl(action="stop")))
            self.engine.log_event("input", now, source="RULE", channel="gesture", text="✋ liniște", value="silence")
            self.speaking, self.paused = None, False

    # --- every tick ----------------------------------------------------------------------------------------------

    def on_tick(self, state: State, now: float) -> None:
        if not self.available:
            return
        expired = self.dialog.expire(now)
        if expired.handled and expired.cancelled:
            self.engine.log_event("assistant_action", now, source="RULE", action_type="expired",
                                  text="Fără răspuns: anulat " + ", ".join(a.type for a in expired.cancelled))
        self._greet(state, now)
        self._messages(state, now)
        self._yield(state, now)
        window = self.engine.safety.dialog.is_open(now)
        state.interaction.state = ("paused" if self.paused else "speaking" if self.speaking
                                   else "listening" if window else "idle")

    def _greet(self, state: State, now: float) -> None:
        if self.greeted:
            return
        seen = state.safety.monitoring_ok and any(o.seat == "driver" for o in state.occupants)
        if not seen:
            self.driver_seen_since = None
            return
        self.driver_seen_since = self.driver_seen_since if self.driver_seen_since is not None else now
        if now - self.driver_seen_since >= float(th("assistant", "greet_after_s")):
            self.greeted = True
            self.submit("trip_start", now)

    def _messages(self, state: State, now: float) -> None:
        """F2 for every message not handed to the assistant yet.

        While the driver is being seen but not greeted yet, messages wait for the greeting: the greeting would
        otherwise replace the "Îl citesc tare?" question (a new utterance drops the pending one in P3's dialog).
        """
        if not self.greeted and self.driver_seen_since is not None:
            return
        for message in state.messages:
            if message.id in self.offered or message.state not in ("pending", "deferred"):
                continue
            if message.state == "deferred" and now < self.deferred_next.get(message.id, 0.0):
                continue
            delivery, reason = messages_timing.decide(state)
            if delivery == "defer":
                message.state, message.deferred_reason = "deferred", reason
                self.deferred_next[message.id] = now + float(th("messages", "retry_s"))
                if message.id not in self.deferred_said:
                    self.deferred_said.add(message.id)
                    if (state.safety.level or "P4") not in ("P0", "P1", "P2"):
                        self.engine.say(str(template("clips", "message_deferred")),
                                        "Ți-l citesc imediat ce e liniște.", prefix="msg")
                    self.engine.log_event("message_deferred", now, text=f"Mesaj de la {message.from_}: amânat.",
                                          msg_id=message.id, reason=reason)
                continue
            self.offered.add(message.id)
            contact = state.safe_contact
            from_contact = bool(contact.name) and contact.notified_ts is not None and message.from_ == contact.name
            self.submit("safe_contact_reply" if from_contact else "message_received", now, msg_id=message.id,
                        delivery=delivery)

    def _yield(self, state: State, now: float) -> None:
        """D4: pause while the driver checks a mirror, resume ("...cum ziceam") when the gaze is back."""
        if self.speaking is None:
            return
        zone = state.driver.gaze.zone
        if not self.paused and zone in th("assistant", "yield_zones"):
            self.paused = True
            self.engine.hub.broadcast_ui(to_wire(UiSpeakControl(action="pause")))
            self.engine.log_event("assistant_action", now, source="RULE", action_type="yield",
                                  text=f"Vocea așteaptă: privire {template('zones').get(zone, zone)}.")
        elif self.paused and zone == "road":
            self.paused = False
            self.engine.hub.broadcast_ui(to_wire(UiSpeakControl(action="resume")))

    async def warm_up(self) -> None:
        """Plan section 8, rule 5: load what the first answer needs before the demo starts."""
        if not self.available:
            return
        try:
            from assistant import media_search

            await media_search.warm_up()
        except Exception as exc:  # warm-up is an optimisation only
            log.info("assistant warm-up skipped: %s", exc)
