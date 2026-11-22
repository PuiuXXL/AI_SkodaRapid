"""Tests for core/assistant_link.py (C), core/validator.py (C8), core/messages_timing.py (F2) and core/reminders.py
(K3): events to P3's assistant, actions checked and executed, answers on every channel, scenes 1, 3 and 5 (D4)."""

from __future__ import annotations

from typing import Any

import pytest
from p2_helpers import ALARM_S, ASK_AFTER, FakeClient, Rig

from assistant.client import AnswerInfo, AssistantClient
from core import messages_timing, validator
from core.reminders import pick_stop
from core.settings import th
from shared import contracts as c

pytestmark = pytest.mark.asyncio


def speak(text: str, **kwargs: Any) -> c.Action:
    return c.Action(type="speak", to="driver", text=text, **kwargs)


def ask(question: str, expects: str = "yes_no", **kwargs: Any) -> c.Action:
    return c.Action(type="ask", to="driver", question=question, expects=expects, **kwargs)


def spoken(rig: Rig) -> list[str]:
    return [s["text"] for s in rig.speaks()]


def rejected(rig: Rig) -> list[str]:
    return [e["data"]["reason"] for e in rig.hub.events("action_rejected")]


def say(rig: Rig, text: str) -> None:
    rig.say(text, addressed=True)


def speak_done(rig: Rig, text: str) -> None:
    """The browser finished saying ``text`` (opens the dialog window after a question)."""
    utterance = next(s for s in rig.speaks() if s["text"] == text)
    rig.browser({"type": "speak_done", "id": utterance["id"], "is_question": utterance["is_question"],
                 "interrupted": False, "ts": rig.t})


# --- scene 1: greeting -----------------------------------------------------------------------------------------------


async def test_trip_start_greets_once_with_p3s_fixed_texts() -> None:
    rig = Rig(scene=1, assistant=AssistantClient())  # no LLM key: P3's fixed texts
    rig.run(th("assistant", "greet_after_s") + 0.3)
    await rig.link.drain()
    rig.run(10.0)
    await rig.link.drain()
    assert spoken(rig) == ["Salut Andrei. Salut Maria."]
    assert rig.hub.events("assistant_action")[0]["source"] == "RULE"
    assert rig.state.integrations.llm == "off"


# --- speech, early speech, veto --------------------------------------------------------------------------------------


async def test_driver_speech_is_answered() -> None:
    client = FakeClient({"driver_speech": [speak("Pun ceva energic.")]})
    rig = Rig(scene=5, assistant=client)
    rig.run(0.5)
    say(rig, "pune ceva muzică")
    await rig.link.drain()
    assert client.events[-1].data == {"text": "pune ceva muzică"}
    assert spoken(rig) == ["Pun ceva energic."]
    assert rig.hub.events("assistant_action")[-1]["source"] == "LLM"
    rig.run(0.2)
    assert rig.state.perf.llm_ttft_ms == 420.0 and rig.state.integrations.llm == "ok"


async def test_unaddressed_speech_is_ignored() -> None:
    client = FakeClient()
    rig = Rig(scene=5, assistant=client)
    rig.say("vorbim între noi", addressed=False)
    await rig.link.drain()
    assert client.events == []


async def test_streamed_sentence_is_said_once() -> None:
    first = speak("Pare monoton.")
    client = FakeClient({"driver_speech": [first.model_copy(update={"streamed": True}), ask("Pun ceva energic?")]},
                        early={"driver_speech": [first]})
    rig = Rig(scene=5, assistant=client)
    say(rig, "mă plictisesc")
    await rig.link.drain()
    assert spoken(rig) == ["Pare monoton.", "Pun ceva energic?"]


async def test_no_llm_speech_during_a_safety_alert() -> None:
    client = FakeClient({"driver_speech": [speak("Sigur, uite o glumă.")]})
    rig = Rig(scene=8, assistant=client)
    rig.press("3")  # phone in hand at 118 km/h -> P2
    rig.run(1.5)
    assert rig.state.safety.level == "P2"
    rig.link.submit("driver_speech", rig.t, text="spune o glumă")
    await rig.link.drain()
    assert "Sigur, uite o glumă." not in spoken(rig)  # nothing from the assistant during the alert...
    rig.press("1")  # ... the phone is put down
    rig.run(1.0)
    assert spoken(rig)[-1] == "Sigur, uite o glumă."  # ... and the answer comes after it, not lost (resume)


