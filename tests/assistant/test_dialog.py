"""Tests for assistant.dialog (confirmations, KSS, quiz), assistant.quiz and parse_kss."""

import pytest

from assistant.actions import validate_actions
from assistant.answers import InputEvent, parse_kss
from assistant.client import AssistantClient
from assistant.contract import Action, Event
from assistant.dialog import DialogManager
from assistant.fallback import build_fallback
from assistant.llm import OfflineProvider
from assistant.quiz import QuizSession, is_correct, load_questions
from p3_helpers import load_scene, make_state

NOW = 1763672400.0


def voice(text, ts=NOW + 1):
    return InputEvent("voice", text, ts)


def _held(raw, state=None):
    """Validated actions (so needs_confirmation is set like in the real flow)."""
    return validate_actions(raw, state or make_state()).accepted


REMINDER = [
    {"type": "create_reminder", "task": "lichid de parbriz", "trigger": {"type": "stop_at_category", "category": "fuel"}},
    {"type": "ask", "to": "driver", "question": "Notat: lichid de parbriz, la prima benzinărie. Bine?", "expects": "yes_no"},
]

# ----------------------------------------------------------------- KSS parsing (plan D3)


@pytest.mark.parametrize("text,value", [("7", 7), ("Cam șapte", 7), ("vreo opt", 8), ("Nouă.", 9),
                                         ("unu", 1), ("cred că 5, poate 6", 5), ("nu știu", None), ("10", None)])
def test_parse_kss(text, value):
    assert parse_kss(text) == value


# ----------------------------------------------------------------- confirmations (plan section 6, E3)


def test_register_holds_actions_needing_confirmation():
    dialog = DialogManager()
    immediate = dialog.register(_held(REMINDER), NOW)
    assert [a.type for a in immediate] == ["ask"]
    assert dialog.has_pending(NOW) and dialog.pending.kind == "confirm"


def test_yes_by_voice_executes_and_says_noted():
    dialog = DialogManager()
    dialog.register(_held(REMINDER), NOW)
    result = dialog.handle([voice("Da")], NOW + 2)
    assert result.handled and result.answer == "yes" and result.channel == "voice"
    assert [a.type for a in result.execute] == ["create_reminder"]
    assert result.execute[0].needs_confirmation is False
    assert result.speak[0].clip_id == "confirm_noted"
    assert not dialog.has_pending(NOW + 2)


def test_nod_counts_as_yes():
    dialog = DialogManager()
    dialog.register(_held(REMINDER), NOW)
    result = dialog.handle([InputEvent("nod", "yes", NOW + 1)], NOW + 2)
    assert result.answer == "yes" and result.channel == "nod"


def test_no_cancels_with_clip():
    dialog = DialogManager()
    dialog.register(_held(REMINDER), NOW)
    result = dialog.handle([InputEvent("gesture", "Thumb_Down", NOW + 1)], NOW + 2)
    assert result.answer == "no" and [a.type for a in result.cancelled] == ["create_reminder"]
    assert result.speak[0].clip_id == "confirm_cancelled" and not result.execute


def test_reply_yes_says_sent():
    dialog = DialogManager()
    dialog.register(_held([{"type": "ask", "to": "driver", "question": "Îi scriu: «Ajung la 18:40.» Trimit?", "expects": "yes_no"},
                           {"type": "reply_message", "msg_id": "m17", "text": "Ajung la 18:40."}]), NOW)
    result = dialog.handle([InputEvent("gesture", "Thumb_Up", NOW + 1)], NOW + 2)
    assert result.execute[0].type == "reply_message" and result.speak[0].clip_id == "confirm_sent"


def test_music_yes_becomes_play_media_with_cabin_volume():
    state = make_state(passenger={"awake": False})
    dialog = DialogManager()
    dialog.register(_held([{"type": "ask", "to": "driver", "question": "Pun ceva mai energic?", "expects": "yes_no"},
                           {"type": "suggest_media", "track_id": "t16", "reason": "disengagement"}], state), NOW)
    result = dialog.handle([voice("da, pune")], NOW + 2, state=state)
    assert result.execute[0].type == "play_media" and result.execute[0].track_id == "t16"
    assert result.execute[0].volume == 0.25


def test_music_no_triggers_quiz_offer_event():
    dialog = DialogManager()
    dialog.register(_held([{"type": "suggest_media", "track_id": "t16", "reason": "disengagement"}]), NOW)
    result = dialog.handle([voice("nu")], NOW + 2)
    assert [e.type for e in result.events] == ["media_declined"] and not result.speak


