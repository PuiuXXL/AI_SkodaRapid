"""Hands and gestures (AS9 / AP6): MediaPipe Gesture Recognizer, held gestures, hand positions.

Standalone module: configuration in :class:`HandsConfig` (defaults = ``perception/config/pending/modules.yaml``,
section ``hands``), input = a camera frame + timestamp (:meth:`HandTracker.process`) or the recorded hands of a
FeatureFrame (:meth:`HandTracker.update`, same logic, used on replayed sessions), output = :class:`HandsResult`.

* Gesture Recognizer in VIDEO mode, ``num_hands = 2``; ``Thumb_Up`` / ``Thumb_Down`` / ``Open_Palm`` with their score
  plus the hand positions in pixels (wrist = landmark 0, palm centre = mean of 0, 5, 9, 13, 17).
* Two rates: **background** (``background_hz``) for the hand positions (phone geometry, lap pattern) and a raised hand;
  **dialog window** (``dialog_hz``, 0 = every frame) while core waits for an answer. A raised hand outside the window
  switches to the dialog rate for ``raised_boost_s``, so the hold time can be measured (plan AS9: "only in the dialog
  window or with the hand raised").
* A gesture is reported only once the same allowed gesture (score >= ``min_score``) has been seen continuously for
  ``min_ms`` (measured up to its last sighting). A run without it is tolerated for ``dropout_ms`` (the recognizer
  flickers to ``None`` for a frame), a different gesture or observations further apart than ``max_gap_s`` restart the
  hold. Outside the dialog window only a raised hand's gesture counts.

Timestamps are seconds on one monotonic clock (``time.perf_counter`` based); the dialog ``until`` uses the same clock.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
import numpy.typing as npt

from perception.config import REPO_ROOT
from perception.driver_cam.face import VideoClock
from perception.features import HandFeatures

__all__ = ["PALM_POINTS", "WRIST", "Hand", "HandTracker", "HandsConfig", "HandsResult", "as_bgr"]

WRIST = 0
PALM_POINTS = (0, 5, 9, 13, 17)  # wrist + the four finger MCP joints
Box = tuple[float, float, float, float]  # x, y, w, h in pixels
Mode = Literal["background", "dialog"]


def as_bgr(image: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    """3-channel BGR view of a camera frame: mono (GREY / IR) frames are expanded, colour frames pass through."""
    if image.ndim == 2:
        return np.asarray(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    if image.ndim == 3 and image.shape[2] == 1:
        return np.asarray(cv2.cvtColor(image[:, :, 0], cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    return image


def _config_kwargs(cls: type, data: Mapping[str, Any]) -> dict[str, Any]:
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"{cls.__name__}: unknown keys {unknown}")
    return {k: tuple(v) if isinstance(v, list) else v for k, v in data.items()}


@dataclass(frozen=True)
class HandsConfig:
    model: str = "perception/models/gesture_recognizer.task"
    num_hands: int = 2
    min_hand_detection_conf: float = 0.5
    min_hand_presence_conf: float = 0.5
    min_tracking_conf: float = 0.5
    background_hz: float = 2.0  # 0 = off outside the dialog window
    dialog_hz: float = 0.0  # 0 = every frame
    allowed: tuple[str, ...] = ("Thumb_Up", "Thumb_Down", "Open_Palm")
    min_score: float = 0.60
    min_ms: float = 500.0
    dropout_ms: float = 200.0
    max_gap_s: float = 0.7
    raised_margin: float = 0.5
    raised_y_frac: float = 0.6
    raised_boost_s: float = 2.0

    def __post_init__(self) -> None:
        if not 1 <= self.num_hands <= 4:
            raise ValueError("hands.num_hands must be 1..4")
        if self.background_hz < 0 or self.dialog_hz < 0:
            raise ValueError("hands rates must be >= 0")
        if not 0.0 <= self.min_score <= 1.0:
            raise ValueError("hands.min_score must be in [0, 1]")
        if min(self.min_ms, self.dropout_ms, self.raised_boost_s) < 0 or self.max_gap_s <= 0:
            raise ValueError("hands.min_ms / dropout_ms / raised_boost_s must be >= 0 and max_gap_s > 0")
        if not self.allowed:
            raise ValueError("hands.allowed must not be empty")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> HandsConfig:
        return cls(**_config_kwargs(cls, data))

    def model_path(self) -> Path:
        path = Path(self.model)
        return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True, slots=True)
class Hand:
    handedness: str  # as reported by MediaPipe ("Left" / "Right")
    score: float
    gesture: str | None
    gesture_score: float | None
    wrist_px: tuple[float, float]
    palm_px: tuple[float, float]
    box_px: Box
    raised: bool


@dataclass(frozen=True, slots=True)
class HandsResult:
    hands: tuple[Hand, ...] = ()
    gesture: str | None = None  # held >= min_ms (the AS9 output)
    gesture_score: float | None = None
    held_ms: float = 0.0  # how long the current candidate has been held
    candidate: str | None = None  # gesture seen now, not necessarily held long enough (debug overlay)
    ran: bool = False  # the model ran on this frame (False: last hands repeated)
    mode: Mode = "background"
    last_hand_t: float | None = None  # when a hand was last seen (lap pattern "hands seen recently")
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HandTracker:
    """Gesture Recognizer + hold logic for one camera.

    Args:
        cfg: module configuration.
        recognizer: an object with ``recognize_for_video(mp_image, timestamp_ms)`` (MediaPipe API); created from
            ``cfg.model`` on first use when omitted. Tests pass a fake.
    """

    def __init__(self, cfg: HandsConfig | None = None, *, recognizer: Any = None) -> None:
        self.cfg = cfg or HandsConfig()
        self._recognizer = recognizer
        self._clock = VideoClock()
        self._dialog_open = False
        self._dialog_until: float | None = None
        self._boost_until = -math.inf
        self._last_run: float | None = None
        self._candidate: str | None = None
        self._candidate_score: float | None = None
        self._since = 0.0
        self._last_seen = -math.inf
        self._last_hand_t: float | None = None
        self._hands: tuple[Hand, ...] = ()

    # --- dialog window and scheduling ------------------------------------------------------------------

    def set_dialog(self, open: bool, until: float | None = None) -> None:
        """Dialog window from core (``until`` on the same clock as ``t``; ``None`` = until closed)."""
        self._dialog_open = open
        self._dialog_until = until if open else None
        self._reset_hold()

    def dialog_open(self, t: float) -> bool:
        if self._dialog_open and self._dialog_until is not None and t >= self._dialog_until:
            self._dialog_open = False
            self._dialog_until = None
            self._reset_hold()
        return self._dialog_open

    def mode(self, t: float) -> Mode:
        return "dialog" if self.dialog_open(t) else "background"

    def fast(self, t: float) -> bool:
        """Dialog window open, or a raised hand was seen within ``raised_boost_s``: run at the dialog rate."""
        return self.dialog_open(t) or t < self._boost_until

    def rate_hz(self, t: float) -> float:
        """Current model rate; ``0`` with the dialog rate = every frame, ``0`` with the background rate = off."""
        return self.cfg.dialog_hz if self.fast(t) else self.cfg.background_hz

    def should_run(self, t: float) -> bool:
        rate = self.rate_hz(t)
        if rate <= 0:
            return self.fast(t)  # dialog: every frame; background 0: off
        return self._last_run is None or t - self._last_run >= 1.0 / rate - 1e-6

    # --- inputs ----------------------------------------------------------------------------------------

    def process(self, image: npt.NDArray[np.uint8], t: float, face_box: Box | None = None) -> HandsResult:
        """Run the Gesture Recognizer on ``image`` (BGR or mono) if scheduled, then the hold logic."""
        t0 = time.perf_counter()
        h, w = image.shape[:2]
        if not self.should_run(t):
            return self._finish(t, None, (w, h), face_box, t0)
        return self._finish(t, self._recognize(image, t), (w, h), face_box, t0)

    def update(
        self,
        t: float,
        hands: Sequence[HandFeatures] | None,
        frame_size: tuple[int, int],
        face_box: Box | None = None,
    ) -> HandsResult:
        """Hold logic on already recognised hands (FeatureFrame.hands); ``None`` = the model did not run."""
        return self._finish(t, hands, frame_size, face_box, time.perf_counter())

    # --- internals -------------------------------------------------------------------------------------

    def _reset_hold(self) -> None:
        self._candidate, self._candidate_score = None, None
        self._last_seen = -math.inf

    def _finish(
        self,
        t: float,
        hands: Sequence[HandFeatures] | None,
        frame_size: tuple[int, int],
        face_box: Box | None,
        t0: float,
    ) -> HandsResult:
        mode = self.mode(t)
        ran = hands is not None
        if hands is not None:
            self._last_run = t
            self._hands = tuple(self._hand(h, frame_size, face_box) for h in hands)
            if self._hands:
                self._last_hand_t = t
            if mode == "background" and any(h.raised for h in self._hands):
                self._boost_until = t + self.cfg.raised_boost_s
            self._observe(t, mode)
        elif t - self._last_seen > self.cfg.max_gap_s:
            self._reset_hold()  # no observation for too long: the hold is broken
        held_ms = (self._last_seen - self._since) * 1000.0 if self._candidate is not None else 0.0
        held = self._candidate is not None and held_ms >= self.cfg.min_ms
        return HandsResult(
            hands=self._hands,
            gesture=self._candidate if held else None,
            gesture_score=self._candidate_score if held else None,
            held_ms=round(held_ms, 1),
            candidate=self._candidate,
            ran=ran,
            mode=mode,
            last_hand_t=self._last_hand_t,
            ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )

    def _observe(self, t: float, mode: Mode) -> None:
        cfg = self.cfg
        seen = [
            h
            for h in self._hands
            if h.gesture in cfg.allowed and (h.gesture_score or 0.0) >= cfg.min_score and (mode == "dialog" or h.raised)
        ]
        if not seen:
            if self._candidate is not None and (t - self._last_seen) * 1000.0 > cfg.dropout_ms:
                self._reset_hold()
            return
        best = max(seen, key=lambda h: h.gesture_score or 0.0)
        if best.gesture != self._candidate or t - self._last_seen > cfg.max_gap_s:
            self._candidate, self._since = best.gesture, t
        self._candidate_score = best.gesture_score
        self._last_seen = t

    def _hand(self, h: HandFeatures, frame_size: tuple[int, int], face_box: Box | None) -> Hand:
        w, h_px = frame_size
        xs = [p[0] * w for p in h.landmarks]
        ys = [p[1] * h_px for p in h.landmarks]
        palm = (
            sum(xs[i] for i in PALM_POINTS) / len(PALM_POINTS),
            sum(ys[i] for i in PALM_POINTS) / len(PALM_POINTS),
        )
        if face_box is not None:
            _, fy, _, fh = face_box
            raised = palm[1] <= fy + fh * (1.0 + self.cfg.raised_margin)
        else:
            raised = palm[1] <= self.cfg.raised_y_frac * h_px
        x0, y0 = min(xs), min(ys)
        return Hand(
            handedness=h.handedness,
            score=h.score,
            gesture=h.gesture,
            gesture_score=h.gesture_score,
            wrist_px=(round(xs[WRIST], 1), round(ys[WRIST], 1)),
            palm_px=(round(palm[0], 1), round(palm[1], 1)),
            box_px=(round(x0, 1), round(y0, 1), round(max(xs) - x0, 1), round(max(ys) - y0, 1)),
            raised=raised,
        )

    def warmup(self) -> None:
        """Load the Gesture Recognizer and run it once on a blank frame (plan §8 rule 5: no stall on first use)."""
        self._recognize(np.zeros((128, 128, 3), dtype=np.uint8), -1.0)

    def _ensure_recognizer(self) -> Any:
        if self._recognizer is None:
            from mediapipe.tasks.python import BaseOptions, vision

            cfg = self.cfg
            self._recognizer = vision.GestureRecognizer.create_from_options(
                vision.GestureRecognizerOptions(
                    base_options=BaseOptions(model_asset_path=str(cfg.model_path())),
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=cfg.num_hands,
                    min_hand_detection_confidence=cfg.min_hand_detection_conf,
                    min_hand_presence_confidence=cfg.min_hand_presence_conf,
                    min_tracking_confidence=cfg.min_tracking_conf,
                )
            )
        return self._recognizer

    def _recognize(self, image: npt.NDArray[np.uint8], t: float) -> list[HandFeatures]:
        import mediapipe as mp

        recognizer = self._ensure_recognizer()
        rgb = cv2.cvtColor(as_bgr(image), cv2.COLOR_BGR2RGB)
        result = recognizer.recognize_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), self._clock(t))
        hands: list[HandFeatures] = []
        for i, points in enumerate(result.hand_landmarks):
            handed = result.handedness[i][0] if i < len(result.handedness) and result.handedness[i] else None
            gesture = result.gestures[i][0] if i < len(result.gestures) and result.gestures[i] else None
            hands.append(
                HandFeatures(
                    handedness=handed.category_name if handed else "unknown",
                    score=round(min(1.0, max(0.0, float(handed.score))), 3) if handed else 0.0,
                    gesture=gesture.category_name if gesture else None,
                    gesture_score=round(min(1.0, max(0.0, float(gesture.score))), 3) if gesture else None,
                    landmarks=[(round(p.x, 5), round(p.y, 5), round(p.z, 5)) for p in points],
                )
            )
        return hands

    def close(self) -> None:
        if self._recognizer is not None and hasattr(self._recognizer, "close"):
            self._recognizer.close()
