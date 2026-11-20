"""Pre-processing: camera frame (BGR uint8) -> model input tensors. No inference here."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

__all__ = ["IMAGENET_MEAN", "IMAGENET_STD", "LetterboxMeta", "crop_box", "gaze_input", "letterbox"]

Image = npt.NDArray[np.uint8]
Tensor = npt.NDArray[np.float32]

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass(frozen=True)
class LetterboxMeta:
    """How a frame was mapped into the square model input (needed to map boxes back)."""

    scale: float
    pad_x: int
    pad_y: int
    size: int


def letterbox(image: Image, size: int, pad_value: int = 114) -> tuple[Tensor, LetterboxMeta]:
    """Resize keeping the aspect ratio, pad to ``size`` x ``size``; return NCHW RGB float32 in [0, 1]."""
    h, w = image.shape[:2]
    scale = min(size / h, size / w)
    new_w, new_h = round(w * scale), round(h * scale)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), pad_value, dtype=np.uint8)
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    rgb = canvas[:, :, ::-1]
    tensor = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None], dtype=np.float32) / np.float32(255.0)
    return tensor, LetterboxMeta(scale=scale, pad_x=pad_x, pad_y=pad_y, size=size)


def crop_box(image: Image, box: tuple[float, float, float, float], expand: float = 1.0) -> Image | None:
    """Crop ``(x, y, w, h)`` scaled by ``expand`` around its centre, clipped to the frame; ``None`` if empty."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    half_w, half_h = w * expand / 2, h * expand / 2
    img_h, img_w = image.shape[:2]
    x0, y0 = max(0, int(cx - half_w)), max(0, int(cy - half_h))
    x1, y1 = min(img_w, int(cx + half_w)), min(img_h, int(cy + half_h))
    if x1 <= x0 or y1 <= y0:
        return None
    return image[y0:y1, x0:x1]


def gaze_input(face: Image, size: int = 448) -> Tensor:
    """MobileGaze input: face crop -> ``size`` x ``size`` RGB, ImageNet-normalized, NCHW float32."""
    resized = cv2.resize(face, (size, size), interpolation=cv2.INTER_LINEAR)
    rgb = resized[:, :, ::-1].astype(np.float32) / np.float32(255.0)
    normalized = (rgb - IMAGENET_MEAN) / IMAGENET_STD
    return np.ascontiguousarray(normalized.transpose(2, 0, 1)[None], dtype=np.float32)
