"""frame_builder.py: newest camera results -> a valid PerceptionFrame (defaults, capture time, data age, modules)."""

from __future__ import annotations

import logging
import time
import typing
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from pydantic import BaseModel

from perception import frame_builder
from perception.config import PerceptionConfig, load_config
from perception.contract import PerceptionFrame
from perception.driver_cam.pipeline import DriverPipeline
from perception.features import FaceFeatures, FeatureFrame
from perception.frame_builder import build_frame, build_valid_frame, deep_merge, register_mapper
from tests.perception.driver_factory import H, W, frames

MAX_AGE_MS = 1000.0


@pytest.fixture(scope="module")
def cfg() -> PerceptionConfig:
    return load_config()


@pytest.fixture(scope="module")
def state(cfg: PerceptionConfig) -> dict[str, Any]:
    pipeline = DriverPipeline(cfg, (W, H))
    out = None
    for ff in frames([(3.0, {"ear_left": 0.30})]):
        out = pipeline.update(ff)
    assert out is not None
    return out.model_dump(mode="json")


def _msg(state: dict[str, Any], camera: str, t_capture: float, t_wall: float, **extra: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "kind": "frame",
        "camera": camera,
        "seq": 5,
        "t_capture": t_capture,
        "t_wall": t_wall,
        "connected": True,
        "state": state,
        "phone": {"in_use": False, "conf": 0.1, "near_face": False, "side": None},
        "gesture": None,
        "dialog_open": False,
        "monitoring": {"ok": True, "reason": None, "face_missing_s": 0.0},
        "luma": 110.0,
        "modules": ["detectors", "phone", "gesture", "monitoring"],
        "commands": ["debug", "dialog_window"],
        "perf": {
            "models": {"face": {"p50": 9.0, "p95": 11.0, "n": 120.0}},
            "capture_fps": 30.0,
            "process_fps": 29.5,
            "dropped_frames": 2,
            "dropped_results": 1,
        },
    }
    msg.update(extra)
    return msg


def _build(cfg: PerceptionConfig, **kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "seq": 1,
        "driver": None,
        "passenger": None,
        "cameras": {"driver": True},
        "e2e_ms_p95": None,
        "system": {},
        "max_age_ms": MAX_AGE_MS,
    }
    return build_valid_frame(cfg, **{**base, **kwargs})


@pytest.fixture
def no_mappers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(frame_builder, "_MAPPERS", {})
    monkeypatch.setattr(frame_builder, "_patch_errors_logged", set())
    yield


def test_defaults_only_frame_is_valid(cfg: PerceptionConfig) -> None:
    frame = _build(cfg, cameras={"driver": False}, publish_ts=1763672400.5)
    parsed = PerceptionFrame.model_validate(frame)
    assert parsed.driver.eyes.ear is None and parsed.driver.eyes.microsleep is False
    assert parsed.driver.gaze.zone == "unknown" and parsed.driver.phone.in_use is False
    assert parsed.passenger.present is False and parsed.occupants == []
    assert frame["ts"] == 1763672400.5  # no driver data: publication time
    assert frame["driver"]["monitoring_reason"] == "camera_unavailable"
    assert frame["perf"]["cameras"]["driver"]["available"] is False


def test_defaults_only_in_strict_mode(cfg: PerceptionConfig) -> None:
    """Strict mode: P1 writes only the plan §7 fields. The P1 additions (``eyes.state``, ``monitoring_reason``,
    ``perf.cameras.*.available``, ``publish_ts``) are part of contract v2.0 (shared/contracts.py) with defaults, so the
    VALIDATED frame always carries them, on their defaults; what P1 itself writes is checked before validation."""
    strict = cfg.model_copy(update={"output": cfg.output.model_copy(update={"proposed_fields": False})})
    kwargs: dict[str, Any] = {
        "seq": 1,
        "driver": None,
        "passenger": None,
        "cameras": {"driver": False},
        "e2e_ms_p95": None,
        "system": {},
        "max_age_ms": MAX_AGE_MS,
        "publish_ts": 1.0,
    }
    written = build_frame(strict, **kwargs)
    assert written["driver"] == {}  # no driver data: nothing written, not even the proposed eyes.state
    assert set(written["perf"]["cameras"]["driver"]) == {"capture_fps", "process_fps", "dropped_frames"}
    assert "publish_ts" not in written["perf"]
    frame = build_valid_frame(strict, **kwargs)
    assert frame["driver"]["eyes"]["ear"] is None
    assert frame["driver"]["eyes"].get("state", "UNKNOWN") == "UNKNOWN"  # contract default
    assert frame["driver"].get("monitoring_reason") is None
    assert frame["perf"].get("publish_ts") is None


