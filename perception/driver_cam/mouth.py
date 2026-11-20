"""Yawn and speaking from FeatureFrames.

* Yawn: ``jawOpen >= yawn.jaw_open_threshold`` held for ``yawn.min_duration_s`` (Debounce).
* Speaking: standard deviation over ``speaking.window_s`` of the inner-lip gap (landmarks 13-14) divided by the face
  height (10-152), at least ``speaking.lip_std_threshold``, and never during a yawn. A yawn opens the mouth too,
  but once and slowly; speech makes the gap oscillate. So speaking also needs ``speaking.min_reversals`` direction
  changes of the gap inside the window, and is blocked for one window after the jaw was wide open (otherwise the
  closing of a yawn still sits in the window and looks like a large standard deviation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from perception.config import SpeakingConfig, YawnConfig
from perception.features import FaceFeatures
from perception.filters import Debounce, RollingWindow

__all__ = ["MouthEvent", "MouthOutput", "MouthTracker", "lip_ratio"]


def _reversals(values: list[float], min_step: float) -> int:
    """Direction changes in a series, ignoring steps smaller than ``min_step`` (landmark noise)."""
    count, direction, anchor = 0, 0, values[0] if values else 0.0
    for v in values[1:]:
        step = v - anchor
        if abs(step) < min_step:
            continue
        new_dir = 1 if step > 0 else -1
        if direction and new_dir != direction:
            count += 1
        direction, anchor = new_dir, v
    return count


def lip_ratio(face: FaceFeatures, frame_w: int, frame_h: int) -> float | None:
    """Inner-lip gap / face height, both in pixels."""
    if not face.present or face.landmarks is None:
        return None

    def px(i: int) -> tuple[float, float]:
        x, y, _ = face.point(i)
        return x * frame_w, y * frame_h

    (ux, uy), (lx, ly) = px(13), px(14)
    (tx, ty), (bx, by) = px(10), px(152)
    height = math.hypot(tx - bx, ty - by)
    return math.hypot(ux - lx, uy - ly) / height if height > 0 else None


@dataclass(frozen=True)
class MouthEvent:
    kind: str  # "yawn"
    start: float
    end: float


@dataclass
class MouthOutput:
    yawn: bool = False
    speaking: bool = False
    jaw_open: float | None = None
    lip_ratio: float | None = None
    lip_std: float | None = None
    new_events: list[MouthEvent] = field(default_factory=list)


class MouthTracker:
    def __init__(self, yawn: YawnConfig, speaking: SpeakingConfig, frame_size: tuple[int, int]) -> None:
        self._yawn_cfg = yawn
        self._speak_cfg = speaking
        self.w, self.h = frame_size
        self._yawn = Debounce(yawn.min_duration_s * 1000.0)
        self._lips = RollingWindow(speaking.window_s)
        self._yawning_since: float | None = None
        self._last_jaw_wide: float | None = None
        self.events: list[MouthEvent] = []

    def update(self, t: float, face: FaceFeatures) -> MouthOutput:
        out = MouthOutput()
        if not face.present or face.blendshapes is None:
            self._yawn.update(t, False)
            self._finish_yawn(t, out)
            self._lips.clear()
            return out
        jaw = face.blendshapes.get("jawOpen", 0.0)
        out.jaw_open = round(jaw, 4)
        jaw_wide = jaw >= self._yawn_cfg.jaw_open_threshold
        if jaw_wide:
            self._last_jaw_wide = t
        out.yawn = self._yawn.update(t, jaw_wide)
        if out.yawn and self._yawning_since is None:
            self._yawning_since = self._yawn.since
        if not out.yawn:
            self._finish_yawn(t, out)

        ratio = lip_ratio(face, self.w, self.h)
        if ratio is not None:
            out.lip_ratio = round(ratio, 4)
            self._lips.add(t, ratio)
        if self._lips.span_s >= 0.5 * self._speak_cfg.window_s:
            threshold = self._speak_cfg.lip_std_threshold
            out.lip_std = round(self._lips.std(), 5)
            after_wide_jaw = self._last_jaw_wide is not None and t - self._last_jaw_wide < self._speak_cfg.window_s
            oscillates = _reversals(self._lips.values(), min_step=threshold) >= self._speak_cfg.min_reversals
            out.speaking = out.lip_std >= threshold and oscillates and not after_wide_jaw and not out.yawn
        return out

    def _finish_yawn(self, t: float, out: MouthOutput) -> None:
        if self._yawning_since is not None:
            event = MouthEvent("yawn", self._yawning_since, t)
            self.events.append(event)
            out.new_events.append(event)
            self._yawning_since = None
