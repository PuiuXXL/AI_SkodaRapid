"""Validated perception config, loaded from ``perception/config/perception.yaml``.

The YAML is the only place where perception values live. The models below declare types and allowed ranges
but **no default values**, so a missing key fails at start-up instead of silently falling back to a number
hidden in code. Unknown keys are rejected too (typos fail loudly).
"""

from __future__ import annotations

import re
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
    # second way to find the camera when the usb: selector matches nothing: a unique, case-insensitive substring of
    # the device's friendly name ("C615"); null = no name fallback
    device_name: Annotated[str, StringConstraints(min_length=1)] | None
    # models work on one copy resized to this width (null = capture size): 1080p capture, 720p processing
    process_width: Annotated[int, Field(ge=160, le=3840)] | None
    controls: CameraControls


class CamerasConfig(_Section):
    driver: CameraConfig
    passenger: CameraConfig
    # development only: a camera found neither by usb: selector nor by name takes a device no camera claims (preferring
    # one whose name contains fallback_name, e.g. the laptop's integrated camera); the driver has priority. The frame
    # then reports monitoring_reason="camera_fallback".
    dev_fallback: bool
    fallback_name: Annotated[str, StringConstraints(min_length=1)] | None

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
    eye_state: str  # open-closed-eye-0001 (eye-crop CNN, perception/driver_cam/eye_cnn.py)
    # ONNX Runtime intra-op threads per session (0 = ORT default = all physical cores). One process per camera, each
    # with several sessions: the default oversubscribes the CPU when both cameras run (docs/benchmark/*-dual.md).
    onnx_threads: Annotated[int, Field(ge=0, le=64)] = 0
    phone_threads: Annotated[int, Field(ge=0, le=64)] = 0  # CPU threads of the phone detector (0 = onnx_threads)

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


class EyeCnnConfig(_Section):
    enabled: bool  # used when the model file is present; without it the detector runs on EAR + blendshapes only
    crop_scale: PositiveFloat  # square crop side = this x the eye-corner distance
    open_max: Fraction  # p(closed) below this on the reliable eyes = clearly open: vetoes a closure plateau
    closed_min: Fraction  # p(closed) at or above this = clearly closed: confirms a plateau

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.open_max >= self.closed_min:
            raise ValueError("eyes.cnn.open_max must be lower than eyes.cnn.closed_min")
        return self


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
    reopen_min_frames: Annotated[int, Field(ge=1, le=10)]  # consecutive frames above the reopen level end a closure
    closure_gap_max_ms: Annotated[float, Field(ge=0)]  # face / eyes unreliable this long keeps a closure going
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
    squint_veto: Fraction  # eyeSquint at or above this, ratio inside the band -> squint, never closed (1.0 = off)
    # PERCLOS P80
    closed_level_default: RatioOfRef
    perclos_closure: RatioOfRef
    perclos_window_s: PositiveFloat
    min_eye_width_px: Annotated[float, Field(ge=1)]
    unreliable_when_face_small: bool  # face narrower than face.min_face_width_px -> eyes unreliable (no verdict)
    cnn: EyeCnnConfig

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
    closed_recent_s: PositiveFloat  # a closure longer than a blink within this long arms the nod (lids may read SQUINT)
    max_gap_s: Annotated[float, Field(ge=0)]  # face lost this long keeps the pitch history (the head falls out of view)
    hold_s: Annotated[float, Field(ge=0)]  # a detected nod is reported this long, also on frames without a face


class HeadAnswerConfig(_Section):
    """AS8 yes / no from the head (perception/driver_cam/head_answer.py), only inside an open dialog window."""

    min_reversals: Annotated[int, Field(ge=1, le=10)]  # zero crossings of the detrended angle (Schmitt trigger)
    window_s: PositiveFloat
    min_amplitude_deg: PositiveFloat  # peak-to-peak; the Schmitt trigger sits at +- half of it
    slow_tau_s: PositiveFloat  # slow mean (EMA time constant) subtracted from yaw and pitch
    dominance_ratio: Annotated[float, Field(ge=1)]  # both axes oscillate: the answer axis needs this x the other RMS
    max_closed_ms: Annotated[float, Field(ge=0)]  # eyes closed longer than this reset the count (a fatigue nod)
    answer_hold_s: Annotated[float, Field(ge=0)]  # a detected answer is reported this long
    max_gap_s: PositiveFloat  # no angles for longer (face lost, implausible pose) -> state reset


