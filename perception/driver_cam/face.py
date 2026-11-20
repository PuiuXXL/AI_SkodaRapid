"""MediaPipe Face Landmarker for the driver camera, with the Face Landmarker rules R-FL1..R-FL3.

* R-FL1: exactly one face (``face.num_faces`` must be 1 on the driver camera; anything else is refused).
* R-FL2: detection / presence / tracking confidences from yaml.
* R-FL3: face width in pixels from the face-oval landmarks; below ``face.min_face_width_px`` the face is flagged
  ``too_small`` and its confidence is scaled down (``width / min_width``).

VIDEO running mode on the full frame (MediaPipe tracks the face itself), timestamps strictly increasing in ms from
the capture time. Output: :class:`~perception.features.FaceFeatures` (the FeatureFrame face block).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from perception.config import PerceptionConfig
from perception.features import LANDMARK_GROUPS, LANDMARK_INDICES, FaceFeatures
from perception.perf import LatencyWindow

__all__ = ["FaceLandmarkerModel", "VideoClock", "face_box_px", "face_from_landmarks"]

_OVAL = LANDMARK_GROUPS["face_oval"]
Box = tuple[float, float, float, float]  # x, y, w, h in pixels


class VideoClock:
    """Strictly increasing millisecond timestamps for MediaPipe VIDEO mode, from ``time.perf_counter`` seconds."""

    def __init__(self) -> None:
        self.last = -1

    def __call__(self, t_capture: float) -> int:
        ts = max(int(t_capture * 1000), self.last + 1)
        self.last = ts
        return ts


def face_from_landmarks(
    points: Sequence[Any],
    blendshapes: dict[str, float],
    matrix: Sequence[float],
    frame_w: int,
    frame_h: int,
    min_face_width_px: float,
) -> tuple[FaceFeatures, Box]:
    """Build the FaceFeatures block from all 478 MediaPipe landmarks (objects with ``x, y, z``). R-FL3 applied here."""
    xs = [points[i].x * frame_w for i in _OVAL]
    ys = [points[i].y * frame_h for i in _OVAL]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    width = max(0.0, x1 - x0)
    face = FaceFeatures(
        present=True,
        conf=round(min(1.0, width / min_face_width_px), 3),
        width_px=round(width, 1),
        too_small=width < min_face_width_px,
        landmarks=[(round(points[i].x, 5), round(points[i].y, 5), round(points[i].z, 5)) for i in LANDMARK_INDICES],
        blendshapes=blendshapes,
        head_matrix=[round(float(v), 5) for v in matrix],
    )
    return face, (x0, y0, width, y1 - y0)


def face_box_px(face: FaceFeatures, frame_w: int, frame_h: int) -> Box | None:
    """Face-oval bounding box in pixels from a FeatureFrame face (works on replayed frames too)."""
    if not face.present or face.landmarks is None:
        return None
    pts = [face.point(i) for i in _OVAL]
    xs = [p[0] * frame_w for p in pts]
    ys = [p[1] * frame_h for p in pts]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


class FaceLandmarkerModel:
    """Face Landmarker for one camera. ``min_tracking_conf`` can be overridden (R-FL2 tuning only)."""

    def __init__(
        self, cfg: PerceptionConfig, *, camera: str = "driver", min_tracking_conf: float | None = None
    ) -> None:
        if camera == "driver" and cfg.face.num_faces != 1:
            raise ValueError(f"R-FL1: face.num_faces must be 1 on the driver camera, got {cfg.face.num_faces}")
        from mediapipe.tasks.python import BaseOptions, vision

        self._cfg = cfg
        self.path = cfg.models.path(cfg.models.face_landmarker)
        self.min_tracking_conf = cfg.face.min_tracking_conf if min_tracking_conf is None else min_tracking_conf
        self._landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self.path)),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=cfg.face.num_faces,
                min_face_detection_confidence=cfg.face.min_detection_conf,
                min_face_presence_confidence=cfg.face.min_presence_conf,
                min_tracking_confidence=self.min_tracking_conf,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
            )
        )
        self._clock = VideoClock()
        self.latency = LatencyWindow(cfg.rates.perf_window)

    def detect(self, mp_image: Any, t_capture: float, frame_w: int, frame_h: int) -> tuple[FaceFeatures, Box | None]:
        """Run on one RGB ``mediapipe.Image``; returns the face block and the face box in pixels (or None)."""
        with self.latency.time():
            result = self._landmarker.detect_for_video(mp_image, self._clock(t_capture))
        if not result.face_landmarks:
            return FaceFeatures(present=False, conf=0.0), None
        blendshapes = {c.category_name: round(float(c.score), 4) for c in result.face_blendshapes[0]}
        matrix = np.asarray(result.facial_transformation_matrixes[0], dtype=np.float64).reshape(-1)
        return face_from_landmarks(
            result.face_landmarks[0], blendshapes, matrix.tolist(), frame_w, frame_h, self._cfg.face.min_face_width_px
        )

    def close(self) -> None:
        self._landmarker.close()
