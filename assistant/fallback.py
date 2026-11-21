"""Fixed answers used without the LLM (plan C9, D1, C6).

Used when:

* no API key / model is configured (the jury can run the project without a key);
* the director switched the LLM off (plan C6: "safety works identically");
* the LLM did not answer within ``llm.timeout_s`` (2.5 s);
* the LLM answered but every action was rejected by validation.

Each event type gets a short, deterministic answer built from
``assistant/config/texts.<language>.yaml``. The answers are real actions (the same
ones the LLM could return), validated by ``assistant/actions.py`` and marked
``source = "RULE"``.
"""

from __future__ import annotations

from typing import Any, Callable

from assistant import cabin, media_search, music
from assistant.contract import Action, Event, State
from assistant.settings import cfg, get_texts
from assistant.textutil import fill, word_count

_DEFAULT_NAME = ""  # placeholder used when a name is unknown ("Salut ." is avoided by fill())


def _t(key: str, *subkeys: str) -> Any:
    """Read a text from the ``fallback`` group of texts.<language>.yaml."""
    node: Any = get_texts().get("fallback", {}).get(key)
    for sub in subkeys:
        node = node.get(sub) if isinstance(node, dict) else None
    return node


def _names(state: State) -> dict[str, Any]:
    """Placeholder values for names in the current cabin."""
    return {
        "driver": cabin.driver_name(state),
        "passenger": cabin.passenger_name(state),
        "child": cabin.child_name(state),
        "contact": state.safe_contact.name,
    }


def _speak(text: str, to: str = "driver", clip_id: str | None = None) -> dict[str, Any]:
    """Build a raw ``speak`` action."""
    return {"type": "speak", "to": to, "text": text, "clip_id": clip_id}


def _ask(question: str, expects: str = "yes_no", to: str = "driver") -> dict[str, Any]:
    """Build a raw ``ask`` action."""
    return {"type": "ask", "to": to, "question": question, "expects": expects}


def _message_sender(state: State, msg_id: Any) -> str | None:
    """Spoken name of the sender of message ``msg_id``."""
    message = next((m for m in state.messages if m.id == msg_id), None)
    return message.from_ if message else None


# --- one builder per event type -------------------------------------------------

def _trip_start(event: Event, state: State) -> list[dict]:
    """Scene 1 greeting: names the driver (and the front passenger if present)."""
    names = _names(state)
    key = "trip_start_with_passenger" if names["passenger"] else "trip_start_driver_only"
    return [_speak(fill(_t(key), **names))]


def _cause_detected(event: Event, state: State) -> list[dict]:
    """Plan D2: resolve the distraction cause (delegate to the passenger, or 'ți-l citesc eu')."""
    names = _names(state)
    label = state.cause.label or event.data.get("label") or "default"
    entry = _t("cause", label) or _t("cause", "default")
    if isinstance(entry, dict):  # passenger_showing_phone: delegate + speak (plan D2)
        actions: list[dict] = []
        if names["passenger"]:
            actions.append(_speak(fill(entry["to_passenger"], **names), to="passenger"))
            actions.append({"type": "delegate", "to_person": names["passenger"], "task": "tell_story"})
        actions.append(_speak(fill(entry["to_driver"], **names)))
        return actions
    return [_speak(fill(entry, **names))]


def _fatigue_high(event: Event, state: State) -> list[dict]:
    """Plan D3/D10: start the keep-awake conversation with the KSS question (1-9)."""
    return [_ask(fill(_t("fatigue_kss"), **_names(state)), expects="kss")]


def _disengagement_high(event: Event, state: State) -> list[dict]:
    """Plan D8: propose energetic music from the driver's tastes (quiz if no track fits)."""
    track = music.pick_track(state, "disengagement")
    if track is None:
        return [_ask(_t("disengagement_no_music"))]
    return [
        _ask(_t("disengagement_music")),
        {"type": "suggest_media", "track_id": track.id, "reason": "disengagement"},
    ]


def _media_declined(event: Event, state: State) -> list[dict]:
    """Plan D8: music refused -> offer a quiz (or a podcast, if the catalog has one).

    The question carries ``reason="quiz_offer"`` so ``assistant/dialog.py`` knows the
    next "da" / "quiz" / "podcast" answer starts the quiz or plays the podcast.
    """
    key = "media_declined_with_podcast" if music.podcasts(state) else "media_declined"
    question = _ask(_t(key), expects="free")
    question["reason"] = "quiz_offer"
    return [question]


