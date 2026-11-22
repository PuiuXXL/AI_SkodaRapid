"""Custom alarms (2026-11-22): the alarm says what to do, varies, gets firmer; a personal sentence after it; the
passenger helps; the assistant explains a distraction that came to the alarm (alert_explain)."""

from __future__ import annotations

from typing import Any

import pytest
from p2_helpers import FakeClient, Rig, alarm_clip_s

from core import clips
from core.settings import th

pytestmark = pytest.mark.asyncio

ALL = {"alarm_andrei": {"text": "ANDREI!", "duration_s": 1.8},
       "alarm_microsleep_1_andrei": {"text": "ANDREI! Trezește-te!", "duration_s": 2.9},
       "alarm_microsleep_2_andrei": {"text": "ANDREI! Deschide ochii!", "duration_s": 3.0},
       "alarm_repeat_microsleep_andrei": {"text": "ANDREI! A doua oară! Hai să oprim.", "duration_s": 4.5},
       "alarm_phone_1_andrei": {"text": "ANDREI! Lasă telefonul!", "duration_s": 2.9}}


@pytest.fixture
def index(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """P3's clips.json as these tests need it (not the generated one)."""
    data = dict(ALL)
    monkeypatch.setattr(clips, "available", lambda: data)
    return data


async def test_the_clip_says_what_to_do_and_varies(index: dict[str, Any]) -> None:
    assert clips.alarm_clip("andrei", "microsleep") == "alarm_microsleep_1_andrei"
    assert clips.alarm_clip("andrei", "microsleep", variant=1) == "alarm_microsleep_2_andrei"
    assert clips.alarm_clip("andrei", "microsleep", variant=2) == "alarm_microsleep_1_andrei"  # in turn
    assert clips.alarm_clip("andrei", "nodding") == "alarm_microsleep_1_andrei"  # alias
    assert clips.alarm_clip("andrei", "microsleep", repeat=True) == "alarm_repeat_microsleep_andrei"
    assert clips.alarm_clip("andrei", "off_road") == "alarm_andrei"  # no clip for it: the name alone
    assert clips.alarm_clip("ioana", "phone") == "alarm_andrei"  # nobody's clip: the default driver's
    assert clips.duration_s("alarm_microsleep_1_andrei") == 2.9


async def test_the_same_alert_again_soon_is_firmer_and_the_sos_waits_for_it(index: dict[str, Any]) -> None:
    rig = Rig(scene=8)
    alarms = rig.engine.safety.alarms
    alarms.send(rig.t, "microsleep", "P1")
    first = rig.hub.of_type("alarm")[-1]["clip_url"]
    assert first.endswith("alarm_microsleep_1_andrei.mp3")
    assert alarms.last_clip_s == pytest.approx(2.9 + th("safety", "alarms", "beep_s"))
    alarms.send(rig.t + 60.0, "microsleep", "P1")  # a minute later: firmer, and longer
    assert rig.hub.of_type("alarm")[-1]["clip_url"].endswith("alarm_repeat_microsleep_andrei.mp3")
    assert alarms.last_clip_s == pytest.approx(4.5 + th("safety", "alarms", "beep_s"))
    alarms.send(rig.t + 60.0 + th("safety", "alarms", "repeat_window_min") * 60.0 + 1.0, "microsleep", "P1")
    assert rig.hub.of_type("alarm")[-1]["clip_url"].endswith("alarm_microsleep_1_andrei.mp3")  # long after: normal


async def test_the_sos_question_waits_for_a_long_alarm() -> None:
    rig = Rig(scene=8)
    rig.press("7")
    rig.run_until(lambda: bool(rig.hub.of_type("alarm")), limit_s=5.0)
    alarm_at = rig.t
    rig.run_until(lambda: rig.engine.safety.sos.state == "asking", limit_s=8.0)
    assert rig.t - alarm_at >= alarm_clip_s() + th("sos", "ask_after_alarm_s") - 0.11


def _alarm_then_yes(rig: Rig) -> None:
    rig.press("7")
    rig.run_until(lambda: rig.engine.safety.sos.state == "asking", limit_s=10.0)
    rig.press("1")
    rig.say("Da, sunt bine.")
    rig.run(0.2)


async def test_after_a_microsleep_the_awake_passenger_is_asked_to_help() -> None:
    rig = Rig(scene=8)
    _alarm_then_yes(rig)
    wake = [s for s in rig.speaks() if s["to"] == "passenger"]
    assert [s["text"] for s in wake] == ["Maria, te rog, vorbește puțin cu Andrei, să rămână treaz."]
    assert rig.hub.events("passenger_wake")


async def test_no_passenger_line_when_she_sleeps() -> None:
    rig = Rig(scene=8)
    rig.patch = lambda frame, t: frame["passenger"].update(awake=False)
    _alarm_then_yes(rig)
    assert not [s for s in rig.speaks() if s["to"] == "passenger"]


async def test_the_spoken_warning_varies_then_gets_firmer() -> None:
    from core.safety.distraction import DistractionRule

    rig = Rig(scene=3)
    rule: DistractionRule = next(r for r in vars(rig.engine.safety).values() if isinstance(r, DistractionRule))
    said = []
    for minutes in (0, 30, 60):  # far apart: the variants in turn
        rule._voice(rig.state, "phone", "x", rig.t + minutes * 60.0)
        said.append(rig.speaks()[-1]["text"])
    assert said == ["Andrei, lasă telefonul, te rog.", "Andrei, telefonul jos, te rog.",
                    "Andrei, pune telefonul deoparte."]
    rule._voice(rig.state, "phone", "x", rig.t + 60 * 60.0 + 30.0)  # 30 s later: firmer
    assert rig.speaks()[-1]["text"] == "Andrei, iar telefonul. Lasă-l jos; ce e urgent îți citesc eu."


# --- alert_explain ------------------------------------------------------------------------------------------------------


def _phone_to_the_alarm(rig: Rig) -> None:
    rig.press("3")  # the phone in hand at 50 km/h, long enough for the alarm
    phone = th("safety", "distraction", "phone_min_ms") / 1000.0
    rig.run(phone + th("safety", "escalation", "alarm_after_ms") / 1000.0 + 0.3)
    assert rig.hub.of_type("alarm")
    rig.press("1")
    rig.run(0.3)


async def test_after_a_distraction_alarm_the_assistant_explains_it() -> None:
    client = FakeClient()
    rig = Rig(scene=3, assistant=client)
    rig.run(1.0)
    await rig.link.drain()
    _phone_to_the_alarm(rig)
    assert "alert_explain" not in client.types()  # not over the alarm clip
    rig.run(th("assistant", "alert_explain_after_s") + 0.3)
    await rig.link.drain()
    event = next(e for e in client.events if e.type == "alert_explain")
    assert event.data["alert"] == "phone" and event.data["explanation"].startswith("Telefon în mână")


async def test_one_explanation_per_cooldown() -> None:
    client = FakeClient()
    rig = Rig(scene=3, assistant=client)
    rig.run(1.0)
    for _ in range(2):
        _phone_to_the_alarm(rig)
        rig.run(th("assistant", "alert_explain_after_s") + 0.5)
        await rig.link.drain()
    assert client.types().count("alert_explain") == 1


async def test_no_explanation_when_the_conversation_resumes() -> None:
    client = FakeClient()
    rig = Rig(scene=3, assistant=client)
    rig.run(1.0)
    rig.link.interrupted = [object()]  # a stopped answer will be said again: no extra talk on top of it
    rig.link.explain_alert(rig.t, alert="phone", explanation="Telefon în mână 4 s la 50 km/h.")
    assert "alert_explain" not in rig.link.retries


# --- P3's generator -----------------------------------------------------------------------------------------------------


async def test_the_generator_lists_the_new_clips_and_measures_mp3s() -> None:
    from pathlib import Path

    from integrations.audio_clips import build_clip_list, mp3_duration_s

    ids = build_clip_list()
    assert ids["alarm_microsleep_1_andrei"][0] == "ANDREI! Trezește-te!"
    assert ids["alarm_repeat_phone_andrei"][1] is True  # alarms use the faster rate
    assert "passenger_wake_maria_andrei" in ids
    sample = Path(__file__).resolve().parents[2] / "dashboard" / "public" / "sounds" / "clips" / "are_you_ok.mp3"
    if sample.exists():
        assert 0.5 < mp3_duration_s(sample.read_bytes()) < 5.0
    assert mp3_duration_s(b"not an mp3") == 0.0
