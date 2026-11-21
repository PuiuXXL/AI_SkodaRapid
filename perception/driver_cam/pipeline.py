"""DriverPipeline: FeatureFrame -> driver state (contract fields driver.eyes / head / yawn / speaking).

Detectors only read FeatureFrames, so the pipeline runs identically on the live camera and on a replayed session
(perception/replay.py, development and evaluation only).

``shared/contracts.py`` does not exist yet; the field names follow DriveMate-PLAN-FINAL.md §7. Fields beyond the
contract (``closed_ms``, ``squint``, ``blink_rate``, ``state``, ...) are listed in docs/perception.md §9.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict

from perception.config import PerceptionConfig
from perception.driver_cam.eyes import EyeOutput, EyeTracker
from perception.driver_cam.head import HeadOutput, HeadTracker
from perception.driver_cam.mouth import MouthOutput, MouthTracker
from perception.features import FeatureFrame

__all__ = ["DriverEyes", "DriverFace", "DriverHead", "DriverPipeline", "DriverState"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DriverEyes(_Out):
    # contract §7
    ear: float | None = None
    eye_used: Literal["left", "right"] | None = None
    perclos_60s: float = 0.0
    blink_ms: int | None = None
    microsleep: bool = False  # always False from P1: P2 decides from closed_ms
    reliable: bool = False
    # proposed additions (docs/perception.md §9)
    closed_ms: int = 0
    blink_rate: float | None = None
    squint: bool = False
    state: Literal["OPEN", "CLOSED", "SQUINT", "UNKNOWN"] = "UNKNOWN"
    ear_left: float | None = None
    ear_right: float | None = None
    ratio: float | None = None  # bilateral: max EAR / local reference over the reliable eyes
    ratio_left: float | None = None
    ratio_right: float | None = None
    ref_left: float | None = None  # local open-eye reference
    ref_right: float | None = None
    eye_squint: float | None = None
    eye_blink: float | None = None
    look_down: float | None = None
    cnn_closed: float | None = None  # eye-state CNN p(closed) (None: model absent or no face)
    relaxed: bool = False  # gaze conditioning active (looking down / head tilted)
    long_closure: bool = False  # CLOSED for longer than eyes.blink_max_ms
    baseline_left: float | None = None
    baseline_right: float | None = None
    baseline_provisional: bool = True


class DriverHead(_Out):
    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None
    nodding: bool = False
    answer: Literal["yes", "no"] | None = None  # AS8, only inside the dialog window (step 4)
    raw_yaw: float | None = None  # before One Euro (jitter measurement, debug overlay)
    raw_pitch: float | None = None
    raw_roll: float | None = None


class DriverFace(_Out):
    present: bool = False
    conf: float = 0.0
    width_px: float | None = None
    too_small: bool = False  # R-FL3


class DriverState(_Out):
    t: float
    frame_id: int
    eyes: DriverEyes
    head: DriverHead
    yawn: bool
    speaking: bool
    lip_ratio: float | None = None  # inner-lip gap / face height (speech onset in the eval, debug overlay)
    face: DriverFace
    perf: dict[str, float]  # detector stage timings in ms


class DriverPipeline:
    def __init__(
        self,
        cfg: PerceptionConfig,
        frame_size: tuple[int, int],
        ear_baseline: tuple[float, float] | None = None,
    ) -> None:
        self.cfg = cfg
        self.frame_size = frame_size
        self.eyes = EyeTracker(cfg.eyes, frame_size, ear_baseline)
        self.head = HeadTracker(cfg.head, cfg.filters)
        self.mouth = MouthTracker(cfg.yawn, cfg.speaking, frame_size)
        self.last_eyes = EyeOutput()
        self.last_head = HeadOutput()
        self.last_mouth = MouthOutput()

    def update(self, ff: FeatureFrame) -> DriverState:
        t0 = time.perf_counter()
        eyes = self.eyes.update(ff)
        t1 = time.perf_counter()
        closing = eyes.state == "CLOSED" or (eyes.ratio is not None and eyes.ratio < self.cfg.eyes.reopen_ratio)
        head = self.head.update(ff.t, ff.face.head_matrix, closing)
        t2 = time.perf_counter()
        mouth = self.mouth.update(ff.t, ff.face)
        t3 = time.perf_counter()
        self.last_eyes, self.last_head, self.last_mouth = eyes, head, mouth
        face = ff.face
        return DriverState(
            t=ff.t,
            frame_id=ff.frame_id,
            eyes=DriverEyes(
                ear=eyes.ear,
                eye_used=eyes.eye_used,
                perclos_60s=eyes.perclos_60s,
                blink_ms=eyes.blink_ms,
                reliable=eyes.reliable,
                closed_ms=eyes.closed_ms,
                blink_rate=eyes.blink_rate,
                squint=eyes.squint,
                state=eyes.state,
                ear_left=eyes.ear_left,
                ear_right=eyes.ear_right,
                ratio=eyes.ratio,
                ratio_left=eyes.ratio_left,
                ratio_right=eyes.ratio_right,
                ref_left=eyes.ref_left,
                ref_right=eyes.ref_right,
                eye_squint=eyes.eye_squint,
                eye_blink=eyes.eye_blink,
                look_down=eyes.look_down,
                cnn_closed=eyes.cnn_closed,
                relaxed=eyes.relaxed,
                long_closure=eyes.long_closure,
                baseline_left=eyes.baseline_left,
                baseline_right=eyes.baseline_right,
                baseline_provisional=eyes.baseline_provisional,
            ),
            head=DriverHead(
                yaw=head.yaw,
                pitch=head.pitch,
                roll=head.roll,
                nodding=head.nodding,
                raw_yaw=head.raw_yaw,
                raw_pitch=head.raw_pitch,
                raw_roll=head.raw_roll,
            ),
            yawn=mouth.yawn,
            speaking=mouth.speaking,
            lip_ratio=mouth.lip_ratio,
            face=DriverFace(present=face.present, conf=face.conf, width_px=face.width_px, too_small=face.too_small),
            perf={
                "eyes_ms": round((t1 - t0) * 1000, 3),
                "head_ms": round((t2 - t1) * 1000, 3),
                "mouth_ms": round((t3 - t2) * 1000, 3),
                "detectors_ms": round((t3 - t0) * 1000, 3),
            },
        )