def _kss_answer(event: Event, state: State) -> list[dict]:
    """Plan D3: acknowledge the KSS value; P2's rule picks the actual stop for high values."""
    value = event.data.get("value")
    if not isinstance(value, int):
        return []
    high = int(cfg("kss", "high", default=7))
    mid = int(cfg("kss", "mid", default=5))
    key = "kss_high" if value >= high else "kss_mid" if value >= mid else "kss_low"
    return [_speak(fill(_t(key), value=value))]


def _message(event: Event, state: State) -> list[dict]:
    """Plan F2/F8: announce a message; ask first unless P2 said delivery='read'."""
    msg_id = event.data.get("msg_id")
    sender = _message_sender(state, msg_id) or event.data.get("from")
    if event.data.get("delivery") == "read":
        return [
            _speak(fill(_t("message_read_intro"), sender=sender)),
            {"type": "read_message", "msg_id": msg_id},
        ]
    return [
        _ask(fill(_t("message_ask"), sender=sender)),
        {"type": "read_message", "msg_id": msg_id},
    ]


def _reply_dictated(event: Event, state: State) -> list[dict]:
    """Plan F3: repeat the dictated reply and ask for confirmation before sending."""
    msg_id = event.data.get("msg_id")
    # Trailing punctuation removed so the template does not produce "minute.. Trimit?".
    text = (event.data.get("text") or "").strip().rstrip(".!?… ")
    sender = _message_sender(state, msg_id)
    question = fill(_t("reply_confirm"), text=text)
    if word_count(question) > 15:
        question = fill(_t("reply_confirm_long"), sender=sender)
    return [_ask(question), {"type": "reply_message", "msg_id": msg_id, "text": text}]


def _stop_suggested(event: Event, state: State) -> list[dict]:
    """Plan K3/D3: phrase the stop chosen by P2's rule (with the open reminder task)."""
    data = event.data
    key = "stop_suggest_with_task" if data.get("task") else "stop_suggest"
    km = data.get("dist_km")
    km_text = f"{km:g}" if isinstance(km, (int, float)) else km
    question = fill(_t(key), poi=data.get("poi_name") or data.get("poi_id"), km=km_text, task=data.get("task"))
    return [_ask(question), {"type": "suggest_stop", "poi_id": data.get("poi_id")}]


def _alert_explain(event: Event, state: State) -> list[dict]:
    """Plan D5: say P2's one-sentence explanation of the last alert."""
    explanation = event.data.get("explanation")
    if not explanation:
        return []
    return [_speak(fill(_t("alert_explain"), explanation=explanation))]


def _driver_refused(event: Event, state: State) -> list[dict]:
    """Plan D10: 'Ok, te las în pace.' (pre-generated clip) and stay silent."""
    return [
        _speak(_t("refusal_ack"), clip_id="refusal_ack"),
        {"type": "stay_silent", "reason": "driver_refused"},
    ]


def _not_understood(event: Event, state: State) -> list[dict]:
    """Free request that cannot be handled without the LLM."""
    return [_speak(_t("not_understood"))]


def _speech(event: Event, state: State) -> list[dict]:
    """Free request without the LLM: a music / podcast request still works (YouTube search), else 'n-am înțeles'."""
    found = media_search.media_request(str(event.data.get("text", "")))
    if found is not None and cfg("youtube", "enabled", default=True):
        query, kind = found
        return [{"type": "search_media", "query": query, "kind": kind}]
    return _not_understood(event, state)


#: Event type -> builder. Unknown events get :func:`_not_understood` for speech
#: events and an empty answer otherwise.
BUILDERS: dict[str, Callable[[Event, State], list[dict]]] = {
    "trip_start": _trip_start,
    "cause_detected": _cause_detected,
    "fatigue_high": _fatigue_high,
    "disengagement_high": _disengagement_high,
    "media_declined": _media_declined,
    "kss_answer": _kss_answer,
    "message_received": _message,
    "safe_contact_reply": _message,
    "message_reply_dictated": _reply_dictated,
    "stop_suggested": _stop_suggested,
    "alert_explain": _alert_explain,
    "driver_refused": _driver_refused,
    "driver_speech": _speech,
    "passenger_speech": _speech,
}


def build_fallback(event: Event, state: State) -> list[dict]:
    """Return the raw fixed actions for ``event`` (not validated yet).

    Args:
        event: The event from core.
        state: Current state.

    Returns:
        Raw action dicts; validate them with ``assistant.actions.validate_actions``
        (``source="RULE"``). Empty list when there is nothing sensible to say.
    """
    builder = BUILDERS.get(event.type)
    return builder(event, state) if builder else []


def silent(reason: str) -> Action:
    """A ``stay_silent`` action with ``source = "RULE"`` (used by policies)."""
    return Action(type="stay_silent", reason=reason, source="RULE")
