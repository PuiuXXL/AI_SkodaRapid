"""Validated perception config, loaded from ``perception/config/perception.yaml``.

The YAML is the only place where perception values live. The models below declare types and allowed ranges
but **no default values**, so a missing key fails at start-up instead of silently falling back to a number
hidden in code. Unknown keys are rejected too (typos fail loudly).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "REPO_ROOT",
    "CameraConfig",
    "CameraControls",
    "ConfigError",
    "PerceptionConfig",
    "load_config",
]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "perception.yaml"

PositiveFloat = Annotated[float, Field(gt=0)]
PositiveInt = Annotated[int, Field(gt=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]

CalibratedZone = Literal[
    "road",
    "mirror_left",
    "mirror_right",
    "mirror_rear",
    "cluster",
    "infotainment",
    "lap",
    "passenger",
]
OnnxProvider = Literal["CUDAExecutionProvider", "OpenVINOExecutionProvider", "CPUExecutionProvider"]
GestureName = Literal["Thumb_Up", "Thumb_Down", "Open_Palm"]


class ConfigError(ValueError):
    """The config file is missing or is not a YAML mapping."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- cameras -------------------------------------------------------------------------------------------


class CameraControls(_Section):
    """Fixed image controls. ``null`` = leave the camera's own setting untouched.

    Applied by ``scripts/camera_setup.sh`` (Linux, v4l2-ctl) or by ``perception/capture.py`` (Windows, OpenCV
    properties, best effort). Units are semantic and converted per platform (e.g. ``exposure_ms``).
    """

    power_line_hz: Literal[0, 50, 60] | None
    autofocus: bool | None
    focus: Annotated[int, Field(ge=0)] | None
    auto_exposure: bool | None
    exposure_ms: Annotated[float, Field(gt=0, le=1000)] | None
    gain: Annotated[int, Field(ge=0)] | None
    auto_white_balance: bool | None
    white_balance_k: Annotated[int, Field(ge=2000, le=10000)] | None


class CameraConfig(_Section):
    enabled: bool
    device: int | str
    backend: Literal["auto", "dshow", "msmf", "v4l2", "any"]
    width: PositiveInt
    height: PositiveInt
    fps: Annotated[int, Field(gt=0, le=120)]
    fourcc: Annotated[str, StringConstraints(min_length=4, max_length=4)]
    buffer_size: Annotated[int, Field(ge=1, le=4)]
    reconnect_s: PositiveFloat
    max_read_failures: Annotated[int, Field(ge=1, le=1000)]
    controls: CameraControls


class CamerasConfig(_Section):
    driver: CameraConfig
    passenger: CameraConfig

    @model_validator(mode="after")
    def _driver_enabled(self) -> Self:
        if not self.driver.enabled:
            raise ValueError("cameras.driver.enabled must be true: the driver camera is the safety camera")
        return self


# --- models --------------------------------------------------------------------------------------------


class YoloVariant(_Section):
    weights: str
    imgsz: Annotated[int, Field(ge=160, le=1280, multiple_of=32)]


class ModelsConfig(_Section):
    dir: Path
    face_landmarker: str
    gesture_recognizer: str
    gaze: str
    yunet: str
    sface: str
    phone_device: Literal["auto", "cpu", "gpu"]
    phone_cpu: YoloVariant
    phone_gpu: YoloVariant
    pose: str
    onnx_providers: Annotated[list[OnnxProvider], Field(min_length=1)]

    @model_validator(mode="after")
    def _cpu_fallback(self) -> Self:
        if len(set(self.onnx_providers)) != len(self.onnx_providers):
            raise ValueError("models.onnx_providers contains duplicates")
        if self.onnx_providers[-1] != "CPUExecutionProvider":
            raise ValueError("models.onnx_providers must end with CPUExecutionProvider (always-available fallback)")
        return self

    def path(self, filename: str) -> Path:
        """Absolute path of a model file; ``dir`` is relative to the repo root unless absolute."""
        base = self.dir if self.dir.is_absolute() else REPO_ROOT / self.dir
        return base / filename


# --- rates ---------------------------------------------------------------------------------------------


class RatesConfig(_Section):
    driver_face_every_frame: Literal[True]
    passenger_face_hz: PositiveFloat
    gaze_hz: PositiveFloat
    phone_hz: PositiveFloat
    pose_hz: PositiveFloat
    identity_recheck_s: PositiveFloat
    perf_window: Annotated[int, Field(ge=10, le=10_000)]
    degrade_e2e_p95_ms: PositiveFloat


# --- per-signal thresholds -----------------------------------------------------------------------------


class EyesConfig(_Section):
    baseline_window_s: PositiveFloat
    baseline_percentile: Annotated[float, Field(gt=50, le=100)]
    k_close: Annotated[float, Field(gt=0, lt=1)]
    k_open: Annotated[float, Field(gt=0, lt=1)]
    median_frames: Annotated[int, Field(ge=1, le=9)]
    min_state_frames: Annotated[int, Field(ge=1, le=10)]
    blink_max_ms: PositiveInt
    blendshape_closed: Fraction
    perclos_window_s: PositiveFloat

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.k_close >= self.k_open:
            raise ValueError("eyes.k_close must be lower than eyes.k_open (hysteresis band)")
        if self.median_frames % 2 == 0:
            raise ValueError("eyes.median_frames must be odd")
        return self


class YawnConfig(_Section):
    jaw_open_threshold: Fraction
    min_duration_s: PositiveFloat


