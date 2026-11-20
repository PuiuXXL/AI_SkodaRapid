"""Run the perception models on one camera frame and return a :class:`~perception.features.FeatureFrame`.

Models and cadence (frame-count based, so rates line up with the camera's frame period):
* Face Landmarker: every frame (R-FL1: one face; R-FL2: thresholds from yaml).
* MobileGaze: every ``round(camera_fps / rates.gaze_hz)`` frames, on ``models.gaze_providers``.
* YOLO26 phone: every ``round(camera_fps / rates.phone_hz)`` frames; GPU variant on CUDA when available.
* Gesture Recognizer: every ``round(camera_fps / gesture_hz)`` frames, only if ``gesture_hz`` is given
  (live it runs only inside the dialog window; recording sessions turn it on to capture labelled gestures).

No detector logic and no filtering here: this is the raw, per-frame model output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from perception.capture import Frame
from perception.config import PerceptionConfig
from perception.features import (
    LANDMARK_GROUPS,
    LANDMARK_INDICES,
    FaceFeatures,
    FeatureFrame,
    GazeFeatures,
    HandFeatures,
    PhoneBox,
)
from perception.log import get_logger
from perception.postprocess import gaze_from_outputs, yolo26_detections
from perception.preprocess import crop_box, gaze_input, letterbox
from perception.runtime import OnnxModel, available_providers

__all__ = ["FeatureExtractor", "every_n_frames"]

log = get_logger("perception.extractor")

CUDA = "CUDAExecutionProvider"
_OVAL = LANDMARK_GROUPS["face_oval"]


def every_n_frames(camera_fps: float, rate_hz: float) -> int:
    """Run a model every N frames to approximate ``rate_hz`` at ``camera_fps`` (at least every frame)."""
    if rate_hz <= 0 or camera_fps <= 0:
        return 1
    return max(1, round(camera_fps / rate_hz))


class _VideoClock:
    """Strictly increasing millisecond timestamps for MediaPipe VIDEO mode."""

    def __init__(self) -> None:
        self.last = -1

    def __call__(self, t_capture: float) -> int:
        ts = max(int(t_capture * 1000), self.last + 1)
        self.last = ts
        return ts


class FeatureExtractor:
    def __init__(
        self,
        cfg: PerceptionConfig,
        *,
        camera_fps: float,
        gaze: bool = True,
        phone: bool = True,
        gesture_hz: float | None = None,
    ) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        self._cfg = cfg
        self._frame_index = 0
        self.models: dict[str, dict[str, str]] = {}

        face_path = cfg.models.path(cfg.models.face_landmarker)
        self._face = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(face_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=cfg.face.num_faces,
                min_face_detection_confidence=cfg.face.min_detection_conf,
                min_face_presence_confidence=cfg.face.min_presence_conf,
                min_tracking_confidence=cfg.face.min_tracking_conf,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
            )
        )
        self._face_clock = _VideoClock()
        self.models["face_landmarker"] = {"file": face_path.name, "backend": "mediapipe"}

        self._gaze: OnnxModel | None = None
        self._gaze_every = every_n_frames(camera_fps, cfg.rates.gaze_hz)
        if gaze:
            self._gaze = OnnxModel(cfg.models.path(cfg.models.gaze), providers=cfg.models.gaze_providers, name="gaze")
            self._gaze_size = next((d for d in self._gaze.inputs[0].shape[2:] if isinstance(d, int)), 448)
            self.models["gaze"] = {"file": self._gaze.path.name, "backend": self._gaze.provider}

        self._phone: OnnxModel | None = None
        self._phone_every = every_n_frames(camera_fps, cfg.rates.phone_hz)
        if phone:
            use_gpu = cfg.models.phone_device == "gpu" or (
                cfg.models.phone_device == "auto" and CUDA in available_providers()
            )
            variant = cfg.models.phone_gpu if use_gpu else cfg.models.phone_cpu
            providers = (
                [CUDA, "CPUExecutionProvider"] if use_gpu else [p for p in cfg.models.onnx_providers if p != CUDA]
            )
            path = cfg.models.path(f"{Path(variant.weights).stem}_{variant.imgsz}.onnx")
            self._phone = OnnxModel(path, providers=providers, name="phone")
            self._phone_size = variant.imgsz
            self.models["phone"] = {"file": path.name, "backend": self._phone.provider}

        self._gesture: Any = None
        self._gesture_every = every_n_frames(camera_fps, gesture_hz or 0)
        if gesture_hz:
            gesture_path = cfg.models.path(cfg.models.gesture_recognizer)
            self._gesture = vision.GestureRecognizer.create_from_options(
                vision.GestureRecognizerOptions(
                    base_options=BaseOptions(model_asset_path=str(gesture_path)),
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=2,
                )
            )
            self._gesture_clock = _VideoClock()
            self.models["gesture_recognizer"] = {"file": gesture_path.name, "backend": "mediapipe"}

        self.cadence = {
            "gaze_every": self._gaze_every,
            "phone_every": self._phone_every,
            "gesture_every": self._gesture_every if gesture_hz else 0,
        }
        log.info("feature extractor ready", extra={"fields": {"models": self.models, "cadence": self.cadence}})

    # -----------------------------------------------------------------------------------------------------

    def extract(self, frame: Frame, t: float, camera: str) -> FeatureFrame:
        """Run the scheduled models on ``frame``; ``t`` = seconds since session start."""
        index = self._frame_index
        self._frame_index += 1
        image = frame.image
        h, w = image.shape[:2]
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

        face, face_box = self._face_features(mp_image, frame.t_capture, w, h)

        gaze_out: GazeFeatures | None = None
        if self._gaze is not None and index % self._gaze_every == 0 and face_box is not None:
            crop = crop_box(image, face_box, expand=1.2)
            if crop is not None:
                outputs = self._gaze.run(gaze_input(crop, self._gaze_size))
                pitch, yaw = gaze_from_outputs([o.name for o in self._gaze.outputs], outputs)
                gaze_out = GazeFeatures(pitch_deg=round(pitch, 2), yaw_deg=round(yaw, 2))

        phones: list[PhoneBox] | None = None
        if self._phone is not None and index % self._phone_every == 0:
            tensor, meta = letterbox(image, self._phone_size)
            (raw,) = self._phone.run(tensor)[:1]
            detections = yolo26_detections(
                raw, meta, image.shape, conf_min=self._cfg.phone.conf_min, class_ids={self._cfg.phone.class_id}
            )
            phones = [
                PhoneBox(
                    x1=round(d.x1, 1), y1=round(d.y1, 1), x2=round(d.x2, 1), y2=round(d.y2, 1), score=round(d.score, 3)
                )
                for d in detections
            ]

        hands: list[HandFeatures] | None = None
        if self._gesture is not None and index % self._gesture_every == 0:
            hands = self._hand_features(mp_image, frame.t_capture)

        return FeatureFrame(
            t=round(t, 4), frame_id=frame.frame_id, camera=camera, face=face, gaze=gaze_out, hands=hands, phones=phones
        )

    def close(self) -> None:
        self._face.close()
        if self._gesture is not None:
            self._gesture.close()

    # -----------------------------------------------------------------------------------------------------

    def _face_features(
        self, mp_image: Any, t_capture: float, w: int, h: int
    ) -> tuple[FaceFeatures, tuple[float, float, float, float] | None]:
        result = self._face.detect_for_video(mp_image, self._face_clock(t_capture))
        if not result.face_landmarks:
            return FaceFeatures(present=False, conf=0.0), None
        points = result.face_landmarks[0]
        xs = [points[i].x * w for i in _OVAL]
        ys = [points[i].y * h for i in _OVAL]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        width = max(0.0, x1 - x0)
        min_width = self._cfg.face.min_face_width_px
        landmarks = [(round(points[i].x, 5), round(points[i].y, 5), round(points[i].z, 5)) for i in LANDMARK_INDICES]
        blendshapes = {c.category_name: round(float(c.score), 4) for c in result.face_blendshapes[0]}
        matrix = np.asarray(result.facial_transformation_matrixes[0], dtype=np.float64).reshape(-1)
        face = FaceFeatures(
            present=True,
            conf=round(min(1.0, width / min_width), 3),
            width_px=round(width, 1),
            too_small=width < min_width,
            landmarks=landmarks,
            blendshapes=blendshapes,
            head_matrix=[round(float(v), 5) for v in matrix],
        )
        return face, (x0, y0, width, y1 - y0)

    def _hand_features(self, mp_image: Any, t_capture: float) -> list[HandFeatures]:
        result = self._gesture.recognize_for_video(mp_image, self._gesture_clock(t_capture))
        hands: list[HandFeatures] = []
        for i, points in enumerate(result.hand_landmarks):
            handed = result.handedness[i][0] if i < len(result.handedness) and result.handedness[i] else None
            gesture = result.gestures[i][0] if i < len(result.gestures) and result.gestures[i] else None
            hands.append(
                HandFeatures(
                    handedness=handed.category_name if handed else "unknown",
                    score=round(float(handed.score), 3) if handed else 0.0,
                    gesture=gesture.category_name if gesture else None,
                    gesture_score=round(float(gesture.score), 3) if gesture else None,
                    landmarks=[(round(p.x, 5), round(p.y, 5), round(p.z, 5)) for p in points],
                )
            )
        return hands
