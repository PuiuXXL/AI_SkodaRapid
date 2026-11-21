"""MobileGaze MobileOne-S0 (``yakhyo/gaze-estimation``, MIT code, Gaze360 weights) on the driver's face crop.

Pre-processing checked against the repo's ``onnx_inference.py`` (2026-11-21), not assumed:

* crop = the face detector box (RetinaFace there, the landmark face-oval box here), **no expansion, no squaring**
  (``gaze.crop_expand`` = 1.0 reproduces it; ``scripts/eval_zones.py --ab-crop`` compares other values on live frames);
* BGR -> RGB, ``cv2.resize`` to the model input (448 x 448, default = bilinear), / 255, ImageNet mean / std, NCHW
  float32 (:func:`perception.preprocess.gaze_input`);
* decoding: softmax over 90 bins, expectation x 4 - 180 = degrees (:func:`perception.postprocess.gaze_angles`); the
  two outputs are picked **by name** (the export orders them yaw, pitch).

The FeatureFrame stores the **raw** model angles. :data:`GAZE_SIGNS` maps them to the driver convention used by the head
(``yaw > 0`` = towards the driver's left, ``pitch > 0`` = up). The repo draws the arrow on a mirrored webcam image
(``dx = -L sin(yaw) cos(pitch)``), so on our non-mirrored frames the raw yaw is the opposite of the driver's left.
Measured on the laptop session 2026-11-21 (1899 frames): corr(head yaw, raw gaze yaw) = -0.51, corr(head pitch, raw
gaze pitch) = +0.65. The guided zone eval re-checks both signs live (``sign_ok``).
"""

from __future__ import annotations

from typing import Any

from perception.config import PerceptionConfig
from perception.features import GazeFeatures
from perception.filters import OneEuroFilter
from perception.perf import LatencyWindow
from perception.postprocess import gaze_from_outputs
from perception.preprocess import crop_box, gaze_input
from perception.runtime import OnnxModel

__all__ = ["GAZE_SIGNS", "GazeSmoother", "MobileGazeModel", "driver_gaze"]

# raw MobileGaze angles -> driver convention (yaw left, pitch up)
GAZE_SIGNS = {"yaw": -1.0, "pitch": 1.0}

Box = tuple[float, float, float, float]


def driver_gaze(raw: GazeFeatures) -> tuple[float, float]:
    """(yaw, pitch) in degrees, driver convention, from a raw FeatureFrame gaze."""
    return GAZE_SIGNS["yaw"] * raw.yaw_deg, GAZE_SIGNS["pitch"] * raw.pitch_deg


class MobileGazeModel:
    """MobileGaze on a face crop. ``estimate`` returns the raw angles (as stored in the FeatureFrame)."""

    def __init__(self, cfg: PerceptionConfig, crop_expand: float | None = None) -> None:
        self.model = OnnxModel(
            cfg.models.path(cfg.models.gaze),
            providers=cfg.models.gaze_providers,
            name="gaze",
            perf_window=cfg.rates.perf_window,
        )
        self.size = next((d for d in self.model.inputs[0].shape[2:] if isinstance(d, int)), 448)
        self.crop_expand = cfg.gaze.crop_expand if crop_expand is None else crop_expand
        self._names = [o.name for o in self.model.outputs]
        self.latency = LatencyWindow(cfg.rates.perf_window)  # crop + pre-processing + inference + decoding

    @property
    def path(self) -> Any:
        return self.model.path

    @property
    def provider(self) -> str:
        return self.model.provider

    def estimate(self, image: Any, face_box: Box | None) -> GazeFeatures | None:
        if face_box is None:
            return None
        with self.latency.time():
            crop = crop_box(image, face_box, expand=self.crop_expand)
            if crop is None:
                return None
            outputs = self.model.run(gaze_input(crop, self.size))
            pitch, yaw = gaze_from_outputs(self._names, outputs)
        return GazeFeatures(pitch_deg=round(pitch, 2), yaw_deg=round(yaw, 2))


class GazeSmoother:
    """One Euro on the driver-convention gaze angles, holding the last value for at most ``max_age_ms``.

    MobileGaze runs every few frames (``rates.gaze_hz``); between runs the zone classifier uses the last smoothed value
    while it is fresh enough, and ``None`` after that (zone -> unknown).
    """

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float, max_age_ms: float) -> None:
        self._yaw = OneEuroFilter(min_cutoff, beta, d_cutoff)
        self._pitch = OneEuroFilter(min_cutoff, beta, d_cutoff)
        self.max_age_s = max_age_ms / 1000.0
        self._last: tuple[float, float] | None = None
        self._t_last: float | None = None

    def update(self, t: float, raw: GazeFeatures | None) -> tuple[float, float] | None:
        if raw is not None:
            if self._t_last is not None and t - self._t_last > self.max_age_s:  # long gap: restart the filters
                self._yaw.reset()
                self._pitch.reset()
            yaw, pitch = driver_gaze(raw)
            self._last = (self._yaw.update(t, yaw), self._pitch.update(t, pitch))
            self._t_last = t
        if self._t_last is None or t - self._t_last > self.max_age_s:
            return None
        return self._last

    def reset(self) -> None:
        self._yaw.reset()
        self._pitch.reset()
        self._last = None
        self._t_last = None