class PlausibleAnglesConfig(_Section):
    yaw: PositiveFloat
    pitch: PositiveFloat
    roll: PositiveFloat


class HeadConfig(_Section):
    nod: NodConfig
    answer: HeadAnswerConfig
    plausible_deg: PlausibleAnglesConfig


class GazeGroupValues(_Section):
    """One value per gaze feature group: head yaw/pitch, MobileGaze yaw/pitch, eyeLook blendshapes, iris offset."""

    head: Annotated[float, Field(ge=0)]
    gaze: Annotated[float, Field(ge=0)]
    eye_look: Annotated[float, Field(ge=0)]
    iris: Annotated[float, Field(ge=0)]


class GazeCalibrationConfig(_Section):
    s_per_zone: PositiveFloat  # per zone and mode (owl / lizard)
    modes: Annotated[list[Literal["owl", "lizard"]], Field(min_length=1)]
    road_factor: Annotated[float, Field(ge=1)]  # road gets this many times more data
    discard_s: Annotated[float, Field(ge=0)]  # dropped after every prompt (reaction time)
    owl_min_head_deg: Annotated[float, Field(ge=0)]  # OWL zone head this close to the road -> calibration warning
    transition_s: Annotated[float, Field(ge=0)]  # "back to the road" between zones, not recorded
    min_samples_per_zone: PositiveInt
    quick_zones: Annotated[list[CalibratedZone], Field(min_length=1)]
    quick_s_per_zone: PositiveFloat
    quick_transition_s: Annotated[float, Field(ge=0)]


class RearSeatConfig(_Section):
    """AS13: face lost right after a growing yaw towards the passenger side -> rear_seat (switch demo.rear_seat)."""

    min_yaw_deg: PositiveFloat
    min_rise_deg: Annotated[float, Field(ge=0)]
    rising_s: PositiveFloat
    max_gap_s: PositiveFloat
    max_s: PositiveFloat
    right_sign: Literal[-1, 1]  # sign of the raw yaw when the head turns right (towards the passenger)


class GazeConfig(_Section):
    zones: Annotated[list[CalibratedZone], Field(min_length=2)]
    crop_expand: Annotated[float, Field(ge=1.0, le=2.0)]  # MobileGaze crop = face box x this (yakhyo: 1.0)
    max_age_ms: PositiveFloat  # a MobileGaze result older than this is not used
    k: Annotated[int, Field(ge=1, le=50)]
    feature_weights: GazeGroupValues  # applied to the z-scored groups before the kNN distance
    std_floor: GazeGroupValues  # z-score std floor per group (feature units), so a near-constant feature cannot explode
    reject_factor: PositiveFloat  # tau = p95 of the blocked-LOO kNN distances x this
    loo_exclude_s: Annotated[float, Field(ge=0)]  # blocked LOO: same-segment samples this close in time are left out
    min_conf: Fraction
    zone_min_frames: PositiveInt
    rear_seat: RearSeatConfig
    unknown_hold_s: Annotated[float, Field(ge=0)]  # a classifier "unknown" keeps the last zone this long (no flicker)
    away_margin_deg: Annotated[float, Field(ge=0)]
    on_road_zones: Annotated[list[CalibratedZone], Field(min_length=1)]
    mirror_zones: list[CalibratedZone]
    mirror_glance_max_ms: PositiveFloat
    vats_max_glance_s: PositiveFloat
    window_s: PositiveFloat
    default_profile: str | None
    calibration: GazeCalibrationConfig

    @model_validator(mode="after")
    def _check(self) -> Self:
        if "road" not in self.zones:
            raise ValueError("gaze.zones must contain 'road'")
        if len(set(self.zones)) != len(self.zones):
            raise ValueError("gaze.zones contains duplicates")
        for key, listed in (
            ("on_road_zones", self.on_road_zones),
            ("mirror_zones", self.mirror_zones),
            ("calibration.quick_zones", self.calibration.quick_zones),
        ):
            missing = set(listed) - set(self.zones)
            if missing:
                raise ValueError(f"gaze.{key} has zones not in gaze.zones: {sorted(missing)}")
        if set(self.on_road_zones) & set(self.mirror_zones):
            raise ValueError("gaze.on_road_zones and gaze.mirror_zones overlap")
        if self.default_profile is not None and not re.fullmatch(r"[A-Za-z0-9_-]+", self.default_profile):
            raise ValueError("gaze.default_profile must be letters, digits, '-' or '_'")
        return self