# --- confirmations (E3) ----------------------------------------------------------------------------------------------


def reminder_reply() -> list[c.Action]:
    trigger = c.ReminderTrigger(type="stop_at_category", category="fuel")
    return [ask("Notat: lichid de parbriz, la prima benzinărie. Bine?"),
            c.Action(type="create_reminder", task="lichid de parbriz", trigger=trigger, needs_confirmation=True)]


async def test_reminder_waits_for_a_nod() -> None:
    rig = Rig(scene=1, assistant=FakeClient({"driver_speech": reminder_reply()}))
    say(rig, "amintește-mi să iau lichid de parbriz la benzinărie")
    await rig.link.drain()
    assert rig.state.reminders == []
    speak_done(rig, "Notat: lichid de parbriz, la prima benzinărie. Bine?")
    window = rig.hub.perception_sent[-1]
    assert (window["cmd"], window["open"], window["to"]) == ("dialog_window", True, "driver")
    rig.press("y")
    rig.run(0.3)
    reminder = rig.state.reminders[0]
    assert (reminder.id, reminder.task, reminder.state, reminder.trigger.category) == (
        "r1", "lichid de parbriz", "active", "fuel")
    assert any(s["clip_url"] == "/sounds/clips/confirm_noted.mp3" for s in rig.speaks())
    assert rig.state.interaction.last_input is not None and rig.state.interaction.last_input.channel == "nod"
    assert rig.state.scorecard.suggestions_accepted == 1


async def test_no_cancels_the_reminder() -> None:
    rig = Rig(scene=1, assistant=FakeClient({"driver_speech": reminder_reply()}))
    say(rig, "amintește-mi ceva")
    await rig.link.drain()
    say(rig, "nu")
    assert rig.state.reminders == [] and rig.state.scorecard.suggestions_rejected == 1


async def test_a_safety_alert_drops_the_pending_question() -> None:
    rig = Rig(scene=8, assistant=FakeClient({"driver_speech": reminder_reply()}))
    say(rig, "amintește-mi ceva")
    await rig.link.drain()
    assert rig.link.dialog.has_pending(rig.t)
    rig.press("7")
    rig.run(ALARM_S + 0.2)
    assert rig.state.safety.level == "P1" and not rig.link.dialog.has_pending(rig.t)


async def test_the_sos_answer_never_reaches_the_assistant() -> None:
    client = FakeClient()
    rig = Rig(scene=8, assistant=client)
    rig.press("7")
    rig.run(ALARM_S + 0.2 + ASK_AFTER + 0.5)
    rig.press("1")
    say(rig, "da")
    await rig.link.drain()
    assert rig.state.safety.sos.state == "normal" or rig.engine.safety.sos.state == "normal"
    assert "driver_speech" not in client.types()


# --- C8 --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        (c.Action(type="reply_message", msg_id="m1", text="Ajung."), "needs_confirmation"),
        (c.Action(type="search_media", query="metal", kind="music"), "internal_to_assistant"),
        (c.Action(type="speak", to="driver"), "invalid:text"),
        (c.Action(type="set_preference", key="voice_speed", value=1.2), "needs_confirmation"),
    ],
)
async def test_core_rejects_what_section_6_forbids(action: c.Action, reason: str) -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [action]}))
    say(rig, "fă ceva")
    await rig.link.drain()
    assert rejected(rig) == [reason]


async def test_validator_levels_and_exceptions() -> None:
    state = c.State()
    volume = c.Action(type="set_preference", key="volume", value=0.3)
    assert validator.check(volume, state, confirmed=False) is None  # "mai încet": no "Bine?" (D11)
    state.safety.level = "P3"
    assert validator.check(c.Action(type="play_media", track_id="t1"), state, confirmed=True) == "level:P3"
    assert validator.check(c.Action(type="stop_media"), state, confirmed=False) is None
    state.safety.level = "P1"
    assert validator.check(c.Action(type="stay_silent", reason="safety_veto"), state, confirmed=False) is None
    assert validator.check(speak("Ok."), state, confirmed=True) == "level:P1"


