"""Eye-state CNN on eye crops: a second, appearance-based opinion for the cases EAR cannot separate.

Why: on the held-out session of 2026-11-21 a hard squint went down to EAR ratio 0.30-0.42 with eyeBlink 0.51-0.55,
exactly like a closure (0.28-0.45, 0.52-0.65). Landmarks and blendshapes describe the lid *geometry*; a CNN on the
pixels sees whether iris / sclera are still visible (docs/perception.md §3.2, §11 Ersoy et al.: 99.1 % with a CNN on
eye crops vs 93.2 % with personalised EAR).

Model: **open-closed-eye-0001** (Intel OpenVINO Open Model Zoo, Apache-2.0), trained on the MRL Eye Dataset,
95.84 % accuracy, 0.0014 GFLOPs: input ``1x3x32x32`` BGR, ``(x - 127) / 255``; output ``19``: softmax
``[open, closed]``. Downloaded by ``scripts/download_models.sh`` (SHA-384 from the official ``model.yml``).

The crop is a square around the two eye corners (``eyes.cnn.crop_scale`` x the corner distance), axis-aligned.
Crops are computed in memory and never stored (data policy, docs/perception.md §5).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt

from perception.driver_cam.eyes import EAR_POINTS
from perception.features import FaceFeatures
from perception.runtime import OnnxModel

__all__ = ["EyeStateCNN", "eye_crop", "eye_input"]

Image = npt.NDArray[np.uint8]
INPUT = 32


def eye_crop(image: Image, face: FaceFeatures, side: str, scale: float) -> Image | None:
    """Square crop around one eye (``side`` = "left" / "right", the person's), or None if it leaves the frame."""
    if not face.present or face.landmarks is None:
        return None
    h, w = image.shape[:2]
    p1, _, _, p4, _, _ = EAR_POINTS[side]
    (x1, y1, _), (x4, y4, _) = face.point(p1), face.point(p4)
    ax, ay, bx, by = x1 * w, y1 * h, x4 * w, y4 * h
    size = float(np.hypot(bx - ax, by - ay)) * scale
    if size < 8:
        return None
    cx, cy, half = (ax + bx) / 2, (ay + by) / 2, size / 2
    x0, y0, x_1, y_1 = int(cx - half), int(cy - half), int(cx + half), int(cy + half)
    if x0 < 0 or y0 < 0 or x_1 > w or y_1 > h:
        return None
    return image[y0:y_1, x0:x_1]


def eye_input(crop: Image) -> npt.NDArray[np.float32]:
    """32x32 BGR, (x - 127) / 255, NCHW float32 (the model's Model Optimizer arguments)."""
    resized = cv2.resize(crop, (INPUT, INPUT), interpolation=cv2.INTER_AREA).astype(np.float32)
    return np.ascontiguousarray(((resized - 127.0) / 255.0).transpose(2, 0, 1)[None], dtype=np.float32)


class EyeStateCNN:
    def __init__(self, path: str | Path, providers: Sequence[str], crop_scale: float, perf_window: int = 120) -> None:
        self.model = OnnxModel(path, providers=list(providers), name="eye_state", perf_window=perf_window)
        self.crop_scale = crop_scale

    @property
    def latency(self):  # type: ignore[no-untyped-def]
        return self.model.latency

    def closed_probs(self, image: Image, face: FaceFeatures) -> list[float] | None:
        """[p_closed_left, p_closed_right] (-1 for an eye that could not be cropped), or None without a face."""
        if not face.present:
            return None
        probs: list[float] = []
        for side in ("left", "right"):
            crop = eye_crop(image, face, side, self.crop_scale)
            if crop is None:
                probs.append(-1.0)
                continue
            (out,) = self.model.run(eye_input(crop))[:1]
            scores = np.asarray(out, dtype=np.float64).reshape(-1)[:2]
            total = float(scores.sum())
            probs.append(round(float(scores[1] / total) if total > 0 else 0.0, 4))
        return probs
