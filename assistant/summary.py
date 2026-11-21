"""State -> short text summary for the LLM (plan D1, section 8 rule 7).

The LLM never sees images or the raw ~10 Hz state: it gets about ten lines with
what matters for the decision (roluri/P3, step 2: safety level, F, D, cause, cabin,
messages, reminders and the last 3 utterances). This keeps the request small and
fast, and is what the privacy slide promises (plan section 3: only the summarised
JSON state and the conversation / message text reach the cloud).
"""

from __future__ import annotations

import time
from typing import Iterable

from assistant import cabin, music
from assistant.contract import Event, State
from assistant.memory import Turn
from assistant.settings import cfg, poi_categories


def _pct(value: float) -> str:
    """0.61 -> ``"0.61"`` (two decimals, compact)."""
    return f"{value:.2f}"


def _cabin_line(state: State) -> str:
    """Who is in the car, awake / asleep, phone in hand, talking."""
    parts = []
    driver = cabin.driver_name(state) or "unknown"
    parts.append(f"driver {driver}")
    if state.passenger.present:
        flags = ["awake" if state.passenger.awake else "ASLEEP"]
        if state.passenger.holding_phone:
            flags.append("holding phone")
        if state.passenger.speaking:
            flags.append("speaking")
        parts.append(f"front passenger {cabin.passenger_name(state) or 'unknown'} ({', '.join(flags)})")
    for person in state.occupants:
        if person.seat == "rear":
            parts.append(f"rear {cabin.display_name(person.profile) or 'unknown'} ({person.role}, declared)")
    line = "; ".join(parts)
    if state.conversation:
        line += ". People are talking to each other."
    return line


def _trip_line(state: State) -> str:
    """Road, speed, time at the wheel, ETA, next stop."""
    trip = state.trip
    text = f"{trip.road}, {trip.speed_kmh:.0f} km/h, {trip.elapsed_min:.0f} min driving"
    if trip.eta_min is not None:
        text += f", ETA {trip.eta_min:.0f} min"
    if trip.stopped:
        text += ", STOPPED" + (f" at {trip.at_poi.id} ({trip.at_poi.category})" if trip.at_poi else "")
    if trip.next_poi:
        poi = trip.next_poi
        dist = f" in {poi.dist_km:g} km" if poi.dist_km is not None else ""
        text += f". Next stop: {poi.name or poi.id} [{poi.id}] ({poi.category}){dist}"
    return text


def _messages_line(state: State) -> str:
    """Queued messages with id, app, sender, state (text only if core included it)."""
    if not state.messages:
        return "none"
    items = []
    for msg in state.messages[-4:]:
        item = f"{msg.id} {msg.app} from {msg.from_ or '?'} [{msg.state}{', replyable' if msg.replyable else ''}]"
        if msg.text:
            item += f' "{msg.text}"'
        items.append(item)
    return "; ".join(items)


def _reminders_line(state: State) -> str:
    """Reminders with id, task, trigger category and state."""
    if not state.reminders:
        return "none"
    return "; ".join(
        f'{r.id} "{r.task}" at {r.trigger.category or r.trigger.type} [{r.state}]' for r in state.reminders
    )


def _media_line(state: State) -> str:
    """What is playing and which tracks may be suggested now."""
    now = "nothing playing"
    if state.media.playing:
        now = f"playing {state.media.track_id} \"{state.media.title or ''}\""
    youtube = "YouTube search on" if cfg("youtube", "enabled", default=True) else "YouTube search off"
    found = music.candidates(state)
    if found:
        options = ", ".join(f"{t.id} ({t.genre}, energy {t.energy}) \"{t.title}\"" for t in found)
        return f"{now}. {youtube}. Tracks you may suggest: {options}"
    return f"{now}. {youtube}. No track available to suggest."


def summarize(state: State, event: Event, turns: Iterable[Turn] = ()) -> str:
    """Build the ~10-line text the LLM receives for one event.

    Args:
        state: Current state.
        event: The event to answer (type and data are included verbatim).
        turns: Recent utterances from :class:`assistant.memory.ShortMemory`.

    Returns:
        A plain-text block, one fact per line.
    """
    a = state.assessment
    cause = state.cause
    cause_text = "none"
    if cause.label:
        cause_text = f"{cause.label} (target {cause.target}, {cause.glances_30s} glances in 30 s, conf {_pct(cause.conf)})"
    muted = "MUTED after refusal" if state.assistant.muted_until else "not muted"
    contact = state.safe_contact
    contact_text = f"{contact.name} (configured)" if contact.configured and contact.name else "none"
    history = " | ".join(f"{t.speaker}: {t.text}" for t in turns) or "none"
    data = ", ".join(f"{k}={v}" for k, v in event.data.items()) or "-"

    clock = time.strftime("%H:%M", time.localtime(state.ts or event.ts or time.time()))

    lines = [
        f"EVENT: {event.type} ({data}). Local time {clock}.",
        f"Safety: level {state.safety.level or 'P4'}, risk {a.risk}/3, monitoring {'ok' if state.safety.monitoring_ok else 'LOST'}.",
        f"Driver state: attention {_pct(a.attention)}, fatigue F {_pct(a.fatigue)}, disengagement D {_pct(a.disengagement)}, gaze {state.driver.gaze.zone}.",
        f"Distraction cause: {cause_text}.",
        f"Cabin: {_cabin_line(state)}.",
        f"Trip: {_trip_line(state)}.",
        f"Messages: {_messages_line(state)}.",
        f"Reminders: {_reminders_line(state)}. Valid reminder categories: {', '.join(poi_categories())}.",
        f"Media: {_media_line(state)}.",
        f"Assistant: {muted}. Trusted contact: {contact_text}.",
        f"Last utterances: {history}",
    ]
    return "\n".join(lines)
