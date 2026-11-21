"""B2: disengagement D = 0.30·slow reaction + 0.25·(1 - gaze entropy) + 0.20·low response rate + 0.15·short answers
+ 0.10·monotony (thresholds.yaml ``disengagement``), smoothed with ``ema_tau_s``.

**D only counts when F is low and the context is monotonous** (plan B2): demanding traffic also lowers the gaze
entropy (Victor et al., 2005), and a tired driver needs a break, not music. Outside that context D decays to 0.
Monotonous = ``trip.road`` in ``monotony.roads`` for ``monotony.min_minutes`` of trip time with the speed's standard
deviation under ``max_speed_std_kmh`` (trip time follows the director's time scale).
"""

from __future__ import annotations

import statistics
from collections import deque

from core.scoring.common import ema, norm, weighted
from core.settings import th
from shared.contracts import State


class DisengagementScore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.value = 0.0
        self.terms: dict[str, float] = {}
        self.monotonous = False
        self.last_t: float | None = None
        self.trip: deque[tuple[float, float, str]] = deque()  # (elapsed_min, speed, road)

    def _monotony(self, state: State) -> bool:
        trip = state.trip
        if self.trip and trip.elapsed_min < self.trip[-1][0]:  # a new trip (reset): start over
            self.trip.clear()
        if self.trip and trip.elapsed_min == self.trip[-1][0]:  # trip time not moving (parked): one sample
            self.trip[-1] = (trip.elapsed_min, trip.speed_kmh, trip.road)
        else:
            self.trip.append((trip.elapsed_min, trip.speed_kmh, trip.road))
        span = float(th("disengagement", "monotony", "min_minutes"))
        while len(self.trip) > 1 and self.trip[1][0] <= trip.elapsed_min - span:
            self.trip.popleft()
        if trip.elapsed_min - self.trip[0][0] < span:
            return False
        roads = set(th("disengagement", "monotony", "roads"))
        speeds = [speed for _, speed, _ in self.trip]
        steady = statistics.pstdev(speeds) <= float(th("disengagement", "monotony", "max_speed_std_kmh"))
        return steady and all(road in roads for _, _, road in self.trip) and min(speeds) > 0

    def update(self, state: State, now: float, slow_ratio: float | None, response_rate: float | None,
               mean_words: float | None, fatigue: float) -> float:
        dt = 0.0 if self.last_t is None else now - self.last_t
        self.last_t = now
        self.monotonous = self._monotony(state)
        ranges = th("disengagement", "norm")
        terms = {"monotony": 1.0 if self.monotonous else 0.0}
        if slow_ratio is not None:
            terms["slow_reaction"] = norm(slow_ratio, ranges["slow_reaction"])
        entropy = state.driver.gaze.entropy_60s
        if state.safety.monitoring_ok and entropy is not None:
            terms["low_entropy"] = norm(entropy, ranges["low_entropy"])
        if response_rate is not None:
            terms["low_response_rate"] = norm(response_rate, ranges["low_response_rate"])
        if mean_words is not None:
            terms["short_answers"] = norm(mean_words, ranges["short_answers"])
        self.terms = terms
        counts = self.monotonous and fatigue < float(th("disengagement", "max_fatigue"))
        target = weighted(terms, th("disengagement", "weights")) if counts else 0.0
        self.value = ema(self.value, target, dt, float(th("disengagement", "ema_tau_s")))
        return self.value