class SpeakingConfig(_Section):
    window_s: PositiveFloat
    jaw_var_threshold: PositiveFloat


class NodConfig(_Section):
    pitch_drop_deg: PositiveFloat
    window_s: PositiveFloat


class HeadAnswerConfig(_Section):
    min_reversals: Annotated[int, Field(ge=1, le=10)]
    window_s: PositiveFloat
    min_amplitude_deg: PositiveFloat


class HeadConfig(_Section):
    nod: NodConfig
    answer: HeadAnswerConfig


class GazeConfig(_Section):
    zones: Annotated[list[CalibratedZone], Field(min_length=2)]
    k: Annotated[int, Field(ge=1, le=50)]
    weighted: bool
    reject_distance: PositiveFloat
    min_conf: Fraction
    calibration_s_per_zone: PositiveFloat
    calibration_modes: Annotated[list[Literal["owl", "lizard"]], Field(min_length=1)]
    vats_max_glance_s: PositiveFloat
    window_s: PositiveFloat

    @model_validator(mode="after")
    def _check(self) -> Self:
        if "road" not in self.zones:
            raise ValueError("gaze.zones must contain 'road'")
        if len(set(self.zones)) != len(self.zones):
            raise ValueError("gaze.zones contains duplicates")
        return self


class LapPatternConfig(_Section):
    min_glances: PositiveInt
    window_s: PositiveFloat
    long_glance_s: PositiveFloat
    conf: Fraction


class PhoneConfig(_Section):
    class_id: Annotated[int, Field(ge=0, le=79)]
    conf_min: Fraction
    vote_window: Annotated[int, Field(ge=1, le=30)]
    vote_min: Annotated[int, Field(ge=1, le=30)]
    near_face_ratio: PositiveFloat
    lap_pattern: LapPatternConfig

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.vote_min > self.vote_window:
            raise ValueError("phone.vote_min must not exceed phone.vote_window")
        return self


class GestureConfig(_Section):
    allowed: Annotated[list[GestureName], Field(min_length=1)]
    min_score: Fraction
    min_duration_s: PositiveFloat


class IdentityConfig(_Section):
    cosine_threshold: Annotated[float, Field(gt=-1, lt=1)]
    yunet_score_threshold: Fraction
    yunet_nms_threshold: Fraction
    enroll_frames: Annotated[int, Field(ge=1, le=100)]


class MonitoringConfig(_Section):
    face_lost_s: PositiveFloat
    frozen_frame_s: PositiveFloat
    frozen_pixel_diff: Annotated[float, Field(ge=0)]


class OneEuroConfig(_Section):
    min_cutoff: PositiveFloat
    beta: Annotated[float, Field(ge=0)]
    d_cutoff: PositiveFloat


class FiltersConfig(_Section):
    one_euro: OneEuroConfig
    min_detection_conf: Fraction
    min_tracking_conf: Fraction
    unknown_below_conf: Fraction


class OutputConfig(_Section):
    ws_url: Annotated[str, StringConstraints(pattern=r"^wss?://.+")]
    ws_reconnect_s: PositiveFloat
    publish_hz: Annotated[float, Field(gt=0, le=60)]
    mjpeg_port: Annotated[int, Field(ge=1024, le=65535)]
    video_width: Annotated[int, Field(ge=160, le=1920)]
    video_fps: Annotated[float, Field(gt=0, le=60)]
    jpeg_quality: Annotated[int, Field(ge=10, le=100)]


# --- root ----------------------------------------------------------------------------------------------


class PerceptionConfig(_Section):
    cameras: CamerasConfig
    models: ModelsConfig
    rates: RatesConfig
    eyes: EyesConfig
    yawn: YawnConfig
    speaking: SpeakingConfig
    head: HeadConfig
    gaze: GazeConfig
    phone: PhoneConfig
    gesture: GestureConfig
    identity: IdentityConfig
    monitoring: MonitoringConfig
    filters: FiltersConfig
    output: OutputConfig

    @model_validator(mode="after")
    def _cross_check(self) -> Self:
        driver_fps = self.cameras.driver.fps
        for name, rate in (
            ("output.publish_hz", self.output.publish_hz),
            ("output.video_fps", self.output.video_fps),
            ("rates.gaze_hz", self.rates.gaze_hz),
        ):
            if rate > driver_fps:
                raise ValueError(f"{name} ({rate}) exceeds the driver camera fps ({driver_fps})")
        passenger = self.cameras.passenger
        if passenger.enabled and self.rates.passenger_face_hz > passenger.fps:
            raise ValueError(
                f"rates.passenger_face_hz ({self.rates.passenger_face_hz}) exceeds the passenger camera fps "
                f"({passenger.fps})"
            )
        if self.cameras.driver.device == passenger.device and passenger.enabled:
            raise ValueError("cameras.driver.device and cameras.passenger.device must differ")
        return self


def load_config(path: str | Path | None = None) -> PerceptionConfig:
    """Load and validate the perception config.

    Args:
        path: YAML file; defaults to ``perception/config/perception.yaml`` next to this package.

    Raises:
        ConfigError: the file is missing or is not a YAML mapping.
        pydantic.ValidationError: a value is missing, unknown or out of range (the message names the field path).
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"perception config not found: {config_path}") from exc
    data: Any = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError(f"perception config must be a YAML mapping: {config_path}")
    return PerceptionConfig.model_validate(data)
