"""Tests for core/scoring (B): reaction on 3 channels (B1), F and D (B2), attention and risk (B3), blind meters (B6),
conversation (B9), and the fatigue_high / disengagement_high events for the assistant. Scenes 5 and 6, fake time."""

from __future__ import annotations

from typing import Any

import pytest
from p2_helpers import FakeClient, Rig

from core.scoring.common import ema, norm, weighted
from core.settings import th

pytestmark = pytest.mark.asyncio


def question(rig: Rig) -> None:
    """The browser finished a question (the verbal / gesture clocks start)."""
    rig.browser({"type": "speak_done", "id": "q", "is_question": True, "interrupted": False, "ts": rig.t})


def look_at(zone: str, start: float, end: float) -> Any:
    def patch(frame: dict[str, Any], t: float) -> None:
        if start <= t < end:
            frame["driver"]["gaze"].update(zone=zone, conf=0.9, off_road_ms=round((t - start) * 1000.0, 1))

    return patch


# --- helpers ---------------------------------------------------------------------------------------------------------


async def test_term_helpers() -> None:
    assert norm(0.175, [0.05, 0.30]) == pytest.approx(0.5)
    assert (norm(2.0, [1.0, 0.3]), norm(0.0, [1.0, 0.3])) == (0.0, 1.0)  # inverted range
    assert weighted({"a": 1.0}, {"a": 0.25, "b": 0.75}) == 1.0  # b has no data: a carries the score
    assert weighted({}, {"a": 1.0}) == 0.0
    assert ema(0.0, 1.0, dt=1.0, tau=1.0) == pytest.approx(0.632, abs=0.001)


# --- reaction (B1) ---------------------------------------------------------------------------------------------------


async def test_verbal_reaction_and_baseline() -> None:
    rig = Rig(scene=5)
    for latency in (0.8, 1.0, 1.2):
        question(rig)
        rig.run(latency)
        rig.browser({"type": "speech_onset", "ts": rig.t})
        rig.run(0.2)
    reaction = rig.state.driver.reaction
    assert reaction.verbal_ms == pytest.approx(1200, abs=70)
    assert reaction.baseline_ms["verbal"] == pytest.approx(1000, abs=70)  # median of the first three
    assert reaction.baseline_ms["visual"] == th("reaction", "default_baseline_ms", "visual")  # not learned yet
    assert reaction.response_rate_10min == 1.0 and reaction.missed == 0


async def test_unanswered_question_counts_as_missed() -> None:
    rig = Rig(scene=5)
    question(rig)
    rig.run(th("reaction", "missed_ms", "verbal") / 1000.0 + 0.3)
    reaction = rig.state.driver.reaction
    assert reaction.missed == 1 and reaction.response_rate_10min == 0.0
    assert reaction.verbal_ms == th("reaction", "missed_ms", "verbal")


async def test_gesture_reaction() -> None:
    rig = Rig(scene=5)
    rig.run(0.5)
    question(rig)
    rig.run(0.9)
    rig.press("y")
    rig.run(0.2)
    assert rig.state.driver.reaction.gesture_ms == pytest.approx(900, abs=70)


async def test_visual_reaction_from_an_off_road_episode() -> None:
    rig = Rig(scene=8)
    off = th("safety", "distraction", "off_road_ms_high_speed") / 1000.0
    rig.patch = look_at("infotainment", rig.t + 0.5, rig.t + 0.5 + off + 0.8)  # cue at +off, back 0.8 s later
    rig.run(0.5 + off + 1.5)
    assert rig.hub.events("visual_cue")
    assert rig.state.driver.reaction.visual_ms == pytest.approx(800, abs=150)


# --- fatigue F, disengagement D, events ------------------------------------------------------------------------------


