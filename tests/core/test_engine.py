"""Tests for core/engine.py (the 10 Hz state) and core/simulation.py (the stand-in trip)."""

from __future__ import annotations

from typing import Any

import pytest

from core.engine import Engine
from core.hub import Hub
from core.settings import th
from core.simulation import FUEL, FakeSimulator
from scripts.fake_perception import FakePerception
from shared import contracts as c

T0 = 1_000_000.0


class RecordingHub(Hub):
    """A hub without sockets: remembers what core sent."""

    def __init__(self) -> None:
        super().__init__()
        self.ui_sent: list[dict[str, Any]] = []
        self.perception_sent: list[dict[str, Any]] = []
        self.phone_sent: list[dict[str, Any]] = []

    def broadcast_ui(self, message: dict[str, Any]) -> bool:
        self.ui_sent.append(message)
        return True

    def send_perception(self, message: dict[str, Any]) -> bool:
        self.perception_sent.append(message)
        return True

    def send_phone(self, message: dict[str, Any]) -> bool:
        self.phone_sent.append(message)
        return True

    def events(self, type_: str) -> list[dict[str, Any]]:
        return [m["event"] for m in self.ui_sent if m["type"] == "event" and m["event"]["type"] == type_]


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def hub() -> RecordingHub:
    return RecordingHub()


@pytest.fixture
def engine(hub: RecordingHub) -> Engine:
    return Engine(hub, FakeSimulator())


def feed(engine: Engine, key: str = "1", now: float = T0) -> c.PerceptionFrame:
    fake = FakePerception(now=now)
    fake.press(key, now)
    frame = fake.frame(now)
    engine.on_perception_message(frame, now)
    assert engine.frame is not None
    return engine.frame


# --- perception -> state ---------------------------------------------------------------------------------------------


def test_no_perception_means_monitoring_lost(engine: Engine) -> None:
    state = engine.tick(T0)
    assert state.seq == 1 and state.ts == T0
    assert state.safety.monitoring_ok is False
    assert state.driver.monitoring_reason == "camera_unavailable"
    assert state.occupants == [] and state.passenger.present is False
    assert state.trip.speed_kmh > 0  # the fake trip is running
    assert state.integrations.phone_bridge == "down"


def test_fresh_frame_fills_the_perception_blocks(engine: Engine) -> None:
    frame = feed(engine)
    engine.state.driver.reaction.missed = 2  # P2's block survives the copy
    engine.core_perf["alarm_ms_last"] = 120.0
    state = engine.tick(T0 + 0.05)
    assert state.safety.monitoring_ok is True
    assert state.driver.eyes.ear == frame.driver.eyes.ear and state.driver.gaze.zone == frame.driver.gaze.zone
    assert state.driver.reaction.missed == 2
    assert [o.seat for o in state.occupants] == ["driver", "front_right"]
    assert state.passenger.present is True
    assert state.perf.face_driver_ms_p50 == frame.perf.face_driver_ms_p50 and state.perf.alarm_ms_last == 120.0


def test_stale_frame_is_not_used(engine: Engine) -> None:
    engine.on_perception_connected(True, T0)
    feed(engine)
    state = engine.tick(T0 + th("loop", "perception_stale_ms") / 1000.0 + 0.1)
    assert state.safety.monitoring_ok is False
    assert state.driver.monitoring_reason == "no_frames"
    assert state.driver.eyes.ear is None


def test_covered_camera_reaches_the_safety_block(engine: Engine) -> None:
    feed(engine, "9")
    state = engine.tick(T0)
    assert state.safety.monitoring_ok is False and state.driver.monitoring_reason == "occluded"


def test_invalid_perception_message_is_counted_not_raised(engine: Engine) -> None:
    engine.on_perception_message({"seq": "not a number"}, T0)
    engine.on_perception_message({"type": "ack"}, T0)  # no cmd / status
    assert engine.invalid_messages == 2 and engine.frame is None


