"""Blink shape measurements on a sampled eye-openness signal (EAR or EAR / reference), with sub-frame timing.

Used by the diagnostics (``scripts/diag_eyes.py``), the Face Landmarker A/B (``scripts/eval_eyes.py --ab-num-faces``)
and the tests. Durations are measured at **50 % of the blink amplitude** (full width at half depth), with linear
interpolation between frames, so the result does not depend on where the frames fall (± a few ms instead of ± 1 frame).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["BlinkShape", "crossing_time", "measure_dip"]


def crossing_time(t0: float, v0: float, t1: float, v1: float, level: float) -> float:
    """Time at which the segment (t0, v0) -> (t1, v1) crosses ``level`` (linear interpolation)."""
    if v1 == v0:
        return t0
    frac = (level - v0) / (v1 - v0)
    return t0 + min(1.0, max(0.0, frac)) * (t1 - t0)


@dataclass(frozen=True)
class BlinkShape:
    ref: float  # open level used
    minimum: float  # lowest value of the dip
    t_min: float
    depth: float  # 1 - minimum / ref (0 = no dip, 1 = value reached 0)
    t_down: float | None  # 50 % crossing on the way down
    t_up: float | None  # 50 % crossing on the way up
    frames_below_half: int

    @property
    def width_ms(self) -> float | None:
        if self.t_down is None or self.t_up is None:
            return None
        return (self.t_up - self.t_down) * 1000.0

    @property
    def reopen_ms(self) -> float | None:
        """From the minimum to the 50 % crossing on the way up."""
        return None if self.t_up is None else (self.t_up - self.t_min) * 1000.0


def measure_dip(times: Sequence[float], values: Sequence[float], ref: float) -> BlinkShape | None:
    """Measure the deepest dip of ``values`` below ``ref`` inside the given samples.

    The half level is ``ref - (ref - minimum) / 2``. The crossings are searched outwards from the minimum; if the
    signal never comes back above the half level inside the window, that side is ``None``.
    """
    if len(times) != len(values) or len(values) < 3 or ref <= 0:
        return None
    k_min = min(range(len(values)), key=values.__getitem__)
    minimum = values[k_min]
    if minimum >= ref:
        return None
    half = ref - (ref - minimum) / 2.0
    t_down: float | None = None
    for k in range(k_min, 0, -1):
        if values[k - 1] > half >= values[k]:
            t_down = crossing_time(times[k - 1], values[k - 1], times[k], values[k], half)
            break
    t_up: float | None = None
    for k in range(k_min, len(values) - 1):
        if values[k] <= half < values[k + 1]:
            t_up = crossing_time(times[k], values[k], times[k + 1], values[k + 1], half)
            break
    below = 0
    for k in range(k_min, -1, -1):
        if values[k] > half:
            break
        below += 1
    for k in range(k_min + 1, len(values)):
        if values[k] > half:
            break
        below += 1
    return BlinkShape(
        ref=ref,
        minimum=minimum,
        t_min=times[k_min],
        depth=1.0 - minimum / ref,
        t_down=t_down,
        t_up=t_up,
        frames_below_half=below,
    )
