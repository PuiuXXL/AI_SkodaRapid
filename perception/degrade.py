"""Degradation rule (plan §8.9, docs/perception.md §2): keep the end-to-end latency under control.

If the end-to-end p95 goes above ``rates.degrade_e2e_p95_ms``:
1. lower the **passenger camera** face rate first (step by step, down to ``degrade_min_passenger_face_hz``);
2. then the **YOLO** (phone) rate on both cameras (down to ``degrade_min_phone_hz``).
The **driver face is never degraded** (it is the safety camera, plan §8 "Fața șoferului nu se degradează niciodată").

Recovery goes the other way (YOLO first, then the passenger) once p95 < ``degrade_recover_ratio`` x the limit.
At least ``degrade_hold_s`` between two steps, so the controller does not oscillate.
"""

from __future__ import annotations

from dataclasses import dataclass

from perception.config import RatesConfig

__all__ = ["DegradeController", "Rates"]


@dataclass(frozen=True)
class Rates:
    passenger_face_hz: float
    phone_hz: float
    level: int  # 0 = nominal; each step adds 1


class DegradeController:
    def __init__(self, cfg: RatesConfig) -> None:
        self.cfg = cfg
        self._passenger_steps = self._steps(cfg.passenger_face_hz, cfg.degrade_min_passenger_face_hz)
        self._phone_steps = self._steps(cfg.phone_hz, cfg.degrade_min_phone_hz)
        self.level = 0
        self._last_change: float | None = None

    def _steps(self, nominal: float, minimum: float) -> int:
        n, rate = 0, nominal
        while rate * self.cfg.degrade_step >= minimum - 1e-9:
            rate *= self.cfg.degrade_step
            n += 1
        return n

    @property
    def max_level(self) -> int:
        return self._passenger_steps + self._phone_steps

    @property
    def rates(self) -> Rates:
        p_steps = min(self.level, self._passenger_steps)
        y_steps = max(0, self.level - self._passenger_steps)
        return Rates(
            passenger_face_hz=round(self.cfg.passenger_face_hz * self.cfg.degrade_step**p_steps, 3),
            phone_hz=round(self.cfg.phone_hz * self.cfg.degrade_step**y_steps, 3),
            level=self.level,
        )

    def update(self, now: float, e2e_p95_ms: float | None) -> Rates | None:
        """Feed the current p95; returns the new rates when they change, else None."""
        if e2e_p95_ms is None or e2e_p95_ms != e2e_p95_ms:  # None / NaN: not enough data yet
            return None
        if self._last_change is not None and now - self._last_change < self.cfg.degrade_hold_s:
            return None
        limit = self.cfg.degrade_e2e_p95_ms
        if e2e_p95_ms > limit and self.level < self.max_level:
            self.level += 1
        elif e2e_p95_ms < self.cfg.degrade_recover_ratio * limit and self.level > 0:
            self.level -= 1
        else:
            return None
        self._last_change = now
        return self.rates
