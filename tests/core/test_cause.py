"""Tests for core/cause.py (B4: the cause from the two cameras) and core/intervention.py (D2, D6: the measured effect).
Scene 4 (the passenger shows a phone, "Maria, poți să-i povestești tu?"), scene 5 (music), in fake time."""

from __future__ import annotations

from typing import Any

import pytest
from p2_helpers import FakeClient, Rig

from assistant.client import AssistantClient
from core import messages_timing
from core.settings import th
from shared import contracts as c

pytestmark = pytest.mark.asyncio


def look_at(zone: str, windows: list[tuple[float, float]]) -> Any:
    """A patch: the driver looks at ``zone`` during each (start, end) window."""

    def patch(frame: dict[str, Any], t: float) -> None:
        if any(a <= t < b for a, b in windows):
            frame["driver"]["gaze"].update(zone=zone, conf=0.9, off_road_ms=0.0)

    return patch


def causes(rig: Rig) -> list[str]:
    return [e["data"]["label"] for e in rig.hub.events("cause")]


# --- B4 --------------------------------------------------------------------------------------------------------------


async def test_scene_4_passenger_shows_a_phone() -> None:
    """Three glances at the passenger + the passenger camera sees her phone = one cause, from both cameras."""
    client = FakeClient()
    rig = Rig(scene=4, assistant=client)
    rig.run(3.0)
    rig.press("4")
    rig.run(9.0)
    await rig.link.drain()
    cause = rig.state.cause
    assert (cause.label, cause.target, cause.person_id) == ("passenger_showing_phone", "passenger", 2)
    assert cause.glances_30s == 3 and set(cause.sources) == {"cam_driver", "cam_passenger"}
    assert causes(rig) == ["passenger_showing_phone"]
    assert rig.hub.events("cause")[0]["text"] == "Cauză: pasagerul îi arată ceva pe telefon (3 priviri spre dreapta)."
    assert client.types().count("cause_detected") == 1
    assert not rig.hub.events("visual_cue") and rig.state.ab.our_alerts == 0  # G5: no driver alert


async def test_glances_without_the_phone_are_not_that_cause() -> None:
    rig = Rig(scene=4)
    start = rig.t + 1
    rig.patch = look_at("passenger", [(start, start + 1), (start + 3, start + 4), (start + 6, start + 7)])
    rig.run(9.0)
    assert rig.state.cause.label is None  # the passenger camera sees no phone and no talking


async def test_passenger_talk() -> None:
    rig = Rig(scene=4)
    rig.press("c")  # the passenger speaks every other 2 s
    start = rig.t + 1
    rig.patch = look_at("passenger", [(start, start + 1), (start + 3, start + 4), (start + 6, start + 7)])
    rig.run(9.0)
    assert rig.state.cause.label == "passenger_talk"


async def test_incoming_message_then_phone() -> None:
    rig = Rig(scene=3)
    rig.command("fake_message", {"from": "Mihai", "app": "whatsapp", "text": "Unde ești?"})
    rig.press("3")  # takes the phone
    rig.run(0.5)
    assert rig.state.cause.label == "incoming_message" and rig.state.cause.target == "phone"
    rig.run(th("cause", "message_window_s") + 1.0)
    assert rig.state.cause.label == "phone"  # the message is old now: just the phone
    assert causes(rig) == ["incoming_message", "phone"]


async def test_child_in_the_back() -> None:
    rig = Rig(scene=4)
    rig.command("declare_occupant", {"profile": "ioana", "role": "child"})
    start = rig.t + 1
    rig.patch = look_at("rear_seat", [(start, start + 1), (start + 3, start + 4), (start + 6, start + 7)])
    rig.run(9.0)
    assert (rig.state.cause.label, rig.state.cause.target, rig.state.cause.person_id) == ("child_activity", "rear", 3)


async def test_cause_is_held_then_cleared() -> None:
    rig = Rig(scene=4)
    rig.press("4")  # glances at 0, 3.5 and 7 s
    rig.run(9.0)
    rig.press("1")  # the passenger puts the phone away
    # the evidence ends when the first glance leaves the window (window_s after it); the label stays hold_s more
    rig.run(th("cause", "window_s") + th("cause", "hold_s") / 2 - 9.0)
    assert rig.state.cause.label == "passenger_showing_phone"
    rig.run(th("cause", "hold_s"))
    assert rig.state.cause.label is None


