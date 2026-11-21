"""K4 (core/attractions.py): a tourist sight on the map route is proposed once, and a "yes" stops the car there."""

from __future__ import annotations

from typing import Any

import pytest
from p2_helpers import Rig

from assistant.client import AssistantClient
from core.attractions import AttractionRule, attractions_ahead
from core.reminders import pick_stop
from shared import contracts as c

simulator = pytest.importorskip("simulator")


def route_file() -> dict[str, Any]:
    """11 km north along 23°E; a fort 1.5 km east of the road at km 7.8."""
    return {"id": "r1", "origin": {"id": "a", "name": "Sud", "category": "origin", "lat": 46.0, "lon": 23.0},
            "stops": [{"id": "d", "name": "Nord", "category": "destination", "lat": 46.1, "lon": 23.0}],
            "geometry": [{"lat": 46.0 + i * 0.01, "lon": 23.0} for i in range(11)],
            "attractions": [{"id": "s1", "name": "Cetate", "kind": "fort", "lat": 46.07, "lon": 23.02,
                             "description": "O cetate."}]}


def spoken(rig: Rig) -> list[str]:
    return [s["text"] for s in rig.speaks()]


def speak_done(rig: Rig, text: str) -> None:
    utterance = next(s for s in rig.speaks() if s["text"] == text)
    rig.browser({"type": "speak_done", "id": utterance["id"], "is_question": utterance["is_question"],
                 "interrupted": False, "ts": rig.t})


async def map_rig() -> tuple[Rig, Any]:
    rig = Rig(scene=1, assistant=AssistantClient())  # no LLM key: P3's fixed texts
    sim = simulator.Simulator(clock=lambda: rig.t)
    rig.engine.simulator = sim
    AttractionRule(rig.engine)
    sim.set_route(route_file())
    for cmd, value in (("speed", 60), ("time_scale", 20), ("start", None)):
        rig.command(cmd, value)
    rig.run(3.0)  # the greeting first, out of the way
    await rig.link.drain()
    for text in spoken(rig):
        speak_done(rig, text)
    return rig, sim


@pytest.mark.asyncio
async def test_a_sight_ahead_is_proposed_once_and_yes_stops_the_car_there() -> None:
    rig, sim = await map_rig()
    rig.run_until(lambda: rig.hub.events("attraction_suggested"))
    event = rig.hub.events("attraction_suggested")[0]
    assert event["data"]["poi_id"] == "s1" and event["data"]["description"] == "O cetate."
    assert rig.state.trip.elapsed_min >= 5  # attractions.min_drive_min
    await rig.link.drain()
    question = spoken(rig)[-1]
    assert question.startswith("Peste ") and question.endswith("e Cetate. Facem o pauză acolo?")
    speak_done(rig, question)
    rig.press("y")  # a nod
    rig.run(0.3)
    assert any("Mașina oprește acolo." in (e["text"] or "") for e in rig.hub.events("assistant_action"))
    rig.run_until(lambda: rig.state.trip.at_poi is not None, limit_s=60)
    assert (rig.state.trip.at_poi.id, rig.state.trip.speed_kmh) == ("s1", 0.0)
    assert sim.km == pytest.approx(7.78, abs=0.05)
    rig.command("start")
    rig.run(20)
    assert len(rig.hub.events("attraction_suggested")) == 1  # each sight once


@pytest.mark.asyncio
async def test_no_proposal_while_the_driver_is_not_seen() -> None:
    rig, _ = await map_rig()

    def unseen(frame: dict[str, Any], t: float) -> None:
        frame["driver"].update(monitoring_ok=False, monitoring_reason="face_lost")

    rig.patch = unseen
    rig.run(25)
    assert rig.hub.events("attraction_suggested") == []


def test_without_a_map_route_the_rule_does_nothing() -> None:
    rig = Rig(scene=5)
    AttractionRule(rig.engine)
    rig.run(30)
    assert attractions_ahead(rig.state) == [] and rig.hub.events("attraction_suggested") == []


def test_a_break_prefers_a_sight_unless_a_reminder_needs_the_next_stop() -> None:
    state = c.State()
    state.trip = c.Trip(next_poi=c.Poi(id="b", category="fuel", name="OMV", dist_km=5.0),
                        attractions_ahead=[{"id": "s1", "name": "Cetate", "kind": "fort", "dist_km": 8.0,
                                            "detour_km": 1.5, "description": "O cetate."}])
    stop = pick_stop(state)
    assert stop is not None
    assert (stop["poi_id"], stop["kind"], stop["description"]) == ("s1", "attraction", "O cetate.")
    state.reminders = [c.Reminder(id="r1", task="lichid", state="active",
                                  trigger=c.ReminderTrigger(type="stop_at_category", category="fuel"))]
    stop = pick_stop(state)
    assert stop is not None and stop["poi_id"] == "b" and stop["task"] == "lichid"
