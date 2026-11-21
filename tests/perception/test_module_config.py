"""The interaction modules get their settings from the ONE validated config (perception/module_config.py).

The yaml values were moved from the former ``perception/config/pending/modules.yaml`` unchanged: the adapters must
reproduce every module's defaults (paths compared as files), and keys that exist elsewhere in the yaml must be read
from there (one value per setting).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from perception.config import REPO_ROOT, load_config
from perception.driver_cam.head_answer import HeadAnswerConfig
from perception.hands import HandsConfig
from perception.identity import IdentityConfig
from perception.module_config import (
    camera_monitor_config,
    hands_config,
    head_answer_config,
    identity_config,
    phone_config,
)
from perception.monitoring import CameraMonitorConfig
from perception.phone import PhoneConfig


def _same(got: Any, want: Any) -> None:
    for f in dataclasses.fields(want):
        a, b = getattr(got, f.name), getattr(want, f.name)
        if isinstance(b, str) and b.startswith("perception/"):
            assert Path(a).resolve() == (REPO_ROOT / b).resolve(), f.name
        else:
            assert a == b, f.name


@pytest.mark.parametrize(
    ("adapter", "defaults"),
    [
        (hands_config, HandsConfig()),
        (head_answer_config, HeadAnswerConfig()),
        (phone_config, PhoneConfig()),
        (identity_config, IdentityConfig()),
        (camera_monitor_config, CameraMonitorConfig()),
    ],
)
def test_adapters_reproduce_the_module_defaults(adapter: Any, defaults: Any) -> None:
    _same(adapter(load_config()), defaults)


def test_shared_keys_have_one_value() -> None:
    cfg = load_config()
    assert hands_config(cfg).min_ms == cfg.gesture.min_duration_s * 1000.0
    assert tuple(cfg.gesture.allowed) == hands_config(cfg).allowed
    assert head_answer_config(cfg).min_crossings == cfg.head.answer.min_reversals
    assert phone_config(cfg).rate_hz == cfg.rates.phone_hz
    assert phone_config(cfg).lap_conf == cfg.phone.lap_pattern.conf
    assert identity_config(cfg).recheck_s == cfg.rates.identity_recheck_s
    assert camera_monitor_config(cfg).frozen_s == cfg.monitoring.frozen_frame_s
    assert camera_monitor_config(cfg).min_face_width_px == cfg.face.min_face_width_px


def test_phone_models_follow_the_yolo_variants() -> None:
    cfg = load_config()
    p = phone_config(cfg)
    assert Path(p.cpu_model).name == f"{Path(cfg.models.phone_cpu.weights).stem}_{cfg.models.phone_cpu.imgsz}.onnx"
    assert "CUDAExecutionProvider" not in p.cpu_providers