class LapPatternConfig(_Section):
    min_glances: PositiveInt
    window_s: PositiveFloat
    long_glance_s: PositiveFloat
    conf: Fraction
    hands_recent_s: PositiveFloat  # hands seen within this -> no lap pattern


class PhoneConfig(_Section):
    class_id: Annotated[int, Field(ge=0, le=79)]
    conf_min: Fraction
    vote_window: Annotated[int, Field(ge=1, le=30)]
    vote_min: Annotated[int, Field(ge=1, le=30)]
    near_face_ratio: PositiveFloat
    hand_radius_ratio: PositiveFloat  # palm / wrist within this x face width of the box -> phone in that hand
    foreign_dx_ratio: PositiveFloat  # passenger side, farther than this x face width, not near the face -> foreign
    passenger_side: Literal["left", "right"]  # the passenger's side in the DRIVER's terms (left-hand-drive car)
    mirrored: bool  # the camera image is mirrored (False: image right = the driver's left)
    owned_needs_contact: bool  # a driver phone must be near the face or in a hand to vote (AS7 geometry)
    async_inference: bool  # YOLO in its own thread: the face never waits for it (the result is 1-2 frames older)
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
    top_k: PositiveInt
    min_face_px: PositiveFloat  # smaller YuNet boxes are ignored
    retry_s: PositiveFloat  # Face Landmarker sees a face but YuNet did not: retry this soon
    lost_s: PositiveFloat  # face absent this long -> the next face is a NEW face (identified at once)
    enroll_interval_s: Annotated[float, Field(ge=0)]  # at least this between two enrollment frames
    enroll_min_face_px: PositiveFloat  # enrollment needs a closer face than recognition
    enroll_min_sharpness: Annotated[float, Field(ge=0)]  # variance of the Laplacian on the aligned 112x112 crop
    enroll_min_consistency: Annotated[float, Field(gt=-1, lt=1)]  # every frame's cosine to the mean at least this


class MonitoringConfig(_Section):
    face_lost_s: PositiveFloat
    frozen_frame_s: PositiveFloat
    frozen_pixel_diff: Annotated[float, Field(ge=0)]
    dark_luma: Annotated[float, Field(ge=0, le=255)]
    no_frames_s: PositiveFloat  # no frame for this long -> no_frames
    occluded_std_max: Annotated[float, Field(ge=0)]  # luma std below this = uniform image (lens covered)
    blur_var_min: Annotated[float, Field(ge=0)]  # Laplacian variance below this = blurred
    covered_s: PositiveFloat  # AS12 / AP5 fast path: no face + very dark / uniform / sharpless this long -> occluded
    covered_luma_max: Annotated[float, Field(ge=0, le=255)]
    covered_sharpness_max: Annotated[float, Field(ge=0)]
    mono_chroma_max: Annotated[float, Field(ge=0)]  # mean |R-G|, |B-G| below this = monochrome (IR night mode)
    mode_switch_luma_delta: PositiveFloat  # luma jump between frames, image still structured -> mode_switch
    mode_switch_hold_s: Annotated[float, Field(ge=0)]
    analysis_width: Annotated[int, Field(ge=16, le=1920)]  # image statistics on a frame resized to this width


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
    one_euro_gaze: OneEuroConfig  # MobileGaze yaw / pitch (runs at rates.gaze_hz)
    unknown_below_conf: Fraction


