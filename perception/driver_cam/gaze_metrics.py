"""Window metrics on the stable gaze zone (AS6, AS7 lap pattern). docs/perception.md §3.4.

Rules:

* **Off-road** = any zone outside ``gaze.on_road_zones`` (``away`` included). A glance at a ``gaze.mirror_zones`` zone
  is part of driving: it counts as off-road only once it lasts longer than ``mirror_glance_max_ms``, and then from its
  start (Euro NCAP treats mirror checks as on-task).
* ``off_road_ms`` = the current continuous time away from the road (a run of glances, broken only by the road).
* ``unknown`` **freezes** the counters: it adds no time and resets nothing (a missing face is the monitoring rule's job,
  "Nu te mai văd"; an unknown zone never triggers an alert).
* ``vats_60s`` = completed off-road runs shorter than ``vats_max_glance_s`` in the last ``window_s`` (short mirror
  glances are not off-road, so they are not counted).
* ``entropy_60s`` = Shannon entropy (bits) of the time-weighted zone distribution over ``window_s``, ``unknown``
  excluded; ``None`` until there is data.
* **Lap pattern** (AS7, plan §4.A): at least ``phone.lap_pattern.min_glances`` glances at ``lap`` started in the last
  ``window_s``, or one lasting longer than ``long_glance_s``, with no hand seen in the last ``hands_recent_s``. The
  gesture model runs only inside the dialog window, so "not run" (``ff.hands is None``) counts as not seen.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from perception.config import PerceptionConfig

__all__ = ["GazeMetrics", "GazeMetricsOutput"]


@dataclass
class GazeMetricsOutput:
    off_road_ms: float = 0.0
    vats_60s: int = 0
    entropy_60s: float | None = None
    off_road_60s_ms: float = 0.0
    lap_pattern: bool = False
    glance_zone: str | None = None
    glance_ms: float = 0.0


class GazeMetrics:
    def __init__(self, cfg: PerceptionConfig) -> None:
        g = cfg.gaze
        lap = cfg.phone.lap_pattern
        self.on_road = set(g.on_road_zones)
        self.mirrors = set(g.mirror_zones)
        self.mirror_max_ms = g.mirror_glance_max_ms
        self.vats_max_ms = g.vats_max_glance_s * 1000.0
        self.window_s = g.window_s
        self.lap_min = lap.min_glances
        self.lap_window_s = lap.window_s
        self.lap_long_ms = lap.long_glance_s * 1000.0
        self.hands_recent_s = lap.hands_recent_s
        self._t_prev: float | None = None
        self._prev_known = False
        self._zone: str | None = None  # current glance (never "unknown")
        self._glance_ms = 0.0
        self._glance_contrib = 0.0  # off-road ms the current glance already added
        self._run_closed_ms = 0.0  # off-road ms of the closed glances of the current run
        self._zone_time: deque[tuple[float, str, float]] = deque()  # (t, zone, ms) for the entropy
        self._off_time: deque[tuple[float, float]] = deque()  # (t, off-road ms added)
        self._runs: deque[tuple[float, float]] = deque()  # (t_end, duration ms) of completed off-road runs
        self._lap_starts: deque[float] = deque()
        self._lap_long_until: float | None = None
        self._hands_t: float | None = None
        self.last = GazeMetricsOutput()

    def _contribution(self, zone: str | None, ms: float) -> float:
        if zone is None or zone in self.on_road:
            return 0.0
        if zone in self.mirrors:
            return ms if ms > self.mirror_max_ms else 0.0
        return ms

    def _close_glance(self, t: float, new_zone: str) -> None:
        if self._zone is None:
            return
        self._run_closed_ms += self._glance_contrib
        if new_zone in self.on_road:  # the off-road run ends
            if self._run_closed_ms > 0:
                self._runs.append((t, self._run_closed_ms))
            self._run_closed_ms = 0.0

    def update(self, t: float, zone: str, hands_seen: bool | None = None) -> GazeMetricsOutput:
        dt_ms = 0.0 if self._t_prev is None else max(0.0, (t - self._t_prev) * 1000.0)
        self._t_prev = t
        if hands_seen:
            self._hands_t = t
        known = zone != "unknown"
        if known:
            if zone != self._zone:
                self._close_glance(t, zone)
                self._zone, self._glance_ms, self._glance_contrib = zone, 0.0, 0.0
                if zone == "lap":
                    self._lap_starts.append(t)
            elif self._prev_known:
                self._glance_ms += dt_ms
                self._zone_time.append((t, zone, dt_ms))
            contrib = self._contribution(self._zone, self._glance_ms)
            if contrib > self._glance_contrib:
                self._off_time.append((t, contrib - self._glance_contrib))
                self._glance_contrib = contrib
            if zone == "lap" and self._glance_ms > self.lap_long_ms:
                self._lap_long_until = t + self.lap_window_s
        self._prev_known = known
        self._trim(t)

        counts: dict[str, float] = {}
        for _, z, ms in self._zone_time:
            counts[z] = counts.get(z, 0.0) + ms
        total = sum(counts.values())
        entropy = -sum(v / total * math.log2(v / total) for v in counts.values() if v > 0) if total > 0 else None
        hands_recent = self._hands_t is not None and t - self._hands_t <= self.hands_recent_s
        lap_long = self._lap_long_until is not None and t <= self._lap_long_until
        lap = not hands_recent and (len(self._lap_starts) >= self.lap_min or lap_long)
        self.last = GazeMetricsOutput(
            off_road_ms=round(self._run_closed_ms + self._glance_contrib, 1) if self._zone not in self.on_road else 0.0,
            vats_60s=sum(1 for _, ms in self._runs if ms < self.vats_max_ms),
            entropy_60s=round(entropy, 3) if entropy is not None else None,
            off_road_60s_ms=round(sum(ms for _, ms in self._off_time), 1),
            lap_pattern=lap,
            glance_zone=self._zone,
            glance_ms=round(self._glance_ms, 1),
        )
        return self.last

    def _trim(self, t: float) -> None:
        for q, horizon in (
            (self._zone_time, self.window_s),
            (self._off_time, self.window_s),
            (self._runs, self.window_s),
        ):
            while q and t - q[0][0] > horizon:
                q.popleft()
        while self._lap_starts and t - self._lap_starts[0] > self.lap_window_s:
            self._lap_starts.popleft()
