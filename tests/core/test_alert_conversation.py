"""Alerts vs. a conversation with the assistant (plan "alert severity", steps 1 and 3; baseline:
docs/eval/alerts-conversation-baseline-2026-11-22.md).

* Step 1: the discrete cue of a distraction only PAUSES the assistant (its question stays pending) and the sentence
  resumes when the gaze is back before the spoken warning; the spoken stage stops voice and music. The LLM stays
  vetoed during the whole P2 alert, as before.
* Step 3: a cause goes to the assistant only when it is not in a conversation with the driver, and the same label
  only once per ``cause.notify_cooldown_s``.
"""

from __future__ import annotations

from typing import Any

import pytest
from p2_helpers import FakeClient, Rig

from core.settings import th
from shared import contracts as c

pytestmark = pytest.mark.asyncio

LIMIT_HIGH = th("safety", "distraction", "off_road_ms_high_speed") / 1000.0  # scene 5: 118 km/h
VOICE_AFTER = th("safety", "escalation", "voice_after_ms") / 1000.0
ANSWER = "Mai ai cam douăzeci de minute până la destinație, iar drumul e liber până la Deva."


def speak(text: str) -> c.Action:
    return c.Action(type="speak", to="driver", text=text)


def ask(question: str) -> c.Action:
    return c.Action(type="ask", to="driver", question=question, expects="free", reason="follow_up")


def glance(start: float, seconds: float, zone: str = "infotainment") -> Any:
    """A patch: the driver looks at ``zone`` from ``start`` for ``seconds`` (P1's off_road_ms grows meanwhile), and
    at the road otherwise (no automatic mirror check, which would pause the voice by itself: D4)."""

    def patch(frame: dict[str, Any], t: float) -> None:
        if start <= t < start + seconds:
            frame["driver"]["gaze"].update(zone=zone, conf=0.9, off_road_ms=round((t - start) * 1000.0, 1))
        else:
            frame["driver"]["gaze"].update(zone="road", conf=0.9, off_road_ms=0.0)

    return patch


def controls(rig: Rig) -> list[str]:
    return [m["action"] for m in rig.hub.of_type("speak_control")]


async def answering(rig: Rig) -> None:
    """The driver asks; the assistant answers with a long sentence plus a question (still speaking)."""
    rig.say("copilot, cât mai am?")
    await rig.link.drain()
    assert rig.link.speaking is not None


async def test_a_short_glance_pauses_and_resumes_the_answer() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak(ANSWER), ask("Te mai ajut cu ceva?")]}))
    rig.run(1.0)
    await answering(rig)
    pending = rig.link.dialog.has_pending(rig.t)
    rig.patch = glance(rig.t, LIMIT_HIGH + 0.3)  # over the limit, back before the spoken warning
    rig.run(LIMIT_HIGH + 0.1)
    assert rig.hub.events("visual_cue") and rig.state.safety.level == "P2"
    assert rig.state.safety.llm_allowed is False  # the veto is unchanged
    assert controls(rig) == ["pause"] and rig.state.interaction.state == "paused"
    rig.run(1.0)
    assert controls(rig) == ["pause", "resume"]  # "...cum ziceam": no stop, nothing lost
    assert rig.link.speaking is not None and rig.link.dialog.has_pending(rig.t) == pending
    assert not rig.hub.of_type("media") or all(m["action"] != "stop" for m in rig.hub.of_type("media"))
    assert not [s for s in rig.speaks() if s["id"].startswith("dis")]  # no words from P2 either


async def test_the_spoken_warning_stops_the_assistant() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak(ANSWER)]}))
    rig.run(1.0)
    await answering(rig)
    rig.patch = glance(rig.t, LIMIT_HIGH + VOICE_AFTER + 1.0)
    rig.run(LIMIT_HIGH + VOICE_AFTER + 0.3)
    assert controls(rig) == ["pause", "stop"]
    assert any(m["action"] == "stop" for m in rig.hub.of_type("media"))  # the music stops with the words
    sent = [m.get("type") for m in rig.hub.ui_sent]
    warning = next(i for i, m in enumerate(rig.hub.ui_sent) if m.get("type") == "speak" and m["id"].startswith("dis"))
    assert sent.index("speak_control", len(sent) - sent[::-1].index("speak_control") - 1) < warning
    assert rig.link.speaking is None


async def test_a_sentence_sent_during_the_cue_starts_paused() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak("Sigur.")]}))
    rig.run(1.0)
    rig.patch = glance(rig.t, LIMIT_HIGH + 0.4)
    rig.run(LIMIT_HIGH + 0.1)
    rig.link.hold_voice(rig.t, "test")  # already held by the cue: idempotent
    rig.link._send_speech(speak("Ok, gata."), rig.t)  # e.g. a rule's sentence going through the assistant's voice
    assert controls(rig)[-1] == "pause" and rig.link.paused
    rig.run(1.0)
    assert controls(rig)[-1] == "resume" and not rig.link.paused


