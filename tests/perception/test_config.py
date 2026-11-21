from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from perception.config import DEFAULT_CONFIG_PATH, REPO_ROOT, ConfigError, PerceptionConfig, load_config


def _default_data() -> dict[str, Any]:
    data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "perception.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_default_config_loads() -> None:
    cfg = load_config()
    assert isinstance(cfg, PerceptionConfig)
    assert cfg.cameras.driver.enabled
    assert isinstance(cfg.cameras.driver.device, int | str)  # the index depends on the machine (0 laptop, 1 USB)
    assert (cfg.cameras.driver.width, cfg.cameras.driver.height, cfg.cameras.driver.fps) == (1280, 720, 30)
    assert cfg.cameras.driver.process_width is None  # 720p captured and processed as is
    assert cfg.cameras.driver.fourcc == "MJPG"
    assert cfg.output.publish_hz == 15
    assert cfg.output.mjpeg_port == 8001


def test_both_cameras_on_by_usb_id() -> None:
    """Both webcams run on one laptop (docs/benchmark/cameras-*.md); each is named by its USB id, never an index."""
    cams = load_config().cameras
    assert cams.driver.enabled and cams.passenger.enabled
    assert str(cams.driver.device).startswith("usb:") and str(cams.passenger.device).startswith("usb:")
    assert cams.driver.device != cams.passenger.device
    assert cams.driver.fourcc == cams.passenger.fourcc == "MJPG"  # two streams on one root hub need MJPG


def test_key_decisions_are_in_yaml() -> None:
    cfg = load_config()
    assert cfg.eyes.drop_ratio_relaxed <= cfg.eyes.drop_ratio < cfg.eyes.reopen_ratio
    assert cfg.eyes.ref_floor_ratio == pytest.approx(0.6)  # local EAR reference never below 0.6 x global
    assert cfg.eyes.squint_ear_band[1] == pytest.approx(cfg.eyes.drop_ratio)
    assert cfg.identity.cosine_threshold == pytest.approx(0.363)
    assert cfg.phone.class_id == 67
    assert (cfg.phone.vote_min, cfg.phone.vote_window) == (3, 5)
    assert cfg.yawn.min_duration_s == pytest.approx(1.5)
    assert "road" in cfg.gaze.zones and "passenger" in cfg.gaze.zones


def test_model_path_is_relative_to_repo_root() -> None:
    cfg = load_config()
    assert cfg.models.path("x.onnx") == REPO_ROOT / "perception" / "models" / "x.onnx"


def test_config_is_frozen() -> None:
    cfg = load_config()
    with pytest.raises(ValidationError):
        cfg.eyes.drop_ratio = 0.1  # type: ignore[misc]


def test_tmp_yaml_loads(tmp_path: Path) -> None:
    data = _default_data()
    data["cameras"]["passenger"]["enabled"] = True
    cfg = load_config(_write(tmp_path, data))
    assert cfg.cameras.passenger.enabled is True


def test_drop_ratio_must_be_below_reopen_ratio(tmp_path: Path) -> None:
    data = _default_data()
    data["eyes"]["drop_ratio"] = 0.9
    data["eyes"]["reopen_ratio"] = 0.8
    with pytest.raises(ValidationError, match="drop_ratio"):
        load_config(_write(tmp_path, data))


def test_unknown_key_rejected(tmp_path: Path) -> None:
    data = _default_data()
    data["eyes"]["ear_treshold"] = 0.2
    with pytest.raises(ValidationError, match="ear_treshold"):
        load_config(_write(tmp_path, data))


def test_missing_key_rejected(tmp_path: Path) -> None:
    data = _default_data()
    del data["phone"]["conf_min"]
    with pytest.raises(ValidationError, match="conf_min"):
        load_config(_write(tmp_path, data))


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("phone", "vote_min", 6),
        ("eyes", "ref_floor_ratio", 1.2),
        ("output", "publish_hz", 60),
        ("output", "ws_url", "http://localhost:8000"),
        ("identity", "cosine_threshold", 1.5),
        # face / eye rules (R-FL1, R-FL4)
        ("face", "num_faces", 2),
        ("eyes", "squint_ear_band", [0.8, 0.5]),
        ("eyes", "squint_ear_band", [0.5]),
        ("eyes", "drop_ratio_relaxed", 0.9),
        ("models", "gaze_providers", ["CUDAExecutionProvider"]),
    ],
)
def test_invalid_values_rejected(tmp_path: Path, section: str, key: str, value: object) -> None:
    data = _default_data()
    data[section][key] = value
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, data))


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("gaze", "zones", ["mirror_left", "lap"], "road"),
        ("models", "onnx_providers", ["CPUExecutionProvider", "CUDAExecutionProvider"], "CPUExecutionProvider"),
    ],
)
def test_rule_violation_names_the_rule(tmp_path: Path, section: str, key: str, value: object, message: str) -> None:
    data = _default_data()
    data[section][key] = value
    with pytest.raises(ValidationError, match=message):
        load_config(_write(tmp_path, data))


def test_same_device_for_both_cameras_rejected(tmp_path: Path) -> None:
    data = _default_data()
    data["cameras"]["passenger"]["enabled"] = True
    data["cameras"]["passenger"]["device"] = data["cameras"]["driver"]["device"]
    with pytest.raises(ValidationError, match="must differ"):
        load_config(_write(tmp_path, data))


def test_face_landmarker_rules_in_yaml() -> None:
    cfg = load_config()
    assert cfg.face.num_faces == 1  # R-FL1
    assert (cfg.face.min_detection_conf, cfg.face.min_presence_conf, cfg.face.min_tracking_conf) == (0.5, 0.5, 0.6)
    assert cfg.face.min_face_width_px == 250  # R-FL3
    low, high = cfg.eyes.squint_ear_band  # R-FL4
    assert 0 < low < high < 1


def test_camera_controls_and_reconnect() -> None:
    cam = load_config().cameras.driver
    assert cam.controls.power_line_hz == 50
    assert cam.controls.autofocus is False
    # laptop profile: auto modes set explicitly to undo manual values the camera driver remembers
    assert cam.controls.auto_exposure is True and cam.controls.exposure_ms is None
    assert cam.controls.auto_white_balance is True
    assert cam.controls.focus is None  # null = leave the camera's setting
    assert cam.reconnect_s > 0 and cam.max_read_failures >= 1


@pytest.mark.parametrize(
    ("key", "value"),
    [("power_line_hz", 55), ("exposure_ms", 0), ("white_balance_k", 500)],
)
def test_invalid_camera_controls_rejected(tmp_path: Path, key: str, value: object) -> None:
    data = _default_data()
    data["cameras"]["driver"]["controls"][key] = value
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, data))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_non_mapping_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)
