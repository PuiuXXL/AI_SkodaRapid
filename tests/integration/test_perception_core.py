"""End to end: the real core server (``core.main.create_app``) and the real ``perception.main`` process over WebSocket.

Perception runs on synthetic frames without models (``--source synthetic --no-models``): no camera, no model files.
Checked: core receives valid frames at the publish rate, commands sent by core are acknowledged by P1, and core keeps
working when perception stops and comes back (a worker crash or a restart in the demo).

Marked ``slow`` (two camera processes are spawned): ``python -m pytest tests/integration -m slow``.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="needs core (requirements/p2-core.txt)")
pytest.importorskip("uvicorn", reason="needs core (requirements/p2-core.txt)")
pytest.importorskip("cv2", reason="needs the perception runtime (requirements/p1-perception.txt)")

import uvicorn

from shared import contracts as c

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
START_TIMEOUT_S = 90.0  # two spawned camera processes + MediaPipe import on a cold CI runner


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Core:
    """core's FastAPI app on a free port, in a background thread; records every message perception sends."""

    def __init__(self) -> None:
        from core.engine import Engine
        from core.hub import Hub
        from core.main import create_app
        from core.simulation import FakeSimulator

        self.engine = Engine(Hub(), FakeSimulator())
        self.received: list[tuple[float, dict[str, Any]]] = []
        original = self.engine.on_perception_message

        def record(data: dict[str, Any], now: float) -> None:
            self.received.append((time.monotonic(), data))
            original(data, now)

        self.engine.on_perception_message = record  # type: ignore[method-assign]
        self.port = _free_port()
        config = uvicorn.Config(
            create_app(self.engine), host="127.0.0.1", port=self.port, log_level="warning", ws_ping_interval=None
        )
        self.server = uvicorn.Server(config)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="core", daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.server.serve())

    def start(self) -> Core:
        self.thread.start()
        deadline = time.monotonic() + 20.0
        while not self.server.started:
            assert time.monotonic() < deadline, "core did not start"
            time.sleep(0.05)
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)

    def send(self, command: c.PerceptionCommand) -> None:
        """``Engine.send_perception_command`` on core's own event loop (the hub is not thread-safe)."""
        self.loop.call_soon_threadsafe(self.engine.send_perception_command, command)

    def frames(self, since: float = 0.0) -> list[tuple[float, dict[str, Any]]]:
        return [(t, m) for t, m in list(self.received) if t >= since and "type" not in m]

    def acks(self) -> list[dict[str, Any]]:
        return [m for _, m in list(self.received) if m.get("type") == "ack"]

    def events(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in list(self.engine.recent_events) if e["event"]["type"] == kind]


def wait_until(predicate: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.05)


@pytest.fixture
def core() -> Iterator[Core]:
    server = Core().start()
    try:
        yield server
    finally:
        server.stop()


def _perception(core: Core, tmp_path: Path, seconds: float) -> subprocess.Popen[str]:
    """``perception.main`` towards this core: a copy of perception.yaml with core's port in ``output.ws_url``."""
    text = (ROOT / "perception" / "config" / "perception.yaml").read_text(encoding="utf-8")
    url = f"ws://127.0.0.1:{core.port}/ws/perception"
    config = tmp_path / "perception.yaml"
    config.write_text(
        "\n".join(f"  ws_url: {url}" if line.strip().startswith("ws_url:") else line for line in text.splitlines()),
        encoding="utf-8",
    )
    cmd = [
        sys.executable, "-m", "perception.main", "--source", "synthetic", "--no-models", "--no-mjpeg",
        "--seconds", str(seconds), "--config", str(config), "--log-level", "WARNING",
    ]  # fmt: skip
    return subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def _finish(proc: subprocess.Popen[str]) -> str:
    try:
        _, err = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
    assert proc.returncode == 0, err[-3000:]
    return err


def test_core_receives_valid_frames_and_p1_acks_its_commands(core: Core, tmp_path: Path) -> None:
    proc = _perception(core, tmp_path, seconds=20.0)
    try:
        wait_until(lambda: len(core.frames()) >= 15, START_TIMEOUT_S, "the first second of frames")
        assert core.engine.perception_connected

        t0 = time.monotonic()
        time.sleep(3.0)
        window = core.frames(since=t0)
        rate = len(window) / 3.0
        assert rate >= 10.0, f"{rate:.1f} frames/s at core (publish_hz 15)"
        seqs = [m["seq"] for _, m in window]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

        for command in (
            c.PerceptionCommand(cmd="debug", on=True),
            c.PerceptionCommand(cmd="dialog_window", open=True, to="driver", until=time.time() + 3.0),
            c.PerceptionCommand(cmd="enroll", name="ci_test", camera="driver"),
            c.PerceptionCommand(cmd="calibrate", profile="ci_test", quick=True),
        ):
            core.send(command)
        wait_until(
            lambda: {"debug", "dialog_window", "enroll", "calibrate"} <= {a["cmd"] for a in core.acks()},
            15.0,
            "an ack for every command",
        )
        status = {a["cmd"]: a["status"] for a in reversed(core.acks())}  # the first ack of each command
        assert status["debug"] == "ok" and status["dialog_window"] == "ok"
        assert status["enroll"] in ("started", "queued") and status["calibrate"] in ("started", "queued")
        # no models in CI: the identity module reports it through the enroll event stream, which core logs
        wait_until(lambda: bool(core.events("enroll_error")), 15.0, "the enroll error event (no models)")

        assert core.engine.invalid_messages == 0
        assert core.engine.frame is not None and core.engine.frame.perf.cameras["driver"].available
    finally:
        _finish(proc)


def test_core_survives_perception_stopping_and_coming_back(core: Core, tmp_path: Path) -> None:
    _finish(_perception(core, tmp_path, seconds=6.0))
    first = len(core.frames())
    assert first > 0, "no frames from the first perception run"
    wait_until(lambda: not core.engine.perception_connected, 10.0, "core to see perception gone")

    proc = _perception(core, tmp_path, seconds=8.0)
    try:
        wait_until(lambda: len(core.frames()) >= first + 15, START_TIMEOUT_S, "frames after the restart")
    finally:
        _finish(proc)
    assert len(core.events("perception_connected")) == 2
    assert len(core.events("perception_disconnected")) >= 1
    assert core.engine.invalid_messages == 0
