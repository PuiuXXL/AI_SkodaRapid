"""B2: fatigue F = 0.30·PERCLOS + 0.20·blink duration + 0.15·yawns + 0.20·slow reaction + 0.10·nodding
+ 0.05·trip duration (weights and ranges in thresholds.yaml ``fatigue``), smoothed with ``ema_tau_s``.

Yawns and nods are counted (rising edges) and the last blink duration is averaged over ``window_s``. While the
driver camera does not see the face the score is held, not reset. The eye terms are used only when
``eyes.reliable`` (AS14).
"""

from __future__ import annotations

import statistics
from collections import deque

from core.scoring.common import ema, norm, weighted
from core.settings import th
from shared.contracts import State


class FatigueScore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.value = 0.0
        self.terms: dict[str, float] = {}
        self.last_t: float | None = None
        self.blinks: deque[tuple[float, float]] = deque()
        self.yawns: deque[float] = deque()
        self.nods: deque[float] = deque()
        self.yawning = self.nodding = False

    def update(self, state: State, now: float, slow_ratio: float | None) -> float:
        dt = 0.0 if self.last_t is None else now - self.last_t
        self.last_t = now
        if not state.safety.monitoring_ok:
            return self.value
        driver = state.driver
        eyes = driver.eyes
        if eyes.blink_ms:  # P1 reports the last blink's duration: sampled every tick, averaged over the window
            self.blinks.append((now, eyes.blink_ms))
        if driver.yawn and not self.yawning:
            self.yawns.append(now)
        if driver.head.nodding and not self.nodding:
            self.nods.append(now)
        self.yawning, self.nodding = driver.yawn, driver.head.nodding
        cutoff = now - float(th("fatigue", "window_s"))
        while self.blinks and self.blinks[0][0] < cutoff:
            self.blinks.popleft()
        for queue in (self.yawns, self.nods):
            while queue and queue[0] < cutoff:
                queue.popleft()

        ranges = th("fatigue", "norm")
        terms = {
            "yawn": norm(len(self.yawns), ranges["yawn"]),
            "nodding": norm(len(self.nods), ranges["nodding"]),
            "trip_duration": norm(state.trip.elapsed_min, ranges["trip_duration"]),
        }
        if eyes.reliable:
            terms["perclos"] = norm(eyes.perclos_60s, ranges["perclos"])
            if self.blinks:
                terms["blink_duration"] = norm(statistics.fmean(ms for _, ms in self.blinks), ranges["blink_duration"])
        if slow_ratio is not None:
            terms["slow_reaction"] = norm(slow_ratio, ranges["slow_reaction"])
        self.terms = terms
        self.value = ema(self.value, weighted(terms, th("fatigue", "weights")), dt, float(th("fatigue", "ema_tau_s")))
        return self.value
