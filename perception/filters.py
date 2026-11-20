"""Temporal filters for perception signals (docs/perception.md §3.2-3.3).

* :class:`OneEuroFilter`: continuous signals with variable speed (head angles): low lag on fast moves,
  strong smoothing at rest (Casiez, Roussel & Vogel, CHI 2012).
* :class:`MedianFilter` / :class:`Median3`: removes single-frame spikes without smearing short events
  (used on EAR instead of an EMA, which would erase 100-300 ms blinks).
* :class:`Hysteresis`: two thresholds + a minimum number of frames; remembers *when* the state changed, so
  event durations are measured from the transition, not from the filter's output delay.
* :class:`Debounce`: true only after the input stayed true for ``min_ms`` (slow events: yawn, gesture).
* :class:`RollingWindow`: time window of samples with time-weighted fraction (PERCLOS), mean, std, percentiles.
"""

from __future__ import annotations

import math
import statistics
from collections import deque

from perception.perf import percentile

__all__ = ["Debounce", "Hysteresis", "Median3", "MedianFilter", "OneEuroFilter", "RollingWindow"]


class OneEuroFilter:
    """1€ filter. ``update(t, x)`` with ``t`` in seconds."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._t: float | None = None
        self._x = 0.0
        self._dx = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def update(self, t: float, x: float) -> float:
        if self._t is None:
            self._t, self._x, self._dx = t, x, 0.0
            return x
        if t <= self._t:  # duplicate / out-of-order timestamp: keep the last estimate
            return self._x
        dt = t - self._t
        dx = (x - self._x) / dt
        self._dx += self._alpha(self.d_cutoff, dt) * (dx - self._dx)
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        self._x += self._alpha(cutoff, dt) * (x - self._x)
        self._t = t
        return self._x

    def reset(self) -> None:
        self._t = None


class MedianFilter:
    """Running median of the last ``n`` values (``n`` odd)."""

    def __init__(self, n: int = 3) -> None:
        if n < 1 or n % 2 == 0:
            raise ValueError("median length must be a positive odd number")
        self._values: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> float:
        self._values.append(x)
        return statistics.median(self._values)

    def reset(self) -> None:
        self._values.clear()


class Median3(MedianFilter):
    def __init__(self) -> None:
        super().__init__(3)


class Hysteresis:
    """Binary state from a value with two thresholds and a minimum number of consecutive frames.

    ``active`` turns True after ``min_frames`` consecutive values ``< low`` and back to False after ``min_frames``
    consecutive values ``> high``. Values in between keep the state. ``t_change`` is the time of the *first* frame
    of the run that caused the last transition, so durations do not include the ``min_frames`` confirmation delay.
    """

    def __init__(self, low: float, high: float, min_frames: int = 1) -> None:
        if low >= high:
            raise ValueError("hysteresis needs low < high")
        self.low = low
        self.high = high
        self.min_frames = max(1, min_frames)
        self.active = False
        self.t_change: float | None = None
        self._run = 0
        self._run_start: float | None = None

    def update(self, t: float, value: float) -> bool:
        wants_change = value > self.high if self.active else value < self.low
        if wants_change:
            if self._run == 0:
                self._run_start = t
            self._run += 1
            if self._run >= self.min_frames:
                self.active = not self.active
                self.t_change = self._run_start
                self._run = 0
        else:
            self._run = 0
        return self.active

    def hold(self) -> None:
        """Skip a frame without counting it toward a transition (e.g. a squint frame)."""
        self._run = 0

    def reset(self, active: bool = False) -> None:
        self.active = active
        self.t_change = None
        self._run = 0


class Debounce:
    """True only once the input has been true continuously for at least ``min_ms``."""

    def __init__(self, min_ms: float) -> None:
        self.min_ms = min_ms
        self._since: float | None = None

    def update(self, t: float, value: bool) -> bool:
        if not value:
            self._since = None
            return False
        if self._since is None:
            self._since = t
        return (t - self._since) * 1000.0 >= self.min_ms

    @property
    def since(self) -> float | None:
        return self._since


class RollingWindow:
    """Samples ``(t, value)`` kept for ``window_s`` seconds."""

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self._samples: deque[tuple[float, float]] = deque()

    def add(self, t: float, value: float) -> None:
        self._samples.append((t, value))
        while self._samples and t - self._samples[0][0] > self.window_s:
            self._samples.popleft()

    def values(self) -> list[float]:
        return [v for _, v in self._samples]

    @property
    def count(self) -> int:
        return len(self._samples)

    @property
    def span_s(self) -> float:
        return self._samples[-1][0] - self._samples[0][0] if len(self._samples) > 1 else 0.0

    def fraction(self) -> float:
        """Time-weighted mean of the values (for 0/1 values: the fraction of time they were 1).

        Each sample holds until the next one, so uneven frame intervals are weighted correctly.
        """
        if len(self._samples) < 2:
            return self._samples[0][1] if self._samples else 0.0
        total = weighted = 0.0
        for (t0, v0), (t1, _) in zip(self._samples, list(self._samples)[1:], strict=False):
            dt = t1 - t0
            total += dt
            weighted += v0 * dt
        return weighted / total if total > 0 else 0.0

    def mean(self) -> float:
        values = self.values()
        return sum(values) / len(values) if values else float("nan")

    def std(self) -> float:
        values = self.values()
        return statistics.pstdev(values) if len(values) > 1 else 0.0

    def p50(self) -> float:
        return percentile(self.values(), 50)

    def p95(self) -> float:
        return percentile(self.values(), 95)

    def max(self) -> float:
        values = self.values()
        return max(values) if values else float("nan")

    def clear(self) -> None:
        self._samples.clear()
