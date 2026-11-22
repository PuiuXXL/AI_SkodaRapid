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

from assistant import cabin, media_search, music, preferences
from assistant.contract import Action, Event, State
from assistant.settings import cfg, get_texts
from assistant.textutil import fill, normalize, word_count

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
    if word_count(question) > int(cfg("speech", "max_words_to_driver", default=30)):
        question = fill(_t("reply_confirm_long"), sender=sender)
    return [_ask(question), {"type": "reply_message", "msg_id": msg_id, "text": text}]


def _stop_suggested(event: Event, state: State) -> list[dict]:
    """Plan K3/D3: phrase the stop chosen by P2's rule (with the open reminder task)."""
    data = event.data
    key = "stop_suggest_with_task" if data.get("task") else "stop_suggest"
    km = data.get("dist_km")
    km_text = f"{km:g}" if isinstance(km, (int, float)) else km
    if data.get("kind") == "attraction":  # K4: a tourist sight on the map route; "peste 13 km" is easier to say
        key = "stop_suggest_attraction"
        if isinstance(km, (int, float)) and km >= 2:
            km_text = f"{round(km)}"
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


#: Words that ask to stop / pause (normalised) and words that name what is playing.
_STOP_VERBS = frozenset({"opreste", "opresti", "oprim", "stop", "stopeaza", "inchide", "taie", "pauza", "ajunge"})
_MEDIA_WORDS = frozenset({"muzica", "muzicii", "melodia", "melodie", "piesa", "cantecul", "podcastul", "podcast",
                          "play", "radio", "redarea", "sunetul"})
#: "Oprește aici / la OMV / mașina" is about stopping the car, never the music.
_PLACE_WORDS = frozenset({"aici", "acolo", "la", "masina", "benzinarie", "dreapta"})


def stop_media_request(text: str, state: State) -> bool:
    """ "Oprește muzica" / "oprește ce dă play acum" / just "stop" while something plays.

    A stop word plus a media word, or a stop word alone (at most two words) while media is
    playing. "Oprește la OMV" (stop the car) is not a media request.
    """
    tokens = normalize(text).split()
    if not _STOP_VERBS & set(tokens) or _PLACE_WORDS & set(tokens):
        return False
    return bool(_MEDIA_WORDS & set(tokens)) or (state.media.playing and len(tokens) <= 2)


_VOLUME_WORDS = frozenset({"volumul", "volum", "sonorul", "sunetul", "muzica", "muzicii", "melodia", "piesa",
                           "podcastul"})
_QUIETER = frozenset({"incet", "incetisor", "jos", "scade", "scazi", "redu", "reduce", "micsoreaza", "coboara"})
_LOUDER = frozenset({"tare", "sus", "creste", "cresti", "mareste", "maresti", "urca"})
#: "Vorbește mai încet" / "mergi mai încet" are about speech or speed, not the volume.
_NOT_VOLUME = frozenset({"vorbeste", "vorbesti", "vorbiti", "vorbesc", "mergi", "merg", "conduci", "conduc", "viteza",
                         "ruleaza", "citeste", "spune",
                         "ceva"})  # "pune ceva mai tare" asks for another track (a search), not the volume
_VOLUME_MAX_WORDS = 7


def volume_request(text: str, state: State) -> float | None:
    """The new volume (0-1) asked by "mai încet", "dă mai tare", "e prea tare", "la jumătate", "volumul la 30".

    Only while media plays or when the volume / music is named, in a short sentence, and not about
    speech or speed. Relative steps use ``music.volume_step`` ("foarte" doubles it, "prea" inverts the
    direction: "prea tare" = quieter); the result stays within ``[music.volume_min, 1]``.
    """
    tokens = normalize(text).split()
    words = set(tokens)
    if not tokens or len(tokens) > _VOLUME_MAX_WORDS or words & _NOT_VOLUME:
        return None
    if not (state.media.playing or words & _VOLUME_WORDS):
        return None
    low = float(cfg("music", "volume_min", default=0.05))
    numbers = [int(t) for t in tokens if t.isdigit()]
    if numbers and words & (_VOLUME_WORDS | {"la", "suta", "procent", "procente"}):
        value = numbers[0] / (10 if numbers[0] <= 10 else 100)
    elif "jumatate" in words:
        value = 0.5
    elif words & {"maxim", "maximum", "maximul"}:
        value = 1.0
    elif words & {"minim", "minimum", "minimul"}:
        value = low
    else:
        down, up = bool(words & _QUIETER), bool(words & _LOUDER)
        if down == up:
            return None
        if "prea" in words:  # "e prea tare" = make it quieter
            down, up = up, down
        step = float(cfg("music", "volume_step", default=0.2)) * (2 if "foarte" in words else 1)
        current = state.media.volume if state.media.volume is not None else music.volume_for(state)
        value = current - step if down else current + step
    return round(min(1.0, max(low, value)), 2)


def media_command(text: str, state: State) -> bool:
    """True for a stop / volume / preference command, answered at once without the LLM (``assistant/client.py``)."""
    return (stop_media_request(text, state) or volume_request(text, state) is not None
            or preferences.voice_command(text) is not None)


