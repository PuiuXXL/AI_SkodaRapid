"""Helpers shared by the scores: term normalization, weighted sums over the terms that have data, smoothing."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def norm(value: float, bounds: Sequence[float]) -> float:
    """``[a, b]`` from thresholds.yaml: 0 at a, 1 at b, linear and clipped (b < a = inverted range)."""
    a, b = float(bounds[0]), float(bounds[1])
    return min(1.0, max(0.0, (value - a) / (b - a)))


def weighted(terms: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Sum of weight x term over the terms present, rescaled so the present weights sum to 1 (0 without terms)."""
    present = [name for name in terms if name in weights]
    total = sum(float(weights[name]) for name in present)
    if total <= 0:
        return 0.0
    return sum(float(weights[name]) * terms[name] for name in present) / total


def ema(previous: float, target: float, dt: float, tau: float) -> float:
    """Exponential smoothing with time constant ``tau`` seconds over a step of ``dt`` seconds."""
    if tau <= 0 or dt <= 0:
        return target if dt > 0 or tau <= 0 else previous
    alpha = 1.0 - math.exp(-dt / tau)
    return previous + alpha * (target - previous)
