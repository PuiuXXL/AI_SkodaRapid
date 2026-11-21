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
    gaze_providers: Annotated[list[OnnxProvider], Field(min_length=1)]

    @model_validator(mode="after")
    def _cpu_fallback(self) -> Self:
        for key, providers in (("onnx_providers", self.onnx_providers), ("gaze_providers", self.gaze_providers)):
            if len(set(providers)) != len(providers):
                raise ValueError(f"models.{key} contains duplicates")
            if providers[-1] != "CPUExecutionProvider":
                raise ValueError(f"models.{key} must end with CPUExecutionProvider (always-available fallback)")
        return self

    def path(self, filename: str) -> Path:
        """Absolute path of a model file; ``dir`` is relative to the repo root unless absolute."""
        base = self.dir if self.dir.is_absolute() else REPO_ROOT / self.dir
        return base / filename


# --- face (MediaPipe Face Landmarker, rules R-FL1..R-FL5 in docs/perception.md) ------------------------


class FaceConfig(_Section):
    num_faces: Literal[1]  # R-FL1: internal tracking/smoothing only works with one face
    min_detection_conf: Fraction  # R-FL2
    min_presence_conf: Fraction  # R-FL2
    min_tracking_conf: Fraction  # R-FL2
    min_face_width_px: Annotated[int, Field(ge=50, le=2000)]  # R-FL3


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
    degrade_step: Annotated[float, Field(gt=0, lt=1)]  # rate multiplier per degradation step
    degrade_min_passenger_face_hz: PositiveFloat
    degrade_min_phone_hz: PositiveFloat
    degrade_recover_ratio: Annotated[float, Field(gt=0, lt=1)]  # recover below ratio x degrade_e2e_p95_ms
    degrade_hold_s: PositiveFloat  # minimum time between two degradation / recovery steps


# --- per-signal thresholds -----------------------------------------------------------------------------


RatioOfRef = Annotated[float, Field(gt=0, lt=1)]


class EyesConfig(_Section):
    # global reference (calibration, or provisional p90 of the first seconds): only a floor for the local one
    baseline_window_s: PositiveFloat
    baseline_percentile: Annotated[float, Field(gt=50, le=100)]
    baseline_min_s: PositiveFloat
    # local reference: p90 of open-eye EAR over the last seconds, never below ref_floor_ratio x global
    local_ref_window_s: PositiveFloat
    local_ref_percentile: Annotated[float, Field(gt=50, le=100)]
    local_ref_min_s: PositiveFloat
    ref_floor_ratio: RatioOfRef
    # blink shape (ratios of the local reference)
    drop_ratio: RatioOfRef
    reopen_ratio: RatioOfRef
    fall_max_ms: PositiveFloat
    fall_window_s: PositiveFloat
    min_fall_depth: RatioOfRef
    slow_close_ratio: RatioOfRef
    min_state_frames: Annotated[int, Field(ge=1, le=10)]
    blink_max_ms: PositiveInt
    plateau_check_ms: PositiveFloat
    blendshape_closed: Fraction  # eyeBlink needed to accept a SLOW closure (drowsy lids), never needed for a fast one
    blendshape_strong: Fraction  # eyeBlink that confirms closed on its own (people whose EAR barely drops)
    # bilateral rule + gaze conditioning
    unilateral_width_ratio: RatioOfRef
    look_down_threshold: Fraction
    pitch_down_deg: PositiveFloat
    pitch_up_deg: PositiveFloat
    drop_ratio_relaxed: RatioOfRef
    head_motion_window_s: PositiveFloat
    head_motion_deg: PositiveFloat
    # R-FL4
    squint_ear_band: Annotated[list[Annotated[float, Field(gt=0, lt=1)]], Field(min_length=2, max_length=2)]
    # PERCLOS P80
    closed_level_default: RatioOfRef
    perclos_closure: RatioOfRef
    perclos_window_s: PositiveFloat
    min_eye_width_px: Annotated[float, Field(ge=1)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.drop_ratio >= self.reopen_ratio:
            raise ValueError("eyes.drop_ratio must be lower than eyes.reopen_ratio")
        if self.drop_ratio_relaxed > self.drop_ratio:
            raise ValueError("eyes.drop_ratio_relaxed must not exceed eyes.drop_ratio (stricter when looking down)")
        low, high = self.squint_ear_band
        if low >= high:
            raise ValueError("eyes.squint_ear_band must be [low, high] with low < high (fractions of the EAR baseline)")
        return self


class YawnConfig(_Section):
    jaw_open_threshold: Fraction
    min_duration_s: PositiveFloat


class SpeakingConfig(_Section):
    window_s: PositiveFloat
    lip_std_threshold: PositiveFloat
    reversal_step: PositiveFloat  # smallest lip-gap change (fraction of face height) that counts as a movement
    min_reversals: Annotated[int, Field(ge=1, le=20)]
    hold_ms: Annotated[float, Field(ge=0)]  # keep speaking=true this long after the last oscillating window


class NodConfig(_Section):
    pitch_drop_deg: PositiveFloat
    window_s: PositiveFloat


class HeadAnswerConfig(_Section):
    min_reversals: Annotated[int, Field(ge=1, le=10)]
    window_s: PositiveFloat
    min_amplitude_deg: PositiveFloat


class PlausibleAnglesConfig(_Section):
    yaw: PositiveFloat
    pitch: PositiveFloat
    roll: PositiveFloat


class HeadConfig(_Section):
    nod: NodConfig
    answer: HeadAnswerConfig
    plausible_deg: PlausibleAnglesConfig


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
    dark_luma: Annotated[float, Field(ge=0, le=255)]


class OneEuroConfig(_Section):
    min_cutoff: PositiveFloat
    beta: Annotated[float, Field(ge=0)]
    d_cutoff: PositiveFloat


class HeadOneEuroConfig(_Section):
    """Per-axis One Euro for the head angles (scripts/tune_one_euro.py, docs/eval/one-euro-*.md)."""

    yaw: OneEuroConfig
    pitch: OneEuroConfig
    roll: OneEuroConfig


class FiltersConfig(_Section):
    one_euro: OneEuroConfig  # default for continuous signals without their own tuning
    one_euro_head: HeadOneEuroConfig
    unknown_below_conf: Fraction


class PassengerConfig(_Section):
    asleep_closed_s: PositiveFloat  # AP2: eyes closed this long -> awake = false


class WorkersConfig(_Section):
    restart_backoff_s: PositiveFloat  # first restart delay after a camera process died
    restart_backoff_max_s: PositiveFloat
    stale_s: PositiveFloat  # no message from a live worker for this long -> it hangs: restart it
    first_frame_timeout_s: PositiveFloat


class OutputConfig(_Section):
    ws_url: Annotated[str, StringConstraints(pattern=r"^wss?://.+")]
    ws_reconnect_s: PositiveFloat
    ws_reconnect_max_s: PositiveFloat
    proposed_fields: bool  # also send the fields proposed for the contract (docs/perception.md §9)
    publish_hz: Annotated[float, Field(gt=0, le=60)]
    mjpeg_port: Annotated[int, Field(ge=1024, le=65535)]
    video_width: Annotated[int, Field(ge=160, le=1920)]
    video_fps: Annotated[float, Field(gt=0, le=60)]
    jpeg_quality: Annotated[int, Field(ge=10, le=100)]


# --- root ----------------------------------------------------------------------------------------------


class PerceptionConfig(_Section):
    cameras: CamerasConfig
    models: ModelsConfig
    face: FaceConfig
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
    passenger: PassengerConfig
    filters: FiltersConfig
    workers: WorkersConfig
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