def test_calibration_messages_reach_the_log(engine: Engine, hub: RecordingHub) -> None:
    engine.on_perception_message({"type": "calibration_prompt", "zone": "mirror_left", "text": "Uită-te în oglindă"},
                                 T0)
    engine.on_perception_message({"type": "ack", "cmd": "calibrate", "status": "done", "detail": {"acc": 0.9}}, T0)
    assert hub.events("calibration_prompt")[0]["text"] == "Uită-te în oglindă"
    assert hub.events("calibrate_done")[0]["data"]["detail"] == {"acc": 0.9}


# --- director commands -----------------------------------------------------------------------------------------------


def test_debug_and_calibrate_are_forwarded_to_perception(engine: Engine, hub: RecordingHub) -> None:
    engine.on_browser_message({"type": "command", "cmd": "debug", "on": True}, T0)
    engine.on_browser_message({"type": "command", "cmd": "calibrate", "value": {"profile": "andrei", "quick": True}},
                              T0)
    assert hub.perception_sent[0] == {**hub.perception_sent[0], "type": "command", "cmd": "debug", "on": True}
    assert (hub.perception_sent[1]["cmd"], hub.perception_sent[1]["profile"], hub.perception_sent[1]["quick"]) == (
        "calibrate", "andrei", True)
    for sent in hub.perception_sent:
        c.PerceptionCommand.model_validate(sent)


def test_llm_switch(engine: Engine, hub: RecordingHub) -> None:
    engine.on_browser_message({"type": "command", "cmd": "llm", "on": False}, T0)
    state = engine.tick(T0)
    assert state.safety.llm_enabled is False and state.integrations.llm == "off"
    assert hub.events("llm_toggled")[0]["data"] == {"enabled": False}
    engine.on_browser_message({"type": "command", "cmd": "llm", "on": True}, T0)
    assert engine.tick(T0).integrations.llm == "unknown"


def test_declared_rear_occupant(engine: Engine) -> None:
    feed(engine)
    engine.on_browser_message({"type": "command", "cmd": "declare_occupant",
                               "value": {"profile": "ioana", "role": "child"}}, T0)
    rear = [o for o in engine.tick(T0).occupants if o.seat == "rear"]
    assert len(rear) == 1 and (rear[0].id, rear[0].role, rear[0].source) == (3, "child", "declared")
    engine.on_browser_message({"type": "command", "cmd": "declare_occupant", "value": {"remove": 3}}, T0)
    assert not [o for o in engine.tick(T0).occupants if o.seat == "rear"]


def test_scene_and_poi_commands_drive_the_trip(engine: Engine) -> None:
    engine.on_browser_message({"type": "command", "cmd": "scene", "value": 8}, T0)
    trip = engine.tick(T0).trip
    assert (trip.road, trip.speed_kmh, trip.scene) == ("highway", 118.0, 8)
    engine.on_browser_message({"type": "command", "cmd": "stop_at_next_poi"}, T0)
    trip = engine.tick(T0).trip
    assert trip.stopped and trip.speed_kmh == 0 and trip.at_poi is not None and trip.at_poi.category == "fuel"


def test_fake_message_is_queued_and_its_text_stays_in_core(engine: Engine, hub: RecordingHub) -> None:
    engine.on_browser_message({"type": "command", "cmd": "fake_message",
                               "value": {"from": "Mihai", "app": "whatsapp", "text": "Unde ești?"}}, T0)
    state = engine.tick(T0)
    assert [(m.id, m.from_, m.state, m.text) for m in state.messages] == [("m1", "Mihai", "pending", "Unde ești?")]
    wire = engine.ui_payload(state)["state"]["messages"][0]
    assert wire["from"] == "Mihai" and "text" not in wire
    engine.on_browser_message({"type": "command", "cmd": "fake_message", "value": {"app": "telegram"}}, T0)
    assert len(engine.state.messages) == 1  # invalid app: rejected, counted
    assert hub.events("message_queued")


