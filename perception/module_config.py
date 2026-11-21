"""Module configurations built from the ONE validated config (``perception/config/perception.yaml``).

The interaction modules (hands, head answer, phone, identity, camera monitor) keep their own frozen dataclasses (they
are standalone and testable without a yaml file). Their values come from here, so every setting has exactly one
place in the yaml: keys that exist elsewhere (``gesture.min_score``, ``rates.phone_hz``, ``face.min_face_width_px``,
``monitoring.frozen_frame_s``, ...) are read from there, never duplicated.
"""

from __future__ import annotations

from pathlib import Path

from perception.config import PerceptionConfig
from perception.driver_cam.head_answer import HeadAnswerConfig as HeadAnswerSettings
from perception.hands import HandsConfig as HandsSettings
from perception.identity import IdentityConfig as IdentitySettings
from perception.monitoring import CameraMonitorConfig
from perception.phone import PhoneConfig as PhoneSettings

__all__ = ["camera_monitor_config", "hands_config", "head_answer_config", "identity_config", "phone_config"]

_CUDA = "CUDAExecutionProvider"


def hands_config(cfg: PerceptionConfig) -> HandsSettings:
    h, g = cfg.hands, cfg.gesture
    return HandsSettings(
        model=str(cfg.models.path(cfg.models.gesture_recognizer)),
        num_hands=h.num_hands,
        min_hand_detection_conf=h.min_hand_detection_conf,
        min_hand_presence_conf=h.min_hand_presence_conf,
        min_tracking_conf=h.min_tracking_conf,
        background_hz=h.background_hz,
        dialog_hz=h.dialog_hz,
        allowed=tuple(g.allowed),
        min_score=g.min_score,
        min_ms=g.min_duration_s * 1000.0,
        dropout_ms=h.dropout_ms,
        max_gap_s=h.max_gap_s,
        raised_margin=h.raised_margin,
        raised_y_frac=h.raised_y_frac,
        raised_boost_s=h.raised_boost_s,
    )


def head_answer_config(cfg: PerceptionConfig) -> HeadAnswerSettings:
    a = cfg.head.answer
    return HeadAnswerSettings(
        slow_tau_s=a.slow_tau_s,
        min_amplitude_deg=a.min_amplitude_deg,
        min_crossings=a.min_reversals,
        window_s=a.window_s,
        dominance_ratio=a.dominance_ratio,
        max_closed_ms=a.max_closed_ms,
        answer_hold_s=a.answer_hold_s,
        max_gap_s=a.max_gap_s,
    )


def _onnx_name(weights: str, imgsz: int) -> str:
    """The exported ONNX file of a YOLO variant (``scripts/download_models.sh``: ``<stem>_<imgsz>.onnx``)."""
    return f"{Path(weights).stem}_{imgsz}.onnx"


def phone_config(cfg: PerceptionConfig) -> PhoneSettings:
    p, m = cfg.phone, cfg.models
    return PhoneSettings(
        class_id=p.class_id,
        conf_min=p.conf_min,
        device=m.phone_device,
        cpu_model=str(m.path(_onnx_name(m.phone_cpu.weights, m.phone_cpu.imgsz))),
        cpu_imgsz=m.phone_cpu.imgsz,
        gpu_model=str(m.path(_onnx_name(m.phone_gpu.weights, m.phone_gpu.imgsz))),
        gpu_imgsz=m.phone_gpu.imgsz,
        cpu_providers=tuple(pr for pr in m.onnx_providers if pr != _CUDA),
        rate_hz=cfg.rates.phone_hz,
        vote_window=p.vote_window,
        vote_min=p.vote_min,
        near_face_ratio=p.near_face_ratio,
        hand_radius_ratio=p.hand_radius_ratio,
        foreign_dx_ratio=p.foreign_dx_ratio,
        passenger_side=p.passenger_side,
        mirrored=p.mirrored,
        lap_conf=p.lap_pattern.conf,
        threads=m.phone_threads,
    )


def identity_config(cfg: PerceptionConfig) -> IdentitySettings:
    i, m = cfg.identity, cfg.models
    return IdentitySettings(
        yunet_model=str(m.path(m.yunet)),
        sface_model=str(m.path(m.sface)),
        cosine_threshold=i.cosine_threshold,
        score_threshold=i.yunet_score_threshold,
        nms_threshold=i.yunet_nms_threshold,
        top_k=i.top_k,
        min_face_px=i.min_face_px,
        recheck_s=cfg.rates.identity_recheck_s,
        retry_s=i.retry_s,
        lost_s=i.lost_s,
        enroll_frames=i.enroll_frames,
        enroll_interval_s=i.enroll_interval_s,
        enroll_min_face_px=i.enroll_min_face_px,
        enroll_min_sharpness=i.enroll_min_sharpness,
        enroll_min_consistency=i.enroll_min_consistency,
    )


def camera_monitor_config(cfg: PerceptionConfig) -> CameraMonitorConfig:
    m = cfg.monitoring
    return CameraMonitorConfig(
        no_frames_s=m.no_frames_s,
        frozen_s=m.frozen_frame_s,
        frozen_pixel_diff=m.frozen_pixel_diff,
        face_lost_s=m.face_lost_s,
        dark_luma=m.dark_luma,
        occluded_std_max=m.occluded_std_max,
        blur_var_min=m.blur_var_min,
        mono_chroma_max=m.mono_chroma_max,
        mode_switch_luma_delta=m.mode_switch_luma_delta,
        mode_switch_hold_s=m.mode_switch_hold_s,
        min_face_width_px=float(cfg.face.min_face_width_px),
        analysis_width=m.analysis_width,
    )
