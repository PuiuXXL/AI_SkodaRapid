"""main.py: --print --no-ws on a synthetic source, command routing to the workers, WS to core, MJPEG (stream.py).

No camera and no model files needed: workers run on a synthetic source without models.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from perception.config import load_config
from perception.contract import PerceptionFrame, validate_frame
from perception.main import Perception, _with_driver_device
from perception.stream import MjpegServer
from perception.worker import WorkerOptions

REPO = Path(__file__).resolve().parents[2]
SYNTH = WorkerOptions(synthetic=True, models=False)
ECHO = "tests.perception.test_worker:EchoPipeline"


def test_main_print_no_ws_synthetic_source_without_camera() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "perception.main",
            "--print",
            "--no-ws",
            "--no-mjpeg",
            "--source",
            "synthetic",
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
    raw = [json.loads(line) for line in lines]
    assert [f.seq for f in parsed] == list(range(1, len(parsed) + 1))
    with_data = [r for r in raw if r["perf"]["cameras"]["driver"]["available"]]
    assert len(with_data) >= 30
    publish = [r["perf"]["publish_ts"] for r in raw]
    rate = (len(publish) - 1) / (publish[-1] - publish[0])
    assert rate == pytest.approx(load_config().output.publish_hz, rel=0.15)
    for r in with_data:  # ts = capture time of the newest driver frame: a bit before the publication
        assert 0.0 <= r["perf"]["publish_ts"] - r["ts"] < 0.5
        assert r["perf"]["cameras"]["driver"]["age_ms"] < 500
    assert [r["ts"] for r in with_data] == sorted(r["ts"] for r in with_data)


# --- command routing (no processes started) -------------------------------------------------------------


def _app(**kwargs: Any) -> Perception:
    return Perception(load_config(), options=SYNTH, ws=False, mjpeg=False, **{"cameras": ["driver"], **kwargs})


def test_commands_without_a_module_are_only_logged(caplog: pytest.LogCaptureFixture) -> None:
    app = _app()
    try:
        worker = app.workers["driver"]
        app.handle_message({"cmd": "enroll", "name": "andrei"})
        assert app.acks[-1]["status"] == "queued"  # worker not reported yet: sent, it logs if nobody handles it
        worker.capabilities = frozenset({"debug", "dialog_window", "calibrate", "rates"})
        logging.getLogger("perception").propagate = True
        with caplog.at_level(logging.INFO, logger="perception.main"):
            app.handle_message({"type": "enroll", "name": "andrei"})
        assert app.acks[-1] == {
            "type": "ack",
            "cmd": "enroll",
            "status": "not_implemented",
            "detail": "no module handles 'enroll' on camera driver yet",
        }
        assert any("logged only" in r.getMessage() for r in caplog.records)
        worker.capabilities = worker.capabilities | {"enroll"}
        app.handle_message({"cmd": "enroll", "name": "andrei"})
        assert app.acks[-1] == {"type": "ack", "cmd": "enroll", "status": "started", "detail": "camera driver"}
        app.handle_message({"cmd": "enroll"})
        assert app.acks[-1]["status"] == "error"  # no name
        app.handle_message({"cmd": "dialog_window", "open": True, "to": "passenger"})
        assert app.acks[-1]["status"] == "error"  # passenger camera not enabled
        app.handle_message({"cmd": "calibrate"})
        assert app.acks[-1]["status"] == "error"  # no profile
        app.handle_message({"cmd": "debug", "on": True})
        assert app.acks[-1]["status"] == "ok" and worker._persist["debug"] == {"cmd": "debug", "on": True}
        app.handle_message({"cmd": "self_destruct"})  # invalid: ignored, no ack
        assert app.acks[-1]["cmd"] == "debug"
    finally:
        app.system.close()


def test_commands_reach_the_worker_through_main() -> None:
    async def scenario() -> Perception:
        app = _app(factory=ECHO)
        run = asyncio.create_task(app.run(seconds=30.0))
        try:
            worker = app.workers["driver"]
            for _ in range(600):
                if worker.available and worker.capabilities:
                    break
                await asyncio.sleep(0.05)
            app.handle_message({"cmd": "enroll", "name": "andrei"})
            app.handle_message({"cmd": "dialog_window", "open": True, "to": "driver"})
            app.handle_message({"cmd": "debug", "on": True})
            for _ in range(200):
                echo = (worker.latest or {}).get("echo") or []
                if len(echo) >= 3:
                    break
                await asyncio.sleep(0.05)
            return app
        finally:
            run.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run

    app = asyncio.run(scenario())
    first = {a["cmd"]: a["status"] for a in reversed(app.acks)}  # the command acks (enroll events follow)
    assert first == {"enroll": "started", "dialog_window": "ok", "debug": "ok"}
    echo = (app.workers["driver"].latest or {}).get("echo") or []
    assert [c["cmd"] for c in echo] == ["enroll", "dialog_window", "debug"]
    assert echo[0]["name"] == "andrei"
    assert app.last_frame is not None and validate_frame(app.last_frame)


def test_frames_reach_core_over_ws_and_commands_are_acked() -> None:
    import websockets

    received: list[dict[str, Any]] = []

    async def scenario() -> None:
        async def handler(ws: Any) -> None:
            sent = False
            async for raw in ws:
                msg = json.loads(raw)
                received.append(msg)
                if not sent and msg.get("perf", {}).get("cameras", {}).get("driver", {}).get("available"):
                    sent = True
                    await ws.send(json.dumps({"type": "enroll", "name": "andrei"}))

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            cfg = load_config()
            cfg = cfg.model_copy(
                update={"output": cfg.output.model_copy(update={"ws_url": f"ws://127.0.0.1:{port}/ws/perception"})}
            )
            app = Perception(cfg, cameras=["driver"], options=SYNTH, ws=True, mjpeg=False)
            await app.run(seconds=8.0)

    asyncio.run(scenario())
    frames = [validate_frame(m) for m in received if "seq" in m]
    assert len(frames) >= 30
    acks = [m for m in received if m.get("type") == "ack"]
    assert acks and acks[0]["cmd"] == "enroll" and acks[0]["status"] == "started"
    # synthetic camera, no models: the identity module reports the failure as an enroll event
    assert any(a["cmd"] == "enroll" and a["status"] == "error" for a in acks[1:])


# --- MJPEG (stream.py) ----------------------------------------------------------------------------------


class FakeSource:
    def __init__(self) -> None:
        self.latest_jpeg: bytes | None = b"\xff\xd8fake-jpeg\xff\xd9"
        self.jpeg_seq = 0
        self.available = True
        self.wanted: list[bool] = []

    def want_jpeg(self, on: bool) -> None:
        self.wanted.append(on)


def test_mjpeg_encodes_only_while_watched() -> None:
    import aiohttp

    source = FakeSource()

    async def scenario() -> tuple[int, int, dict[str, Any]]:
        server = MjpegServer({"driver": source}, host="127.0.0.1", port=0, fps=30.0, health=lambda: {"ok": True})
        port = await server.start()
        assert port

        async def produce() -> None:
            while True:
                source.jpeg_seq += 1
                await asyncio.sleep(0.02)

        producer = asyncio.create_task(produce())
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:{port}/video/passenger") as resp:
                    missing = resp.status
                async with session.get(f"http://127.0.0.1:{port}/video/driver") as resp:
                    assert resp.headers["Content-Type"].startswith("multipart/x-mixed-replace")
                    buf = b""
                    async for chunk in resp.content.iter_chunked(65536):
                        buf += chunk
                        if buf.count(b"--frame") >= 3:
                            break
                for _ in range(100):
                    if source.wanted[-1] is False:
                        break
                    await asyncio.sleep(0.02)
                async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                    health = await resp.json()
            return missing, buf.count(b"\xff\xd8"), health
        finally:
            producer.cancel()
            await server.stop()

    missing, parts, health = asyncio.run(scenario())
    assert missing == 404
    assert parts >= 3
    assert source.wanted[0] is True and source.wanted[-1] is False  # off again once the client left
    assert health["ok"] is True and health["mjpeg_clients"] == {"driver": 0}


def test_busy_mjpeg_port_disables_only_the_preview() -> None:
    async def scenario() -> tuple[int | None, int | None]:
        first = MjpegServer({"driver": FakeSource()}, host="127.0.0.1", port=0, fps=10.0)
        port = await first.start()
        assert port is not None
        second = MjpegServer({"driver": FakeSource()}, host="127.0.0.1", port=port, fps=10.0)
        try:
            return port, await second.start()
        finally:
            await second.stop()
            await first.stop()

    port, again = asyncio.run(scenario())
    assert port and again is None


# --- config ---------------------------------------------------------------------------------------------


def test_output_and_worker_keys_live_in_the_validated_config() -> None:
    cfg = load_config()
    assert cfg.output.result_max_age_ms > 0 and cfg.output.mjpeg_host
    assert cfg.workers.modules == {"driver": [], "passenger": []}
    assert not (Path(__file__).resolve().parents[2] / "perception" / "config" / "pending").exists()


def test_device_override_keeps_the_yaml_rules() -> None:
    cfg = load_config()
    assert _with_driver_device(cfg, "0").cameras.driver.device == 0
    assert _with_driver_device(cfg, "rtsp://cam").cameras.driver.device == "rtsp://cam"
    data = cfg.model_dump(mode="json")
    data["cameras"]["passenger"]["enabled"] = True
    with_passenger = type(cfg).model_validate(data)
    with pytest.raises(ValidationError):  # the same device for both cameras is refused
        _with_driver_device(with_passenger, str(with_passenger.cameras.passenger.device))


def test_publish_once_without_workers_gives_a_valid_frame() -> None:
    app = _app()
    try:
        t0 = time.time()
        frame = app.publish_once()
        assert frame["seq"] == 1 and frame["ts"] >= t0 - 0.01  # no driver data: publication time
        assert frame["driver"]["monitoring_reason"] == "camera_unavailable"
        PerceptionFrame.model_validate(frame)
    finally:
        app.system.close()
