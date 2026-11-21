"""Validation of the actions proposed by the LLM (plan section 6).

The LLM may only return actions from the plan's table. This module enforces the
table before anything reaches core (core validates again, plan C: "validate de C"):

* the action type must exist (unknown types are rejected and logged);
* the current safety level must allow it ("Permisă la" column);
* the required parameters must be present and valid (message exists, track is a
  current candidate, POI was proposed by P2's rule, category exists, ...);
* anything said to the driver is at most ``speech.max_words_to_driver`` words;
* at most ``llm.max_actions`` actions per answer (the rest are dropped);
* ``needs_confirmation`` is filled from the "Cere confirmare" column;
* a ``speak`` to the driver that ends with "?" becomes an ``ask`` (``expects="free"``),
  so core opens the dialog window and the driver can answer without the wake word.

Rejected actions are returned with the reason so the client can log them (plan:
"Orice altceva primit de la LLM e respins și trecut în jurnal").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from pydantic import ValidationError

from assistant import cabin, media_search, music
from assistant.contract import Action, Event, State
from assistant.settings import cfg, poi_categories
from assistant.textutil import word_count

log = logging.getLogger("drivemate.assistant.actions")

#: "Permisă la" column of the plan table. "any" = oricând (any level, even P0-P2).
ALLOWED_LEVELS: dict[str, frozenset[str]] = {
    "speak": frozenset({"P3", "P4"}),
    "ask": frozenset({"P3", "P4"}),
    "suggest_media": frozenset({"P4"}),
    "play_media": frozenset({"P4"}),
    "stop_media": frozenset({"any"}),
    "read_message": frozenset({"P3", "P4"}),
    "reply_message": frozenset({"P3", "P4"}),
    "create_reminder": frozenset({"P3", "P4"}),
    "complete_reminder": frozenset({"any"}),
    "suggest_stop": frozenset({"P3", "P4"}),
    "delegate": frozenset({"P3"}),
    "show_on_screen": frozenset({"any"}),
    "set_preference": frozenset({"P4"}),
    "stay_silent": frozenset({"any"}),
    # P3 addition (YouTube, internal: resolved by the client into an ``ask`` with options).
    "search_media": frozenset({"P4"}),
}

#: "Cere confirmare" column of the plan table. ``read_message`` needs a confirmation
#: only when passengers are present (handled in :func:`needs_confirmation`).
CONFIRMATION_REQUIRED: frozenset[str] = frozenset({
    "suggest_media", "reply_message", "create_reminder", "complete_reminder",
    "suggest_stop", "set_preference",
})

#: Level used when core has not set ``safety.level`` (nothing happening = comfort).
DEFAULT_LEVEL = "P4"


@dataclass
class Rejected:
    """An action that did not pass validation.

    Attributes:
        raw: What the LLM sent (dict or Action).
        reason: Short machine-readable reason, e.g. ``"too_many_words"``.
    """

    raw: Any
    reason: str


@dataclass
class ValidationResult:
    """Outcome of :func:`validate_actions`.

    Attributes:
        accepted: Valid actions, in the LLM's order, with ``needs_confirmation`` set.
        rejected: Invalid actions with the reason (to be logged by the caller).
        accepted_indexes: For each accepted action, its index in the raw input list
            (lets the client match actions already spoken while streaming).
    """

    accepted: list[Action] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    accepted_indexes: list[int] = field(default_factory=list)


def current_level(state: State) -> str:
    """Safety level in force, defaulting to P4 when core has not set one."""
    return state.safety.level or DEFAULT_LEVEL


def level_allows(action_type: str, level: str) -> bool:
    """True when ``action_type`` is allowed at safety ``level`` (plan table)."""
    allowed = ALLOWED_LEVELS.get(action_type, frozenset())
    return "any" in allowed or level in allowed


def needs_confirmation(action: Action, state: State) -> bool:
    """Whether core must wait for a "yes" before executing (plan table + F2)."""
    if action.type == "read_message":
        return cabin.others_present(state)
    if action.type == "set_preference" and action.key == "volume" and cfg("music", "volume_without_confirmation",
                                                                         default=True):
        return False  # "mai încet" is done at once (assistant.yaml -> music.volume_without_confirmation)
    return action.type in CONFIRMATION_REQUIRED


def _word_limit(addressee: Optional[str]) -> int:
    """Max words for an utterance to this addressee (driver = strict rule)."""
    if addressee in (None, "driver", "all"):
        return int(cfg("speech", "max_words_to_driver", default=30))
    return int(cfg("speech", "max_words_to_passenger", default=30))


def _allowed_poi_ids(state: State, event: Optional[Event]) -> set[str]:
    """POIs the LLM may suggest: only those proposed by P2's rule (plan D3, K3).

    Sources: ``event.data["poi_id"]`` / ``event.data["poi_options"]`` of a
    ``stop_suggested`` event, ``state.trip.next_poi``, and the tourist sights ahead
    on the map route (``trip.attractions_ahead``, listed by P2's trip source).
    """
    ids: set[str] = set()
    if event is not None:
        if event.data.get("poi_id"):
            ids.add(str(event.data["poi_id"]))
        ids.update(str(p) for p in event.data.get("poi_options", []) or [])
    if state.trip.next_poi is not None:
        ids.add(state.trip.next_poi.id)
    for sight in (state.trip.model_extra or {}).get("attractions_ahead") or []:
        if isinstance(sight, dict) and sight.get("id"):
            ids.add(str(sight["id"]))
    return ids


def check_action(action: Action, state: State, event: Optional[Event] = None) -> Optional[str]:
    """Check one parsed action against the plan rules.

    Args:
        action: The parsed action.
        state: Current state (safety level, messages, occupants, ...).
        event: The event being answered (gives the POIs proposed by the rule).

    Returns:
        None if valid, otherwise a short reason string.
    """
    level = current_level(state)
    if not level_allows(action.type, level):
        return f"not_allowed_at_{level}"

    t = action.type
    if t == "speak":
        if not action.text:
            return "missing_text"
        if word_count(action.text) > _word_limit(action.to):
            return "too_many_words"
    elif t == "ask":
        if not action.question or action.expects is None:
            return "missing_question_or_expects"
        if word_count(action.question) > _word_limit(action.to):
            return "too_many_words"
        if action.expects == "choice" and not action.options:
            return "choice_without_options"
    elif t == "suggest_media":
        allowed = {track.id for track in music.candidates(state)}
        if action.track_id not in allowed:
            return "track_not_a_candidate"
    elif t == "play_media":
        if media_search.is_youtube_track(action.track_id):
            found = media_search.known(action.track_id)
            if found is None:
                return "youtube_track_not_found_by_search"
            if cabin.has_child(state) and not found.kid_safe:
                return "track_not_kid_safe"
            return None
        track = music.get_track(action.track_id)
        if track is None:
            return "unknown_track"
        if cabin.has_child(state) and not track.kid_safe:
            return "track_not_kid_safe"
    elif t == "search_media":
        if not cfg("youtube", "enabled", default=True):
            return "youtube_disabled"
        if not (action.query or "").strip():
            return "missing_query"
        if len(action.query) > 100:
            return "query_too_long"
        if action.kind is None:
            return "missing_kind"
    elif t in ("read_message", "reply_message"):
        message = next((m for m in state.messages if m.id == action.msg_id), None)
        if message is None:
            return "unknown_message"
        if t == "reply_message":
            if not message.replyable:
                return "message_not_replyable"
            if not action.text:
                return "missing_text"
    elif t == "create_reminder":
        if not action.task or action.trigger is None:
            return "missing_task_or_trigger"
        if action.trigger.type not in cfg("reminders", "trigger_types", default=["stop_at_category"]):
            return "unknown_trigger_type"
        if action.trigger.category not in poi_categories():
            return "unknown_category"
    elif t == "complete_reminder":
        if not any(r.id == action.reminder_id for r in state.reminders):
            return "unknown_reminder"
    elif t == "suggest_stop":
        if action.poi_id not in _allowed_poi_ids(state, event):
            return "poi_not_proposed_by_rule"
    elif t == "delegate":
        if not action.to_person or not action.task:
            return "missing_person_or_task"
        if action.to_person.lower() not in cabin.known_people(state):
            return "person_not_in_car"
        if action.to_person.lower() in ("driver",) or (
            cabin.driver_name(state) and action.to_person.lower() == cabin.driver_name(state).lower()
        ):
            return "cannot_delegate_to_driver"
    elif t == "show_on_screen":
        if not action.text:
            return "missing_text"
    elif t == "set_preference":
        limits = cfg("preferences", action.key or "", default=None)
        if limits is None:
            return "unknown_preference"
        if _is_numeric_range(limits):
            try:
                value = float(action.value)
            except (TypeError, ValueError):
                return "preference_not_a_number"
            if not limits[0] <= value <= limits[1]:
                return "preference_out_of_range"
        elif action.value not in limits:
            return "preference_value_not_allowed"
    elif t == "stay_silent":
        if not action.reason:
            return "missing_reason"
    return None


def question_as_ask(action: Action) -> Action:
    """Turn a ``speak`` to the driver that ends with a question mark into an ``ask``.

    Core opens the dialog window (no wake word needed for the answer, plan E1) only
    after an ``ask``. The LLM often asks with a plain ``speak`` ("Sunt bine. Cu ce te
    pot ajuta?"), and the driver's answer was then ignored or slow. The text is kept;
    ``expects="free"`` changes nothing in the dialog manager (no confirmation held).

    Args:
        action: Any parsed action.

    Returns:
        The ``ask`` version, or ``action`` unchanged.
    """
    if action.type != "speak" or action.to not in (None, "driver", "all"):
        return action
    text = (action.text or "").rstrip()
    if not text.endswith("?"):
        return action
    return action.model_copy(update={"type": "ask", "question": text, "text": None, "expects": "free"})


def _is_numeric_range(limits: Any) -> bool:
    """True for ``[min, max]`` numeric limits (vs. a list of allowed values)."""
    return (
        isinstance(limits, list) and len(limits) == 2
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in limits)
    )


def validate_actions(
    raw_actions: Iterable[Any],
    state: State,
    event: Optional[Event] = None,
    source: str = "LLM",
) -> ValidationResult:
    """Parse and validate a list of actions coming from the LLM (or a fallback).

    Args:
        raw_actions: Dicts (parsed JSON) or :class:`Action` objects.
        state: Current state.
        event: The event being answered.
        source: ``"LLM"`` or ``"RULE"``, written on every accepted action.

    Returns:
        A :class:`ValidationResult`. Only the first ``llm.max_actions`` valid
        actions are kept; extra ones are rejected with ``"over_max_actions"``.
    """
    result = ValidationResult()
    max_actions = int(cfg("llm", "max_actions", default=3))
    for index, raw in enumerate(raw_actions):
        try:
            action = raw if isinstance(raw, Action) else Action.model_validate(raw)
        except ValidationError as exc:
            result.rejected.append(Rejected(raw, f"schema:{exc.errors()[0].get('msg', 'invalid')}"))
            continue
        action = question_as_ask(action)
        reason = check_action(action, state, event)
        if reason is not None:
            result.rejected.append(Rejected(raw, reason))
            continue
        if len(result.accepted) >= max_actions:
            result.rejected.append(Rejected(raw, "over_max_actions"))
            continue
        action = action.model_copy(update={
            "source": source,
            "needs_confirmation": needs_confirmation(action, state),
        })
        result.accepted.append(action)
        result.accepted_indexes.append(index)

    for item in result.rejected:
        log.info("Rejected %s action %r: %s", source, item.raw, item.reason)
    return result
