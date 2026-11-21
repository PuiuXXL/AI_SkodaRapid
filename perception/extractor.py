"""Run the perception models on one camera frame and return a :class:`~perception.features.FeatureFrame`.

Models and cadence (frame-count based, so rates line up with the camera's frame period):
* Face Landmarker: every frame (R-FL1: one face; R-FL2: thresholds from yaml).
* MobileGaze: every ``round(camera_fps / rates.gaze_hz)`` frames, on ``models.gaze_providers``
  (:class:`~perception.driver_cam.gaze_model.MobileGazeModel`, crop = face box x ``gaze.crop_expand``).
* YOLO26 phone: every ``round(camera_fps / rates.phone_hz)`` frames; GPU variant on CUDA when available.
* Gesture Recognizer: every ``round(camera_fps / gesture_hz)`` frames, only if ``gesture_hz`` is given
  (live it runs only inside the dialog window; recording sessions turn it on to capture labelled gestures).

No detector logic and no filtering here: this is the raw, per-frame model output.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from perception.capture import Frame
from perception.config import PerceptionConfig
from perception.driver_cam.face import FaceLandmarkerModel, VideoClock
from perception.driver_cam.gaze_model import MobileGazeModel
from perception.features import FeatureFrame, GazeFeatures, HandFeatures, PhoneBox
from perception.log import get_logger
from perception.perf import LatencyWindow
from perception.postprocess import yolo26_detections
from perception.preprocess import letterbox
from perception.runtime import OnnxModel, available_providers

__all__ = ["FeatureExtractor", "every_n_frames"]

log = get_logger("perception.extractor")

CUDA = "CUDAExecutionProvider"


def every_n_frames(camera_fps: float, rate_hz: float) -> int:
    """Run a model every N frames to approximate ``rate_hz`` at ``camera_fps`` (at least every frame)."""
    if rate_hz <= 0 or camera_fps <= 0:
        return 1
    return max(1, round(camera_fps / rate_hz))


class FeatureExtractor:
    def __init__(
        self,
        cfg: PerceptionConfig,
        *,
        camera_fps: float,
        camera: str = "driver",
        gaze: bool = True,
        phone: bool = True,
        gesture_hz: float | None = None,
    ) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        self.camera_fps = camera_fps
        self._cfg = cfg
        self._frame_index = 0
        self.models: dict[str, dict[str, str]] = {}

        self.face = FaceLandmarkerModel(cfg, camera=camera)
        self.models["face_landmarker"] = {"file": self.face.path.name, "backend": "mediapipe"}

        self._gaze: MobileGazeModel | None = None
        self._gaze_every = every_n_frames(camera_fps, cfg.rates.gaze_hz)  # nominal, for the recording meta
        # time-based: at 22 processed fps a frame count runs MobileGaze at ~11 Hz instead of gaze_hz
        self._gaze_period = 1.0 / cfg.rates.gaze_hz if cfg.rates.gaze_hz > 0 else 0.0
        self._gaze_next = float("-inf")
        if gaze:
            self._gaze = MobileGazeModel(cfg)
            self.models["gaze"] = {
                "file": self._gaze.path.name,
                "backend": self._gaze.provider,
                "crop_expand": str(self._gaze.crop_expand),
            }

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
        self._gesture_on = bool(gesture_hz)
        self._gesture_latency = LatencyWindow(cfg.rates.perf_window)
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
            self._gesture_clock = VideoClock()
            self.models["gesture_recognizer"] = {"file": gesture_path.name, "backend": "mediapipe"}

        self._eye_cnn: Any = None
        eye_path = cfg.models.path(cfg.models.eye_state)
        if cfg.eyes.cnn.enabled and eye_path.exists():
            from perception.driver_cam.eye_cnn import EyeStateCNN

            providers = [p for p in cfg.models.gaze_providers if p != CUDA]  # tiny model: CPU / OpenVINO
            self._eye_cnn = EyeStateCNN(eye_path, providers, cfg.eyes.cnn.crop_scale, cfg.rates.perf_window)
            self.models["eye_state"] = {"file": eye_path.name, "backend": self._eye_cnn.model.provider}
        elif cfg.eyes.cnn.enabled:
            log.warning("eye-state CNN enabled but its model is missing", extra={"fields": {"path": str(eye_path)}})

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

        face, face_box = self.face.detect(mp_image, frame.t_capture, w, h)
        if self._eye_cnn is not None and face.present:
            face = face.model_copy(update={"eye_closed_p": self._eye_cnn.closed_probs(image, face)})

        gaze_out: GazeFeatures | None = None
        if self._gaze is not None and face.present and self._gaze_due(frame.t_capture):
            gaze_out = self._gaze.estimate(image, face_box)

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
        if self._gesture is not None and self._gesture_on and index % self._gesture_every == 0:
            with self._gesture_latency.time():
                hands = self._hand_features(mp_image, frame.t_capture)

        return FeatureFrame(
            t=round(t, 4), frame_id=frame.frame_id, camera=camera, face=face, gaze=gaze_out, hands=hands, phones=phones
        )

    def _gaze_due(self, t_capture: float) -> bool:
        """True when the gaze model is due (10 ms tolerance so a 30 fps camera hits 15 Hz exactly)."""
        if t_capture < self._gaze_next - 0.010:
            return False
        late = t_capture - self._gaze_next > self._gaze_period
        self._gaze_next = t_capture + self._gaze_period if late else self._gaze_next + self._gaze_period
        return True

    def warmup(self, width: int, height: int) -> None:
        """One inference of every loaded model on a blank frame (plan §8 rule 5: no first-frame stall)."""
        image = np.zeros((height, width, 3), dtype=np.uint8)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=image)
        t0 = time.perf_counter()
        self.face.detect(mp_image, t0 - 1.0, width, height)  # earlier than any real frame (VideoClock stays monotonic)
        if self._gaze is not None:
            self._gaze.estimate(image, (width / 4, height / 4, width / 2, height / 2))
        if self._eye_cnn is not None:
            from perception.driver_cam.eye_cnn import eye_input

            self._eye_cnn.model.run(eye_input(np.zeros((32, 32, 3), dtype=np.uint8)))
        if self._phone is not None:
            tensor, _ = letterbox(image, self._phone_size)
            self._phone.run(tensor)
        for window in (self.gaze_latency, self.eye_state_latency, self.phone_latency):
            if window is not None:
                window.clear()
        log.info("models warmed up", extra={"fields": {"ms": round((time.perf_counter() - t0) * 1000, 1)}})

    def set_phone_hz(self, rate_hz: float) -> None:
        """Change the YOLO rate at run time (degradation rule, plan §8)."""
        self._phone_every = every_n_frames(self.camera_fps, rate_hz)
        self.cadence["phone_every"] = self._phone_every

    def set_gesture(self, rate_hz: float | None) -> None:
        """Gesture Recognizer on (inside the dialog window) or off; the model is loaded on first use."""
        if not rate_hz:
            self._gesture_on = False
            return
        if self._gesture is None:
            from mediapipe.tasks.python import BaseOptions, vision

            gesture_path = self._cfg.models.path(self._cfg.models.gesture_recognizer)
            self._gesture = vision.GestureRecognizer.create_from_options(
                vision.GestureRecognizerOptions(
                    base_options=BaseOptions(model_asset_path=str(gesture_path)),
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=2,
                )
            )
            self._gesture_clock = VideoClock()
            self.models["gesture_recognizer"] = {"file": gesture_path.name, "backend": "mediapipe"}
        self._gesture_every = every_n_frames(self.camera_fps, rate_hz)
        self.cadence["gesture_every"] = self._gesture_every
        self._gesture_on = True

    @property
    def phone_latency(self) -> LatencyWindow | None:
        return self._phone.latency if self._phone is not None else None

    @property
    def gaze_latency(self) -> LatencyWindow | None:
        return self._gaze.latency if self._gaze is not None else None

    @property
    def eye_state_latency(self) -> LatencyWindow | None:
        return self._eye_cnn.latency if self._eye_cnn is not None else None

    @property
    def gesture_latency(self) -> LatencyWindow:
        return self._gesture_latency

    def close(self) -> None:
        self.face.close()
        if self._gesture is not None:
            self._gesture.close()

    # -----------------------------------------------------------------------------------------------------

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
