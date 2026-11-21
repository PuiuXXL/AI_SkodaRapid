"""Golden messages of the perception <-> core boundary (tests/contract/fixtures/*.json). Regenerate with

    python tests/contract/make_fixtures.py

whenever P1 deliberately changes what it sends, or P2 changes what core sends to P1, and say so to the other side.

* ``p1_frame_full.json``: a PerceptionFrame as ``perception.main`` publishes it with every module active (proposed
  fields on), both seats present, an identity, a head answer, a phone, a gesture.
* ``p1_frame_strict.json``: the same with ``output.proposed_fields: false`` (only the plan §7 fields).
* ``p1_frame_cameras_down.json``: driver worker up but no fresh frame, passenger camera disabled.
* ``p1_messages.json``: the other P1 -> core messages (acks of every command, enroll progress / done, calibration
  prompt and done), produced by ``perception.main.Perception`` itself.
* ``core_commands.json``: every command core sends to P1, serialized with P2's ``shared.contracts`` models.

How the frames are made: the real worker pipeline (``perception.worker.default_pipeline``: detectors, monitoring,
hands, phone, head answer, identity, posture, passenger state) runs on seeded noise images with synthetic face
features (tests/perception/driver_factory.py) in place of the camera and the models; its payload is wrapped like
``run_camera`` wraps it and merged by the real ``perception.frame_builder``. Values that the synthetic input cannot
produce (an enrolled identity, a nod) are set on the worker message, the way the modules report them.

No image, video or biometric data is written: only the JSON messages.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PUBLISH_TS = 1_795_000_000.0  # fixed wall clock of the fixtures (time.time() scale)


def core_commands() -> list[dict[str, Any]]:
    """Every command core sends to P1, as core serializes it (P2's models)."""
    from shared import contracts as c

    commands = [
        c.PerceptionCommand(cmd="dialog_window", open=True, to="driver", until=PUBLISH_TS + 6.0),
        c.PerceptionCommand(cmd="dialog_window", open=True, to="passenger", until=PUBLISH_TS + 6.0),
        c.PerceptionCommand(cmd="dialog_window", open=False, to="driver"),
        c.PerceptionCommand(cmd="dialog_window", open=True, to=2, until=PUBLISH_TS + 6.0),
        c.PerceptionCommand(cmd="calibrate", profile="andrei"),
        c.PerceptionCommand(cmd="calibrate", profile="andrei", quick=True),
        c.PerceptionCommand(cmd="debug", on=True),
        c.PerceptionCommand(cmd="debug", on=False),
        c.PerceptionCommand(cmd="enroll", name="andrei", camera="driver"),
        c.PerceptionCommand(cmd="enroll", name="maria", camera="passenger"),
        c.PerceptionCommand(cmd="enroll", name="maria", to="passenger"),
    ]
    return [c.to_wire(cmd) for cmd in commands]


# --- frames from the real pipeline ---------------------------------------------------------------------------------


class _SyntheticExtractor:
    """Stands in for the FeatureExtractor: synthetic face features (+ a phone box near the face on the driver)."""

    def __init__(self, camera: str) -> None:
        from perception.features import PhoneBox
        from tests.perception.driver_factory import face, frame

        self.camera = camera
        self.models: dict[str, dict[str, str]] = {}
        self.cadence: dict[str, int] = {}
        self._face, self._frame, self._box = face, frame, PhoneBox
        self._i = 0

    def extract(self, f: Any, t: float, camera: str) -> Any:
        ff = self._frame(self._i, self._face(ear_left=0.30))
        self._i += 1
        phones = [self._box(x1=560.0, y1=300.0, x2=640.0, y2=430.0, score=0.82)] if camera == "driver" else []
        return ff.model_copy(update={"t": round(t, 4), "frame_id": f.frame_id, "camera": camera, "phones": phones})

    def close(self) -> None:
        return None


def _images(seed: int, w: int, h: int) -> Iterator[Any]:
    import numpy as np

    rng = np.random.default_rng(seed)
    base = rng.integers(40, 200, size=(h, w, 3), dtype=np.uint8)
    while True:  # a structured, lit, never identical image: no frozen / occluded / dark monitoring reason
        noise = rng.integers(0, 6, size=(h, w, 3), dtype=np.uint8)
        yield np.ascontiguousarray(base + noise)


def worker_message(camera: str, seconds: float = 3.0) -> dict[str, Any]:
    """The last message a camera worker would publish after ``seconds`` of synthetic frames."""
    from unittest import mock

    from perception import worker as w
    from perception.capture import Frame
    from perception.config import load_config
    from perception.perf import PerfTracker
    from tests.perception.driver_factory import FPS, H, W

    cfg = load_config()
    ctx = w.CameraContext(
        name=camera,
        cfg=cfg,
        options=w.WorkerOptions(synthetic=True, models=False),
        width=W,
        height=H,
        fps=FPS,
        backend="synthetic",
    )
    perf = PerfTracker(cfg.rates.perf_window)
    with mock.patch.object(w, "make_extractor", lambda _ctx: _SyntheticExtractor(camera)):
        pipeline = w.default_pipeline(ctx, perf)
    payload: dict[str, Any] = {}
    images = _images(1 if camera == "driver" else 2, W, H)
    try:
        for k in range(round(seconds * FPS)):
            t = k / FPS
            frame = Frame(image=next(images), frame_id=k + 1, t_capture=100.0 + t)
            payload = pipeline.process(w.FrameInput(frame=frame, t=t, t_wall=PUBLISH_TS - seconds + t))
    finally:
        pipeline.close()
    return {
        **payload,
        "kind": "frame",
        "camera": camera,
        "seq": round(seconds * FPS),
        "t_capture": 100.0 + seconds,
        "t_wall": PUBLISH_TS - 0.04,
        "connected": True,
        "commands": sorted(pipeline.commands | w.WORKER_COMMANDS),
        "perf": {
            "models": {"face": {"p50": 3.4, "p95": 4.8, "n": 90.0}, "phone": {"p50": 14.3, "p95": 17.2, "n": 15.0}},
            "capture_fps": 30.0,
            "process_fps": 29.8 if camera == "driver" else 10.0,
            "dropped_frames": 0,
            "dropped_results": 0,
            "reconnects": 0,
        },
    }


def _with_values(msg: dict[str, Any], camera: str) -> dict[str, Any]:
    """Values the synthetic input cannot produce, set the way the modules report them."""
    out = dict(msg)
    profile = "andrei" if camera == "driver" else "maria"
    out["identity"] = {**(msg.get("identity") or {}), "profile": profile, "score": 0.712, "reason": "match"}
    out["gesture"] = "Thumb_Up"
    seat_patch = {"driver": {"head": {"answer": "yes"}}} if camera == "driver" else {"passenger": {"answer": "no"}}
    out["frame_patch"] = {**(msg.get("frame_patch") or {}), "head_answer": seat_patch}
    if camera == "passenger":
        out["phone"] = {**(msg.get("phone") or {}), "in_use": True, "conf": 0.74, "source": "detector", "usage": "hand"}
    return out


def frames() -> dict[str, dict[str, Any]]:
    from perception.config import load_config
    from perception.frame_builder import build_valid_frame

    cfg = load_config()
    driver = _with_values(worker_message("driver"), "driver")
    passenger = _with_values(worker_message("passenger"), "passenger")
    common: dict[str, Any] = {
        "e2e_ms_p95": 64.2,
        "system": {"cpu": 35.5, "ram_mb": 758.2, "gpu": 0.0},
        "now_perf": 100.0 + 3.0 + 0.02,
        "max_age_ms": float(cfg.output.result_max_age_ms),
        "publish_ts": PUBLISH_TS,
    }
    strict = cfg.model_copy(update={"output": cfg.output.model_copy(update={"proposed_fields": False})})
    both = {"driver": True, "passenger": True}
    return {
        "p1_frame_full": build_valid_frame(cfg, seq=42, driver=driver, passenger=passenger, cameras=both, **common),
        "p1_frame_strict": build_valid_frame(
            strict, seq=42, driver=driver, passenger=passenger, cameras=both, **common
        ),
        "p1_frame_cameras_down": build_valid_frame(
            cfg, seq=43, driver=None, passenger=None, cameras={"driver": True}, **common
        ),
    }


# --- the other P1 -> core messages, from perception.main itself ------------------------------------------------------


class _Ws:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_json(self, obj: dict[str, Any]) -> None:
        self.sent.append(obj)


def p1_messages() -> list[dict[str, Any]]:
    """Acks for every core command, then enroll progress / done and a calibration prompt / done, as P1 sends them."""
    from perception.config import load_config
    from perception.main import Perception
    from perception.worker import WorkerOptions

    app = Perception(
        load_config(),
        cameras=["driver", "passenger"],
        options=WorkerOptions(synthetic=True, models=False),
        ws=False,
        mjpeg=False,
    )
    ws = _Ws()
    app.ws = ws  # type: ignore[assignment]
    try:
        for worker in app.workers.values():
            worker.capabilities = frozenset({"dialog_window", "calibrate", "debug", "enroll", "load_profile", "rates"})
            worker.send = lambda cmd, persist=False: None  # type: ignore[method-assign]
        for cmd in core_commands():
            app.handle_message(cmd)
        enroll = {"id": 1, "state": "running", "name": "maria", "count": 3, "needed": 20, "reason": None}
        app._enroll_events("passenger", {"identity": {"enroll": enroll}})
        app._enroll_events("passenger", {"identity": {"enroll": {**enroll, "state": "done", "count": 20}}})
        prompt = {
            "step": 1,
            "steps": 9,
            "zone": "mirror_left",
            "mode": "owl",
            "text": "Priveste oglinda stanga",
            "remaining_s": 4.0,
        }
        app._calibration_events({"calibration": {"id": 1, "state": "running", "profile": "andrei", "prompt": prompt}})
        app._calibration_events({"calibration": {"id": 1, "state": "done", "profile": "andrei", "accuracy": 0.97}})
    finally:
        app.system.close()
    return ws.sent


def build_all() -> dict[str, Any]:
    out: dict[str, Any] = dict(frames())
    out["p1_messages"] = p1_messages()
    out["core_commands"] = core_commands()
    return out


def write(fixtures: dict[str, Any]) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, data in fixtures.items():
        (FIXTURES / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    import logging

    logging.disable(logging.WARNING)
    fixtures = build_all()
    write(fixtures)
    for name in fixtures:
        print(f"wrote {FIXTURES / name}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