def test_reset_starts_a_new_trip_but_keeps_the_llm_switch(engine: Engine) -> None:
    engine.on_browser_message({"type": "command", "cmd": "llm", "on": False}, T0)
    engine.on_browser_message({"type": "command", "cmd": "declare_occupant", "value": {"profile": "ioana"}}, T0)
    engine.on_browser_message({"type": "command", "cmd": "fake_message", "value": {"from": "Mihai", "text": "x"}}, T0)
    engine.on_browser_message({"type": "command", "cmd": "reset"}, T0)
    state = engine.tick(T0)
    assert state.messages == [] and not [o for o in state.occupants if o.seat == "rear"]
    assert state.safety.llm_enabled is False and state.seq == 1


# --- phone bridge ----------------------------------------------------------------------------------------------------


def test_phone_bridge_messages(engine: Engine) -> None:
    engine.on_phone_message({"type": "phone_status", "connected": True, "battery": 64}, T0)
    engine.on_phone_message({"type": "phone_message", "notification_id": "n42", "app": "whatsapp", "from": "Mihai",
                             "text": "Salut", "replyable": True, "ts": T0}, T0)
    engine.on_phone_message({"type": "phone_result", "request_id": "r1", "ok": True}, T0)
    engine.on_phone_message({"type": "phone_message", "app": "telegram"}, T0)  # not whitelisted: invalid
    state = engine.tick(T0)
    assert (state.phone.connected, state.phone.battery) == (True, 64)
    assert state.messages[0].replyable and engine.notifications == {"m1": "n42"}
    assert engine.invalid_messages == 1


# --- plug-in points --------------------------------------------------------------------------------------------------


def test_listeners_see_frames_browser_messages_and_ticks(engine: Engine) -> None:
    seen: dict[str, list[Any]] = {"frame": [], "browser": [], "tick": []}
    engine.add_frame_listener(lambda frame, now: seen["frame"].append(frame.seq))
    engine.add_browser_listener(lambda message, now: seen["browser"].append(message.type))
    engine.add_tick_listener(lambda state, now: seen["tick"].append(state.seq))
    feed(engine)
    assert seen["frame"] == [1]  # at once, not at the next tick: the fast safety path
    engine.on_browser_message({"type": "speech_onset", "ts": T0}, T0)
    engine.on_browser_message({"type": "alarm_played", "id": "a1", "ts": T0}, T0)
    engine.tick(T0)
    assert seen["browser"] == ["speech_onset", "alarm_played"] and seen["tick"] == [1]


def test_published_state_is_valid_json_for_the_dashboard(engine: Engine, hub: RecordingHub) -> None:
    feed(engine)
    engine.publish(engine.tick(T0))
    message = hub.ui_sent[-1]
    assert message["type"] == "state"
    assert isinstance(c.parse_ui_message(message), c.UiState)


# --- fake simulator --------------------------------------------------------------------------------------------------


def test_fake_simulator_moves_and_stops() -> None:
    clock = Clock()
    sim = FakeSimulator(clock)
    sim.command(c.UiCommand(cmd="speed", value=60))
    sim.tick()
    clock.t += 60.0  # one minute at 60 km/h
    trip = sim.tick()
    assert trip.elapsed_min == pytest.approx(1.0) and trip.next_poi is not None
    assert trip.next_poi.dist_km == pytest.approx((FUEL.km or 0) - 31.0, abs=0.1)
    sim.command(c.UiCommand(cmd="time_scale", value=20))
    clock.t += 60.0
    assert sim.tick().elapsed_min == pytest.approx(21.0)
    sim.command(c.UiCommand(cmd="pause"))
    clock.t += 60.0
    paused = sim.tick()
    assert paused.speed_kmh == 0 and paused.stopped and paused.elapsed_min == pytest.approx(21.0)