def _null_required(model: type[BaseModel], data: Any, path: str = "") -> list[str]:
    """Paths of fields the contract declares without ``None`` that hold null (recursing into nested models)."""
    bad: list[str] = []
    if not isinstance(data, dict):
        return bad
    for name, info in model.model_fields.items():
        key = info.alias or name
        if key not in data:
            continue
        value, ann = data[key], info.annotation
        nullable = ann is None or type(None) in typing.get_args(ann) or ann is type(None)
        if value is None and not nullable:
            bad.append(f"{path}{key}")
        sub = ann if isinstance(ann, type) and issubclass(ann, BaseModel) else None
        if sub is not None:
            bad += _null_required(sub, value, f"{path}{key}.")
        elif typing.get_origin(ann) is dict and isinstance(value, dict):
            args = typing.get_args(ann)
            if len(args) == 2 and isinstance(args[1], type) and issubclass(args[1], BaseModel):
                for k, v in value.items():
                    bad += _null_required(args[1], v, f"{path}{key}.{k}.")
    return bad


def test_empty_pipeline_result_gives_a_valid_frame(cfg: PerceptionConfig) -> None:
    """No face on either camera and minimal worker messages (no monitoring confidence, no phone result): every
    numeric field the contract declares without null is a number. ``face_conf`` is 0.0 without a face (P1's choice;
    contract 2.1 also accepts null there)."""
    pipeline = DriverPipeline(cfg, (W, H))
    out = None
    no_face = FaceFeatures(present=False, conf=0.0)
    for i in range(30):
        out = pipeline.update(FeatureFrame(t=i / 30.0, frame_id=i + 1, camera="driver", face=no_face))
    assert out is not None and out.face.present is False
    empty = out.model_dump(mode="json")
    now = time.perf_counter()
    minimal: dict[str, Any] = {"monitoring": {}, "phone": {}, "perf": {}, "modules": []}
    frame = _build(
        cfg,
        driver=_msg(empty, "driver", now, time.time(), **minimal),
        passenger=_msg(empty, "passenger", now, time.time(), **minimal),
        cameras={"driver": True, "passenger": True},
        now_perf=now,
        publish_ts=time.time(),
    )
    shared = pytest.importorskip("shared.contracts")
    parsed = shared.PerceptionFrame.model_validate(frame)
    assert parsed.driver.face_conf == 0.0
    assert _null_required(shared.PerceptionFrame, frame) == []


def test_full_frame_with_capture_time(cfg: PerceptionConfig, state: dict[str, Any]) -> None:
    now = time.perf_counter()
    wall = time.time() - 0.04
    frame = _build(
        cfg,
        driver=_msg(state, "driver", now - 0.04, wall),
        passenger=_msg(state, "passenger", now - 0.08, wall - 0.04),
        cameras={"driver": True, "passenger": True},
        e2e_ms_p95=55.0,
        system={"cpu": 20.0, "ram_mb": 800.0, "gpu": None},
        now_perf=now,
        publish_ts=wall + 0.04,
    )
    parsed = PerceptionFrame.model_validate(frame)
    assert frame["ts"] == round(wall, 3)  # capture of the newest driver frame, not the publication
    assert frame["perf"]["publish_ts"] == round(wall + 0.04, 3)
    assert [o.seat for o in parsed.occupants] == ["driver", "front_right"]
    assert parsed.driver.eyes.reliable and parsed.passenger.present
    cams = frame["perf"]["cameras"]
    assert cams["driver"]["age_ms"] == pytest.approx(40.0, abs=1.0)
    assert cams["passenger"]["age_ms"] == pytest.approx(80.0, abs=1.0)
    assert cams["driver"]["capture_ts"] == round(wall, 3)
    assert cams["driver"]["available"] and cams["driver"]["dropped_results"] == 1
    assert parsed.perf.face_driver_ms_p50 == 9.0 and parsed.perf.face_passenger_ms_p50 == 9.0


def test_stale_results_count_as_no_data(cfg: PerceptionConfig, state: dict[str, Any]) -> None:
    now = time.perf_counter()
    old = now - (MAX_AGE_MS + 500) / 1000.0
    frame = _build(
        cfg,
        driver=_msg(state, "driver", old, 1763672399.0),
        passenger=_msg(state, "passenger", old, 1763672399.0),
        cameras={"driver": True, "passenger": True},
        now_perf=now,
        publish_ts=1763672400.5,
    )
    assert frame["ts"] == 1763672400.5  # stale driver data: publication time
    assert frame["driver"]["monitoring_reason"] == "no_frames"  # worker up, no fresh frame
    assert frame["passenger"]["present"] is False
    assert frame["occupants"] == []
    for cam in ("driver", "passenger"):
        assert frame["perf"]["cameras"][cam]["available"] is False
        assert frame["perf"]["cameras"][cam]["age_ms"] == pytest.approx(MAX_AGE_MS + 500, abs=2.0)


def test_status_heartbeat_is_not_frame_data(cfg: PerceptionConfig) -> None:
    status = {"kind": "status", "camera": "driver", "t_capture": time.perf_counter(), "connected": False}
    frame = _build(cfg, driver=status, now_perf=time.perf_counter(), publish_ts=2.0)
    assert frame["ts"] == 2.0 and frame["driver"]["monitoring_ok"] is False


def test_module_patch_is_merged(cfg: PerceptionConfig, state: dict[str, Any], no_mappers: None) -> None:
    now = time.perf_counter()
    msg = _msg(
        state,
        "driver",
        now,
        time.time(),
        modules=["detectors", "head_answer"],
        frame_patch={"head_answer": {"driver": {"head": {"answer": "yes"}}}},
    )
    frame = _build(cfg, driver=msg, now_perf=now)
    assert frame["driver"]["head"]["answer"] == "yes"
    assert frame["driver"]["head"]["yaw"] == state["head"]["yaw"]  # deep merge keeps the rest


def test_invalid_patch_is_dropped_and_logged_once(
    cfg: PerceptionConfig, state: dict[str, Any], no_mappers: None, caplog: pytest.LogCaptureFixture
) -> None:
    now = time.perf_counter()
    msg = _msg(state, "driver", now, time.time(), frame_patch={"bad": {"driver": {"head": {"answer": "maybe"}}}})
    logging.getLogger("perception").propagate = True
    with caplog.at_level(logging.ERROR, logger="perception.frame_builder"):
        first = _build(cfg, driver=msg, now_perf=now)
        second = _build(cfg, seq=2, driver=msg, now_perf=now)
    assert first["driver"]["head"]["answer"] is None and second["seq"] == 2  # the stream goes on
    assert first["driver"]["eyes"]["reliable"] is True  # the rest of the frame is intact
    errors = {id(r) for r in caplog.records if "module patch" in r.getMessage()}
    assert len(errors) == 1


def test_registered_mapper_for_lists(cfg: PerceptionConfig, state: dict[str, Any], no_mappers: None) -> None:
    @register_mapper("identity")
    def _identity(frame: dict[str, Any], msg: Mapping[str, Any], camera: str, _cfg: PerceptionConfig) -> None:
        seat = "driver" if camera == "driver" else "front_right"
        for occ in frame["occupants"]:
            if occ["seat"] == seat:
                occ["profile"] = msg["identity"]["profile"]

    now = time.perf_counter()
    msg = _msg(state, "driver", now, time.time(), modules=["detectors", "identity"], identity={"profile": "andrei"})
    frame = _build(cfg, driver=msg, now_perf=now)
    assert frame["occupants"][0]["profile"] == "andrei"


def test_build_frame_without_patches(cfg: PerceptionConfig, state: dict[str, Any]) -> None:
    now = time.perf_counter()
    msg = _msg(state, "driver", now, time.time(), frame_patch={"x": {"driver": {"gesture": "Thumb_Up"}}})
    kwargs: dict[str, Any] = {
        "seq": 1,
        "driver": msg,
        "passenger": None,
        "cameras": {"driver": True},
        "e2e_ms_p95": None,
        "system": {},
        "now_perf": now,
    }
    assert build_frame(cfg, **kwargs)["driver"]["gesture"] == "Thumb_Up"
    assert build_frame(cfg, **kwargs, patches=False)["driver"]["gesture"] is None


def test_deep_merge() -> None:
    base: dict[str, Any] = {"a": {"b": 1, "c": {"d": 2}}, "e": [1]}
    deep_merge(base, {"a": {"c": {"d": 3, "f": 4}}, "e": [2], "g": {"h": 5}})
    assert base == {"a": {"b": 1, "c": {"d": 3, "f": 4}}, "e": [2], "g": {"h": 5}}


def test_fallback_camera_is_reported(cfg: PerceptionConfig, state: dict[str, Any]) -> None:
    """A camera opened through the development fallback says so (unless the monitor has a real reason)."""
    now = time.perf_counter()
    fallback = {"device": "0", "via": "fallback", "name": "Integrated Camera"}
    frame = _build(cfg, driver=_msg(state, "driver", now, time.time(), capture=fallback), now_perf=now)
    assert frame["driver"]["monitoring_reason"] == "camera_fallback"
    lost = {"ok": False, "reason": "face_lost", "face_missing_s": 3.0}
    frame = _build(cfg, driver=_msg(state, "driver", now, time.time(), capture=fallback, monitoring=lost), now_perf=now)
    assert frame["driver"]["monitoring_reason"] == "face_lost"
    usb = {"device": "1", "via": "usb", "name": "Logi C615 HD WebCam"}
    frame = _build(cfg, driver=_msg(state, "driver", now, time.time(), capture=usb), now_perf=now)
    assert frame["driver"]["monitoring_reason"] is None


def test_nodding_switch_and_posture_defaults_keep_the_frame_shape(cfg: PerceptionConfig, state: dict[str, Any]) -> None:
    nodding = {**state, "head": {**state["head"], "nodding": True}}
    now = time.perf_counter()
    on = _build(cfg, driver=_msg(nodding, "driver", now, time.time()), now_perf=now)
    off_cfg = cfg.model_copy(update={"demo": cfg.demo.model_copy(update={"nodding_triggers": False})})
    off = _build(off_cfg, driver=_msg(nodding, "driver", now, time.time()), now_perf=now)
    assert on["driver"]["head"]["nodding"] is True and off["driver"]["head"]["nodding"] is False
    states = ("leaning_forward", "leaning_side", "slumped", "out_of_position")
    assert on["driver"]["posture"] == dict.fromkeys(states, False)