async def test_phone_cause_is_not_sent_to_the_assistant() -> None:
    client = FakeClient()
    rig = Rig(scene=3, assistant=client)
    rig.press("3")
    rig.run(2.0)
    await rig.link.drain()
    assert rig.state.cause.label == "phone" and "cause_detected" not in client.types()


async def test_cabin_causes_defer_messages_but_a_message_does_not_defer_itself() -> None:
    state = c.State.model_validate({"trip": {"speed_kmh": 50}, "cause": {"label": "passenger_talk"}})
    assert messages_timing.decide(state) == ("defer", "distraction")
    state.cause.label = "incoming_message"
    assert messages_timing.decide(state)[0] in ("ask", "read")


# --- D2, D6 ----------------------------------------------------------------------------------------------------------


async def test_scene_4_remedy_and_its_effect_with_p3s_client() -> None:
    rig = Rig(scene=4, assistant=AssistantClient())  # P3's fixed texts
    rig.run(3.0)
    await rig.link.drain()  # greeting
    rig.press("4")
    rig.run(9.0)
    await rig.link.drain()
    said = [s["text"] for s in rig.speaks()]
    assert "Maria, poți să-i povestești tu?" in said and "Andrei, ochii pe drum." in said
    rig.run(th("intervention", "after_s") + 0.5)
    effect = rig.hub.events("intervention_effect")[0]
    assert effect["data"]["kind"] == "delegate" and effect["data"]["helped"] is True
    assert effect["text"].startswith("Cauză rezolvată ✓ (+100%)")
    assert (rig.state.intervention.last, rig.state.intervention.effect_pct) == ("delegate", 100)
    assert rig.state.intervention.stats == {"delegate": 1.0}


async def test_remedy_that_does_not_help_is_reported() -> None:
    rig = Rig(scene=4, assistant=FakeClient({"cause_detected": [c.Action(type="speak", to="passenger",
                                                                          text="Maria, poți să-i povestești tu?")]}))
    rig.run(3.0)
    rig.press("4")
    rig.run(9.0)
    await rig.link.drain()
    rig.press("4")  # she keeps showing it: three more glances
    rig.run(th("intervention", "after_s") + 0.5)
    effect = rig.hub.events("intervention_effect")[0]
    assert effect["data"]["helped"] is False
    assert effect["text"] == "Remediul nu a ajutat: privirile spre pasager nu au scăzut. Se renunță la el."


async def test_music_effect_on_disengagement() -> None:
    plays = [c.Action(type="play_media", track_id="pop1", title="Pop", reason="disengagement")]
    rig = Rig(scene=5, assistant=FakeClient({"disengagement_high": plays}))
    rig.command("time_scale", 20)
    rig.run(20.0)
    rig.press("5")
    rig.run(40.0)
    await rig.link.drain()
    assert rig.state.media.reason == "disengagement" and rig.scores.intervention.running is not None
    rig.press("1")  # the driver looks around again with the music on...
    for _ in range(2):  # ...and answers the assistant promptly (in the demo: "da" to the music offer, then a chat)
        rig.browser({"type": "speak_done", "id": "q", "is_question": True, "interrupted": False, "ts": rig.t})
        rig.run(0.6)
        rig.browser({"type": "speech_onset", "ts": rig.t})
        rig.browser({"type": "speech", "text": "da, pune ceva bun", "final": True, "addressed": True, "ts": rig.t})
        rig.run(2.0)
    rig.run(th("intervention", "after_s") - 5.2 + 0.5)
    effect = rig.hub.events("intervention_effect")[0]
    assert effect["data"]["kind"] == "music" and effect["data"]["after"] < effect["data"]["before"]
    assert rig.state.intervention.last == "music_energetic" and rig.state.intervention.effect_pct > 0


async def test_requested_music_is_not_an_intervention() -> None:
    rig = Rig(scene=5, assistant=FakeClient({"driver_speech": [c.Action(type="play_media", track_id="pop1")]}))
    rig.run(20.0)
    rig.say("pune muzică", addressed=True)
    await rig.link.drain()
    assert rig.state.media.reason == "driver_request" and rig.scores.intervention.running is None


async def test_too_early_to_measure() -> None:
    rig = Rig(scene=4)
    assert rig.scores.intervention.start("delegate", rig.t) is False
    assert rig.hub.events("intervention_skipped")
