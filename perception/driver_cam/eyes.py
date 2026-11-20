"""Eye state from FeatureFrames: EAR per eye, relative thresholds, squint rule R-FL4, blinks, closures, PERCLOS.

Pipeline per frame (docs/perception.md §3.2):
1. EAR per eye in **pixels** (normalized coordinates would distort the ratio on a 16:9 frame).
2. ``eye_used`` = the eye with the larger corner distance (least foreshortened when the head turns).
3. r = EAR / personal baseline (calibration, or a provisional p90 of the first seconds with a valid face).
4. ``Median3`` on r; fusion with ``eyeBlink``: when the blendshape says closed and r is inside the hysteresis band,
   r is pushed below ``k_close``.
5. **R-FL4:** ``eyeSquint >= squint_threshold`` and r inside ``squint_ear_band`` -> SQUINT: not closed, not in
   PERCLOS, no ``closed_ms``, not a blink.
6. ``Hysteresis(k_close, k_open, min_state_frames)`` -> OPEN / CLOSED. Episode durations come from the hysteresis
   transition times, so the median and confirmation delays cancel out.
7. Closed episode <= ``blink_max_ms`` -> blink (``blink_ms``); longer -> closure. ``closed_ms`` = current closure.

``microsleep`` is never decided here: P1 reports ``closed_ms``, P2 owns the threshold.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from perception.config import EyesConfig
from perception.features import FeatureFrame
from perception.filters import Hysteresis, Median3, RollingWindow
from perception.perf import percentile

__all__ = ["EAR_POINTS", "EyeEvent", "EyeOutput", "EyeTracker", "ear_from_points"]

EyeState = Literal["OPEN", "CLOSED", "SQUINT", "UNKNOWN"]

# p1..p6 = outer/inner corner, two upper lid points, two lower lid points (Soukupová & Čech 2016 ordering).
EAR_POINTS: dict[str, tuple[int, int, int, int, int, int]] = {
    "right": (33, 160, 158, 133, 153, 144),
    "left": (362, 385, 387, 263, 373, 380),
}

Point2 = tuple[float, float]


def _dist(a: Point2, b: Point2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def ear_from_points(p: list[Point2]) -> tuple[float, float]:
    """(EAR, corner distance) from six pixel points p1..p6."""
    width = _dist(p[0], p[3])
    if width <= 0:
        return 0.0, 0.0
    return (_dist(p[1], p[5]) + _dist(p[2], p[4])) / (2.0 * width), width


@dataclass(frozen=True)
class EyeEvent:
    kind: Literal["blink", "closure"]
    start: float
    end: float

    @property
    def duration_ms(self) -> float:
        return (self.end - self.start) * 1000.0


@dataclass
class EyeOutput:
    state: EyeState = "UNKNOWN"
    ear: float | None = None  # EAR of eye_used
    ear_left: float | None = None
    ear_right: float | None = None
    eye_used: Literal["left", "right"] | None = None
    ratio: float | None = None  # EAR / baseline of eye_used, after Median3
    baseline_left: float | None = None
    baseline_right: float | None = None
    baseline_provisional: bool = True
    squint: bool = False
    eye_squint: float | None = None  # max(eyeSquintLeft, eyeSquintRight)
    eye_blink: float | None = None  # mean(eyeBlinkLeft, eyeBlinkRight)
    closed_ms: int = 0
    blink_ms: int | None = None  # duration of the last blink
    blink_rate: float | None = None  # blinks per minute over the last 60 s
    perclos_60s: float = 0.0
    reliable: bool = False
    new_events: list[EyeEvent] = field(default_factory=list)


class EyeTracker:
    def __init__(
        self,
        cfg: EyesConfig,
        frame_size: tuple[int, int],
        baseline: tuple[float, float] | None = None,
    ) -> None:
        """``frame_size`` = (width, height) in pixels; ``baseline`` = (left, right) open-eye EAR from calibration."""
        self.cfg = cfg
        self.w, self.h = frame_size
        self._calibrated = baseline
        self._samples: list[tuple[float, float]] = []  # provisional baseline samples (left, right)
        self._valid_time = 0.0
        self._last_valid_t: float | None = None
        self._provisional: tuple[float, float] | None = None
        self._median = Median3()
        self._hyst = Hysteresis(cfg.k_close, cfg.k_open, cfg.min_state_frames)
        self._closure_start: float | None = None
        self._perclos = RollingWindow(cfg.perclos_window_s)
        self._blinks: deque[float] = deque()
        self._first_t: float | None = None
        self._last_blink_ms: int | None = None
        self.events: list[EyeEvent] = []

    # baseline -------------------------------------------------------------------------------------------

    @property
    def baseline(self) -> tuple[float, float] | None:
        return self._calibrated or self._provisional

    def _update_baseline(self, t: float, ear_l: float, ear_r: float) -> None:
        if self._calibrated is not None:
            return
        if self._last_valid_t is not None:
            self._valid_time += min(t - self._last_valid_t, 0.2)  # gaps (face lost) do not count
        self._last_valid_t = t
        if self._valid_time > self.cfg.baseline_window_s and self._provisional is not None:
            return  # frozen after the window
        self._samples.append((ear_l, ear_r))
        if self._valid_time >= self.cfg.baseline_min_s:
            q = self.cfg.baseline_percentile
            self._provisional = (
                percentile([s[0] for s in self._samples], q),
                percentile([s[1] for s in self._samples], q),
            )

    # per frame ------------------------------------------------------------------------------------------

    def update(self, ff: FeatureFrame) -> EyeOutput:
        t = ff.t
        if self._first_t is None:
            self._first_t = t
        out = EyeOutput(perclos_60s=round(self._perclos.fraction(), 4), blink_ms=self._last_blink_ms)
        face = ff.face
        if not face.present or face.landmarks is None or face.blendshapes is None:
            self._lose(t)
            out.blink_rate = self._blink_rate(t)
            return out

        ears: dict[str, tuple[float, float]] = {}
        for side, idx in EAR_POINTS.items():
            pts = [face.point(i) for i in idx]
            ears[side] = ear_from_points([(x * self.w, y * self.h) for x, y, _ in pts])
        (ear_l, width_l), (ear_r, width_r) = ears["left"], ears["right"]
        used: Literal["left", "right"] = "left" if width_l >= width_r else "right"
        out.ear_left, out.ear_right = round(ear_l, 4), round(ear_r, 4)
        out.eye_used = used
        out.ear = out.ear_left if used == "left" else out.ear_right
        out.reliable = max(width_l, width_r) >= self.cfg.min_eye_width_px
        bs = face.blendshapes
        out.eye_blink = round((bs.get("eyeBlinkLeft", 0.0) + bs.get("eyeBlinkRight", 0.0)) / 2, 4)
        out.eye_squint = round(max(bs.get("eyeSquintLeft", 0.0), bs.get("eyeSquintRight", 0.0)), 4)

        if not out.reliable:
            self._lose(t)
            out.blink_rate = self._blink_rate(t)
            return out

        self._update_baseline(t, ear_l, ear_r)
        base = self.baseline
        out.baseline_provisional = self._calibrated is None
        if base is None:  # not enough data yet for a baseline
            out.blink_rate = self._blink_rate(t)
            return out
        out.baseline_left, out.baseline_right = round(base[0], 4), round(base[1], 4)
        base_used = base[0] if used == "left" else base[1]
        ratio = self._median.update((ear_l if used == "left" else ear_r) / base_used if base_used > 0 else 0.0)
        out.ratio = round(ratio, 4)

        low, high = self.cfg.squint_ear_band
        squint = out.eye_squint >= self.cfg.squint_threshold and low <= ratio <= high  # R-FL4
        was_closed = self._hyst.active
        if squint:
            self._hyst.hold()
            if was_closed:  # eyes opened into a squint: the closure ends now
                self._end_closure(t, out)
                self._hyst.reset(False)
        else:
            value = ratio
            if out.eye_blink >= self.cfg.blendshape_closed and value < self.cfg.k_open:
                value = min(value, self.cfg.k_close * 0.999)  # blendshape confirms closure inside the band
            self._hyst.update(t, value)
            if self._hyst.active and not was_closed:
                self._closure_start = self._hyst.t_change if self._hyst.t_change is not None else t
            elif was_closed and not self._hyst.active:
                self._end_closure(self._hyst.t_change if self._hyst.t_change is not None else t, out)

        closed = self._hyst.active
        out.squint = squint and not closed
        out.state = "CLOSED" if closed else ("SQUINT" if out.squint else "OPEN")
        if closed and self._closure_start is not None:
            out.closed_ms = max(0, round((t - self._closure_start) * 1000))
        self._perclos.add(t, 1.0 if closed else 0.0)
        out.perclos_60s = round(self._perclos.fraction(), 4)
        out.blink_ms = self._last_blink_ms
        out.blink_rate = self._blink_rate(t)
        return out

    # internals ------------------------------------------------------------------------------------------

    def _end_closure(self, end: float, out: EyeOutput) -> None:
        if self._closure_start is None:
            return
        start, self._closure_start = self._closure_start, None
        duration_ms = (end - start) * 1000.0
        kind: Literal["blink", "closure"] = "blink" if duration_ms <= self.cfg.blink_max_ms else "closure"
        event = EyeEvent(kind, start, end)
        self.events.append(event)
        out.new_events.append(event)
        if kind == "blink":
            self._last_blink_ms = round(duration_ms)
            self._blinks.append(end)

    def _lose(self, t: float) -> None:
        """Face missing or eyes unreliable: no state, no closure in progress (monitoring is P2's rule C7)."""
        self._hyst.reset(False)
        self._median.reset()
        self._closure_start = None
        self._last_valid_t = None

    def _blink_rate(self, t: float) -> float | None:
        while self._blinks and t - self._blinks[0] > 60.0:
            self._blinks.popleft()
        span = min(60.0, t - (self._first_t if self._first_t is not None else t))
        if span < 10.0:
            return None
        return round(len(self._blinks) * 60.0 / span, 1)