def _preference(key: str, value: str, state: State) -> list[dict]:
    """ "Răspund mai scurt. Bine?" + the held ``set_preference``, or "E deja așa." when nothing changes."""
    if preferences.effective(state).get(key) == value:
        return [_speak(_t("preference_already") or "Ok.")]
    question = _t("preference_confirm", key, value) or _t("not_understood")
    return [{"type": "set_preference", "key": key, "value": value}, _ask(question)]


_THANKS = frozenset({"multumesc", "multumim", "mersi", "merci", "ms", "multam"})
#: Words that may come with a thank-you without turning it into a request.
_THANKS_FILLERS = frozenset({"mult", "frumos", "foarte", "iti", "va", "tie", "drivemate", "bine", "ok", "okay",
                             "super", "perfect", "bravo", "si", "pentru", "tot", "asta"})


def thanks(text: str) -> bool:
    """ "Mulțumesc mult." / "Mersi, DriveMate!": only thanks, no request (answered without the LLM).

    The baseline evaluation showed the LLM often returns stay_silent to a plain thank-you, which
    then became "n-am înțeles". "Mulțumesc, cât mai am?" still goes to the LLM.
    """
    tokens = normalize(text).split()
    return bool(tokens) and bool(_THANKS & set(tokens)) and set(tokens) <= (_THANKS | _THANKS_FILLERS)


#: LLM failures on a request that was understood: the driver hears "mi-a scăpat", not "n-am înțeles".
LLM_FAILURES = frozenset({"timeout", "llm_error", "invalid_json", "truncated"})


def _speech(event: Event, state: State, reason: str | None = None) -> list[dict]:
    """Handle music controls, preferences, YouTube requests and thanks without the LLM.

    ``reason`` is why the LLM did not answer (``assistant/client.py``): after an LLM failure the
    request was understood, so the driver is asked to repeat with ``llm_hiccup`` instead.
    """
    ok = _speak(get_texts().get("clips", {}).get("confirm_ok", "Ok."), clip_id="confirm_ok")
    text = str(event.data.get("text", ""))
    if thanks(text):
        return [{**_speak(_t("thanks")), "reason": "closing"}]
    if stop_media_request(text, state):
        return [{"type": "stop_media"}, ok]
    volume = volume_request(text, state)
    if volume is not None:
        return [{"type": "set_preference", "key": "volume", "value": volume}, ok]
    wanted = preferences.voice_command(text)
    if wanted is not None:
        return _preference(*wanted, state)
    found = media_search.media_request(text)
    if found is not None and cfg("youtube", "enabled", default=True):
        query, kind = found
        return [{"type": "search_media", "query": query, "kind": kind}]
    if media_search.wants_music(text):  # plain "pune muzică": a track from the catalog, after a "yes"
        track = music.pick_track(state, "request")
        if track is not None:
            return [_ask(_t("music_offer")), {"type": "suggest_media", "track_id": track.id, "reason": "driver_request"}]
    if reason in LLM_FAILURES:
        return [_speak(_t("llm_hiccup"))]
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


def build_fallback(event: Event, state: State, reason: str | None = None) -> list[dict]:
    """Return the raw fixed actions for ``event`` (not validated yet).

    Args:
        event: The event from core.
        state: Current state.
        reason: Why the fixed text is used (``AnswerInfo.reason``); changes only the
            answer to a direct request after an LLM failure.

    Returns:
        Raw action dicts; validate them with ``assistant.actions.validate_actions``
        (``source="RULE"``). Empty list when there is nothing sensible to say.
    """
    if event.type in ("driver_speech", "passenger_speech"):
        return _speech(event, state, reason)
    builder = BUILDERS.get(event.type)
    return builder(event, state) if builder else []


def confirmation_question(action: Action, state: State) -> str:
    """The question for an action that needs a "yes" when the LLM forgot to ask it.

    Seen in the baseline evaluation: "Citește-mi mesajele" with a passenger on board ->
    the LLM returns ``read_message`` alone; it is held for a "yes" that nobody asked for,
    and the driver heard "n-am înțeles".
    """
    t = action.type
    if t == "read_message":
        return fill(_t("confirm_read"), sender=_message_sender(state, action.msg_id))
    if t == "suggest_stop":
        poi = state.trip.next_poi
        name = poi.name if poi is not None and poi.id == action.poi_id and poi.name else None
        for sight in (state.trip.model_extra or {}).get("attractions_ahead") or []:
            if isinstance(sight, dict) and sight.get("id") == action.poi_id:
                name = sight.get("name") or name
        return fill(_t("confirm_stop"), poi=name or action.poi_id)
    if t == "create_reminder" and action.trigger is not None:
        places = _t("reminder_places") or {}
        place = places.get(action.trigger.category or "") or places.get("default")
        return fill(_t("confirm_reminder"), task=action.task, place=place)
    if t == "reply_message":
        return fill(_t("confirm_reply"), text=(action.text or "").strip().rstrip(".!?… "))
    if t == "suggest_media":
        track = music.get_track(action.track_id)
        return fill(_t("confirm_media"), title=track.title if track else action.track_id)
    if t == "complete_reminder":
        task = next((r.task for r in state.reminders if r.id == action.reminder_id), None)
        return fill(_t("confirm_complete"), task=task)
    return _t("confirm_generic")


def silent(reason: str) -> Action:
    """A ``stay_silent`` action with ``source = "RULE"`` (used by policies)."""
    return Action(type="stay_silent", reason=reason, source="RULE")