async def test_normal_driving_keeps_f_and_d_low() -> None:
    rig = Rig(scene=8)
    rig.command("time_scale", 20)
    rig.run(90.0)
    assessment = rig.state.assessment
    assert assessment.fatigue < 0.2
    assert assessment.disengagement < th("disengagement", "low")  # monotonous highway, but the gaze moves
    assert not rig.hub.events("fatigue_high") and not rig.hub.events("disengagement_high")


async def test_scene_6_fatigue_reaches_the_assistant_once() -> None:
    client = FakeClient()
    rig = Rig(scene=6, assistant=client)
    rig.command("time_scale", 20)
    rig.run(30.0)
    rig.press("6")
    rig.run(90.0)
    await rig.link.drain()
    assert rig.state.assessment.fatigue >= th("fatigue", "high")
    assert len(rig.hub.events("fatigue_high")) == 1 and client.types().count("fatigue_high") == 1
    assert rig.state.assessment.disengagement < 0.1  # D does not count with a tired driver
    terms = rig.hub.events("fatigue_high")[0]["data"]["terms"]
    assert {"perclos", "blink_duration", "yawn"} <= set(terms)


async def test_scene_5_disengagement_on_a_monotonous_highway() -> None:
    client = FakeClient()
    rig = Rig(scene=5, assistant=client)
    rig.command("time_scale", 20)
    rig.run(30.0)
    rig.press("5")
    rig.run(90.0)
    await rig.link.drain()
    assert rig.scores.disengagement.monotonous
    assert rig.state.assessment.disengagement >= th("disengagement", "high")
    assert "disengagement_high" in client.types()


async def test_disengagement_does_not_count_in_the_city() -> None:
    rig = Rig(scene=2)  # city: not monotonous
    rig.command("time_scale", 20)
    rig.press("5")
    rig.run(90.0)
    assert rig.state.assessment.disengagement == 0.0 and not rig.hub.events("disengagement_high")


async def test_silenced_assistant_gets_no_initiative() -> None:
    client = FakeClient()
    rig = Rig(scene=5, assistant=client)
    rig.state.assistant.muted_until = rig.t + 3600
    rig.command("time_scale", 20)
    rig.press("5")
    rig.run(60.0)
    await rig.link.drain()
    event = rig.hub.events("disengagement_high")[0]
    assert event["data"]["muted"] is True and "disengagement_high" not in client.types()


# --- attention, risk, blind meters, conversation ---------------------------------------------------------------------


async def test_phone_at_speed_means_low_attention_and_high_risk() -> None:
    rig = Rig(scene=8)
    rig.press("3")
    rig.run(12.0)
    assert rig.state.assessment.attention < 0.3 and rig.state.assessment.risk >= 2
    parked = Rig(scene=1)
    parked.press("3")
    parked.run(12.0)
    assert parked.state.assessment.risk == 0  # no speed, no risk


async def test_blind_meters() -> None:
    rig = Rig(scene=8)  # 118 km/h
    rig.patch = look_at("lap", rig.t + 0.5, rig.t + 2.5)  # 2 s off the road
    rig.run(4.0)
    expected = 118 / 3.6 * 2.0
    assert rig.state.blind_m.last == pytest.approx(expected, rel=0.1)
    assert rig.state.blind_m.trip >= rig.state.blind_m.last


async def test_conversation_needs_alternating_lips() -> None:
    rig = Rig(scene=4)
    rig.press("c")
    rig.run(12.0)
    assert rig.state.conversation is True
    rig.press("c")
    rig.run(th("conversation", "window_s") + th("conversation", "hold_s") + 1.0)
    assert rig.state.conversation is False


async def test_director_reset_clears_the_scores() -> None:
    rig = Rig(scene=5)
    rig.command("time_scale", 20)
    rig.press("5")
    rig.run(60.0)
    assert rig.state.assessment.disengagement > 0.3
    rig.press("1")
    rig.command("reset")
    rig.run(0.5)
    assert rig.state.assessment.disengagement == 0.0 and rig.state.driver.reaction.missed == 0