def test_unrelated_speech_is_not_an_answer():
    dialog = DialogManager()
    dialog.register(_held(REMINDER), NOW)
    assert dialog.handle([voice("cât mai e până la Timișoara")], NOW + 2).handled is False
    assert dialog.has_pending(NOW + 2)


def test_unanswered_question_expires_without_executing():
    dialog = DialogManager()
    dialog.register(_held(REMINDER), NOW)
    result = dialog.expire(NOW + 60)
    assert result.answer == "timeout" and [a.type for a in result.cancelled] == ["create_reminder"]
    assert dialog.handle([voice("da")], NOW + 61).handled is False


# ----------------------------------------------------------------- KSS (plan D3, D10)


def _kss_dialog():
    dialog = DialogManager()
    dialog.register([Action(type="ask", to="driver", question="Cât de obosit ești, de la 1 la 9?", expects="kss")], NOW)
    return dialog


def test_kss_value_becomes_event():
    result = _kss_dialog().handle([voice("cam șapte")], NOW + 2)
    assert result.events[0].type == "kss_answer" and result.events[0].data == {"value": 7}


def test_refusal_during_kss_becomes_driver_refused():
    result = _kss_dialog().handle([voice("lasă-mă în pace")], NOW + 2)
    assert result.events[0].type == "driver_refused"
    result = _kss_dialog().handle([InputEvent("gesture", "Open_Palm", NOW + 1)], NOW + 2)
    assert result.events[0].type == "driver_refused"


@pytest.mark.parametrize("value,expected", [(8, "Ok, 8 e mult. Hai să găsim o pauză."),
                                            (5, "Înțeles. Mai vorbim puțin, te ține treaz."),
                                            (2, "Bine. Spune-mi dacă obosești.")])
def test_kss_answer_fallback_texts(value, expected):
    raw = build_fallback(Event(type="kss_answer", data={"value": value}), make_state())
    assert raw[0]["text"] == expected


# ----------------------------------------------------------------- quiz (plan D8)


def test_media_declined_is_deterministic_quiz_offer():
    event = Event(type="media_declined", ts=NOW)
    client = AssistantClient(OfflineProvider())
    import asyncio

    actions = asyncio.run(client.handle_event(event, make_state(), now=NOW))
    assert actions[0].type == "ask" and actions[0].reason == "quiz_offer"
    assert client.last_result.reason == "deterministic"


def _quiz_offer_dialog():
    dialog = DialogManager()
    dialog.register([Action(type="ask", to="driver", question="Bine. Vrei un quiz scurt?", expects="free",
                            reason="quiz_offer", source="RULE")], NOW)
    return dialog


def test_yes_to_quiz_offer_asks_first_question():
    dialog = _quiz_offer_dialog()
    result = dialog.handle([voice("da")], NOW + 2, state=make_state())
    assert result.answer == "quiz" and result.speak[0].type == "ask"
    assert dialog.pending.kind == "quiz_answer"


def test_full_quiz_counts_score():
    dialog = _quiz_offer_dialog()
    dialog.handle([voice("quiz")], NOW + 2, state=make_state())
    quiz = dialog.pending.quiz
    for i in range(quiz.total):
        right = quiz.current.answers[0]
        result = dialog.handle([voice(f"cred că {right}" if i else "habar n-am", NOW + 3 + i)], NOW + 3 + i)
    assert dialog.pending is None
    assert result.speak[-1].text == f"Gata quizul: {quiz.total - 1} din {quiz.total}. Bravo!"


def test_quiz_can_be_stopped():
    dialog = _quiz_offer_dialog()
    dialog.handle([voice("da")], NOW + 2, state=make_state())
    result = dialog.handle([voice("gata, ajunge")], NOW + 3)
    assert result.speak[0].text == "Bine, oprim quizul." and dialog.pending is None


def test_no_to_quiz_offer():
    result = _quiz_offer_dialog().handle([voice("nu")], NOW + 2, state=make_state())
    assert result.answer == "no" and result.speak[0].clip_id == "confirm_ok"


def test_quiz_questions_are_short_and_answerable():
    from assistant.textutil import word_count

    questions = load_questions()
    assert len(questions) >= 10
    for question in questions:
        assert word_count(question.q) <= 15
        assert is_correct(question, question.answers[0])


def test_quiz_session_kid_safe_and_length():
    quiz = QuizSession(kid_safe_only=True, length=3, seed=1)
    assert quiz.total == 3 and all(q.kid_safe for q in quiz.questions)


# ----------------------------------------------------------------- "Te mai ajut cu ceva?" (speech.follow_up)

FOLLOW_UP = Action(type="ask", to="driver", question="Te mai ajut cu ceva?", expects="free",
                   reason="follow_up", source="RULE")