# --- messages (F2, F3) -----------------------------------------------------------------------------------------------


async def test_message_is_deferred_at_high_speed_then_offered() -> None:
    client = FakeClient()
    rig = Rig(scene=5, assistant=client)
    rig.run(th("assistant", "greet_after_s") + 0.3)  # greeted first: messages wait for the greeting
    rig.command("speed", 130)
    rig.command("fake_message", {"from": "Mihai", "app": "whatsapp", "text": "Unde ești?"})
    rig.run(0.3)
    message = rig.state.messages[0]
    assert (message.state, message.deferred_reason) == ("deferred", "high_speed")
    assert rig.speaks()[-1]["clip_url"] == "/sounds/clips/message_deferred.mp3"
    rig.command("speed", 60)
    rig.run(th("messages", "retry_s") + 0.3)
    await rig.link.drain()
    offered = [e for e in client.events if e.type == "message_received"]
    assert len(offered) == 1 and offered[0].data == {"msg_id": "m1", "delivery": "ask"}
    assert len([s for s in rig.speaks() if s["id"].startswith("msg")]) == 1  # "Ți-l citesc..." said once


async def test_scene_3_message_with_p3s_client() -> None:
    """P3's real client (fixed texts): "Mesaj de la Mihai. Îl citesc tare?" -> nod -> the text is read as is."""
    rig = Rig(scene=3, assistant=AssistantClient())
    rig.engine.on_phone_message({"type": "phone_message", "notification_id": "n42", "app": "whatsapp",
                                 "from": "Mihai", "text": "Salut! Unde ești?", "replyable": True, "ts": rig.t}, rig.t)
    rig.run(th("assistant", "greet_after_s") + 0.3)
    await rig.link.drain()
    assert "Mesaj de la Mihai. Îl citesc tare?" in spoken(rig)
    speak_done(rig, "Mesaj de la Mihai. Îl citesc tare?")
    rig.press("y")
    rig.run(0.3)
    assert spoken(rig)[-1] == "Salut! Unde ești?"
    assert rig.state.messages[0].state == "read" and rig.state.scorecard.hands_free_messages == 1
    assert rig.state.perf.msg_to_voice_ms is not None


async def test_reply_goes_through_the_phone_bridge() -> None:
    reply = c.Action(type="reply_message", msg_id="m1", text="Ajung pe la 18:40.", needs_confirmation=True)
    rig = Rig(scene=3, assistant=FakeClient({"driver_speech": [ask("Îi scriu: Ajung pe la 18:40. Trimit?"), reply]}))
    rig.engine.on_phone_message({"type": "phone_message", "notification_id": "n42", "app": "whatsapp",
                                 "from": "Mihai", "text": "Unde ești?", "replyable": True, "ts": rig.t}, rig.t)
    say(rig, "spune-i că ajung în 20 de minute")
    await rig.link.drain()
    assert rig.hub.phone_sent == []
    rig.press("g")  # 👍
    rig.run(0.3)
    sent = rig.hub.phone_sent[0]
    assert (sent["type"], sent["notification_id"], sent["text"]) == ("send_reply", "n42", "Ajung pe la 18:40.")
    assert rig.state.messages[0].state == "replied"


async def test_f2_rule() -> None:
    state = c.State.model_validate({"trip": {"speed_kmh": 50}, "passenger": {"present": True}})
    assert messages_timing.decide(state) == ("ask", None)
    state.passenger.present = False
    assert messages_timing.decide(state) == ("read", None)
    state.cause.label = "passenger_showing_phone"
    assert messages_timing.decide(state) == ("defer", "distraction")
    state.cause.label = None
    state.assessment.risk = 2
    assert messages_timing.decide(state) == ("defer", "high_risk")
    state.assessment.risk = 0
    state.safety.level = "P1"
    assert messages_timing.decide(state) == ("defer", "safety_alert")


