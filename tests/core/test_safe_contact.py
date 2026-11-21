"""Tests for core/safe_contact.py (C10, D10, F8) and core/profiles.py: the tired driver refuses the assistant, a rule
silences it and tells the trusted contact; the contact's answer is read and one stop is offered. Scene 6."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from p2_helpers import ALARM_S, FakeClient, Rig

from assistant.client import AssistantClient
from core.safe_contact import elapsed_text
from core.settings import th
from shared import contracts as c

pytestmark = pytest.mark.asyncio

PROFILE = {"name": "Andrei", "music_genres": ["rock"], "safe_contact": {"name": "Mihai"},
           "emergency_contact": {"name": "Mihai"}, "consent": {"safe_contact_notify": True}, "announce": True}


def write_profile(root: Path, **changes: Any) -> Path:
    path = root / "andrei" / "profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**PROFILE, **changes}), encoding="utf-8")
    stamp = path.stat().st_mtime + 10  # a new mtime even within the same second
    os.utime(path, (stamp, stamp))
    return path


class Recorder:
    def __init__(self) -> None:
        self.notices: list[c.SafeContactNotice] = []

    def __call__(self, notice: c.SafeContactNotice) -> str:
        self.notices.append(notice)
        return "ok"


def contact_rig(tmp_path: Path, client: Any = None, **profile: Any) -> tuple[Rig, Recorder]:
    write_profile(tmp_path, **profile)
    sms = Recorder()
    rig = Rig(scene=6, assistant=client or FakeClient(), profiles_root=tmp_path,
              contact_channels={"sms": sms, "contact_page": lambda notice: "not_connected"})
    rig.run(0.5)
    return rig, sms


def refuse(rig: Rig, fatigue: float = 0.7) -> None:
    """The fatigue dialog is on and the driver refuses (the keyword path)."""
    rig.contact.fatigue_dialog_started(rig.t, fatigue)
    rig.say("lasă-mă în pace", addressed=True)


def spoken(rig: Rig) -> list[str]:
    return [s["text"] for s in rig.speaks()]


# --- profile ---------------------------------------------------------------------------------------------------------


async def test_profile_fills_the_state(tmp_path: Path) -> None:
    rig, _ = contact_rig(tmp_path)
    contact = rig.state.safe_contact
    assert (contact.name, contact.configured, contact.consent, contact.announce) == ("Mihai", True, True, True)
    write_profile(tmp_path, consent={"safe_contact_notify": False})
    rig.run(th("safe_contact", "profile_check_s") + 0.2)
    assert rig.state.safe_contact.consent is False


async def test_elapsed_text() -> None:
    assert (elapsed_text(74), elapsed_text(20)) == ("1 h 14 min", "20 min")


# --- C10 -------------------------------------------------------------------------------------------------------------


async def test_scene_6_with_p3s_client(tmp_path: Path) -> None:
    """F rises -> KSS question -> "Lasă-mă în pace." -> "Ok, te las în pace." -> "Îi dau de veste lui Mihai." -> SMS."""
    rig, sms = contact_rig(tmp_path, client=AssistantClient())
    rig.command("time_scale", 20)
    rig.run(5.0)
    await rig.link.drain()  # greeting
    rig.press("6")
    question = "Andrei, hai să vorbim puțin. Cât de obosit ești, de la 1 la 9?"
    for _ in range(300):  # F rises; a skipped fatigue_high (one initiative per 30 s) is sent again
        rig.run(0.5)
        await rig.link.drain()
        if question in spoken(rig):
            break
    assert spoken(rig)[-1] == question
    utterance = rig.speaks()[-1]
    rig.browser({"type": "speak_done", "id": utterance["id"], "is_question": True, "interrupted": False, "ts": rig.t})
    rig.say("Lasă-mă în pace.", addressed=False)  # the dialog window is open
    await rig.link.drain()
    assert spoken(rig)[-2:] == ["Ok, te las în pace.", "Îi dau de veste lui Mihai."]
    assert rig.speaks()[-1]["clip_url"] == "/sounds/clips/notify_contact_mihai.mp3"
    muted = rig.state.assistant.muted_until
    assert muted == pytest.approx(rig.t + th("refusal_mute_min") * 60, abs=1) and rig.state.assistant.mute_reason
    assert len(sms.notices) == 1 and sms.notices[0].text.startswith("DriveMate: Andrei pare obosit (")
    assert sms.notices[0].contact_name == "Mihai" and "google.com/maps" in sms.notices[0].maps_url
    notified = rig.hub.events("safe_contact_notified")[0]
    assert notified["source"] == "RULE" and notified["data"]["channels"] == {"sms": "ok",
                                                                            "contact_page": "not_connected"}
    rig.run(0.2)
    assert rig.state.safe_contact.notified_ts is not None
    rig.press("7")  # the assistant is silent, safety is not
    rig.run(ALARM_S + 0.3)
    assert rig.hub.of_type("alarm") and rig.state.safety.level == "P1"


async def test_no_consent_means_silence_but_no_message(tmp_path: Path) -> None:
    rig, sms = contact_rig(tmp_path, consent={"safe_contact_notify": False})
    refuse(rig)
    await rig.link.drain()
    assert rig.state.assistant.muted_until is not None
    assert sms.notices == [] and rig.hub.events("safe_contact_skipped")[0]["data"]["reason"] == "no_consent"
    assert "Îi dau de veste lui Mihai." not in spoken(rig)


async def test_no_profile_no_contact(tmp_path: Path) -> None:
    rig = Rig(scene=6, assistant=FakeClient(), profiles_root=tmp_path)  # empty folder
    rig.run(0.5)
    refuse(rig)
    await rig.link.drain()
    assert rig.state.assistant.muted_until is not None
    assert rig.hub.events("safe_contact_skipped")[0]["data"]["reason"] == "no_contact"


async def test_one_message_per_cooldown(tmp_path: Path) -> None:
    rig, sms = contact_rig(tmp_path)
    refuse(rig)
    await rig.link.drain()
    rig.run(10.0)
    refuse(rig)
    await rig.link.drain()
    assert len(sms.notices) == 1
    assert rig.hub.events("safe_contact_skipped")[0]["data"]["reason"] == "cooldown"


async def test_refusal_outside_the_fatigue_dialog_is_ordinary_speech(tmp_path: Path) -> None:
    client = FakeClient()
    rig, sms = contact_rig(tmp_path, client=client)
    rig.say("lasă-mă în pace", addressed=True)
    await rig.link.drain()
    assert client.types()[-1] == "driver_speech" and rig.state.assistant.muted_until is None and not sms.notices


async def test_the_llms_own_silence_counts_as_a_refusal(tmp_path: Path) -> None:
    client = FakeClient({"driver_speech": [c.Action(type="stay_silent", reason="driver_refused")]})
    rig, sms = contact_rig(tmp_path, client=client)
    rig.contact.fatigue_dialog_started(rig.t, 0.7)
    rig.say("vreau liniște acum", addressed=True)  # not a keyword: the LLM understood it
    await rig.link.drain()
    assert rig.state.assistant.muted_until is not None and len(sms.notices) == 1
    assert rig.hub.events("driver_refused")[0]["channel"] == "llm"


async def test_the_silence_ends(tmp_path: Path) -> None:
    rig, _ = contact_rig(tmp_path)
    refuse(rig)
    await rig.link.drain()
    rig.run(th("refusal_mute_min") * 60 + 0.5)
    assert rig.state.assistant.muted_until is None and rig.hub.events("assistant_unmuted")


# --- F8: the contact's answer, then one stop -------------------------------------------------------------------------


async def test_contact_reply_is_read_then_one_stop_even_while_silent(tmp_path: Path) -> None:
    client = FakeClient({"safe_contact_reply": lambda event, state: [
        c.Action(type="read_message", msg_id=event.data["msg_id"])]})
    rig, _ = contact_rig(tmp_path, client=client)
    rig.run(th("assistant", "greet_after_s") + 0.3)  # messages wait for the greeting
    trigger = c.ReminderTrigger(type="stop_at_category", category="fuel")
    rig.state.reminders.append(c.Reminder(id="r1", task="lichid de parbriz", trigger=trigger, state="active"))
    refuse(rig)
    await rig.link.drain()
    rig.run(1.0)
    rig.engine.on_phone_message({"type": "phone_message", "notification_id": "n7", "app": "whatsapp",
                                 "from": "Mihai", "text": "Oprește la o cafea, te rog!", "ts": rig.t}, rig.t)
    rig.run(0.3)
    await rig.link.drain()
    assert "safe_contact_reply" in client.types()
    assert spoken(rig)[-1] == "Oprește la o cafea, te rog!"
    assert rig.state.safe_contact.last_reply_msg_id == rig.state.messages[0].id
    stop_index = client.types().index("stop_suggested")
    assert client.events[stop_index].data["task"] == "lichid de parbriz"
    assert client.states[stop_index].assistant.muted_until is None  # lifted for this one proposal
    assert rig.state.assistant.muted_until is not None  # still silent otherwise
    rig.engine.on_phone_message({"type": "phone_message", "notification_id": "n8", "app": "whatsapp",
                                 "from": "Mihai", "text": "Ai oprit?", "ts": rig.t}, rig.t)
    rig.run(0.3)
    await rig.link.drain()
    assert client.types().count("stop_suggested") == 1  # once


# --- an initiative skipped by the assistant's policy is sent again --------------------------------------------------


async def test_skipped_initiative_is_sent_again_while_it_still_holds(tmp_path: Path) -> None:
    client = FakeClient(reason="policy:rate_limited")
    rig, _ = contact_rig(tmp_path, client=client)
    rig.command("time_scale", 20)
    rig.press("6")  # real fatigue: F rises and stays up
    for _ in range(300):
        rig.run(0.5)
        await rig.link.drain()
        if "fatigue_high" in client.types():
            break
    client.last_result.reason = "ok"
    rig.run(th("assistant", "retry_s") + 0.5)
    await rig.link.drain()
    sent = [e for e in client.events if e.type == "fatigue_high"]
    assert len(sent) == 2 and sent[1].data == {"retry": 1}


async def test_no_retry_while_muted_or_when_it_passed(tmp_path: Path) -> None:
    client = FakeClient(reason="policy:rate_limited")
    rig, _ = contact_rig(tmp_path, client=client)
    rig.link.submit("disengagement_high", rig.t)  # D is 0 by now: the situation passed
    rig.link.submit("fatigue_high", rig.t)
    await rig.link.drain()
    rig.state.assistant.muted_until = rig.t + 3600
    rig.scores.fatigue.value = 0.7
    rig.run(th("assistant", "retry_s") + 0.3)
    await rig.link.drain()
    assert client.types().count("fatigue_high") == 1 and client.types().count("disengagement_high") == 1
