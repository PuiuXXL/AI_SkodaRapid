"""Head pose from the Face Landmarker transformation matrix, One Euro smoothing, fatigue nodding.

Axis convention, in the **driver's** terms (docs/perception.md §3.3), all in degrees:
* ``yaw   > 0``: head turned to the driver's LEFT (towards the left mirror);
* ``pitch > 0``: head tilted UP;
* ``roll  > 0``: head tilted towards the driver's LEFT shoulder.

MediaPipe gives the face pose in camera space (x = image right, y = up, z = towards the camera; the camera image is
not mirrored). Euler angles are taken as rotations about x (pitch), y (yaw) and z (roll); ``AXIS_SIGNS`` maps them
to the convention above. Verified live with the guided step of ``scripts/eval_eyes.py`` (turn left / up / tilt).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from perception.config import FiltersConfig, HeadConfig
from perception.filters import OneEuroFilter, RollingWindow

__all__ = ["AXIS_SIGNS", "HeadOutput", "HeadTracker", "euler_from_matrix"]

# raw Euler (about x, y, z) -> driver convention (pitch up, yaw left, roll left shoulder)
AXIS_SIGNS = {"pitch": -1.0, "yaw": 1.0, "roll": -1.0}


def euler_from_matrix(matrix: Sequence[float]) -> tuple[float, float, float]:
    """(pitch, yaw, roll) in degrees, driver convention, from a row-major 4x4 transformation matrix."""
    r = [list(matrix[0:3]), list(matrix[4:7]), list(matrix[8:11])]
    pitch = math.atan2(r[2][1], r[2][2])
    yaw = math.atan2(-r[2][0], math.hypot(r[2][1], r[2][2]))
    roll = math.atan2(r[1][0], r[0][0])
    return (
        AXIS_SIGNS["pitch"] * math.degrees(pitch),
        AXIS_SIGNS["yaw"] * math.degrees(yaw),
        AXIS_SIGNS["roll"] * math.degrees(roll),
    )


@dataclass
class HeadOutput:
    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None
    raw_yaw: float | None = None
    raw_pitch: float | None = None
    raw_roll: float | None = None
    nodding: bool = False


class HeadTracker:
    def __init__(self, head: HeadConfig, filters: FiltersConfig) -> None:
        per_axis = filters.one_euro_head
        self._filters = {
            axis: OneEuroFilter(cfg.min_cutoff, cfg.beta, cfg.d_cutoff)
            for axis, cfg in (("yaw", per_axis.yaw), ("pitch", per_axis.pitch), ("roll", per_axis.roll))
        }
        self._nod = head.nod
        self._plausible = head.plausible_deg
        self._pitch_history = RollingWindow(head.nod.window_s)
        self._last_pitch_t: float | None = None  # last frame that fed the pitch history
        self._nod_until = float("-inf")  # nodding is held until then (hold_s)

    def reset(self) -> None:
        """Forget the filter state (day <-> IR switch: the angles jump with the new image)."""
        for f in self._filters.values():
            f.reset()
        self._pitch_history.clear()
        self._last_pitch_t = None
        self._nod_until = float("-inf")

    def _nodding(self, t: float, pitch: float, eyes_closing: bool) -> bool:
        """Fatigue nod on the RAW pitch (the head One Euro, min_cutoff 0.05 Hz, lags a slow drop by ~1 s): a drop of
        more than ``pitch_drop_deg`` within ``window_s`` with the eyes closing; held ``hold_s``."""
        self._pitch_history.add(t, pitch)
        self._last_pitch_t = t
        if eyes_closing and self._pitch_history.max() - pitch > self._nod.pitch_drop_deg:
            self._nod_until = t + self._nod.hold_s
        return t <= self._nod_until

    def update(self, t: float, matrix: Sequence[float] | None, eyes_closing: bool) -> HeadOutput:
        """``eyes_closing``: the eyes are closed now or were in a closure that has not visibly reopened yet
        (DriverPipeline's latch: with the head down the shut lids often read SQUINT). Needed for nodding."""
        if matrix is None:
            # the falling head often leaves the face tracker: a short gap keeps the pitch history (and a nod that was
            # just detected stays reported for hold_s); a longer one starts over
            for f in self._filters.values():
                f.reset()
            if self._last_pitch_t is None or t - self._last_pitch_t > self._nod.max_gap_s:
                self._pitch_history.clear()
            return HeadOutput(nodding=t <= self._nod_until)
        pitch, yaw, roll = euler_from_matrix(matrix)
        lim = self._plausible
        if abs(yaw) > lim.yaw or abs(pitch) > lim.pitch or abs(roll) > lim.roll:
            # near-profile face: the landmark fit is garbage; report unknown, do not feed the filters. A pitch beyond
            # the limit DOWNWARDS with plausible yaw / roll is a deep head drop (chin to chest): it still feeds the nod
            for f in self._filters.values():
                f.reset()
            out = HeadOutput(raw_pitch=round(pitch, 2), raw_yaw=round(yaw, 2), raw_roll=round(roll, 2))
            if pitch < -lim.pitch and abs(yaw) <= lim.yaw and abs(roll) <= lim.roll:
                out.nodding = self._nodding(t, pitch, eyes_closing)
            else:
                out.nodding = t <= self._nod_until
            return out
        out = HeadOutput(raw_pitch=round(pitch, 2), raw_yaw=round(yaw, 2), raw_roll=round(roll, 2))
        out.pitch = round(self._filters["pitch"].update(t, pitch), 2)
        out.yaw = round(self._filters["yaw"].update(t, yaw), 2)
        out.roll = round(self._filters["roll"].update(t, roll), 2)
        out.nodding = self._nodding(t, pitch, eyes_closing)
        return out