# --- media, volume ---------------------------------------------------------------------------------------------------


async def test_music_from_the_catalog_and_from_youtube() -> None:
    plays = {"driver_speech": [c.Action(type="play_media", track_id="pop1", title="Pop")]}
    rig = Rig(scene=5, assistant=FakeClient(plays))
    say(rig, "pune muzică")
    await rig.link.drain()
    media = rig.hub.of_type("media")[-1]
    assert (media["action"], media["url"], media["loop"]) == ("play", "/media/pop1.mp3", True)
    assert (rig.state.media.playing, rig.state.media.source, rig.state.media.reason) == (True, "catalog",
                                                                                        "driver_request")
    rig.link.client.replies["driver_speech"] = [c.Action(type="play_media", track_id="yt:abc123", title="Metal")]
    say(rig, "ceva metal")
    await rig.link.drain()
    media = rig.hub.of_type("media")[-1]
    assert (media["url"], media["loop"], rig.state.media.source) == ("/media/yt/abc123.m4a", False, "youtube")


async def test_stop_music_with_p3s_deterministic_command() -> None:
    rig = Rig(scene=5, assistant=AssistantClient())
    rig.state.media.playing = True
    say(rig, "oprește muzica")
    await rig.link.drain()
    assert rig.hub.of_type("media")[-1]["action"] == "stop" and rig.state.media.playing is False


async def test_volume_runs_at_once() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [c.Action(type="set_preference", key="volume",
                                                                         value=0.3)]}))
    say(rig, "mai încet")
    await rig.link.drain()
    assert rig.hub.of_type("media")[-1] == {**rig.hub.of_type("media")[-1], "action": "volume", "volume": 0.3}
    assert rig.state.media.volume == 0.3


# --- D4, open palm ---------------------------------------------------------------------------------------------------


async def test_voice_pauses_at_the_mirror_and_resumes() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak("Am găsit o piesă pe care o să-ți placă.")]}))
    say(rig, "ce muzică ai?")
    await rig.link.drain()
    rig.press("2")
    rig.run(0.5)
    assert [m["action"] for m in rig.hub.of_type("speak_control")] == ["pause"]
    assert rig.state.interaction.state == "paused"
    rig.run(2.0)  # the glance ends (1.8 s)
    assert [m["action"] for m in rig.hub.of_type("speak_control")] == ["pause", "resume"]


async def test_open_palm_silences_the_assistant() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak("Știai că ...")]}))
    say(rig, "spune ceva")
    await rig.link.drain()
    rig.press("h")
    rig.run(0.2)
    assert rig.hub.of_type("speak_control")[-1]["action"] == "stop"


# --- K3 --------------------------------------------------------------------------------------------------------------


async def test_high_kss_makes_core_pick_the_stop() -> None:
    client = FakeClient()
    rig = Rig(scene=6, assistant=client)
    trigger = c.ReminderTrigger(type="stop_at_category", category="fuel")
    rig.state.reminders.append(c.Reminder(id="r1", task="lichid de parbriz", trigger=trigger, state="active"))
    rig.run(0.2)
    rig.link.submit("kss_answer", rig.t, value=8)
    await rig.link.drain()
    assert client.types() == ["kss_answer", "stop_suggested"]
    data = client.events[1].data
    assert (data["poi_id"], data["poi_name"], data["task"]) == ("omv_km42", "OMV", "lichid de parbriz")


async def test_pick_stop_needs_a_stop_in_range() -> None:
    state = c.State.model_validate({"trip": {"next_poi": {"id": "far", "category": "fuel", "dist_km": 500}}})
    assert pick_stop(state) is None



async def test_llm_status_follows_the_provider_not_a_safety_veto() -> None:
    """No API key: integrations.llm is "off" from the start, and a vetoed or muted answer never turns it into "ok"."""
    rig = Rig(scene=5, assistant=AssistantClient())  # offline provider (no key)
    rig.run(0.2)
    assert rig.state.integrations.llm == "off"
    event = c.Event(type="driver_speech", ts=rig.t)
    for reason in ("policy:safety_veto", "policy:muted", "ok"):  # "ok" here would be a provider claiming success
        rig.link.client.last_result = AnswerInfo(reason=reason)
        rig.link._record(event, rig.t)
        rig.run(0.2)
        assert rig.state.integrations.llm == "off", reason