class DemoConfig(_Section):
    """Demo switches: a detection that misses its target is turned off here (its frame fields keep the defaults)."""

    head_answer: bool  # AS8 yes / no from the head (HeadAnswerModule on both cameras)
    posture_driver: bool  # PostureModule on the driver camera
    posture_passenger: bool  # PostureModule on the passenger camera
    nodding_triggers: bool  # AS4 driver.head.nodding may be true (false: always false in the frame)
    rear_seat: bool  # AS13 rear_seat zone after a large right yaw with the face lost


class PassengerConfig(_Section):
    open_reset_frames: PositiveInt  # consecutive open frames needed to reset the closed time (noise immunity)
    closed_ratio: Annotated[float, Field(gt=0, lt=1)]  # eye ratio (EAR / reference) below this = closed (AP2)
    asleep_closed_s: PositiveFloat  # AP2: eyes not seen open for this long (passenger present) -> awake = false
    asleep_closed_head_s: PositiveFloat  # ... or this long with the head dropped (plan AP2: eyes closed + head down)
    head_drop_deg: PositiveFloat  # head pitch this far below the passenger's upright pitch = dropped
    upright_window_s: PositiveFloat  # upright pitch = median pitch with the eyes open over this window


class PostureConfig(_Section):
    """Posture vs. a reference (perception/posture.py); distances in reference face widths."""

    auto_ref_s: PositiveFloat  # no calibration reference: median of the first seconds with the face seen
    forward_width_ratio: Annotated[float, Field(gt=1)]
    side_shift_ratio: PositiveFloat
    side_roll_deg: PositiveFloat
    slumped_drop_ratio: PositiveFloat
    slumped_pitch_deg: PositiveFloat
    out_shift_ratio: PositiveFloat
    out_width_ratio: Annotated[list[PositiveFloat], Field(min_length=2, max_length=2)]
    min_duration_s: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        low, high = self.out_width_ratio
        if not low < 1 < high:
            raise ValueError("posture.out_width_ratio must be [low < 1, high > 1]")
        return self


class HandsConfig(_Section):
    """MediaPipe Gesture Recognizer as a hand tracker (perception/hands.py): AS9 / AP6 + hand positions (AS7)."""

    num_hands: Annotated[int, Field(ge=1, le=4)]
    min_hand_detection_conf: Fraction
    min_hand_presence_conf: Fraction
    min_tracking_conf: Fraction
    background_hz: Annotated[float, Field(ge=0)]  # outside the dialog window (hand positions, raised hand); 0 = off
    dialog_hz: Annotated[float, Field(ge=0)]  # inside the dialog window; 0 = every frame
    dropout_ms: Annotated[float, Field(ge=0)]  # a run without the gesture is tolerated this long (flicker)
    max_gap_s: PositiveFloat  # observations further apart break the hold
    raised_margin: float  # palm above face bottom + this x face height = raised hand
    raised_y_frac: Fraction  # no face box: palm above this fraction of the frame height = raised
    raised_boost_s: Annotated[float, Field(ge=0)]  # a raised hand outside the window switches to the dialog rate


class WorkersConfig(_Section):
    modules: dict[Literal["driver", "passenger"], list[str]]  # extra PipelineModule classes "package.module:Class"
    restart_backoff_s: PositiveFloat  # first restart delay after a camera process died
    restart_backoff_max_s: PositiveFloat
    stale_s: PositiveFloat  # no message from a running worker for this long -> it hangs: restart it
    startup_s: PositiveFloat  # allowed silence before the first frame (camera open + model load)
    first_frame_timeout_s: PositiveFloat  # still opening after this long -> reported camera_unavailable
    unavailable_report_s: PositiveFloat  # a camera that is not there: camera_unavailable logged this often (no restart)


class OutputConfig(_Section):
    ws_url: Annotated[str, StringConstraints(pattern=r"^wss?://.+")]
    ws_reconnect_s: PositiveFloat
    ws_reconnect_max_s: PositiveFloat
    proposed_fields: bool  # also send the fields proposed for the contract (docs/perception.md §9)
    result_max_age_ms: PositiveFloat  # a camera's newest result older than this = no data from that camera
    mjpeg_host: Annotated[str, StringConstraints(min_length=1)]
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
    hands: HandsConfig
    identity: IdentityConfig
    monitoring: MonitoringConfig
    passenger: PassengerConfig
    posture: PostureConfig
    demo: DemoConfig
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
