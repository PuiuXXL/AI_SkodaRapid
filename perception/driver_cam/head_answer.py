"""Yes / no answer from the head (AS8), only while core's dialog window is open.

Standalone module: configuration in :class:`HeadAnswerConfig` (defaults = ``perception/config/pending/modules.yaml``,
section ``head_answer``), input = yaw / pitch in degrees (driver convention, ``perception/driver_cam/head.py``) and
whether the eyes are open, output = :class:`HeadAnswerResult`.

Method (plan AS8, docs/perception.md §3.3):

1. A slow mean (EMA, time constant ``slow_tau_s``) runs on yaw and pitch on **every** frame, so it is settled when
   the window opens; it is subtracted from the angles (detrending).
2. Zero crossings of the detrended signal are counted with a Schmitt trigger at +-``min_amplitude_deg / 2``: a
   crossing needs the head to swing by at least ``min_amplitude_deg`` peak to peak.
3. ``>= min_crossings`` crossings within ``window_s`` -> **pitch = "yes"**, **yaw = "no"**; when both axes oscillate,
   the answer axis needs ``dominance_ratio`` x the RMS of the other.

Why it ignores what it must ignore:

* a slow head drop or a single turn (mirror check): after a step, the EMA approaches the new angle monotonically, so the
  detrended signal decays towards zero without crossing it -> at most one crossing;
* a fatigue nod comes with the eyes closing: frames with the eyes closed are skipped, and a closure longer than
  ``max_closed_ms`` resets the count (a blink in the middle of a nod does not);
* outside the window nothing is counted; at ``until`` the detector closes and resets.

``eyes_open=None`` (eye state unknown, e.g. ``eyes.reliable = false``) is treated as open: head metrics are what
remains trusted then (docs/perception.md §7). Feed **unfiltered** angles (``DriverHead.raw_yaw / raw_pitch``): the
head One Euro filter is tuned for jitter at rest and damps 2-3 Hz nods.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any, Literal

__all__ = ["Answer", "HeadAnswerConfig", "HeadAnswerDetector", "HeadAnswerResult"]

Answer = Literal["yes", "no"]


@dataclass(frozen=True)
class HeadAnswerConfig:
    slow_tau_s: float = 1.0
    min_amplitude_deg: float = 6.0
    min_crossings: int = 2
    window_s: float = 1.2
    dominance_ratio: float = 1.5
    max_closed_ms: float = 400.0
    answer_hold_s: float = 1.5
    max_gap_s: float = 0.25

    def __post_init__(self) -> None:
        if self.slow_tau_s <= 0 or self.window_s <= 0 or self.max_gap_s <= 0:
            raise ValueError("head_answer: slow_tau_s, window_s and max_gap_s must be > 0")
        if self.min_amplitude_deg <= 0:
            raise ValueError("head_answer.min_amplitude_deg must be > 0")
        if not 1 <= self.min_crossings <= 10:
            raise ValueError("head_answer.min_crossings must be 1..10")
        if self.dominance_ratio < 1.0:
            raise ValueError("head_answer.dominance_ratio must be >= 1")
        if self.max_closed_ms < 0 or self.answer_hold_s < 0:
            raise ValueError("head_answer: max_closed_ms and answer_hold_s must be >= 0")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> HeadAnswerConfig:
        unknown = sorted(set(data) - {f.name for f in fields(cls)})
        if unknown:
            raise ValueError(f"HeadAnswerConfig: unknown keys {unknown}")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class HeadAnswerResult:
    answer: Answer | None = None
    active: bool = False  # the dialog window is open for this seat
    crossings_pitch: int = 0  # within window_s
    crossings_yaw: int = 0
    rms_pitch: float = 0.0  # detrended RMS over window_s, degrees
    rms_yaw: float = 0.0
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _Axis:
    """Slow mean + Schmitt-trigger zero crossings for one angle."""

    def __init__(self) -> None:
        self.mean: float | None = None
        self.state = 0  # -1 / 0 / +1: side of the slow mean the angle was last seen on (0 = not yet)
        self.crossings: deque[float] = deque()

    def reset_count(self) -> None:
        self.state = 0
        self.crossings.clear()

    def reset(self) -> None:
        self.mean = None
        self.reset_count()

    def detrend(self, value: float, dt: float, tau: float) -> float:
        if self.mean is None:
            self.mean = value
        else:
            self.mean += (1.0 - math.exp(-dt / tau)) * (value - self.mean)
        return value - self.mean

    def count(self, t: float, x: float, half_amplitude: float) -> None:
        side = 1 if x >= half_amplitude else -1 if x <= -half_amplitude else 0
        if side == 0:
            return
        if self.state != 0 and side != self.state:
            self.crossings.append(t)
        self.state = side

    def trim(self, t: float, window_s: float) -> int:
        while self.crossings and t - self.crossings[0] > window_s:
            self.crossings.popleft()
        return len(self.crossings)


class HeadAnswerDetector:
    """AS8 for one seat. Call :meth:`update` on every frame; open / close the window with :meth:`open_window`.

    Args:
        cfg: module configuration.
        seat: ``"driver"`` or ``"passenger"``: the window's ``to`` must name it (or be ``None``).
        person_id: ``occupants[].id`` of the person on this seat, when core addresses the window by id.
    """

    def __init__(self, cfg: HeadAnswerConfig | None = None, seat: str = "driver", person_id: int | None = None) -> None:
        self.cfg = cfg or HeadAnswerConfig()
        self.seat = seat
        self.person_id = person_id
        self._yaw = _Axis()
        self._pitch = _Axis()
        self._open = False
        self._until: float | None = None
        self._last_t: float | None = None
        self._closed_since: float | None = None
        self._answer: Answer | None = None
        self._answer_t = 0.0
        self._history: deque[tuple[float, float, float]] = deque()  # (t, detrended yaw, detrended pitch)

    # --- dialog window -------------------------------------------------------------------------------------

    def open_window(self, open: bool, to: str | int | None = None, until: float | None = None) -> bool:
        """Apply a ``dialog_window`` command; returns whether the window is now open for this seat.

        ``until`` is on the same clock as the ``t`` given to :meth:`update` (``None`` = until closed).
        """
        addressed = to is None or to == self.seat or (self.person_id is not None and to == self.person_id)
        self._open = bool(open and addressed)
        self._until = until if self._open else None
        self._clear_count()
        return self._open

    def is_open(self, t: float) -> bool:
        if self._open and self._until is not None and t >= self._until:
            self._open = False
            self._until = None
            self._clear_count()
        return self._open

    # --- per frame -----------------------------------------------------------------------------------------

    def update(
        self, t: float, yaw: float | None, pitch: float | None, eyes_open: bool | None = True
    ) -> HeadAnswerResult:
        t0 = time.perf_counter()
        cfg = self.cfg
        active = self.is_open(t)
        if yaw is None or pitch is None:
            if self._last_t is not None and t - self._last_t > cfg.max_gap_s:
                self._reset()
            return self._result(t, active, t0)
        if eyes_open is False:
            # skipped (the closed-eye head drop must not enter the mean or the count), but the face is still tracked
            self._closed_since = self._closed_since if self._closed_since is not None else t
            if (t - self._closed_since) * 1000.0 > cfg.max_closed_ms:
                self._clear_count()
            self._last_t = t
            return self._result(t, active, t0)
        self._closed_since = None

        dt = 0.0 if self._last_t is None else t - self._last_t
        if self._last_t is not None and dt > cfg.max_gap_s:
            self._reset()
            dt = 0.0
        self._last_t = t
        dyaw = self._yaw.detrend(yaw, dt, cfg.slow_tau_s)
        dpitch = self._pitch.detrend(pitch, dt, cfg.slow_tau_s)
        if not active:
            return self._result(t, active, t0)

        if self._answer is not None:
            if t - self._answer_t < cfg.answer_hold_s:
                return self._result(t, active, t0)
            self._answer = None
            self._clear_count()

        half = cfg.min_amplitude_deg / 2.0
        self._yaw.count(t, dyaw, half)
        self._pitch.count(t, dpitch, half)
        self._history.append((t, dyaw, dpitch))
        while self._history and t - self._history[0][0] > cfg.window_s:
            self._history.popleft()
        n_yaw = self._yaw.trim(t, cfg.window_s)
        n_pitch = self._pitch.trim(t, cfg.window_s)
        rms_yaw, rms_pitch = self._rms()
        candidates: list[Answer] = []
        if n_pitch >= cfg.min_crossings:
            candidates.append("yes")
        if n_yaw >= cfg.min_crossings:
            candidates.append("no")
        for answer in candidates:
            if self._dominant(answer, rms_yaw, rms_pitch):
                self._answer, self._answer_t = answer, t
                break
        return self._result(t, active, t0)

    # --- internals -----------------------------------------------------------------------------------------

    def _dominant(self, answer: Answer, rms_yaw: float, rms_pitch: float) -> bool:
        """The answer axis must dominate the other one by ``dominance_ratio`` (diagonal / circular moves: none)."""
        ratio = self.cfg.dominance_ratio
        return rms_pitch >= ratio * rms_yaw if answer == "yes" else rms_yaw >= ratio * rms_pitch

    def _rms(self) -> tuple[float, float]:
        if not self._history:
            return 0.0, 0.0
        n = len(self._history)
        return (
            math.sqrt(sum(h[1] * h[1] for h in self._history) / n),
            math.sqrt(sum(h[2] * h[2] for h in self._history) / n),
        )

    def _clear_count(self) -> None:
        self._yaw.reset_count()
        self._pitch.reset_count()
        self._history.clear()
        self._answer = None

    def _reset(self) -> None:
        self._yaw.reset()
        self._pitch.reset()
        self._history.clear()
        self._answer = None
        self._last_t = None

    def _result(self, t: float, active: bool, t0: float) -> HeadAnswerResult:
        rms_yaw, rms_pitch = self._rms() if active else (0.0, 0.0)
        return HeadAnswerResult(
            answer=self._answer if active else None,
            active=active,
            crossings_pitch=self._pitch.trim(t, self.cfg.window_s) if active else 0,
            crossings_yaw=self._yaw.trim(t, self.cfg.window_s) if active else 0,
            rms_pitch=round(rms_pitch, 2),
            rms_yaw=round(rms_yaw, 2),
            ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )
