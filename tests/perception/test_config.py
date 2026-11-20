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
    assert cfg.cameras.driver.device == 0
    assert (cfg.cameras.driver.width, cfg.cameras.driver.height, cfg.cameras.driver.fps) == (1280, 720, 30)
    assert cfg.cameras.driver.fourcc == "MJPG"
    assert cfg.output.publish_hz == 15
    assert cfg.output.mjpeg_port == 8001


def test_passenger_camera_disabled_by_default() -> None:
    assert load_config().cameras.passenger.enabled is False


def test_key_decisions_are_in_yaml() -> None:
    cfg = load_config()
    assert cfg.eyes.k_close < cfg.eyes.k_open
    assert cfg.eyes.median_frames == 3
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
        cfg.eyes.k_close = 0.1  # type: ignore[misc]


def test_tmp_yaml_loads(tmp_path: Path) -> None:
    data = _default_data()
    data["cameras"]["passenger"]["enabled"] = True
    cfg = load_config(_write(tmp_path, data))
    assert cfg.cameras.passenger.enabled is True


def test_k_close_must_be_below_k_open(tmp_path: Path) -> None:
    data = _default_data()
    data["eyes"]["k_close"] = 0.9
    data["eyes"]["k_open"] = 0.8
    with pytest.raises(ValidationError, match="k_close"):
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
        ("eyes", "median_frames", 4),
        ("output", "publish_hz", 60),
        ("output", "ws_url", "http://localhost:8000"),
        ("identity", "cosine_threshold", 1.5),
    ],
)
def test_invalid_values_rejected(tmp_path: Path, section: str, key: str, value: object) -> None:
    data = _default_data()
    data[section][key] = value
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, data))


def test_gaze_zones_need_road(tmp_path: Path) -> None:
    data = _default_data()
    data["gaze"]["zones"] = ["mirror_left", "lap"]
    with pytest.raises(ValidationError, match="road"):
        load_config(_write(tmp_path, data))


def test_onnx_providers_must_end_with_cpu(tmp_path: Path) -> None:
    data = _default_data()
    data["models"]["onnx_providers"] = ["CPUExecutionProvider", "CUDAExecutionProvider"]
    with pytest.raises(ValidationError, match="CPUExecutionProvider"):
        load_config(_write(tmp_path, data))


def test_same_device_for_both_cameras_rejected(tmp_path: Path) -> None:
    data = _default_data()
    data["cameras"]["passenger"]["enabled"] = True
    data["cameras"]["passenger"]["device"] = data["cameras"]["driver"]["device"]
    with pytest.raises(ValidationError, match="must differ"):
        load_config(_write(tmp_path, data))


def test_camera_controls_and_reconnect() -> None:
    cam = load_config().cameras.driver
    assert cam.controls.power_line_hz == 50
    assert cam.controls.autofocus is False
    assert cam.controls.auto_exposure is False
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
