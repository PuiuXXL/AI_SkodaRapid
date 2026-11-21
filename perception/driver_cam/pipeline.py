"""DriverPipeline: FeatureFrame -> driver state (contract fields driver.eyes / head / gaze / yawn / speaking).

Detectors only read FeatureFrames, so the pipeline runs identically on the live camera and on a replayed session
(perception/replay.py, development and evaluation only).

``shared/contracts.py`` does not exist yet; the field names follow DriveMate-PLAN-FINAL.md §7. Fields beyond the
contract (``closed_ms``, ``squint``, ``blink_rate``, ``state``, ...) are listed in docs/perception.md §9.
"""

from __future__ import annotations

import time
from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from perception.config import PerceptionConfig
from perception.driver_cam.eyes import EyeOutput, EyeTracker
from perception.driver_cam.gaze_metrics import GazeMetrics
from perception.driver_cam.gaze_model import GazeSmoother
from perception.driver_cam.gaze_zones import (
    GazeFeatureBuilder,
    ZoneModel,
    ZoneResult,
    ZoneTracker,
    zone_head_angles,
)
from perception.driver_cam.head import HeadOutput, HeadTracker
from perception.driver_cam.mouth import MouthOutput, MouthTracker
from perception.features import FeatureFrame

__all__ = ["DriverEyes", "DriverFace", "DriverGaze", "DriverHead", "DriverPipeline", "DriverState"]


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


class DriverGaze(_Out):
    # contract §7
    zone: str = "unknown"
    conf: float = 0.0
    source: Literal["face", "body"] | None = None
    off_road_ms: float = 0.0
    vats_60s: int = 0
    entropy_60s: float | None = None
    # extra (debug overlay, evaluation, docs/perception.md §9)
    calibrated: bool = False
    raw_zone: str | None = None  # this frame's kNN result before the zone tracker
    nearest: str | None = None  # best kNN zone before rejection
    knn_dist: float | None = None
    tau: float | None = None
    reason: str | None = None  # why there are no features (no_face, face_too_small, low_conf, no_gaze, ...)
    gaze_yaw: float | None = None  # MobileGaze, smoothed, driver convention (yaw left, pitch up)
    gaze_pitch: float | None = None
    off_road_60s_ms: float = 0.0
    lap_pattern: bool = False


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
    gaze: DriverGaze = Field(default_factory=DriverGaze)
    perf: dict[str, float]  # detector stage timings in ms


class DriverPipeline:
    def __init__(
        self,
        cfg: PerceptionConfig,
        frame_size: tuple[int, int],
        ear_baseline: tuple[float, float] | None = None,
        zone_model: ZoneModel | None = None,
    ) -> None:
        self.cfg = cfg
        self.frame_size = frame_size
        self.eyes = EyeTracker(cfg.eyes, frame_size, ear_baseline)
        self.head = HeadTracker(cfg.head, cfg.filters)
        self.mouth = MouthTracker(cfg.yawn, cfg.speaking, frame_size)
        g, f = cfg.gaze, cfg.filters.one_euro_gaze
        self.gaze_smoother = GazeSmoother(f.min_cutoff, f.beta, f.d_cutoff, g.max_age_ms)
        self.gaze_features = GazeFeatureBuilder(cfg, frame_size)
        self.zone_model = zone_model
        self.zones = ZoneTracker(g.zone_min_frames, cfg.eyes.blink_max_ms / 1000.0)
        self.gaze_metrics = GazeMetrics(cfg)
        self.last_zone_features: npt.NDArray[np.float64] | None = None  # for the zone parameter sweep
        self.last_eyes = EyeOutput()
        self.last_head = HeadOutput()
        self.last_mouth = MouthOutput()

    def set_calibration(self, zone_model: ZoneModel | None, ear_baseline: tuple[float, float] | None) -> None:
        """Swap in a new gaze calibration while running (the ``calibrate`` command); resets the zone state."""
        self.zone_model = zone_model
        self.zones.reset()
        self.gaze_metrics = GazeMetrics(self.cfg)
        if ear_baseline is not None:
            self.eyes.reference.set_calibrated(ear_baseline)

    def _gaze(self, ff: FeatureFrame, head: HeadOutput, eyes_closed: bool) -> DriverGaze:
        gaze = self.gaze_smoother.update(ff.t, ff.gaze)
        x = self.gaze_features.build(ff, *zone_head_angles(head.yaw, head.raw_yaw, head.raw_pitch), gaze)
        self.last_zone_features = x
        result: ZoneResult | None = None
        if self.zone_model is not None and x is not None and not eyes_closed:
            result = self.zone_model.classify(x)
        zone = self.zones.update(ff.t, result, eyes_closed=eyes_closed and self.zone_model is not None)
        hands_seen = bool(ff.hands) if ff.hands is not None else None
        metrics = self.gaze_metrics.update(ff.t, zone, hands_seen)
        known = zone != "unknown"
        return DriverGaze(
            zone=zone,
            conf=round(self.zones.conf, 3) if known else 0.0,
            source="face" if known else None,
            off_road_ms=metrics.off_road_ms,
            vats_60s=metrics.vats_60s,
            entropy_60s=metrics.entropy_60s,
            calibrated=self.zone_model is not None,
            raw_zone=result.zone if result is not None else None,
            nearest=result.nearest if result is not None else None,
            knn_dist=round(result.distance, 3) if result is not None and result.distance is not None else None,
            tau=round(self.zone_model.tau, 3) if self.zone_model is not None else None,
            reason=self.gaze_features.last_reason,
            gaze_yaw=round(gaze[0], 2) if gaze is not None else None,
            gaze_pitch=round(gaze[1], 2) if gaze is not None else None,
            off_road_60s_ms=metrics.off_road_60s_ms,
            lap_pattern=metrics.lap_pattern,
        )

    def update(self, ff: FeatureFrame) -> DriverState:
        t0 = time.perf_counter()
        eyes = self.eyes.update(ff)
        t1 = time.perf_counter()
        closing = eyes.state == "CLOSED" or (eyes.ratio is not None and eyes.ratio < self.cfg.eyes.reopen_ratio)
        head = self.head.update(ff.t, ff.face.head_matrix, closing)
        t2 = time.perf_counter()
        mouth = self.mouth.update(ff.t, ff.face)
        t3 = time.perf_counter()
        gaze = self._gaze(ff, head, eyes_closed=eyes.state == "CLOSED")
        t4 = time.perf_counter()
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
            gaze=gaze,
            perf={
                "eyes_ms": round((t1 - t0) * 1000, 3),
                "head_ms": round((t2 - t1) * 1000, 3),
                "mouth_ms": round((t3 - t2) * 1000, 3),
                "gaze_ms": round((t4 - t3) * 1000, 3),
                "detectors_ms": round((t4 - t0) * 1000, 3),
            },
        )
