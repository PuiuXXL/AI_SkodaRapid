"""AS13 (S): a look towards the rear seat.

The face tracker loses the face once the driver turns far enough to look behind. The rule (plan §4.A AS13): the face
is lost right after a large yaw that was growing towards the passenger side -> zone ``rear_seat`` (``gaze.source =
"body"``) for at most ``max_s``. A face lost without that turn (a hand in front of the lens, leaning out of the
image) is not a rear glance. Thresholds: ``gaze.rear_seat`` in perception.yaml; switch: ``demo.rear_seat``.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RearGlanceConfig:
    min_yaw_deg: float = 35.0  # |yaw| towards the passenger side on the last frames before the face is lost
    min_rise_deg: float = 10.0  # ... and still growing by this much over rising_s (a turn, not a held pose)
    rising_s: float = 0.6
    max_gap_s: float = 0.3  # the last face frame must be this recent when the face goes
    max_s: float = 3.0  # rear_seat reported at most this long (then unknown until the face is back)
    right_sign: float = -1.0  # sign of the raw yaw when the head turns right (towards the passenger)


class RearGlance:
    def __init__(self, cfg: RearGlanceConfig | None = None, enabled: bool = True) -> None:
        self.cfg = cfg or RearGlanceConfig()
        self.enabled = enabled
        self._hist: deque[tuple[float, float]] = deque()  # (t, yaw towards the passenger side)
        self._since: float | None = None  # rear glance start; -inf = face lost without the turn

    def update(self, t: float, face_present: bool, raw_yaw: float | None) -> bool:
        """True while the driver looks towards the rear seat."""
        if not self.enabled:
            return False
        c = self.cfg
        if face_present and raw_yaw is not None:
            self._since = None
            self._hist.append((t, raw_yaw * c.right_sign))
            while self._hist and t - self._hist[0][0] > c.rising_s:
                self._hist.popleft()
            return False
        if self._since is None:  # the face has just gone: was it a growing turn to the right?
            turned = (
                bool(self._hist)
                and t - self._hist[-1][0] <= c.max_gap_s
                and self._hist[-1][1] >= c.min_yaw_deg
                and self._hist[-1][1] - min(y for _, y in self._hist) >= c.min_rise_deg
            )
            self._since = t if turned else -math.inf
            self._hist.clear()
        return t - self._since <= c.max_s
