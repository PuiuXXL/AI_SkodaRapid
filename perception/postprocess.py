"""Post-processing: raw model outputs -> detections / angles. No inference here."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from perception.preprocess import LetterboxMeta

__all__ = ["Detection", "gaze_angles", "yolo26_detections"]


@dataclass(frozen=True)
class Detection:
    """Box in original frame pixels."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    class_id: int

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2


def yolo26_detections(
    output: npt.NDArray[Any],
    meta: LetterboxMeta,
    frame_shape: tuple[int, ...],
    *,
    conf_min: float,
    class_ids: Collection[int] | None = None,
) -> list[Detection]:
    """Decode a YOLO26 end-to-end (NMS-free) output ``[1, N, 6]`` = ``x1, y1, x2, y2, score, class``.

    Boxes are mapped from the letterboxed input back to the original frame and clipped to it.
    """
    rows = output[0] if output.ndim == 3 else output
    if rows.size == 0:
        return []
    keep = rows[:, 4] >= conf_min
    if class_ids is not None:
        keep &= np.isin(rows[:, 5].astype(np.int64), np.fromiter(class_ids, dtype=np.int64))
    h, w = frame_shape[:2]
    detections: list[Detection] = []
    for x1, y1, x2, y2, score, cls in rows[keep]:
        bx1 = float(np.clip((x1 - meta.pad_x) / meta.scale, 0, w))
        by1 = float(np.clip((y1 - meta.pad_y) / meta.scale, 0, h))
        bx2 = float(np.clip((x2 - meta.pad_x) / meta.scale, 0, w))
        by2 = float(np.clip((y2 - meta.pad_y) / meta.scale, 0, h))
        detections.append(Detection(bx1, by1, bx2, by2, float(score), int(cls)))
    return detections


def _softmax(logits: npt.NDArray[Any]) -> npt.NDArray[np.float64]:
    z = logits.astype(np.float64) - np.max(logits)
    e = np.exp(z)
    return np.asarray(e / e.sum(), dtype=np.float64)


def gaze_angles(
    pitch_logits: npt.NDArray[Any],
    yaw_logits: npt.NDArray[Any],
    *,
    bin_width: float = 4.0,
    angle_offset: float = 180.0,
) -> tuple[float, float]:
    """MobileGaze bin classification -> (pitch, yaw) in degrees: softmax expectation x bin width - offset.

    Defaults are the Gaze360 setup used by ``yakhyo/gaze-estimation`` (90 bins of 4 degrees, offset 180).
    """
    pitch = _softmax(pitch_logits.reshape(-1))
    yaw = _softmax(yaw_logits.reshape(-1))
    idx = np.arange(pitch.size, dtype=np.float64)
    return (
        float(np.sum(pitch * idx) * bin_width - angle_offset),
        float(np.sum(yaw * np.arange(yaw.size, dtype=np.float64)) * bin_width - angle_offset),
    )
