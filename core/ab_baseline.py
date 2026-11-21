"""B8: the simple threshold running next to DriveMate, for the live counter "prag simplu: N · DriveMate: M" (H4).

The naive detector uses the same perception, with fixed thresholds and none of DriveMate's knowledge (no gaze
zones, no calibration, no context, no speed): the head turned or tilted past ``ab_baseline.yaw_deg / pitch_deg`` for
``min_ms`` (a mirror check counts), the eyes closed for ``closed_ms``, any phone seen by the driver camera (the
passenger's too, G5). One naive alert per episode, at most one per ``cooldown_s``.

DriveMate's own alerts are counted by the rules that raise them (:meth:`AbBaseline.our_alert`): a distraction
episode (C2) and a microsleep alarm (C3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.settings import template, th
from shared.contracts import State

if TYPE_CHECKING:
    from core.engine import Engine


class AbBaseline:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.naive = 0
        self.ours = 0
        self.head_since: float | None = None
        self.armed = {"head_pose": True, "eyes_closed": True, "phone": True}
        self.last_naive = float("-inf")

    def our_alert(self, now: float, kind: str) -> None:
        self.ours += 1
        self.engine.state.ab.our_alerts = self.ours

    def _naive(self, reason: str, now: float) -> None:
        self.armed[reason] = False
        if now - self.last_naive < float(th("ab_baseline", "cooldown_s")):
            return  # the same episode seen by another threshold
        self.naive += 1
        self.last_naive = now
        self.engine.state.ab.naive_alerts = self.naive
        self.engine.log_event("naive_alert", now, source=None, text=str(template("naive", reason)), reason=reason)

    def _edge(self, reason: str, active: bool, now: float) -> None:
        if not active:
            self.armed[reason] = True
        elif self.armed[reason]:
            self._naive(reason, now)

    def tick(self, state: State, now: float) -> None:
        driver = state.driver
        yaw, pitch = driver.head.yaw, driver.head.pitch
        turned = yaw is not None and pitch is not None and (
            abs(yaw) > float(th("ab_baseline", "yaw_deg")) or abs(pitch) > float(th("ab_baseline", "pitch_deg")))
        if turned:
            self.head_since = now if self.head_since is None else self.head_since
        else:
            self.head_since = None
        long_enough = self.head_since is not None and (now - self.head_since) * 1000.0 >= float(
            th("ab_baseline", "min_ms"))
        self._edge("head_pose", long_enough, now)

        closed = driver.eyes.reliable and driver.eyes.closed_ms >= float(th("ab_baseline", "closed_ms"))
        self._edge("eyes_closed", closed, now)

        phone = driver.phone.in_use or (bool(th("ab_baseline", "any_phone")) and driver.phone.foreign_seen)
        self._edge("phone", phone, now)

        state.ab.naive_alerts = self.naive
        state.ab.our_alerts = self.ours
