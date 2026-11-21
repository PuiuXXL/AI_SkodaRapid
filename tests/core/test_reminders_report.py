"""Tests for core/reminders.py K2 (scene 7: "Ai zis să iei lichid de parbriz." at the fuel station) and
core/scorecard.py J2 / J3 (the live scorecard and the trip report of scene 10), in fake time."""

from __future__ import annotations

from typing import Any

import pytest
from p2_helpers import FakeClient, Rig

from core.settings import th
from shared import contracts as c

pytestmark = pytest.mark.asyncio

FUEL = c.ReminderTrigger(type="stop_at_category", category="fuel")


def with_reminders(rig: Rig, *tasks: str, category: str = "fuel") -> None:
    trigger = c.ReminderTrigger(type="stop_at_category", category=category)
    for i, task in enumerate(tasks, start=1):
        rig.state.reminders.append(c.Reminder(id=f"r{i}", task=task, trigger=trigger, state="active"))


def stop_at_fuel(rig: Rig) -> None:
    rig.command("scene", 7)  # stopped at OMV (fuel)
    rig.run(th("reminders", "stopped_min_s") + 0.3)


def reminder_speech(rig: Rig) -> list[dict[str, Any]]:
    return [s for s in rig.speaks() if s["id"].startswith("rem")]


# --- K2 --------------------------------------------------------------------------------------------------------------


async def test_scene_7_thumbs_up_ticks_the_reminder() -> None:
    client = FakeClient()
    rig = Rig(scene=5, assistant=client)
    with_reminders(rig, "lichid de parbriz")
    rig.run(1.0)
    stop_at_fuel(rig)
    asked = reminder_speech(rig)[0]
    assert (asked["text"], asked["is_question"]) == ("Ai zis să iei lichid de parbriz.", True)
    assert rig.hub.perception_sent[-1]["cmd"] == "dialog_window" and rig.state.interaction.dialog_window_open
    rig.press("g")  # 👍
    rig.run(0.3)
    assert rig.state.reminders[0].state == "done" and rig.state.scorecard.reminders_done == 1
    assert reminder_speech(rig)[-1]["clip_url"] == "/sounds/clips/confirm_done.mp3"
    assert rig.hub.events("reminder_done")[0]["channel"] == "gesture"
    await rig.link.drain()
    assert "driver_speech" not in client.types()


async def test_no_keeps_it_for_the_next_stop_and_never_reaches_the_assistant() -> None:
    client = FakeClient()
    rig = Rig(scene=5, assistant=client)
    with_reminders(rig, "lichid de parbriz")
    stop_at_fuel(rig)
    rig.say("nu", addressed=False)
    await rig.link.drain()
    assert rig.state.reminders[0].state == "active"
    assert reminder_speech(rig)[-1]["text"] == "Bine, ți-l amintesc la următoarea oprire."
    assert "driver_speech" not in client.types()


async def test_once_per_stop_and_again_at_the_next_one() -> None:
    rig = Rig(scene=5)
    with_reminders(rig, "lichid de parbriz")
    stop_at_fuel(rig)
    rig.run(th("dialog", "window_s") + 5.0)  # no answer: kept
    assert len([s for s in reminder_speech(rig) if s["is_question"]]) == 1
    assert rig.hub.events("reminder_kept")
    rig.command("scene", 5)  # drives off
    rig.run(1.0)
    stop_at_fuel(rig)
    assert len([s for s in reminder_speech(rig) if s["is_question"]]) == 2


async def test_only_its_category_only_stopped() -> None:
    rig = Rig(scene=5)
    with_reminders(rig, "medicamente", category="pharmacy")
    stop_at_fuel(rig)
    rig.command("scene", 5)
    rig.run(5.0)
    assert reminder_speech(rig) == []


async def test_several_tasks_in_one_sentence() -> None:
    rig = Rig(scene=5)
    with_reminders(rig, "lichid de parbriz", "apă")
    stop_at_fuel(rig)
    assert reminder_speech(rig)[0]["text"] == "Ai zis să iei lichid de parbriz și apă."
    rig.say("da", addressed=False)
    assert [r.state for r in rig.state.reminders] == ["done", "done"] and rig.state.scorecard.reminders_done == 2


async def test_said_even_while_the_assistant_is_silent() -> None:
    rig = Rig(scene=5)
    with_reminders(rig, "lichid de parbriz")
    rig.state.assistant.muted_until = rig.t + 3600  # scene 6 just before: the driver refused the assistant
    stop_at_fuel(rig)
    assert reminder_speech(rig)


# --- J2, J3 ----------------------------------------------------------------------------------------------------------


def long_glance(start: float, end: float) -> Any:
    def patch(frame: dict[str, Any], t: float) -> None:
        if start <= t < end:
            frame["driver"]["gaze"].update(zone="infotainment", conf=0.9, off_road_ms=round((t - start) * 1000.0, 1))

    return patch


async def test_longest_focus_breaks_at_a_long_glance() -> None:
    rig = Rig(scene=8)
    rig.command("time_scale", 20)
    rig.run(30.0)  # ~10 trip minutes of normal driving
    focus = rig.state.scorecard.longest_focus_min
    assert focus == pytest.approx(rig.state.trip.elapsed_min, abs=0.5)
    rig.patch = long_glance(rig.t, rig.t + 3.0)
    rig.run(3.5)
    rig.patch = None
    rig.run(6.0)  # 2 trip minutes: shorter than the first stretch
    assert rig.state.scorecard.longest_focus_min == focus


async def test_phone_touches() -> None:
    rig = Rig(scene=8)
    for _ in range(2):
        rig.press("3")
        rig.run(2.0)
        rig.press("1")
        rig.run(1.0)
    assert rig.state.scorecard.phone_touches == 2
    parked = Rig(scene=1)
    parked.press("3")
    parked.run(3.0)
    assert parked.state.scorecard.phone_touches == 0


async def test_trip_report_at_the_end_and_before_a_reset() -> None:
    rig = Rig(scene=5)
    rig.command("time_scale", 20)
    rig.run(25.0)
    rig.browser({"type": "speak_done", "id": "q", "is_question": True, "interrupted": False, "ts": rig.t})
    rig.run(0.8)
    rig.browser({"type": "speech_onset", "ts": rig.t})
    rig.command("end_trip")
    report = rig.hub.events("trip_report")[0]["data"]["report"]
    assert report["distance_km"] > 1.0 and report["elapsed_min"] > 5.0
    assert set(report) >= {"id", "at", "stops", "scorecard", "blind_m", "ab", "history", "effects", "reaction",
                           "reaction_mean_ms", "log"}
    assert report["reaction_mean_ms"]["verbal"] == pytest.approx(800, abs=120)
    assert len(report["history"]) >= 2 and report["blind_m_previous_trip"] is None
    assert rig.hub.events("trip_report")[0]["text"].startswith("Fișa călătoriei:")
    rig.command("reset")  # the second report is the same trip again (reset publishes before clearing)
    second = rig.hub.events("trip_report")[1]["data"]["report"]
    assert second["blind_m_previous_trip"] == report["blind_m"]
    assert rig.state.scorecard.longest_focus_min == 0.0