async def test_the_cue_stops_nothing_with_the_old_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from core import settings

    original = settings.th

    def th_old(*keys: str) -> Any:
        if keys == ("safety", "escalation", "cue_pauses_voice"):
            return False
        return original(*keys)

    monkeypatch.setattr("core.safety.distraction.th", th_old)
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak(ANSWER)]}))
    rig.run(1.0)
    await answering(rig)
    rig.patch = glance(rig.t, LIMIT_HIGH + 0.3)
    rig.run(LIMIT_HIGH + 0.1)
    assert controls(rig) == ["stop"]  # the baseline behaviour, kept behind the switch


# --- step 3: causes ---------------------------------------------------------------------------------------------------


async def test_a_cause_waits_for_the_end_of_the_conversation() -> None:
    client = FakeClient({"driver_speech": [speak(ANSWER), ask("Te mai ajut cu ceva?")]})
    rig = Rig(scene=4, assistant=client)
    rig.run(3.0)
    await rig.link.drain()  # greeting
    await answering(rig)  # the answer, then "Te mai ajut cu ceva?" waits for the driver
    rig.press("4")  # Maria shows her phone, Andrei glances at her
    rig.run(9.0)
    await rig.link.drain()
    assert rig.state.cause.label == "passenger_showing_phone"
    assert "cause_detected" not in client.types()  # the conversation is still going on
    rig.say("nu, mersi")  # the conversation ends
    rig.run(0.5)
    await rig.link.drain()
    assert client.types().count("cause_detected") == 1


async def test_the_same_cause_is_sent_once_per_cooldown() -> None:
    client = FakeClient()
    rig = Rig(scene=4, assistant=client)
    rig.run(3.0)
    await rig.link.drain()
    rig.press("4")
    rig.run(9.0)
    await rig.link.drain()
    assert client.types().count("cause_detected") == 1
    rig.press("1")  # the evidence stops; the label expires after hold_s
    rig.run(th("cause", "hold_s") + th("cause", "window_s") + 2.0)
    assert rig.state.cause.label is None
    rig.press("4")  # the same cause again, well inside the cooldown
    rig.run(9.0)
    await rig.link.drain()
    assert [e["data"]["label"] for e in rig.hub.events("cause")].count("passenger_showing_phone") == 2  # logged
    assert client.types().count("cause_detected") == 1  # but not said again


# --- step 2: the conversation survives a distraction's spoken warning -----------------------------------------------

ALARM_AFTER = th("safety", "escalation", "alarm_after_ms") / 1000.0


def said(rig: Rig) -> list[str]:
    return [s["text"] for s in rig.speaks()]


async def test_after_the_warning_the_answer_resumes_and_the_question_stays() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak(ANSWER), ask("Te mai ajut cu ceva?")]}))
    rig.run(1.0)
    await answering(rig)
    rig.patch = glance(rig.t, LIMIT_HIGH + VOICE_AFTER + 0.5)  # long enough for the words, back before the alarm
    rig.run(LIMIT_HIGH + VOICE_AFTER + 0.2)
    assert controls(rig)[-1] == "stop" and "Andrei, fii atent la drum, te rog." in said(rig)
    assert rig.link.dialog.has_pending(rig.t)  # the question still stands
    rig.run(1.0)  # the gaze is back, the alert is over
    assert f"Cum ziceam, {ANSWER}" in said(rig) and said(rig)[-1] == "Te mai ajut cu ceva?"
    assert rig.hub.events("assistant_action")[-1]["data"]["action_type"] == "resume"
    assert rig.link.dialog.has_pending(rig.t)


async def test_no_resume_after_an_alarm() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak(ANSWER)]}))
    rig.run(1.0)
    await answering(rig)
    rig.patch = glance(rig.t, LIMIT_HIGH + ALARM_AFTER + 0.3)  # the alarm fires before the driver looks back
    rig.run(LIMIT_HIGH + ALARM_AFTER + 1.5)
    assert rig.hub.of_type("alarm")
    assert not any(text.startswith("Cum ziceam") for text in said(rig))


async def test_no_resume_when_the_driver_comes_back_too_late() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak(ANSWER)]}))
    rig.run(1.0)
    await answering(rig)
    rig.link.on_safety_interrupt("distraction")  # as at the spoken stage ...
    rig.link.interrupted_at -= th("assistant", "resume_within_s") + 1.0  # ... but long ago
    rig.run(0.5)
    assert not any(text.startswith("Cum ziceam") for text in said(rig))
    assert rig.hub.events("assistant_action")[-1]["data"]["action_type"] == "resume_dropped"


async def test_a_serious_alert_still_ends_the_conversation() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [speak(ANSWER), ask("Te mai ajut cu ceva?")]}))
    rig.run(1.0)
    await answering(rig)
    rig.link.on_safety_interrupt("sos")  # microsleep alarm / SOS
    assert not rig.link.dialog.has_pending(rig.t) and not rig.link.interrupted
    rig.run(2.0)
    assert not any(text.startswith("Cum ziceam") for text in said(rig))
