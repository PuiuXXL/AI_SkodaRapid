"""Eye state from FeatureFrames: EAR per eye, local reference, blink shape, bilateral rule, gaze conditioning, R-FL4.

Why this design (docs/perception.md §3.2, diag of 2026-11-21 in docs/eval/): the open-eye EAR is not constant. With
the head a few degrees lower it fell from 0.30 to 0.24, so a reference learned in the first seconds made open eyes
look "half closed" and a hysteresis on that reference stayed CLOSED for seconds. Blinks themselves were sharp
(~180 ms at 50 % depth in the raw signal), so the fix is the reference and the decision rule, not more filtering.

Per frame:
1. EAR per eye in **pixels**; an eye is unreliable if narrower than ``min_eye_width_px`` or than
   ``unilateral_width_ratio`` x the other eye (head turned: foreshortened).
2. **Reference per eye** (:class:`EarReference`): p90 of the EAR over the last ``local_ref_window_s`` (blinks
   are < 10 % of the frames, so the p90 is the open level), never below ``ref_floor_ratio`` x the global reference
   (calibration or the provisional p90 of the first seconds). Interface ready for a per-gaze-zone reference
   (phase 5).
3. r = EAR / reference per eye; **bilateral rule**: the eye signal is the MAX over the reliable eyes, so "closed"
   needs both eyes below the threshold (one eye only when the other is unreliable).
4. **Gaze conditioning:** head pitch <= -``pitch_down_deg`` or >= ``pitch_up_deg``, or eyeLookDown >=
   ``look_down_threshold`` on the last open frame (it rises during every blink, so never the current one) -> the
   closing threshold becomes ``drop_ratio_relaxed`` (looking down lowers the lids). No closure may start while the
   head moves fast (``head_motion_deg`` in ``head_motion_window_s``): the lids follow the head.
5. **Shape:** r falls below the threshold. A **fast** fall (<= ``fall_max_ms`` from the last open frame) is a blink
   or a real closure. A **slow** fall counts only with ``eyeBlink >= blendshape_closed`` (drowsy lids); otherwise a
   ratio inside ``squint_ear_band`` with eyeBlink below ``blendshape_closed`` (lids lowered, not meeting) is
   **SQUINT** (R-FL4); a fast fall that settles there for longer than a blink is cancelled (no event).
   ``min_state_frames`` frames below confirm CLOSED, but ``closed_ms`` counts from the (interpolated) drop.
   The episode ends when r rises above ``reopen_ratio``.
6. **Duration = time below 50 % of the depth** (interpolated, perception/eye_signal.py); <= ``blink_max_ms`` =
   blink, longer = closure. Per event also ``reopen_ms`` (minimum -> 50 % on the way up, Schleicher et al. 2008) and
   ``close_speed`` (depth / time from the last open frame to the minimum).
7. **PERCLOS P80** (Wierwille / Dinges, FHWA 1998): share of the last 60 s with closure >= 80 %, closure =
   (1 - r) / (1 - closed level); the closed level is the median minimum of the recent blinks.

``microsleep`` is never decided here: P1 reports ``closed_ms``, P2 owns the threshold.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from perception.config import EyesConfig
from perception.driver_cam.head import euler_from_matrix
from perception.eye_signal import crossing_time, measure_dip
from perception.features import FeatureFrame
from perception.filters import RollingWindow
from perception.perf import percentile

__all__ = ["EAR_POINTS", "EarReference", "EyeEvent", "EyeOutput", "EyeTracker", "ear_from_points"]

EyeState = Literal["OPEN", "CLOSED", "SQUINT", "UNKNOWN"]
Side = Literal["left", "right"]

# p1..p6 = outer/inner corner, two upper lid points, two lower lid points (Soukupová & Čech 2016 ordering).
EAR_POINTS: dict[str, tuple[int, int, int, int, int, int]] = {
    "right": (33, 160, 158, 133, 153, 144),
    "left": (362, 385, 387, 263, 373, 380),
}

Point2 = tuple[float, float]
_SIDES: tuple[Side, Side] = ("left", "right")
_RECENT_MINIMA = 10  # blinks used for the closed level (PERCLOS P80)


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
    start: float  # 50 % crossing on the way down
    end: float  # 50 % crossing on the way up
    min_ratio: float = 0.0
    fall_ms: float = 0.0  # last open frame -> drop threshold
    reopen_ms: float | None = None  # minimum -> 50 % on the way up
    close_speed: float | None = None  # depth per second, last open frame -> minimum

    @property
    def duration_ms(self) -> float:
        return (self.end - self.start) * 1000.0


@dataclass
class EyeOutput:
    state: EyeState = "UNKNOWN"
    ear: float | None = None  # EAR of eye_used
    ear_left: float | None = None
    ear_right: float | None = None
    eye_used: Side | None = None
    ratio: float | None = None  # bilateral eye signal: max EAR / reference over the reliable eyes
    ratio_left: float | None = None
    ratio_right: float | None = None
    ref_left: float | None = None  # local reference in use
    ref_right: float | None = None
    baseline_left: float | None = None  # global reference (floor)
    baseline_right: float | None = None
    baseline_provisional: bool = True
    squint: bool = False
    eye_squint: float | None = None  # max(eyeSquintLeft, eyeSquintRight)
    eye_blink: float | None = None  # mean(eyeBlinkLeft, eyeBlinkRight)
    look_down: float | None = None  # mean(eyeLookDownLeft, eyeLookDownRight)
    cnn_closed: float | None = None  # eye-state CNN p(closed), max over the reliable croppable eyes; None = not run
    pitch: float | None = None  # raw head pitch used for the gaze conditioning
    relaxed: bool = False  # gaze conditioning active (stricter closing threshold)
    closed_ms: int = 0
    long_closure: bool = False  # CLOSED for longer than blink_max_ms
    blink_ms: int | None = None  # duration of the last blink
    blink_rate: float | None = None  # blinks per minute over the last 60 s
    perclos_60s: float = 0.0  # P80
    reliable: bool = False
    new_events: list[EyeEvent] = field(default_factory=list)


class EarReference:
    """Open-eye EAR reference per eye: local p90 over a short window, floored by the global reference.

    ``get(side, zone)`` takes a gaze zone so a per-zone reference (phase 5, gaze calibration) can plug in; today the
    zone is ignored.
    """

    def __init__(self, cfg: EyesConfig, calibrated: tuple[float, float] | None = None) -> None:
        self.cfg = cfg
        self._calibrated = calibrated
        self._samples: list[tuple[float, float]] = []  # provisional global baseline samples (left, right)
        self._valid_time = 0.0
        self._last_valid_t: float | None = None
        self._provisional: tuple[float, float] | None = None
        self._local: dict[Side, deque[tuple[float, float]]] = {"left": deque(), "right": deque()}

    @property
    def calibrated(self) -> bool:
        return self._calibrated is not None

    @property
    def global_ref(self) -> tuple[float, float] | None:
        return self._calibrated or self._provisional

    def observe(self, t: float, ear_l: float, ear_r: float) -> None:
        """Every reliable frame: feeds the provisional global baseline (first seconds only)."""
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

    def add(self, t: float, side: Side, ear: float) -> None:
        """Every reliable frame of this eye.

        All frames go in, closed ones too: blinks fill < 10 % of the time, so the p90 ignores them, and a closure
        shorter than ~90 % of the window does not move it either. Excluding "closed" frames instead deadlocks: a
        closure that started on a too-high reference freezes the reference and never ends (diag 2026-11-21, 56.9 s).
        A closure longer than the window pulls the reference down to the floor, where a closed eye still reads
        ~0.5-0.6 (below ``reopen_ratio``), so it stays CLOSED.
        """
        window = self._local[side]
        window.append((t, ear))
        while window and t - window[0][0] > self.cfg.local_ref_window_s:
            window.popleft()

    def get(self, side: Side, zone: str | None = None) -> float | None:
        del zone  # per-zone references: phase 5 (gaze calibration)
        base = self.global_ref
        if base is None:
            return None
        g = base[0] if side == "left" else base[1]
        window = self._local[side]
        if len(window) < 3 or window[-1][0] - window[0][0] < self.cfg.local_ref_min_s:
            return g
        local = percentile([e for _, e in window], self.cfg.local_ref_percentile)
        return max(local, self.cfg.ref_floor_ratio * g)

    def lose(self) -> None:
        """Face lost: the provisional baseline clock pauses; the local window ages out by time on its own."""
        self._last_valid_t = None


@dataclass
class _Episode:
    t_open: float  # local peak before the fall (max of the last fall_window_s)
    r_open: float
    t_drop: float  # interpolated crossing of the closing threshold
    fall_ms: float
    times: list[float]
    values: list[float]
    below: int = 1
    confirmed: bool = False
    blinks: list[float] = field(default_factory=list)  # eyeBlink during the episode
    closed_frames: int = 0  # frames with ratio below the squint band AND eyeBlink >= blendshape_closed
    open_run: int = 0  # consecutive frames, after blink_max_ms, that do not look closed


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
        self.reference = EarReference(cfg, baseline)
        self._episode: _Episode | None = None
        self._last: tuple[float, float] | None = None  # (t, r) of the previous valid frame
        self._hist: deque[tuple[float, float]] = deque()  # (t, r) over the last fall_window_s
        self._perclos = RollingWindow(cfg.perclos_window_s)
        self._head: deque[tuple[float, float, float]] = deque()  # (t, pitch, yaw) for head-motion gating
        self._open_look_down = 0.0  # eyeLookDown on the last open frame
        self._cnn_open = False  # this frame: the eye-state CNN sees the eyes clearly open
        self._cnn_closed_now = False  # ... clearly closed
        self._minima: deque[float] = deque(maxlen=_RECENT_MINIMA)
        self._blinks: deque[float] = deque()
        self._first_t: float | None = None
        self._last_blink_ms: int | None = None
        self.events: list[EyeEvent] = []

    @staticmethod
    def _cnn_closed(probs: list[float] | None, reliable: dict[Side, bool]) -> float | None:
        """Bilateral like the EAR: the MOST OPEN reliable eye decides (max of p_closed would let one eye win)."""
        if probs is None:
            return None
        values = [p for p, side in zip(probs, _SIDES, strict=True) if reliable[side] and p >= 0.0]
        return min(values) if values else None

    # kept for callers that read the global reference
    @property
    def baseline(self) -> tuple[float, float] | None:
        return self.reference.global_ref

    @property
    def closed_level(self) -> float:
        return statistics.median(self._minima) if self._minima else self.cfg.closed_level_default

    # per frame ------------------------------------------------------------------------------------------

    def update(self, ff: FeatureFrame) -> EyeOutput:
        t = ff.t
        if self._first_t is None:
            self._first_t = t
        out = EyeOutput(perclos_60s=round(self._perclos.fraction(), 4), blink_ms=self._last_blink_ms)
        face = ff.face
        if not face.present or face.landmarks is None or face.blendshapes is None:
            return self._lose(t, out)

        ears: dict[Side, tuple[float, float]] = {}
        for side in _SIDES:
            pts = [face.point(i) for i in EAR_POINTS[side]]
            ears[side] = ear_from_points([(x * self.w, y * self.h) for x, y, _ in pts])
        (ear_l, width_l), (ear_r, width_r) = ears["left"], ears["right"]
        used: Side = "left" if width_l >= width_r else "right"
        out.ear_left, out.ear_right = round(ear_l, 4), round(ear_r, 4)
        out.eye_used = used
        out.ear = out.ear_left if used == "left" else out.ear_right
        bs = face.blendshapes
        out.eye_blink = round((bs.get("eyeBlinkLeft", 0.0) + bs.get("eyeBlinkRight", 0.0)) / 2, 4)
        out.eye_squint = round(max(bs.get("eyeSquintLeft", 0.0), bs.get("eyeSquintRight", 0.0)), 4)
        out.look_down = round((bs.get("eyeLookDownLeft", 0.0) + bs.get("eyeLookDownRight", 0.0)) / 2, 4)

        widest = max(width_l, width_r)
        reliable: dict[Side, bool] = {
            side: ears[side][1] >= self.cfg.min_eye_width_px
            and ears[side][1] >= self.cfg.unilateral_width_ratio * widest
            for side in _SIDES
        }
        out.reliable = any(reliable.values())
        if not out.reliable:
            return self._lose(t, out)

        self.reference.observe(t, ear_l, ear_r)
        base = self.reference.global_ref
        out.baseline_provisional = not self.reference.calibrated
        if base is None:  # not enough data yet for a reference
            out.blink_rate = self._blink_rate(t)
            return out
        out.baseline_left, out.baseline_right = round(base[0], 4), round(base[1], 4)
        for side in _SIDES:
            if reliable[side]:
                self.reference.add(t, side, ears[side][0])
        refs = {side: self.reference.get(side) for side in _SIDES}
        ratios: dict[Side, float] = {}
        for side in _SIDES:
            ref = refs[side]
            if ref:
                ratios[side] = ears[side][0] / ref
        out.ref_left = round(refs["left"], 4) if refs["left"] else None
        out.ref_right = round(refs["right"], 4) if refs["right"] else None
        out.ratio_left = round(ratios["left"], 4) if "left" in ratios else None
        out.ratio_right = round(ratios["right"], 4) if "right" in ratios else None
        r = max(ratios[side] for side in ratios if reliable[side])  # bilateral: closed only if both are below
        out.ratio = round(r, 4)

        pitch, yaw, _ = euler_from_matrix(face.head_matrix) if face.head_matrix else (0.0, 0.0, 0.0)
        out.pitch = round(pitch, 2)
        head_moving = self._head_moving(t, pitch, yaw)
        # eyeLookDown rises during every blink (the lids cover the iris), so it is read on the last OPEN frame,
        # before the fall; head pitch is read on the current frame.
        if self._episode is None and r >= self.cfg.reopen_ratio:
            self._open_look_down = out.look_down
        out.relaxed = (
            pitch <= -self.cfg.pitch_down_deg
            or pitch >= self.cfg.pitch_up_deg
            or self._open_look_down >= self.cfg.look_down_threshold
        )
        threshold = self.cfg.drop_ratio_relaxed if out.relaxed else self.cfg.drop_ratio
        low, high = self.cfg.squint_ear_band
        cnn = self._cnn_closed(face.eye_closed_p, reliable)
        out.cnn_closed = None if cnn is None else round(cnn, 4)
        cnn_open = cnn is not None and cnn < self.cfg.cnn.open_max
        cnn_closed = cnn is not None and cnn >= self.cfg.cnn.closed_min
        # R-FL4: lids lowered (ratio in the band) but not meeting (eyeBlink low, or the CNN sees an open eye).
        # eyeSquint is not used: person-dependent (0.49 at rest in the diag session), 0.71 with eyes squeezed shut.
        squint_like = low <= r <= high and (out.eye_blink < self.cfg.blendshape_closed or cnn_open) and not cnn_closed
        self._cnn_open, self._cnn_closed_now = cnn_open, cnn_closed

        self._step(t, r, threshold, out.eye_blink, squint_like, out.relaxed, head_moving, out)

        closed = self._episode is not None and self._episode.confirmed
        out.squint = squint_like and not closed and self._episode is None
        out.state = "CLOSED" if closed else ("SQUINT" if out.squint else "OPEN")
        if closed and self._episode is not None:
            out.closed_ms = max(0, round((t - self._episode.t_drop) * 1000))
            out.long_closure = out.closed_ms > self.cfg.blink_max_ms

        closure = (1.0 - r) / max(1e-6, 1.0 - self.closed_level)
        self._perclos.add(t, 1.0 if (closure >= self.cfg.perclos_closure and not out.squint) else 0.0)
        out.perclos_60s = round(self._perclos.fraction(), 4)
        out.blink_ms = self._last_blink_ms
        out.blink_rate = self._blink_rate(t)
        return out

    # state machine --------------------------------------------------------------------------------------

    def _head_moving(self, t: float, pitch: float, yaw: float) -> bool:
        """Pitch or yaw changed by more than ``head_motion_deg`` in the last ``head_motion_window_s``.

        While the head moves (looking down at the lap, a mirror check) the lids follow the head and EAR drops as fast
        as in a blink (diag 2026-11-21: pitch -27..-32 deg, ratio 0.3). No closure may START then; one already
        running continues. Fatigue nodding is reported separately by the head tracker.
        """
        self._head.append((t, pitch, yaw))
        while self._head and t - self._head[0][0] > self.cfg.head_motion_window_s:
            self._head.popleft()
        pitches = [h[1] for h in self._head]
        yaws = [h[2] for h in self._head]
        return max(max(pitches) - min(pitches), max(yaws) - min(yaws)) > self.cfg.head_motion_deg

    def _step(
        self,
        t: float,
        r: float,
        threshold: float,
        eye_blink: float,
        squint_like: bool,
        relaxed: bool,
        head_moving: bool,
        out: EyeOutput,
    ) -> None:
        cfg = self.cfg
        ep = self._episode
        if ep is None:
            if r < threshold and self._last is not None and self._hist and not head_moving:
                t_prev, r_prev = self._last
                t_drop = crossing_time(t_prev, r_prev, t, r, threshold) if r_prev >= threshold else t
                # start of the fall: the last frame clearly above the threshold (threshold + min_fall_depth) within
                # fall_window_s; the depth reference is the max just before it. A slow drift before the blink is
                # not fall time, and a dip from an already-low level (blink inside a smile) has no fast fall.
                high = [h for h in self._hist if h[1] >= threshold + cfg.min_fall_depth]
                if high:
                    t_hi = high[-1][0]
                    t_pk, r_pk = max((h for h in self._hist if h[0] >= t_hi - 0.3), key=lambda h: h[1])
                    fall_ms = (t_drop - t_hi) * 1000.0
                else:
                    t_pk, r_pk = max(self._hist, key=lambda h: h[1])
                    fall_ms = float("inf")
                fast = fall_ms <= cfg.fall_max_ms
                # slow (drowsy) fall: only deep (slow_close_ratio), with the lids meeting, never while looking down
                slow_ok = (
                    not relaxed
                    and not self._cnn_open
                    and (
                        (r < cfg.slow_close_ratio and eye_blink >= cfg.blendshape_closed)
                        or eye_blink >= cfg.blendshape_strong
                        or (self._cnn_closed_now and r < cfg.squint_ear_band[0])
                    )
                )
                if fast or slow_ok:
                    samples = [h for h in self._hist if h[0] >= t_pk] + [(t, r)]
                    self._episode = _Episode(
                        t_pk,
                        r_pk,
                        t_drop,
                        fall_ms,
                        [h[0] for h in samples],
                        [h[1] for h in samples],
                        blinks=[eye_blink],
                        confirmed=cfg.min_state_frames <= 1,
                    )
        else:
            ep.times.append(t)
            ep.values.append(r)
            ep.blinks.append(eye_blink)
            r_min = min(ep.values)
            low = cfg.squint_ear_band[0]
            # continuing a closure is more lenient than starting one: cutting a real closure resets closed_ms
            looks_closed = (
                (r < low and eye_blink >= cfg.blendshape_closed)
                or eye_blink >= cfg.blendshape_strong
                or (self._cnn_closed_now and r < cfg.squint_ear_band[1])
            ) and not self._cnn_open  # the pixels show an open eye: a hard squint, not a closure
            ep.closed_frames += looks_closed
            since_drop = t - ep.t_drop
            if head_moving and since_drop <= cfg.head_motion_window_s:
                # the eyes lead the head: a fall followed at once by a head movement is a gaze shift, not a closure
                self._episode = None
            elif r >= max(r_min + 0.5 * (ep.r_open - r_min), min(threshold, ep.r_open - cfg.min_fall_depth)):
                # reopened: back above half the depth of this episode (same 50 % rule as the duration)
                if ep.confirmed:
                    self._finish(ep, out)
                self._episode = None
            elif since_drop > cfg.plateau_check_ms / 1000.0:
                # longer than most blinks: it stays closed only while the lids look closed (R-FL4); checked before
                # blink_max_ms so a squint never reports closed_ms above it
                deep = (
                    r < low * 0.9 and not self._cnn_open
                )  # very low ratio counts as closed unless the CNN sees it open
                ep.open_run = 0 if (looks_closed or deep) else ep.open_run + 1
                if ep.open_run >= cfg.min_state_frames + 1:
                    if ep.confirmed and ep.closed_frames >= 0.5 * (len(ep.values) - ep.open_run):
                        self._finish(ep, out, end=t)  # a real closure that settled into a squint
                    self._episode = None  # the lids never met: a fast squint, no event
            elif not ep.confirmed:
                if r < threshold:
                    ep.below += 1
                    if ep.below >= cfg.min_state_frames:
                        ep.confirmed = True
                else:  # one-frame glitch
                    self._episode = None
        self._last = (t, r)
        self._hist.append((t, r))
        while self._hist and t - self._hist[0][0] > cfg.fall_window_s:
            self._hist.popleft()

    def _finish(self, ep: _Episode, out: EyeOutput, end: float | None = None) -> None:
        shape = measure_dip(ep.times, ep.values, max(ep.r_open, max(ep.values)))
        if end is not None or shape is None or shape.t_down is None or shape.t_up is None:
            t_down = shape.t_down if shape is not None and shape.t_down is not None else ep.t_drop
            min_ratio = min(ep.values)
            start, end, reopen_ms, t_min = t_down, end if end is not None else ep.times[-1], None, ep.t_drop
        else:
            start, end, min_ratio, reopen_ms, t_min = (
                shape.t_down,
                shape.t_up,
                shape.minimum,
                shape.reopen_ms,
                shape.t_min,
            )
        depth = max(0.0, ep.r_open - min_ratio)
        fall_s = t_min - ep.t_open
        duration_ms = (end - start) * 1000.0
        kind: Literal["blink", "closure"] = "blink" if duration_ms <= self.cfg.blink_max_ms else "closure"
        event = EyeEvent(
            kind,
            start,
            end,
            min_ratio=round(min_ratio, 4),
            fall_ms=round(ep.fall_ms, 1),
            reopen_ms=round(reopen_ms, 1) if reopen_ms is not None else None,
            close_speed=round(depth / fall_s, 3) if fall_s > 0 else None,
        )
        self.events.append(event)
        out.new_events.append(event)
        self._minima.append(min_ratio)
        if kind == "blink":
            self._last_blink_ms = round(duration_ms)
            self._blinks.append(end)

    def _lose(self, t: float, out: EyeOutput) -> EyeOutput:
        """Face missing or eyes unreliable: no state, no closure in progress (monitoring is P2's rule C7)."""
        self._episode = None
        self._last = None
        self._hist.clear()
        self._head.clear()
        self.reference.lose()
        out.blink_rate = self._blink_rate(t)
        return out

    def _blink_rate(self, t: float) -> float | None:
        while self._blinks and t - self._blinks[0] > 60.0:
            self._blinks.popleft()
        span = min(60.0, t - (self._first_t if self._first_t is not None else t))
        if span < 10.0:
            return None
        return round(len(self._blinks) * 60.0 / span, 1)
