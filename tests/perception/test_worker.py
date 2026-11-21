"""worker.py: the camera process (spawn) with an injected pipeline: clean stop, restart, commands, extra modules.

Spawned workers run on a synthetic source without models (``WorkerOptions(synthetic=True, models=False)``), so the
tests need no camera and no model files. The classes below are module-level so the spawned process can import them
(``"tests.perception.test_worker:EchoPipeline"``): exactly how the integration plugs in a pipeline or a module.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from perception.capture import Frame
from perception.config import load_config
from perception.features import FeatureFrame
from perception.perf import PerfTracker
from perception.worker import (
    CameraContext,
    CameraPipeline,
    CameraWorker,
    FrameInput,
    ModularPipeline,
    WorkerOptions,
    default_pipeline,
    put_latest,
    resolve_factory,
)

SYNTH = WorkerOptions(synthetic=True, models=False)
ECHO = "tests.perception.test_worker:EchoPipeline"


class EchoPipeline:
    """The default pipeline + ``enroll``; every command it receives is echoed in the result (``echo``)."""

    def __init__(self, ctx: CameraContext, perf: PerfTracker) -> None:
        self.inner = default_pipeline(ctx, perf)
        self.commands = self.inner.commands | {"enroll"}
        self.received: list[dict[str, Any]] = []

    def process(self, inp: FrameInput) -> dict[str, Any]:
        return {**self.inner.process(inp), "echo": list(self.received)}

    def handle(self, cmd: dict[str, Any]) -> bool:
        self.received.append(cmd)
        return self.inner.handle(cmd) or cmd.get("cmd") == "enroll"

    def render(self, inp: FrameInput, payload: dict[str, Any], *, debug: bool, fps: float) -> Any:
        return self.inner.render(inp, payload, debug=debug, fps=fps)

    def close(self) -> None:
        self.inner.close()


class PatchModule:
    """An extra module as the integration would add it (pending ``workers.modules``): head answer on ``enroll``."""

    name = "patch"
    commands = frozenset({"enroll"})

    def __init__(self, ctx: CameraContext, extractor: Any) -> None:
        self.ctx = ctx
        self.last: str | None = None

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        out: dict[str, Any] = {"patch": {"frame_id": ff.frame_id, "last": self.last}}
        if self.last:
            out["frame_patch"] = {"driver": {"head": {"answer": "yes"}}}
        return out

    def handle(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("cmd") == "enroll":
            self.last = str(cmd.get("name"))
            return True
        return False

    def close(self) -> None:
        return None


class FailingModule(PatchModule):
    name = "failing"

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        raise RuntimeError("broken module")


def _wait(worker: CameraWorker, predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        worker.poll()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _jpeg(worker: CameraWorker) -> bytes | None:
    return worker.latest_jpeg


def _latest(worker: CameraWorker) -> dict[str, Any]:
    assert worker.latest is not None
    return worker.latest


# --- in-process: the pipeline interface -----------------------------------------------------------------


def _ctx(modules: tuple[str, ...] = ()) -> CameraContext:
    return CameraContext(
        name="driver",
        cfg=load_config(),
        options=SYNTH,
        width=320,
        height=240,
        fps=30.0,
        backend="synthetic",
        modules=modules,
    )


def _input(i: int) -> FrameInput:
    image = np.full((240, 320, 3), 40 + i % 50, dtype=np.uint8)
    t = time.perf_counter()
    return FrameInput(frame=Frame(image=image, frame_id=i, t_capture=t), t=i / 30.0, t_wall=time.time())


def test_default_pipeline_satisfies_the_interface() -> None:
    pipeline = default_pipeline(_ctx(), PerfTracker())
    try:
        assert isinstance(pipeline, CameraPipeline)
        assert {"debug", "dialog_window", "calibrate"} <= pipeline.commands
        payload = pipeline.process(_input(1))
        keys = {"state", "phone", "gesture", "hands", "monitoring", "calibration", "luma", "head_answer", "identity"}
        assert keys <= set(payload)
        assert payload["modules"] == [
            "detectors",
            "calibration",
            "monitoring",
            "hands",
            "phone",
            "head_answer",
            "identity",
        ]
        assert {"enroll", "load_profile"} <= pipeline.commands
        assert pipeline.handle({"cmd": "debug", "on": True}) and pipeline.debug
        assert pipeline.handle({"cmd": "enroll", "name": "x"})  # identity module (no models here: error state)
        assert pipeline.process(_input(2))["identity"]["enroll"]["state"] == "error"
        img = pipeline.render(_input(2), payload, debug=True, fps=15.0)
        assert img.shape == (240, 320, 3)
    finally:
        pipeline.close()


def test_extra_modules_are_appended_and_isolated() -> None:
    modules = ("tests.perception.test_worker:FailingModule", "tests.perception.test_worker:PatchModule")
    pipeline = default_pipeline(_ctx(modules), PerfTracker())
    try:
        assert isinstance(pipeline, ModularPipeline)
        assert pipeline.modules[-2].name == "failing" and pipeline.modules[-1].name == "patch"
        assert "enroll" in pipeline.commands
        first = pipeline.process(_input(1))  # the failing module is skipped, the frame still comes out
        assert "patch" not in first.get("frame_patch", {}) and first["patch"]["last"] is None
        assert pipeline.handle({"cmd": "enroll", "name": "andrei"})
        second = pipeline.process(_input(2))
        assert second["frame_patch"]["patch"] == {"driver": {"head": {"answer": "yes"}}}
        assert "patch_module" in pipeline.perf.snapshot()  # per-module timing
    finally:
        pipeline.close()


def test_factory_resolution() -> None:
    assert resolve_factory(None) is default_pipeline
    # pytest imports this file under its own module name, so compare by name, not identity
    assert getattr(resolve_factory(ECHO), "__qualname__", None) == EchoPipeline.__qualname__
    with pytest.raises(ValueError):
        resolve_factory("no_colon_here")


def test_put_latest_reports_drops() -> None:
    import multiprocessing as mp

    q: Any = mp.get_context("spawn").Queue(maxsize=1)
    try:
        assert put_latest(q, 1) is False
        time.sleep(0.05)
        assert put_latest(q, 2) is True  # 1 was never read
        time.sleep(0.05)
        assert q.get(timeout=1.0) == 2
    finally:
        q.cancel_join_thread()
        q.close()


# --- spawned worker -------------------------------------------------------------------------------------


def test_worker_streams_stops_cleanly_and_jpeg_only_on_demand() -> None:
    worker = CameraWorker("driver", load_config(), SYNTH).start()
    try:
        assert _wait(worker, lambda: worker.latest is not None and worker.latest["kind"] == "frame", 30.0)
        msg = _latest(worker)
        assert worker.available
        assert abs(msg["t_wall"] - time.time()) < 1.0  # wall-clock capture time
        assert {"debug", "dialog_window", "calibrate", "rates"} <= set(msg["commands"])
        assert worker.capabilities is not None and "calibrate" in worker.capabilities
        first = msg["seq"]
        assert _wait(worker, lambda: _latest(worker)["seq"] > first + 10, 10.0)
        assert _jpeg(worker) is None  # nobody asked for the preview
        worker.want_jpeg(True)
        assert _wait(worker, lambda: _jpeg(worker) is not None, 10.0)
        assert (_jpeg(worker) or b"")[:2] == b"\xff\xd8"
        worker.want_jpeg(False)
    finally:
        t0 = time.monotonic()
        code = worker.stop(timeout=5.0)
        assert time.monotonic() - t0 < 5.0
    assert code == 0  # returned on its own, not killed
    assert not worker.alive and not worker.available


def test_worker_restarts_and_is_unavailable_while_down() -> None:
    cfg = load_config()
    cfg = cfg.model_copy(update={"workers": cfg.workers.model_copy(update={"restart_backoff_s": 0.3})})
    worker = CameraWorker("driver", cfg, SYNTH).start()
    try:
        assert _wait(worker, lambda: worker.available, 30.0)
        pid = worker.pid
        worker.send({"cmd": "debug", "on": True}, persist=True)
        worker._proc.kill()  # simulate a native crash
        assert _wait(worker, lambda: not worker.available, 5.0)
        assert worker.latest is None  # no stale data while it is down
        assert _wait(worker, lambda: worker.available and worker.pid != pid, 30.0)
        assert worker.restarts == 1
    finally:
        worker.stop()


def test_commands_reach_the_injected_pipeline() -> None:
    worker = CameraWorker("driver", load_config(), SYNTH, factory=ECHO).start()
    try:
        assert _wait(worker, lambda: worker.available, 30.0)
        assert worker.capabilities is not None and "enroll" in worker.capabilities
        worker.send({"cmd": "enroll", "name": "andrei"})
        worker.send({"cmd": "dialog_window", "open": True, "until_perf": time.perf_counter() + 2.0})
        worker.send({"cmd": "bogus"})  # nothing handles it: logged, the worker keeps going

        def echoed() -> bool:
            echo = _latest(worker).get("echo") or []
            return [c["cmd"] for c in echo] == ["enroll", "dialog_window", "bogus"]

        assert _wait(worker, echoed, 10.0)
        assert _latest(worker)["echo"][0]["name"] == "andrei"
        assert _wait(worker, lambda: _latest(worker).get("dialog_open") is True, 5.0)
        seq = _latest(worker)["seq"]
        assert _wait(worker, lambda: _latest(worker)["seq"] > seq + 5, 5.0) and worker.alive
    finally:
        assert worker.stop() == 0


def test_extra_module_from_config_runs_in_the_process() -> None:
    worker = CameraWorker("driver", load_config(), SYNTH, modules=["tests.perception.test_worker:PatchModule"]).start()
    try:
        assert _wait(worker, lambda: worker.available, 30.0)
        assert "patch" in _latest(worker)["modules"]
        worker.send({"cmd": "enroll", "name": "andrei"})
        assert _wait(worker, lambda: _latest(worker)["patch"]["last"] == "andrei", 10.0)
        assert "patch" in _latest(worker)["frame_patch"]
    finally:
        worker.stop()


def test_missing_camera_reports_unavailable_and_never_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """No device matches: the process body keeps running with a camera_unavailable heartbeat and logs it every
    workers.unavailable_report_s, instead of exiting with code 2 (which made the supervisor restart it in a loop)."""
    import queue
    import threading
    from types import SimpleNamespace

    import perception.capture as capture
    import perception.worker as worker_mod
    from perception.worker import run_camera

    monkeypatch.setattr(capture, "list_devices", lambda: [])
    warnings: list[str] = []
    monkeypatch.setattr(
        worker_mod, "log", SimpleNamespace(warning=lambda msg, **_: warnings.append(msg), info=lambda *a, **k: None)
    )
    cfg = load_config()
    driver = cfg.cameras.driver.model_copy(update={"device": "usb:dead:beef", "device_name": None, "reconnect_s": 0.1})
    cfg = cfg.model_copy(
        update={
            "cameras": cfg.cameras.model_copy(update={"driver": driver}),
            "workers": cfg.workers.model_copy(update={"unavailable_report_s": 0.4}),
        }
    )
    results: Any = queue.Queue(maxsize=1)
    stop = threading.Event()
    opts = WorkerOptions(models=False)
    args: tuple[Any, ...] = (cfg.model_dump(mode="json"), opts, results, queue.Queue(1), queue.Queue(), stop)
    thread = threading.Thread(target=run_camera, args=("driver", *args, SimpleNamespace(value=0)), daemon=True)
    thread.start()
    time.sleep(1.5)
    assert thread.is_alive()  # no exit, no restart loop
    msg = results.get(timeout=1.0)
    assert msg["kind"] == "status" and msg["reason"] == "camera_unavailable" and msg["connected"] is False
    assert 2 <= warnings.count("camera_unavailable") <= 5  # every 0.4 s, not every frame / reconnect
    stop.set()
    thread.join(5.0)
    assert not thread.is_alive()  # stops cleanly without a camera
