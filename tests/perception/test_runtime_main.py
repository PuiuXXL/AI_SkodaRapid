"""Perception runtime: contract, frame building, degradation, monitoring, worker process, main loop, WS, MJPEG.

Worker and main tests spawn real camera processes on a synthetic source without models (``WorkerOptions(models=False)``,
``--no-models``), so they run in CI without a camera or model files.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from perception.config import load_config
from perception.contract import Command, PerceptionFrame, parse_command, validate_frame
from perception.degrade import DegradeController
from perception.driver_cam.pipeline import DriverPipeline
from perception.main import Perception, build_frame
from perception.monitoring import thumbnail
from perception.worker import CameraWorker, WorkerOptions
from tests.perception.driver_factory import H, W, frames

REPO = Path(__file__).resolve().parents[2]
SYNTH = WorkerOptions(synthetic=True, models=False)


# --- contract and frame building ------------------------------------------------------------------------


def _driver_msg(**overrides: Any) -> dict[str, Any]:
    cfg = load_config()
    pipeline = DriverPipeline(cfg, (W, H))
    state = None
    for ff in frames([(3.0, {"ear_left": 0.30})]):
        state = pipeline.update(ff)
    assert state is not None
    msg: dict[str, Any] = {
        "kind": "frame",
        "camera": "driver",
        "seq": 1,
        "t_capture": time.perf_counter(),
        "connected": True,
        "state": state.model_dump(mode="json"),
        "phone": {"in_use": True, "conf": 0.8, "near_face": True, "side": "left"},
        "gesture": "Thumb_Up",
        "dialog_open": True,
        "monitoring": {"ok": True, "reason": None, "face_missing_s": 0.0},
        "luma": 120.0,
        "perf": {
            "models": {"face": {"p50": 8.0, "p95": 9.0, "n": 100.0}, "phone": {"p50": 12.0, "p95": 15.0, "n": 20.0}},
            "capture_fps": 30.0,
            "process_fps": 29.5,
            "dropped_frames": 3,
            "reconnects": 0,
        },
    }
    msg.update(overrides)
    return msg


def test_built_frame_is_a_valid_perception_frame() -> None:
    cfg = load_config()
    data = build_frame(
        cfg,
        seq=7,
        ts=time.time(),
        driver=_driver_msg(),
        passenger=_driver_msg(camera="passenger"),
        cameras={"driver": True, "passenger": True},
        e2e_ms_p95=42.0,
        system={"cpu": 30.0, "ram_mb": 900.0, "gpu": None},
    )
    frame = PerceptionFrame.model_validate(data)
    assert frame.seq == 7
    assert frame.driver.eyes.reliable and frame.driver.eyes.eye_used in ("left", "right")
    assert frame.driver.eyes.microsleep is False  # P2 decides
    assert frame.driver.phone.in_use and frame.driver.phone.source == "detector"
    assert frame.driver.gesture == "Thumb_Up"
    assert [o.seat for o in frame.occupants] == ["driver", "front_right"]
    assert frame.passenger.present and frame.passenger.holding_phone
    assert frame.perf.face_driver_ms_p50 == 8.0 and frame.perf.e2e_ms_p95 == 42.0
    assert frame.perf.cameras["driver"].dropped_frames == 3
    out = validate_frame(data)
    assert out["driver"]["eyes"]["closed_ms"] == 0  # proposed field kept
    assert out["driver"]["phone"]["near_face"] is True
    json.dumps(out)


def test_strict_mode_sends_only_plan_fields() -> None:
    cfg = load_config()
    cfg = cfg.model_copy(update={"output": cfg.output.model_copy(update={"proposed_fields": False})})
    data = build_frame(
        cfg, seq=1, ts=0.0, driver=_driver_msg(), passenger=None, cameras={"driver": True}, e2e_ms_p95=None, system={}
    )
    assert "closed_ms" not in data["driver"]["eyes"]
    assert "near_face" not in data["driver"]["phone"]
    assert "monitoring_reason" not in data["driver"]
    assert set(data["perf"]["cameras"]["driver"]) == {"capture_fps", "process_fps", "dropped_frames"}
    PerceptionFrame.model_validate(data)


def test_camera_down_still_gives_a_valid_frame() -> None:
    cfg = load_config()
    data = build_frame(
        cfg,
        seq=1,
        ts=0.0,
        driver=None,
        passenger=None,
        cameras={"driver": False, "passenger": False},
        e2e_ms_p95=None,
        system={},
    )
    frame = validate_frame(data)
    assert frame["driver"]["monitoring_reason"] == "camera_unavailable"
    assert frame["passenger"]["present"] is False
    assert frame["occupants"] == []


def test_passenger_asleep_after_closed_eyes() -> None:
    cfg = load_config()
    msg = _driver_msg(camera="passenger")
    msg["state"]["eyes"]["closed_ms"] = int(cfg.passenger.asleep_closed_s * 1000) + 500
    data = build_frame(
        cfg, seq=1, ts=0.0, driver=None, passenger=msg, cameras={"passenger": True}, e2e_ms_p95=None, system={}
    )
    assert data["passenger"]["awake"] is False


@pytest.mark.parametrize(
    ("raw", "cmd"),
    [
        ({"cmd": "debug", "on": True}, "debug"),
        ({"type": "dialog_window", "open": True, "to": "driver"}, "dialog_window"),
        ({"type": "command", "cmd": "calibrate", "profile": "andrei"}, "calibrate"),
        ({"cmd": "enroll", "name": "andrei"}, "enroll"),
    ],
)
def test_commands_parse(raw: dict[str, Any], cmd: str) -> None:
    assert parse_command(raw).cmd == cmd


def test_unknown_command_rejected() -> None:
    with pytest.raises(ValueError):
        parse_command({"cmd": "reboot"})
    assert isinstance(parse_command({"cmd": "debug"}), Command)


# --- degradation rule -----------------------------------------------------------------------------------


def test_degradation_passenger_first_then_yolo_and_back() -> None:
    cfg = load_config().rates
    ctl = DegradeController(cfg)
    hold = cfg.degrade_hold_s
    t = 0.0
    changes = []
    for _ in range(ctl.max_level + 3):  # keep the latency high
        t += hold + 0.1
        change = ctl.update(t, cfg.degrade_e2e_p95_ms * 1.5)
        if change:
            changes.append(change)
    assert len(changes) == ctl.max_level
    passenger = [c.passenger_face_hz for c in changes]
    phone = [c.phone_hz for c in changes]
    assert passenger[0] < cfg.passenger_face_hz and phone[0] == cfg.phone_hz  # passenger degrades first
    assert passenger[-1] >= cfg.degrade_min_passenger_face_hz and phone[-1] >= cfg.degrade_min_phone_hz
    assert phone[-1] < cfg.phone_hz  # then YOLO
    for _ in range(ctl.max_level + 3):  # latency back to normal
        t += hold + 0.1
        ctl.update(t, cfg.degrade_e2e_p95_ms * 0.2)
    assert ctl.rates.passenger_face_hz == cfg.passenger_face_hz and ctl.rates.phone_hz == cfg.phone_hz


def test_degradation_waits_between_steps() -> None:
    cfg = load_config().rates
    ctl = DegradeController(cfg)
    assert ctl.update(10.0, 999.0) is not None
    assert ctl.update(10.0 + cfg.degrade_hold_s / 2, 999.0) is None
    assert ctl.update(10.0, None) is None


# --- monitoring thumbnail (CameraMonitor and the modules: test_monitoring.py, test_modules.py) --------------------


def test_thumbnail_keeps_sensor_noise() -> None:
    rng = np.random.default_rng(1)
    base = rng.integers(0, 255, size=(720, 1280, 3), dtype=np.uint8)
    noise = rng.integers(-2, 3, size=base.shape)
    other = np.clip(base.astype(int) + noise, 0, 255).astype(np.uint8)
    assert float(np.mean(np.abs(thumbnail(base) - thumbnail(other)))) > load_config().monitoring.frozen_pixel_diff
    assert float(np.mean(np.abs(thumbnail(base) - thumbnail(base.copy())))) == 0.0


# --- worker process -------------------------------------------------------------------------------------


def _wait(worker: CameraWorker, predicate: Any, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        worker.poll()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_worker_streams_and_stops_cleanly() -> None:
    worker = CameraWorker("driver", load_config(), SYNTH).start()
    try:
        assert _wait(worker, lambda: worker.latest is not None and worker.latest["kind"] == "frame", 30.0)
        assert worker.available
        first = worker.latest["seq"]  # type: ignore[index]
        assert _wait(worker, lambda: worker.latest["seq"] > first + 10, 10.0)  # type: ignore[index]
        assert worker.latest_jpeg is None  # nobody asked for the preview
        worker.want_jpeg(True)
        assert _wait(worker, lambda: worker.latest_jpeg is not None, 10.0)
        assert worker.latest_jpeg[:2] == b"\xff\xd8"  # type: ignore[index]
    finally:
        t0 = time.monotonic()
        code = worker.stop(timeout=5.0)
        assert time.monotonic() - t0 < 5.0
    assert code == 0  # returned on its own, not killed
    assert not worker.alive and not worker.available


def test_worker_restarts_after_a_crash() -> None:
    cfg = load_config()
    cfg = cfg.model_copy(update={"workers": cfg.workers.model_copy(update={"restart_backoff_s": 0.2})})
    worker = CameraWorker("driver", cfg, SYNTH).start()
    try:
        assert _wait(worker, lambda: worker.available, 30.0)
        pid = worker.pid
        worker._proc.kill()  # simulate a native crash
        assert _wait(worker, lambda: not worker.available, 5.0)  # marked unavailable while down
        assert _wait(worker, lambda: worker.available and worker.pid != pid, 30.0)
        assert worker.restarts == 1
    finally:
        worker.stop()


# --- main loop ------------------------------------------------------------------------------------------


def test_main_print_no_ws_on_a_synthetic_source() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "perception.main",
            "--print",
            "--no-ws",
            "--no-mjpeg",
            "--synthetic",
            "--no-models",
            "--seconds",
            "4",
            "--log-level",
            "WARNING",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
    assert len(lines) >= 40, proc.stderr[-2000:]
    parsed = [PerceptionFrame.model_validate_json(line) for line in lines]
    assert [f.seq for f in parsed] == list(range(1, len(parsed) + 1))
    rate = (len(parsed) - 1) / (parsed[-1].ts - parsed[0].ts)
    assert rate == pytest.approx(load_config().output.publish_hz, rel=0.15)
    assert any(f.perf.cameras.get("driver") and f.perf.cameras["driver"].process_fps > 0 for f in parsed)


def test_ws_frames_reach_core_and_commands_are_acked() -> None:
    import websockets

    received: list[dict[str, Any]] = []

    async def scenario() -> None:
        async def handler(ws: Any) -> None:
            await ws.send(json.dumps({"cmd": "debug", "on": True}))
            await ws.send(json.dumps({"cmd": "calibrate", "profile": "andrei"}))
            async for raw in ws:
                received.append(json.loads(raw))

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            cfg = load_config()
            cfg = cfg.model_copy(
                update={"output": cfg.output.model_copy(update={"ws_url": f"ws://127.0.0.1:{port}/ws/perception"})}
            )
            app = Perception(cfg, cameras=["driver"], options=SYNTH, ws=True, mjpeg=False)
            await app.run(seconds=6.0)

    asyncio.run(scenario())
    acks = {m["cmd"]: m["status"] for m in received if m.get("type") == "ack"}
    assert acks == {"debug": "ok", "calibrate": "started"}  # the full calibration takes ~1 min: not done in 6 s
    prompts = [m for m in received if m.get("type") == "calibration_prompt"]
    assert prompts and prompts[0]["zone"] == "road" and prompts[0]["profile"] == "andrei"
    assert [p["step"] for p in prompts] == sorted({p["step"] for p in prompts})  # one message per step
    frames = [validate_frame(m) for m in received if "seq" in m]
    assert len(frames) >= 30


def test_ws_without_core_keeps_running_and_logs_once(caplog: pytest.LogCaptureFixture) -> None:
    cfg = load_config()
    cfg = cfg.model_copy(
        update={
            "output": cfg.output.model_copy(update={"ws_url": "ws://127.0.0.1:9/ws/perception", "ws_reconnect_s": 0.1})
        }
    )
    app = Perception(cfg, cameras=["driver"], options=SYNTH, ws=True, mjpeg=False)
    import logging

    logging.getLogger("perception").propagate = True
    with caplog.at_level(logging.WARNING, logger="perception.main"):
        asyncio.run(app.run(seconds=3.0))
    # distinct records: other tests may leave a second capturing handler on the "perception" logger
    outages = {id(r) for r in caplog.records if "core not reachable" in r.getMessage()}
    assert len(outages) == 1
    assert app.frames_published >= 30


def test_mjpeg_streams_only_while_watched() -> None:
    import aiohttp

    async def scenario() -> tuple[int, bool, bool]:
        app = Perception(load_config(), cameras=["driver"], options=SYNTH, ws=False, mjpeg=True, mjpeg_port=0)
        run = asyncio.create_task(app.run(seconds=20.0))
        try:
            for _ in range(400):
                if app.bound_port and app.workers["driver"].available:
                    break
                await asyncio.sleep(0.05)
            worker = app.workers["driver"]
            before = bool(worker._want_jpeg.value)
            parts = 0
            url = f"http://127.0.0.1:{app.bound_port}/video/driver"
            async with aiohttp.ClientSession() as session, session.get(url) as resp:
                assert resp.headers["Content-Type"].startswith("multipart/x-mixed-replace")
                buf = b""
                async for chunk in resp.content.iter_chunked(65536):
                    buf += chunk
                    parts = buf.count(b"\xff\xd8")
                    if parts >= 3:
                        break
            for _ in range(100):
                if not worker._want_jpeg.value:
                    break
                await asyncio.sleep(0.05)
            return parts, before, bool(worker._want_jpeg.value)
        finally:
            run.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run

    parts, before, after = asyncio.run(scenario())
    assert parts >= 3
    assert before is False and after is False  # encoding only while a client is connected
