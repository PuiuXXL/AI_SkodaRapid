"""Tests for scripts/fake_perception.py: every key produces valid frames with the situation it promises."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
from typing import Any

import pytest

from scripts import fake_perception as fp
from shared import contracts as c

T0 = 1_000_000.0
HZ = 15.0


def run(fake: fp.FakePerception, start: float, seconds: float) -> list[dict[str, Any]]:
    """Frames from ``start`` for ``seconds`` at 15 Hz, each one re-validated with the contract."""
    frames = []
    for i in range(int(seconds * HZ)):
        frame = fake.frame(start + i / HZ)
        assert isinstance(c.parse_perception_message(frame), c.PerceptionFrame)
        frames.append(frame)
    return frames


def pressed(key: str, seconds: float, *, warmup: float = 0.0, **kwargs: Any) -> list[dict[str, Any]]:
    fake = fp.FakePerception(now=T0, **kwargs)
    if warmup:
        run(fake, T0, warmup)
    fake.press(key, T0 + warmup)
    return run(fake, T0 + warmup, seconds)


@pytest.mark.parametrize("key", sorted(fp.MODES))
def test_every_mode_gives_valid_frames(key: str) -> None:
    frames = pressed(key, 5.0)
    assert [f["seq"] for f in frames] == list(range(1, len(frames) + 1))


def test_normal_driving_has_no_alarm_material() -> None:
    frames = pressed("1", 30.0)
    assert max(f["driver"]["eyes"]["closed_ms"] for f in frames) < 500  # blinks only
    assert {f["driver"]["gaze"]["zone"] for f in frames} >= {"road", "mirror_rear", "cluster", "mirror_left"}
    assert frames[-1]["driver"]["gaze"]["entropy_60s"] > 0.5
    assert all(f["driver"]["monitoring_ok"] for f in frames)
    assert 100 <= frames[-1]["driver"]["eyes"]["blink_ms"] <= 200


def test_mirror_glance_is_driving_but_trips_the_naive_threshold() -> None:
    frames = pressed("2", 4.0)
    mirror = [f for f in frames if f["driver"]["gaze"]["zone"] == "mirror_left"]
    assert len(mirror) / HZ == pytest.approx(fp.MIRROR_GLANCE_S, abs=0.1)
    assert all(f["driver"]["gaze"]["off_road_ms"] == 0 for f in mirror)  # P1 rule: short mirror = on the road
    assert all(abs(f["driver"]["head"]["yaw"]) > 20 for f in mirror)  # naive: |yaw| > 20 deg for > 1.5 s
    assert frames[-1]["driver"]["gaze"]["zone"] == "road"


def test_phone_in_hand() -> None:
    frames = pressed("3", 5.0)
    assert all(f["driver"]["phone"]["in_use"] and f["driver"]["phone"]["source"] == "detector" for f in frames)
    assert any(f["driver"]["gaze"]["zone"] == "lap" for f in frames)


def test_passenger_glances_three_times_while_holding_a_phone() -> None:
    fake = fp.FakePerception(now=T0)
    fake.press("4", T0)
    frames = run(fake, T0, 12.0)
    zones = [f["driver"]["gaze"]["zone"] for f in frames]
    starts = sum(1 for a, b in itertools.pairwise(["road", *zones]) if b == "passenger" and a != "passenger")
    assert starts == 3
    assert all(f["passenger"]["holding_phone"] for f in frames)
    assert any(f["driver"]["phone"]["foreign_seen"] for f in frames)
    assert not any(f["driver"]["phone"]["in_use"] for f in frames)  # G5: not the driver's phone
    fake.press("1", T0 + 12.0)
    assert fake.frame(T0 + 12.1)["passenger"]["holding_phone"] is False


def test_fixed_gaze_has_low_entropy() -> None:
    frames = pressed("5", 61.0, warmup=30.0)
    assert frames[-1]["driver"]["gaze"]["entropy_60s"] < 0.1
    assert frames[-1]["driver"]["gaze"]["vats_60s"] == 0


def test_fatigue_signs_and_sleeping_passenger() -> None:
    frames = pressed("6", 25.0)
    assert any(f["driver"]["yawn"] for f in frames)
    assert all(f["passenger"]["awake"] is False and f["passenger"]["eyes_closed_s"] > 10 for f in frames)
    assert 400 <= frames[-1]["driver"]["eyes"]["blink_ms"] <= 500
    normal = pressed("1", 25.0)
    assert frames[-1]["driver"]["eyes"]["perclos_60s"] > normal[-1]["driver"]["eyes"]["perclos_60s"]


def test_eyes_closed_crosses_the_microsleep_threshold() -> None:
    frames = pressed("7", 1.5)
    eyes = frames[-1]["driver"]["eyes"]
    assert eyes["state"] == "CLOSED" and eyes["closed_ms"] > 1000 and eyes["long_closure"]
    assert all(f["driver"]["eyes"]["microsleep"] is False for f in frames)  # like P1: core decides
    closed = [f["driver"]["eyes"]["closed_ms"] for f in frames]
    assert closed == sorted(closed)  # grows without a reset


def test_head_down_and_no_answer() -> None:
    fake = fp.FakePerception(now=T0, auto_answer=True)
    fake.press("8", T0)
    fake.on_command({"type": "command", "cmd": "dialog_window", "open": True, "to": "driver", "until": T0 + 6}, T0)
    frames = run(fake, T0, 6.0)
    assert frames[0]["driver"]["head"]["nodding"] is True
    assert frames[-1]["driver"]["head"]["pitch"] <= -30
    assert all(f["driver"]["head"]["answer"] is None for f in frames)
    assert frames[-1]["driver"]["eyes"]["closed_ms"] > 5000


def test_camera_covered() -> None:
    frames = pressed("9", 3.0)
    assert all(not f["driver"]["monitoring_ok"] and f["driver"]["monitoring_reason"] == "occluded" for f in frames)
    assert frames[0]["driver"]["head"]["yaw"] is None
    seats = [{o["seat"] for o in f["occupants"]} for f in frames]
    assert "driver" in seats[0] and "driver" not in seats[-1]  # the face is gone after face_lost_s


def test_answers_go_to_the_dialog_window_target() -> None:
    fake = fp.FakePerception(now=T0)
    fake.press("y", T0)
    assert fake.frame(T0 + 0.1)["driver"]["head"]["answer"] == "yes"
    assert fake.frame(T0 + 1.2)["driver"]["head"]["answer"] is None  # held ~1 s
    fake.on_command({"cmd": "dialog_window", "open": True, "to": "passenger", "until": T0 + 10}, T0 + 2)
    fake.press("n", T0 + 2.5)
    frame = fake.frame(T0 + 2.6)
    assert frame["passenger"]["answer"] == "no" and frame["driver"]["head"]["answer"] is None
    fake.press("g", T0 + 3.0)
    assert fake.frame(T0 + 3.1)["passenger"]["gesture"] == "Thumb_Up"


def test_auto_answer_is_slower_when_disengaged() -> None:
    def answer_time(mode: str) -> float | None:
        fake = fp.FakePerception(now=T0, auto_answer=True)
        fake.press(mode, T0)
        fake.on_command({"cmd": "dialog_window", "open": True, "to": "driver", "until": T0 + 6}, T0)
        for i in range(int(6 * HZ)):
            if fake.frame(T0 + i / HZ)["driver"]["head"]["answer"] == "yes":
                return i / HZ
        return None

    normal, slow = answer_time("1"), answer_time("5")
    assert normal is not None and slow is not None and normal < 1.0 < 2.0 < slow
    assert answer_time("7") is None


def test_commands_are_acknowledged_like_p1() -> None:
    fake = fp.FakePerception(now=T0)
    assert fake.on_command({"type": "command", "cmd": "debug", "on": True}, T0)[0]["status"] == "ok"
    statuses = [a["status"] for a in fake.on_command({"type": "calibrate", "profile": "andrei"}, T0)]
    assert statuses == ["started", "done"]
    assert fake.on_command({"cmd": "self_destruct"}, T0)[0]["status"] == "error"


def test_conversation_and_passenger_toggles() -> None:
    fake = fp.FakePerception(now=T0)
    fake.press("c", T0)
    frames = run(fake, T0, 8.0)
    driver = [f["driver"]["speaking"] for f in frames]
    passenger = [f["passenger"]["speaking"] for f in frames]
    assert any(driver) and any(passenger) and not any(d and p for d, p in zip(driver, passenger, strict=True))
    fake.press("p", T0 + 8)
    frame = fake.frame(T0 + 8.1)
    assert frame["passenger"]["present"] is False
    assert [o["seat"] for o in frame["occupants"]] == ["driver"]


def test_parse_script() -> None:
    assert fp.parse_script("3:2, 0:1,8:7") == [(0.0, "1"), (3.0, "2"), (8.0, "7")]
    with pytest.raises(argparse.ArgumentTypeError):
        fp.parse_script("5")


@pytest.mark.asyncio
async def test_websocket_round_trip() -> None:
    """Against a stand-in core: frames arrive valid, a dialog_window gets an ack and an auto answer."""
    websockets = pytest.importorskip("websockets")
    received: list[dict[str, Any]] = []

    async def core(ws: Any) -> None:
        await ws.send(json.dumps({"type": "command", "cmd": "dialog_window", "open": True, "to": "driver"}))
        async for raw in ws:
            received.append(json.loads(raw))

    async with websockets.serve(core, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        args = fp.build_parser().parse_args(["--no-keys", "--auto-answer", "--duration", "2", "--script", "0.2:3"])
        args.url = f"ws://127.0.0.1:{port}/ws/perception"
        await asyncio.wait_for(fp.run(args), timeout=10)

    frames = [m for m in received if "type" not in m]
    acks = [m for m in received if m.get("type") == "ack"]
    assert len(frames) >= 15
    assert all(isinstance(c.parse_perception_message(f), c.PerceptionFrame) for f in frames)
    assert acks and acks[0]["cmd"] == "dialog_window" and acks[0]["status"] == "ok"
    assert any(f["driver"]["head"]["answer"] == "yes" for f in frames)
    assert any(f["driver"]["phone"]["in_use"] for f in frames)  # the scripted key 3 arrived