async def test_a_policy_decision_keeps_the_last_llm_status() -> None:
    client = FakeClient({"driver_speech": [speak("Pun ceva energic.")]})
    rig = Rig(scene=5, assistant=client)
    rig.run(0.5)
    say(rig, "pune ceva muzică")
    await rig.link.drain()
    rig.run(0.2)
    assert rig.state.integrations.llm == "ok"
    client.last_result = AnswerInfo(reason="timeout")
    rig.link._record(c.Event(type="driver_speech", ts=rig.t), rig.t)
    rig.run(0.2)
    assert rig.state.integrations.llm == "down"
    client.last_result = AnswerInfo(reason="policy:safety_veto")  # a veto does not mean the LLM recovered
    rig.link._record(c.Event(type="driver_speech", ts=rig.t), rig.t)
    rig.run(0.2)
    assert rig.state.integrations.llm == "down"


# --- P3's interaction preferences (talkativeness, follow_up, answer_length) ------------------------------------------


def preference(key: str, value: str) -> c.Action:
    return c.Action(type="set_preference", key=key, value=value)


async def test_confirmed_preference_is_applied_after_the_check_and_shown_in_the_state() -> None:
    rig = Rig(scene=5, assistant=FakeClient({}))
    rig.run(0.5)
    assert rig.state.assistant.preferences["answer_length"] == "normal"  # synced every tick (defaults, no profile)
    rig.state.safety.level = "P4"
    assert rig.link.execute(preference("answer_length", "short"), rig.t, confirmed=True)
    assert rig.state.assistant.preferences["answer_length"] == "short"
    rig.run(0.5)
    assert rig.state.assistant.preferences["answer_length"] == "short"  # the tick keeps it (voice change, this trip)


async def test_preference_rejected_by_core_never_applies() -> None:
    rig = Rig(scene=5, assistant=FakeClient({}))
    rig.run(0.5)
    rig.state.safety.level = "P3"  # set_preference is allowed only at P4
    assert not rig.link.execute(preference("follow_up", "never"), rig.t, confirmed=True)
    assert rejected(rig)[-1] == "level:P3"
    assert rig.state.assistant.preferences["follow_up"] == "always"


async def test_reset_forgets_voice_preferences() -> None:
    rig = Rig(scene=5, assistant=AssistantClient())
    rig.run(0.5)
    rig.state.safety.level = "P4"
    rig.link.execute(preference("talkativeness", "low"), rig.t, confirmed=True)
    assert rig.state.assistant.preferences["talkativeness"] == "low"
    rig.link.reset(rig.t)
    rig.run(0.2)
    assert rig.state.assistant.preferences["talkativeness"] == "normal"


async def test_panel_preference_applies_at_once_for_this_trip() -> None:
    """The dashboard's "Copilot · preferințe" selects send ``assistant_preference``: no "Bine?", any level."""
    rig = Rig(scene=5, assistant=FakeClient({}))
    rig.run(0.5)
    rig.browser({"type": "command", "cmd": "assistant_preference", "value": {"key": "follow_up", "value": "never"}})
    assert rig.state.assistant.preferences["follow_up"] == "never"
    assert rig.hub.events("assistant_action")[-1]["data"]["action_type"] == "set_preference"
    rig.command("reset")
    rig.run(0.2)
    assert rig.state.assistant.preferences["follow_up"] == "always"


async def test_panel_preference_with_an_unknown_value_is_rejected() -> None:
    rig = Rig(scene=5, assistant=FakeClient({}))
    rig.run(0.5)
    rig.browser({"type": "command", "cmd": "assistant_preference", "value": {"key": "answer_length", "value": "huge"}})
    assert rig.state.assistant.preferences["answer_length"] == "normal"
    assert rejected(rig)[-1] == "unknown_preference"
