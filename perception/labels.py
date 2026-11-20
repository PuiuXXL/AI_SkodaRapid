"""Ground-truth labels pressed live during a recording session, aligned to the FeatureFrame clock.

Keys (see :data:`KEYS`):
  b       blink                (instant)
  c       eyes closed          (toggle: press at start, press again at end)
  y       yawn                 (toggle)
  s       speaking             (toggle)
  p       phone in use         (toggle)
  z<n>    gaze zone n          (state until the next z<n>; z0 clears it). n = 1-based index in ``gaze.zones``

The file is JSONL: a ``meta`` line, then one :class:`LabelEvent` per line. ``t`` is seconds since the session start,
the same clock as ``FeatureFrame.t``, so labels and frames align directly (:func:`align`).
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Literal

import orjson
from pydantic import BaseModel, ConfigDict

__all__ = [
    "KEYS",
    "Interval",
    "KeyLabeler",
    "LabelEvent",
    "LabelWriter",
    "align",
    "load_labels",
    "to_intervals",
]

KEYS: dict[str, tuple[str, Literal["instant", "toggle"]]] = {
    "b": ("blink", "instant"),
    "c": ("eyes_closed", "toggle"),
    "y": ("yawn", "toggle"),
    "s": ("speaking", "toggle"),
    "p": ("phone", "toggle"),
}
ZONE_KEY = "z"
ZONE_LABEL = "zone"


class LabelEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    t: float
    label: str
    kind: Literal["instant", "start", "end", "state"]
    value: str | None = None  # zone name for kind="state" (None = zone cleared)


class LabelWriter:
    """Appends label events to a JSONL file (meta line first)."""

    def __init__(self, path: str | Path, meta: dict[str, Any]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: IO[bytes] = self.path.open("wb")
        self._fh.write(orjson.dumps({"type": "meta", **meta}) + b"\n")
        self.count = 0

    def write(self, event: LabelEvent) -> None:
        self._fh.write(orjson.dumps({"type": "label", **event.model_dump()}) + b"\n")
        self._fh.flush()  # labels are few and precious: never lose them on a crash
        self.count += 1

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> LabelWriter:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()


class KeyLabeler:
    """Turns key presses into label events (independent of any UI, so it can be tested)."""

    def __init__(
        self,
        writer: LabelWriter | None,
        zones: Sequence[str],
        *,
        zone_timeout_s: float = 1.5,
        repeat_guard_s: float = 0.6,
    ) -> None:
        self._writer = writer
        self._zones = list(zones)
        self._zone_timeout_s = zone_timeout_s
        # Holding a key makes the OS auto-repeat it (first repeat after ~0.5 s, then every ~30 ms). Without a guard a
        # held "c" flips eyes_closed start/end many times. A key seen again within repeat_guard_s of its previous
        # occurrence (pressed or repeated) is ignored: press briefly, do not hold.
        self._repeat_guard_s = repeat_guard_s
        self._last_seen: dict[str, float] = {}
        self._pending_zone_t: float | None = None
        self.active: set[str] = set()
        self.zone: str | None = None
        self.events: list[LabelEvent] = []

    def on_key(self, key: str, t: float) -> str | None:
        """Handle one key at session time ``t``. Returns a short description, or None if the key was ignored."""
        previous = self._last_seen.get(key)
        self._last_seen[key] = t
        if previous is not None and t - previous < self._repeat_guard_s:
            return None  # auto-repeat of a held key
        if self._pending_zone_t is not None:
            pending, self._pending_zone_t = self._pending_zone_t, None
            if key.isdigit() and t - pending <= self._zone_timeout_s:
                n = int(key)
                if n == 0:
                    self._emit(LabelEvent(t=t, label=ZONE_LABEL, kind="state", value=None))
                    self.zone = None
                    return "zone cleared"
                if 1 <= n <= len(self._zones):
                    self.zone = self._zones[n - 1]
                    self._emit(LabelEvent(t=t, label=ZONE_LABEL, kind="state", value=self.zone))
                    return f"zone = {self.zone}"
                return None
            # not a digit (or too late): fall through and treat the key normally
        if key == ZONE_KEY:
            self._pending_zone_t = t
            return "zone: press 1-9 (0 clears)"
        if key not in KEYS:
            return None
        label, kind = KEYS[key]
        if kind == "instant":
            self._emit(LabelEvent(t=t, label=label, kind="instant"))
            return label
        if label in self.active:
            self.active.discard(label)
            self._emit(LabelEvent(t=t, label=label, kind="end"))
            return f"{label} end"
        self.active.add(label)
        self._emit(LabelEvent(t=t, label=label, kind="start"))
        return f"{label} start"

    def finish(self, t: float) -> None:
        """Close any toggle still open and the current zone at the end of the session."""
        for label in sorted(self.active):
            self._emit(LabelEvent(t=t, label=label, kind="end"))
        self.active.clear()
        if self.zone is not None:
            self._emit(LabelEvent(t=t, label=ZONE_LABEL, kind="state", value=None))
            self.zone = None

    def _emit(self, event: LabelEvent) -> None:
        self.events.append(event)
        if self._writer is not None:
            self._writer.write(event)


def load_labels(path: str | Path) -> tuple[dict[str, Any], list[LabelEvent]]:
    meta: dict[str, Any] = {}
    events: list[LabelEvent] = []
    with Path(path).open("rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = orjson.loads(line)
            kind = record.pop("type", None)
            if kind == "meta":
                meta = record
            elif kind == "label":
                events.append(LabelEvent.model_validate(record))
    return meta, events


@dataclass(frozen=True)
class Interval:
    label: str
    start: float
    end: float  # == start for instant events
    value: str | None = None


def to_intervals(events: Iterable[LabelEvent], t_end: float | None = None) -> list[Interval]:
    """Pair start/end events, turn zone states into intervals, keep instants as zero-length intervals.

    An unmatched start is closed at ``t_end`` (or dropped if ``t_end`` is None).
    """
    ordered = sorted(events, key=lambda e: e.t)
    intervals: list[Interval] = []
    open_starts: dict[str, float] = {}
    zone: tuple[str, float] | None = None
    for event in ordered:
        if event.kind == "instant":
            intervals.append(Interval(event.label, event.t, event.t))
        elif event.kind == "start":
            open_starts.setdefault(event.label, event.t)
        elif event.kind == "end":
            start = open_starts.pop(event.label, None)
            if start is not None:
                intervals.append(Interval(event.label, start, event.t))
        elif event.kind == "state":
            if zone is not None:
                intervals.append(Interval(event.label, zone[1], event.t, zone[0]))
            zone = (event.value, event.t) if event.value is not None else None
    if t_end is not None:
        for label, start in open_starts.items():
            intervals.append(Interval(label, start, t_end))
        if zone is not None:
            intervals.append(Interval(ZONE_LABEL, zone[1], t_end, zone[0]))
    return sorted(intervals, key=lambda i: (i.start, i.label))


def align(intervals: Iterable[Interval], frame_times: Sequence[float]) -> list[tuple[Interval, range]]:
    """For each interval, the indices of the frames it covers (``frame_times`` sorted ascending).

    Instant events map to the single nearest frame. Intervals with no frame inside map to an empty range.
    """
    times = list(frame_times)
    result: list[tuple[Interval, range]] = []
    for interval in intervals:
        if not times:
            result.append((interval, range(0)))
            continue
        if interval.end == interval.start:
            i = bisect.bisect_left(times, interval.start)
            candidates = [j for j in (i - 1, i) if 0 <= j < len(times)]
            nearest = min(candidates, key=lambda j: abs(times[j] - interval.start))
            result.append((interval, range(nearest, nearest + 1)))
            continue
        lo = bisect.bisect_left(times, interval.start)
        hi = bisect.bisect_right(times, interval.end)
        result.append((interval, range(lo, hi)))
    return result
