"""Gaze zones as angular boxes around the driver's own road direction (``gaze.mode: boxes``).

Why: the per-driver kNN (gaze_zones.ZoneModel) rejected most real glances as ``unknown`` whenever the calibration was
weak (head barely turned, face too small): "off-road" while looking ahead. A driver does not stare at one point
through the windscreen, so the road gets a WIDE box and every other zone a generous one:

* direction = MobileGaze yaw / pitch (eyes + head) when fresh, else the head angles;
* road centre = the median direction over ``center_window_s`` (the driver looks at the road most of the time), so it
  needs no calibration and follows a camera that is not straight in front;
* boxes ``[yaw_lo, yaw_hi, pitch_lo, pitch_hi]`` in degrees from that centre, in the DRIVER's terms (yaw > 0 = towards
  the passenger, pitch > 0 = up); ``right_sign`` maps them to the camera's raw yaw sign. The first box that contains
  the direction wins (road first);
* outside every box but within ``margin_deg`` of one -> that zone (lower confidence); far to the side -> ``away``;
  otherwise ``unknown`` (never an alert).
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from perception.driver_cam.gaze_zones import ZoneResult

INSIDE_CONF = 0.85
MARGIN_CONF = 0.6


@dataclass(frozen=True)
class Box:
    zone: str
    yaw: tuple[float, float]
    pitch: tuple[float, float]

    def distance(self, yaw: float, pitch: float) -> float:
        """0 inside, else the angular distance (deg) to the box edge."""
        dy = max(self.yaw[0] - yaw, 0.0, yaw - self.yaw[1])
        dp = max(self.pitch[0] - pitch, 0.0, pitch - self.pitch[1])
        return math.hypot(dy, dp)


class BoxClassifier:
    def __init__(
        self,
        zones: Mapping[str, Sequence[float]],
        *,
        margin_deg: float = 8.0,
        right_sign: float = -1.0,
        center_window_s: float = 60.0,
        center_min_s: float = 2.0,
        away_beyond_deg: float = 80.0,
    ) -> None:
        self.boxes = [Box(z, (float(v[0]), float(v[1])), (float(v[2]), float(v[3]))) for z, v in zones.items()]
        self.margin_deg = margin_deg
        self.right_sign = right_sign
        self.center_window_s = center_window_s
        self.center_min_s = center_min_s
        self.away_beyond_deg = away_beyond_deg
        self._hist: deque[tuple[float, float, float]] = deque()  # (t, raw yaw, raw pitch)
        self.center: tuple[float, float] | None = None

    @property
    def ready(self) -> bool:
        return self.center is not None

    def _update_center(self, t: float, yaw: float, pitch: float) -> None:
        self._hist.append((t, yaw, pitch))
        while self._hist and t - self._hist[0][0] > self.center_window_s:
            self._hist.popleft()
        if self._hist[-1][0] - self._hist[0][0] >= self.center_min_s:
            self.center = (statistics.median(h[1] for h in self._hist), statistics.median(h[2] for h in self._hist))

    def classify(self, t: float, yaw: float, pitch: float) -> ZoneResult | None:
        """Zone of one raw (camera) direction; None until the road centre is known."""
        self._update_center(t, yaw, pitch)
        if self.center is None:
            return None
        dyaw = (yaw - self.center[0]) * self.right_sign  # driver's terms: > 0 = towards the passenger
        dpitch = pitch - self.center[1]
        for box in self.boxes:
            if box.distance(dyaw, dpitch) == 0.0:
                return ZoneResult(box.zone, INSIDE_CONF, 0.0, box.zone)
        nearest = min(self.boxes, key=lambda b: b.distance(dyaw, dpitch))
        dist = nearest.distance(dyaw, dpitch)
        if dist <= self.margin_deg:
            return ZoneResult(nearest.zone, MARGIN_CONF, round(dist, 2), nearest.zone)
        if abs(dyaw) >= self.away_beyond_deg:
            return ZoneResult("away", 0.0, round(dist, 2), nearest.zone)
        return ZoneResult("unknown", 0.0, round(dist, 2), nearest.zone)
