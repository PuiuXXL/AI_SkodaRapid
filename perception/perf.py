"""Timing helpers shared by capture, runtime and benchmark (plan §J: perf_counter + deque(maxlen=120))."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager

__all__ = ["LatencyWindow", "RateMeter", "percentile"]


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (``q`` in 0..100) of an unsorted list; NaN if empty."""
    if not values:
        return float("nan")
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


class LatencyWindow:
    """Rolling window of durations in milliseconds. Thread-safe."""

    def __init__(self, maxlen: int = 120) -> None:
        self._values: deque[float] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._total = 0

    def add(self, ms: float) -> None:
        with self._lock:
            self._values.append(ms)
            self._total += 1

    @contextmanager
    def time(self) -> Iterator[None]:
        """``with window.time(): ...`` records the block's duration."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.add((time.perf_counter() - t0) * 1000.0)

    def snapshot(self) -> list[float]:
        with self._lock:
            return list(self._values)

    @property
    def count(self) -> int:
        """Total samples ever added (not only the ones still in the window)."""
        with self._lock:
            return self._total

    def p50(self) -> float:
        return percentile(self.snapshot(), 50)

    def p95(self) -> float:
        return percentile(self.snapshot(), 95)

    def mean(self) -> float:
        values = self.snapshot()
        return sum(values) / len(values) if values else float("nan")


class RateMeter:
    """Events per second over a sliding time window (default 1 s). Thread-safe."""

    def __init__(self, window_s: float = 1.0, clock: Callable[[], float] = time.perf_counter) -> None:
        self._window_s = window_s
        self._clock = clock
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def tick(self, t: float | None = None) -> None:
        now = self._clock() if t is None else t
        with self._lock:
            self._stamps.append(now)
            self._trim(now)

    def rate(self) -> float:
        now = self._clock()
        with self._lock:
            self._trim(now)
            if len(self._stamps) < 2:
                return 0.0
            span = self._stamps[-1] - self._stamps[0]
            return (len(self._stamps) - 1) / span if span > 0 else 0.0

    def _trim(self, now: float) -> None:
        while self._stamps and now - self._stamps[0] > self._window_s:
            self._stamps.popleft()
