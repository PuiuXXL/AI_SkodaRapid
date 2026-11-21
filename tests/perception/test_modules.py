"""The runtime modules wired into the camera workers (perception/modules.py) and their path into the frame.

No models and no camera: module state is driven with stand-in objects, frames are built from worker messages, and the
main-process routing is checked without starting the camera processes.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import numpy as np

from perception.capture import Frame
from perception.config import load_config
from perception.contract import validate_frame
from perception.extractor import FeatureExtractor
from perception.features import FeatureFrame
from perception.frame_builder import build_frame
from perception.main import Perception
from perception.modules import PassengerStateModule, PhoneTrackerModule
from perception.worker import CameraContext, FrameInput, WorkerOptions
from tests.perception.driver_factory import face
from tests.perception.test_runtime_main import _driver_msg

SYNTH = WorkerOptions(synthetic=True, models=False)
FPS = 15.0


def _ctx(name: str = "passenger") -> CameraContext:
    return CameraContext(
        name=name, cfg=load_config(), options=SYNTH, width=1280, height=720, fps=30.0, backend="synthetic"
    )


def _inp(t: float, state: Any = None, monitor: Any = None) -> FrameInput:
    frame = Frame(image=np.zeros((8, 8, 3), dtype=np.uint8), frame_id=int(t * FPS), t_capture=t)
    inp = FrameInput(frame=frame, t=t, t_wall=time.time())
    inp.shared["state"] = state
    inp.shared["monitor"] = monitor
    return inp


def _state(*, face: bool = True, eyes: str = "OPEN", pitch: float = 0.0) -> Any:
    return SimpleNamespace(
        face=SimpleNamespace(present=face),
        eyes=SimpleNamespace(reliable=face, state=eyes if face else "UNKNOWN"),
        head=SimpleNamespace(raw_pitch=pitch if face else None),
    )


def _ff(t: float) -> FeatureFrame:
    return FeatureFrame(t=t, frame_id=int(t * FPS), camera="passenger", face=face())


def _play(mod: PassengerStateModule, t0: float, seconds: float, **state: Any) -> tuple[float, dict[str, Any]]:
    out: dict[str, Any] = {}
    t = t0
    for _ in range(round(seconds * FPS)):
        out = mod.update(_ff(t), _inp(t, _state(**state)))["passenger_state"]
        t += 1.0 / FPS
    return t, out


# --- AP2: passenger asleep -------------------------------------------------------------------------------


def test_passenger_asleep_after_closed_eyes_and_stays_present_when_the_face_drops_out() -> None:
    cfg = load_config().passenger
    mod = PassengerStateModule(_ctx(), None)
    t, out = _play(mod, 0.0, 5.0)
    assert out["present"] and out["awake"]
    t, out = _play(mod, t, cfg.asleep_closed_s - 1.0, eyes="CLOSED")
    assert out["awake"]
    t, out = _play(mod, t, 1.5, eyes="CLOSED")
    assert out["present"] and not out["awake"] and out["eyes_closed_s"] >= cfg.asleep_closed_s
    t, out = _play(mod, t, 2.0, face=False)  # head dropped out of the image: still there, still asleep
    assert out["present"] and not out["awake"]
    _, out = _play(mod, t, 1.0)  # eyes open again
    assert out["awake"]


def test_head_drop_makes_the_passenger_asleep_sooner() -> None:
    cfg = load_config().passenger
    mod = PassengerStateModule(_ctx(), None)
    t, _ = _play(mod, 0.0, 5.0, pitch=0.0)
    t, out = _play(mod, t, cfg.asleep_closed_head_s + 0.5, eyes="CLOSED", pitch=-(cfg.head_drop_deg + 5.0))
    assert out["head_dropped"] and not out["awake"]
    assert cfg.asleep_closed_head_s < cfg.asleep_closed_s


def test_isolated_open_frames_do_not_wake_a_sleeping_passenger() -> None:
    """AP2: the closed time resets only after open_reset_frames open frames in a row (no head drop needed)."""
    cfg = load_config().passenger
    mod = PassengerStateModule(_ctx(), None)
    t, _ = _play(mod, 0.0, 3.0)
    for _ in range(round(cfg.asleep_closed_s + 1.0)):  # one noisy OPEN frame every second
        t, out = _play(mod, t, 1.0 - 1.0 / FPS, eyes="CLOSED")
        t, out = _play(mod, t, 1.0 / FPS, eyes="OPEN")
    assert not out["awake"] and not out["head_dropped"]
    _, out = _play(mod, t, cfg.open_reset_frames / FPS)  # really open: awake again
    assert out["awake"]


def test_frozen_passenger_camera_is_not_present() -> None:
    mod = PassengerStateModule(_ctx(), None)
    out = mod.update(_ff(0.0), _inp(0.0, _state(), SimpleNamespace(reason="frozen")))["passenger_state"]
    assert out["present"] is False


# --- frame building from the module outputs ----------------------------------------------------------------


def _frame(driver: Any = None, passenger: Any = None) -> dict[str, Any]:
    cfg = load_config()
    cams = {"driver": driver is not None, "passenger": passenger is not None}
    data = build_frame(cfg, seq=1, ts=0.0, driver=driver, passenger=passenger, cameras=cams, e2e_ms_p95=None, system={})
    return validate_frame(data)


def test_identity_reaches_the_occupants() -> None:
    msg = _driver_msg(identity={"profile": "andrei", "score": 0.71234, "reason": "match", "enroll": {}})
    frame = _frame(driver=msg)
    occ = frame["occupants"][0]
    assert (occ["seat"], occ["profile"], occ["profile_score"]) == ("driver", "andrei", 0.712)


def test_passenger_state_module_drives_presence_and_awake() -> None:
    msg = _driver_msg(camera="passenger")
    msg["passenger_state"] = {"present": True, "awake": False, "eyes_closed_s": 11.0}
    frame = _frame(passenger=msg)
    assert frame["passenger"]["present"] and not frame["passenger"]["awake"]
    assert frame["passenger"]["eyes_closed_s"] == 11.0
    assert [o["seat"] for o in frame["occupants"]] == ["front_right"]
    msg["passenger_state"] = {"present": False, "awake": True, "eyes_closed_s": 0.0}
    frame = _frame(passenger=msg)
    assert frame["occupants"] == [] and not frame["passenger"]["holding_phone"]


def test_frozen_driver_camera_is_no_occupant_and_reports_why() -> None:
    mon = {"ok": False, "reason": "frozen", "face_missing_s": 0.0, "warnings": [], "mode": "color", "confidence": 1.0}
    frame = _frame(driver=_driver_msg(monitoring=mon))
    assert frame["occupants"] == []
    assert (frame["driver"]["monitoring_ok"], frame["driver"]["monitoring_reason"]) == (False, "frozen")
    assert frame["driver"]["camera_mode"] == "color"


def test_phone_tracker_fields_and_head_answer_patch() -> None:
    phone = {
        "in_use": True,
        "conf": 0.8,
        "source": "detector",
        "usage": "call",
        "near_face": True,
        "side": "left",
        "foreign": True,
    }
    msg = _driver_msg(phone=phone, frame_patch={"head_answer": {"driver": {"head": {"answer": "yes"}}}})
    frame = _frame(driver=msg)
    p = frame["driver"]["phone"]
    assert (p["in_use"], p["source"], p["usage"], p["foreign_seen"]) == (True, "detector", "call", True)
    assert frame["driver"]["head"]["answer"] == "yes"


def test_passenger_camera_flips_the_foreign_phone_side() -> None:
    driver = PhoneTrackerModule(_ctx("driver"), None)
    passenger = PhoneTrackerModule(_ctx("passenger"), None)
    assert driver.tracker.cfg.passenger_side != passenger.tracker.cfg.passenger_side
    assert driver.detector is None  # no models: tracker only (boxes from the feature frame)


# --- extractor cadence -----------------------------------------------------------------------------------


def test_gaze_runs_at_its_rate_in_time_not_in_frames() -> None:
    gate = SimpleNamespace(_gaze_next=float("-inf"), _gaze_period=1.0 / 15.0)
    for fps, expect in ((30.0, 15), (22.0, 15), (15.0, 15)):  # a frame count gave ~11 Hz at 22 fps
        gate._gaze_next = float("-inf")
        runs = sum(FeatureExtractor._gaze_due(gate, k / fps) for k in range(round(fps * 10)))  # type: ignore[arg-type]
        assert abs(runs / 10.0 - expect) <= 1.0, (fps, runs)


# --- main process: routing and events --------------------------------------------------------------------


def _app() -> Perception:
    return Perception(load_config(), cameras=["driver", "passenger"], options=SYNTH, ws=False, mjpeg=False)


def test_calibrate_always_goes_to_the_driver_and_is_persisted_when_done() -> None:
    app = _app()
    try:
        sent: dict[str, list[dict[str, Any]]] = {"driver": [], "passenger": []}
        for name, w in app.workers.items():

            def record(cmd: dict[str, Any], persist: bool = False, n: str = name) -> None:
                sent[n].append({**cmd, "_persist": persist})

            w.send = record  # type: ignore[method-assign]
        app.handle_message({"cmd": "calibrate", "profile": "andrei", "to": "passenger"})
        assert app.acks[-1]["status"] == "started"
        assert [c["cmd"] for c in sent["driver"]] == ["calibrate"] and sent["passenger"] == []
        app._calibration_events({"calibration": {"id": 1, "state": "done", "profile": "andrei"}})
        assert app.acks[-1]["status"] == "done"
        assert sent["driver"][-1] == {"cmd": "load_profile", "profile": "andrei", "_persist": True}
    finally:
        app.system.close()


def test_enroll_follows_its_camera_and_reports_progress_then_done() -> None:
    app = _app()
    try:
        for w in app.workers.values():
            w.capabilities = frozenset({"enroll"})
        got: list[dict[str, Any]] = []

        def record(cmd: dict[str, Any], persist: bool = False) -> None:
            got.append(cmd)

        app.workers["passenger"].send = record  # type: ignore[method-assign]
        app.handle_message({"cmd": "enroll", "name": "maria", "camera": "passenger"})
        assert app.acks[-1] == {"type": "ack", "cmd": "enroll", "status": "started", "detail": "camera passenger"}
        assert got == [
            {"cmd": "enroll", "name": "maria", "camera": "passenger", "open": False, "on": False, "quick": False}
        ]
        for count in (1, 1, 2):
            enroll = {"id": 3, "state": "running", "name": "maria", "count": count, "needed": 2}
            app._enroll_events("passenger", {"identity": {"enroll": enroll}})
        app._enroll_events("passenger", {"identity": {"enroll": {**enroll, "state": "done"}}})
        statuses = [a["status"] for a in app.acks if a["cmd"] == "enroll"]
        assert statuses == ["started", "progress", "progress", "done"]
        assert app.acks[-1]["detail"]["camera"] == "passenger"
    finally:
        app.system.close()


def test_async_phone_detection_never_blocks_the_frame() -> None:
    """YOLO runs in its own thread: a slow detection (here 80 ms) costs the frame loop nothing; its boxes arrive on a
    later frame and are voted like before."""
    from concurrent.futures import ThreadPoolExecutor

    from perception.phone import PhoneDetections

    class SlowDetector:
        rate_hz = 0.0

        def should_run(self, t: float) -> bool:
            return True

        def detect(self, image: Any, t: float) -> PhoneDetections:
            time.sleep(0.08)
            return PhoneDetections((), 80.0)

    mod = PhoneTrackerModule(_ctx("driver"), None)
    mod.detector, mod._pool = SlowDetector(), ThreadPoolExecutor(max_workers=1)
    ff = FeatureFrame(t=0.0, frame_id=1, camera="driver", face=face())
    t0 = time.perf_counter()
    for i in range(5):
        mod.update(ff, _inp(i / 30.0))
    assert time.perf_counter() - t0 < 0.05  # 5 frames, none waited for the 80 ms detection
    time.sleep(0.12)
    mod.update(ff, _inp(0.2))
    assert mod.tracker is not None and mod._future is not None  # the next run is already queued
    mod.close()
