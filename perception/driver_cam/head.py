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
        oe = filters.one_euro
        self._filters = {axis: OneEuroFilter(oe.min_cutoff, oe.beta, oe.d_cutoff) for axis in ("yaw", "pitch", "roll")}
        self._nod = head.nod
        self._pitch_history = RollingWindow(head.nod.window_s)

    def update(self, t: float, matrix: Sequence[float] | None, eyes_closing: bool) -> HeadOutput:
        """``eyes_closing``: the eye state is CLOSED or the EAR ratio is below ``k_open`` (needed for nodding)."""
        if matrix is None:
            for f in self._filters.values():
                f.reset()
            self._pitch_history.clear()
            return HeadOutput()
        pitch, yaw, roll = euler_from_matrix(matrix)
        out = HeadOutput(raw_pitch=round(pitch, 2), raw_yaw=round(yaw, 2), raw_roll=round(roll, 2))
        out.pitch = round(self._filters["pitch"].update(t, pitch), 2)
        out.yaw = round(self._filters["yaw"].update(t, yaw), 2)
        out.roll = round(self._filters["roll"].update(t, roll), 2)
        self._pitch_history.add(t, out.pitch)
        drop = self._pitch_history.max() - out.pitch
        out.nodding = eyes_closing and drop > self._nod.pitch_drop_deg
        return out