STATEMENT = Action(type="speak", to="driver", text="Mai avem 20 de minute.", source="LLM")


def _follow_up_dialog():
    """A dialog manager right after "Mai avem 20 de minute. Te mai ajut cu ceva?"."""
    dialog = DialogManager()
    dialog.register([STATEMENT, FOLLOW_UP], NOW)
    assert dialog.pending is not None and dialog.pending.kind == "follow_up"
    return dialog


@pytest.mark.parametrize("text", ["Nu", "nu, mersi", "Nimic.", "gata", "Atât, mersi", "nu mai am nevoie", "Mersi"])
def test_follow_up_no_is_silent(text):
    dialog = _follow_up_dialog()
    result = dialog.handle([voice(text)], NOW + 1)
    assert result.handled and result.answer == "no"
    assert not result.speak and not result.events and not result.execute
    assert dialog.pending is None


@pytest.mark.parametrize("inputs", [[voice("da")], [voice("Da, te rog")], [InputEvent("gesture", "Thumb_Up", NOW + 1)]])
def test_follow_up_yes_alone_asks_again(inputs):
    dialog = _follow_up_dialog()
    result = dialog.handle(inputs, NOW + 1)
    assert result.handled and result.answer == "yes"
    assert [(a.type, a.question, a.expects) for a in result.speak] == [("ask", "Spune.", "free")]


def test_follow_up_no_then_request_passes_the_request_on():
    dialog = _follow_up_dialog()
    result = dialog.handle([voice("Nu, pune niște muzică")], NOW + 1)
    assert result.handled and not result.speak
    assert [(e.type, e.data["text"]) for e in result.events] == [("driver_speech", "pune niște muzică")]


@pytest.mark.parametrize("text", ["pune muzică", "Cât mai e până ajungem?", "nu, mersi, dar pune muzică"])
def test_follow_up_request_is_normal_speech(text):
    """A request without a plain yes / no goes to the LLM as usual (handled=False or passed on)."""
    dialog = _follow_up_dialog()
    result = dialog.handle([voice(text)], NOW + 1)
    assert not result.speak
    assert not result.handled or [e.type for e in result.events] == ["driver_speech"]
    assert dialog.pending is None


@pytest.mark.asyncio
async def test_client_adds_follow_up_after_a_statement_to_the_driver():
    from p3_helpers import FakeProvider

    _, state = load_scene("scene3_message")
    client = AssistantClient(FakeProvider({"actions": [{"type": "speak", "to": "driver", "text": "Mai avem 20 de minute."}]}))
    actions = await client.handle_event({"type": "driver_speech", "data": {"text": "cât mai e?"}}, state, now=NOW)
    assert [(a.type, a.reason) for a in actions] == [("speak", None), ("ask", "follow_up")]
    assert actions[1].question == "Te mai ajut cu ceva?" and actions[1].expects == "free"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    {"actions": [{"type": "ask", "to": "driver", "question": "Pun ceva rock?", "expects": "yes_no"}]},  # already a question
    {"actions": [{"type": "speak", "to": "driver", "text": "Sunt bine. Cu ce te pot ajuta?"}]},     # becomes an ask
    {"actions": [{"type": "stay_silent", "reason": "driver_refused"}]},                              # refusal
])
async def test_client_no_follow_up_after_questions_or_refusals(answer):
    from p3_helpers import FakeProvider

    _, state = load_scene("scene3_message")
    client = AssistantClient(FakeProvider(answer))
    actions = await client.handle_event({"type": "driver_speech", "data": {"text": "salut"}}, state, now=NOW)
    assert not any(a.reason == "follow_up" for a in actions)


@pytest.mark.asyncio
async def test_client_no_follow_up_after_proactive_events():
    """Only answers to the driver get it: never "Andrei, ochii pe drum. Te mai ajut cu ceva?"."""
    event, state = load_scene("scene4_passenger_phone")
    actions = await AssistantClient(OfflineProvider()).handle_event(event, state, now=NOW)
    assert actions and not any(a.reason == "follow_up" for a in actions)


@pytest.mark.asyncio
async def test_client_follow_up_can_be_disabled(monkeypatch):
    from assistant.settings import get_config
    from p3_helpers import FakeProvider

    monkeypatch.setitem(get_config()["speech"], "follow_up", {"enabled": False})
    _, state = load_scene("scene3_message")
    client = AssistantClient(FakeProvider({"actions": [{"type": "speak", "to": "driver", "text": "Mai avem 20 de minute."}]}))
    actions = await client.handle_event({"type": "driver_speech", "data": {"text": "cât mai e?"}}, state, now=NOW)
    assert [a.type for a in actions] == ["speak"]
