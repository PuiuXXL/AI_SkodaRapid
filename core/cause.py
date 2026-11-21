"""B4: the cause of the distraction, fused from the two cameras and the context (one of the 3 innovations).

The driver camera says where the driver looks (glances = entries into a zone, counted over ``cause.window_s``); the
passenger camera says what the person there is doing; the context adds the messages and the declared rear seat.
In order of priority:

* ``passenger_showing_phone``: >= ``passenger_glances_min`` glances at ``passenger`` AND the passenger held a phone in
  the window (``passenger.holding_phone``, passenger camera);
* ``passenger_talk``: the same glances AND the passenger spoke in the window (``passenger.speaking``);
* ``incoming_message``: a message arrived in the last ``message_window_s`` AND the driver took the phone or glanced
  at the lap since;
* ``phone``: the driver's phone in hand (no message behind it);
* ``child_activity``: >= ``passenger_glances_min`` glances at ``rear_seat`` with a child declared in the back.

The label is kept ``hold_s`` after its evidence stops. The passenger glances are kept longer than the window: the
intervention tracker (D6) compares them before and after a remedy.
"""

from __future__ import annotations

from collections import deque

from core.settings import th
from shared.contracts import Cause, State

TRACKED_ZONES = ("passenger", "rear_seat", "lap")
PASSENGER_ID = 2


class CauseDetector:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.glances: dict[str, deque[float]] = {zone: deque() for zone in TRACKED_ZONES}
        self.zone: str | None = None
        self.phone_seen_at: float | None = None
        self.talk_seen_at: float | None = None
        self.current: Cause | None = None
        self.evidence_at = 0.0

    def count(self, zone: str, since: float, until: float | None = None) -> int:
        """Glances into ``zone`` started in ``[since, until]``."""
        return sum(1 for t in self.glances[zone] if t >= since and (until is None or t <= until))

    def _track(self, state: State, now: float) -> None:
        gaze = state.driver.gaze
        zone: str | None = gaze.zone if state.safety.monitoring_ok else None
        if zone == "unknown":
            zone = self.zone  # P1: unknown freezes, it does not end a glance
        elif zone is not None and gaze.conf < float(th("safety", "min_gaze_conf")):
            zone = None
        if zone in TRACKED_ZONES and zone != self.zone:
            self.glances[zone].append(now)
        self.zone = zone
        keep = max(float(th("cause", "window_s")),
                   float(th("intervention", "before_s")) + float(th("intervention", "after_s"))) + 5.0
        for queue in self.glances.values():
            while queue and queue[0] < now - keep:
                queue.popleft()
        if state.passenger.present and state.passenger.holding_phone:
            self.phone_seen_at = now
        if state.passenger.present and state.passenger.speaking:
            self.talk_seen_at = now

    def _candidate(self, state: State, now: float) -> Cause | None:
        window = float(th("cause", "window_s"))
        since = now - window

        def recent(t: float | None) -> bool:
            return t is not None and t >= since

        passenger = self.count("passenger", since)
        both_cameras = ["cam_driver", "cam_passenger"]
        present = state.passenger.present
        if present and passenger >= int(th("cause", "passenger_glances_min")) and recent(self.phone_seen_at):
            return Cause(target="passenger", person_id=PASSENGER_ID, label="passenger_showing_phone",
                         glances_30s=passenger, conf=_conf(passenger), sources=both_cameras)
        if present and passenger >= int(th("cause", "passenger_talk_glances_min")) and recent(self.talk_seen_at):
            return Cause(target="passenger", person_id=PASSENGER_ID, label="passenger_talk",
                         glances_30s=passenger, conf=_conf(passenger), sources=both_cameras)
        arrived = max((m.ts or 0.0 for m in state.messages), default=0.0)
        if arrived and now - arrived <= float(th("cause", "message_window_s")):
            took_it = state.driver.phone.in_use or self.count("lap", arrived) > 0
            if took_it:
                return Cause(target="phone", label="incoming_message", glances_30s=self.count("lap", arrived),
                             conf=0.8, sources=["cam_driver", "phone"])
        if state.driver.phone.in_use:
            return Cause(target="phone", label="phone", glances_30s=self.count("lap", since),
                         conf=round(state.driver.phone.conf, 2), sources=["cam_driver"])
        rear = self.count("rear_seat", since)
        child = next((o for o in state.occupants if o.seat == "rear" and o.role == "child"), None)
        if child is not None and rear >= int(th("cause", "passenger_glances_min")):
            return Cause(target="rear", person_id=child.id, label="child_activity", glances_30s=rear,
                         conf=_conf(rear), sources=["cam_driver", "declared"])
        return None

    def update(self, state: State, now: float) -> str | None:
        """Update ``state.cause``; returns the label when a new cause starts, else None."""
        self._track(state, now)
        candidate = self._candidate(state, now)
        previous = self.current.label if self.current else None
        if candidate is not None:
            self.current, self.evidence_at = candidate, now
        elif self.current is not None and now - self.evidence_at > float(th("cause", "hold_s")):
            self.current = None
        state.cause = self.current.model_copy() if self.current else Cause()
        label = self.current.label if self.current else None
        return label if label and label != previous else None


def _conf(glances: int) -> float:
    """More glances, more confidence: 0.6 at the minimum, +0.1 per extra glance, at most 0.95."""
    return round(min(0.95, 0.6 + 0.1 * (glances - int(th("cause", "passenger_glances_min")))), 2)
