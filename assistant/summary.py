"""State -> short text summary for the LLM (plan D1, section 8 rule 7).

The LLM never sees images or the raw ~10 Hz state: it gets about ten lines with
what matters for the decision (roluri/P3, step 2: safety level, F, D, cause, cabin,
messages, reminders, the driver's interaction preferences and the last 3 utterances). This keeps the request small and
fast, and is what the privacy slide promises (plan section 3: only the summarised
JSON state and the conversation / message text reach the cloud).
"""

from __future__ import annotations

import time
from typing import Iterable

from assistant import cabin, music, preferences
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


def _km(value: object) -> str:
    return f"{value:g} km" if isinstance(value, (int, float)) and not isinstance(value, bool) else "? km"


def _place_line(state: State) -> str:
    """Where the car is, in names from the map route (P4 simulator: ``trip.place``, an extra field of Trip).

    Names come from the route the user drew, never from coordinates: the LLM cannot misplace the car.
    """
    place = (state.trip.model_extra or {}).get("place")
    if not isinstance(place, dict) or not place.get("after"):
        return ""
    text = f"Location: after {place['after']} ({_km(place.get('after_km'))} behind)"
    if place.get("before"):
        text += f", before {place['before']} ({_km(place.get('before_km'))} ahead)"
    if place.get("destination"):
        text += f"; destination {place['destination']} in {_km(place.get('destination_km'))}"
    return text


def _attractions_line(state: State) -> str:
    """Tourist sights ahead on the map route (``trip.attractions_ahead``), with their id and description."""
    items = (state.trip.model_extra or {}).get("attractions_ahead") or []
    parts = []
    for item in items[:3]:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            continue
        part = (f"{item['name']} [{item['id']}] ({item.get('kind') or 'attraction'}, in {_km(item.get('dist_km'))}, "
                f"{_km(item.get('detour_km'))} off the road)")
        if item.get("description"):
            part += f': "{item["description"]}"'
        parts.append(part)
    return "Tourist sights ahead (facts only from these descriptions): " + "; ".join(parts) if parts else ""


def _trip_line(state: State) -> str:
    """Road, speed, time at the wheel, ETA, next stop; where the car is and the sights ahead (map route)."""
    trip = state.trip
    text = f"{trip.road}, {trip.speed_kmh:.0f} km/h, {trip.elapsed_min:.0f} min driving"
    if trip.eta_min is not None:
        text += f", ETA {trip.eta_min:.0f} min"
    if trip.stopped:
        poi_at = trip.at_poi
        text += ", STOPPED" + (f" at {poi_at.name or poi_at.id} [{poi_at.id}] ({poi_at.category})" if poi_at else "")
    if trip.next_poi:
        poi = trip.next_poi
        dist = f" in {poi.dist_km:g} km" if poi.dist_km is not None else ""
        text += f". Next stop: {poi.name or poi.id} [{poi.id}] ({poi.category}){dist}"
    for extra in (_place_line(state), _attractions_line(state)):
        if extra:
            text += f". {extra}"
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


def _alerts_line(state: State) -> str:
    """The active safety alert and the last eyes-closed episode (P2's rules), for "de ce m-ai alertat?".

    Without this line the LLM invented a reason ("o clipă de neatenție") in the baseline evaluation.
    Only what the state really holds: P2 does not keep alerts that already ended (except the
    drowsiness episodes), so "none recorded" is said explicitly.
    """
    safety = state.safety
    parts = [f"active {safety.alert} ({safety.level or 'P4'})" if safety.alert else "none active"]
    drowsy = safety.drowsiness
    if drowsy.last_episode_ts and drowsy.last_episode_ms:
        now = state.ts or time.time()
        ago = max(0.0, now - drowsy.last_episode_ts)
        parts.append(f"last eyes closed {drowsy.last_episode_ms / 1000.0:.1f} s, {ago:.0f} s ago "
                     f"({drowsy.episodes_10min} such closures in 10 min)")
    elif not safety.alert:
        parts.append("none recorded in this trip")
    return ", ".join(parts)


def _preferences_line(state: State) -> str:
    """How the driver wants the assistant to talk (``assistant/preferences.py``)."""
    prefs = preferences.effective(state)
    words = preferences.answer_words(state)
    answers = f"answers {prefs['answer_length']}" + (f" (aim for at most {words} words)" if words else "")
    return f"talkativeness {prefs['talkativeness']}, {answers}, follow-up question {prefs['follow_up']}"


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
        f"Safety: level {state.safety.level or 'P4'}, risk {a.risk}/3, monitoring {'ok' if state.safety.monitoring_ok else 'LOST'}. "
        f"Driver state: attention {_pct(a.attention)}, fatigue F {_pct(a.fatigue)}, disengagement D {_pct(a.disengagement)}, gaze {state.driver.gaze.zone}.",
        f"Alerts: {_alerts_line(state)}.",
        f"Distraction cause: {cause_text}.",
        f"Cabin: {_cabin_line(state)}.",
        f"Trip: {_trip_line(state)}.",
        f"Messages: {_messages_line(state)}.",
        f"Reminders: {_reminders_line(state)}. Valid reminder categories: {', '.join(poi_categories())}.",
        f"Media: {_media_line(state)}.",
        f"Assistant: {muted}. Trusted contact: {contact_text}.",
        f"Driver preferences: {_preferences_line(state)}.",
        f"Last utterances: {history}",
    ]
    return "\n".join(lines)
