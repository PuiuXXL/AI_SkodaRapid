"""perf.py: p50 / p95 windows, rates, the contract perf block; the degradation rule as applied by the main process."""

from __future__ import annotations

import time
from typing import Any

import pytest

from perception.config import load_config
from perception.main import Perception
from perception.perf import (
    MODEL_FIELDS,
    LatencyWindow,
    PerfTracker,
    RateMeter,
    SystemMonitor,
    build_perf_block,
    percentile,
)
from perception.worker import WorkerOptions


def test_p50_p95_on_a_known_series() -> None:
    window = LatencyWindow(maxlen=120)
    for v in range(1, 101):  # 1..100 ms
        window.add(float(v))
    assert window.p50() == pytest.approx(50.5)
    assert window.p95() == pytest.approx(95.05)
    assert percentile([], 50) != percentile([], 50)  # NaN when empty


def test_window_keeps_only_the_last_120() -> None:
    window = LatencyWindow(maxlen=120)
    for v in range(200):
        window.add(float(v))
    assert window.snapshot() == [float(v) for v in range(80, 200)]
    assert window.p50() == pytest.approx(139.5)
    assert window.count == 200  # total ever added


def test_tracker_times_blocks_and_snapshots_plain_floats() -> None:
    perf = PerfTracker(maxlen=120)
    with perf.time("stage"):
        time.sleep(0.01)
    perf.add("face", 8.0)
    perf.add("face", 10.0)
    snap = perf.snapshot()
    assert snap["face"] == {"p50": 9.0, "p95": 9.9, "n": 2.0}
    assert snap["stage"]["p50"] is not None and snap["stage"]["p50"] >= 9.0


def test_rate_meter_with_a_fake_clock() -> None:
    now = [0.0]
    meter = RateMeter(window_s=1.0, clock=lambda: now[0])
    for i in range(10):
        meter.tick(i * 0.1)
    now[0] = 0.9
    assert meter.rate() == pytest.approx(10.0)
    now[0] = 5.0  # nothing in the last second
    assert meter.rate() == 0.0


def test_system_monitor_reports_cpu_and_ram() -> None:
    mon = SystemMonitor(min_interval_s=0.0)
    try:
        sample = mon.sample()
        assert set(sample) == {"cpu", "ram_mb", "gpu"}
        assert sample["ram_mb"] is not None and sample["ram_mb"] > 10
    finally:
        mon.close()


def _msg(models: dict[str, float], dropped_results: int = 0) -> dict[str, Any]:
    return {
        "kind": "frame",
        "perf": {
            "models": {name: {"p50": p50, "p95": p50 * 1.2, "n": 50.0} for name, p50 in models.items()},
            "capture_fps": 30.0,
            "process_fps": 29.0,
            "dropped_frames": 4,
            "dropped_results": dropped_results,
        },
    }


def test_perf_block_maps_models_to_contract_fields() -> None:
    perf = build_perf_block(
        {"driver": True, "passenger": True},
        {"driver": _msg({"face": 9.0, "phone": 18.0, "sface": 25.0}), "passenger": _msg({"face": 8.0, "gesture": 7.0})},
        e2e_ms_p95=95.0,
        system={"cpu": 61.0, "ram_mb": 2100.0, "gpu": 35.0},
        proposed=False,
    )
    assert perf["face_driver_ms_p50"] == 9.0 and perf["face_passenger_ms_p50"] == 8.0
    assert perf["phone_ms_p50"] == 18.0  # driver's value
    assert perf["gesture_ms_p50"] == 7.0  # only the passenger ran it
    assert perf["sface_ms_p50"] == 25.0  # a module attaching a "sface" window fills the field
    assert perf["pose_ms_p50"] is None  # nobody runs pose
    assert perf["e2e_ms_p95"] == 95.0 and perf["cpu"] == 61.0 and perf["gpu"] == 35.0
    assert perf["cameras"]["driver"] == {"capture_fps": 30.0, "process_fps": 29.0, "dropped_frames": 4}
    for driver_field, passenger_field in MODEL_FIELDS.values():
        assert driver_field in perf and (passenger_field is None or passenger_field in perf)


def test_perf_block_proposed_fields_and_a_camera_without_data() -> None:
    perf = build_perf_block(
        {"driver": True, "passenger": False},
        {"driver": _msg({"face": 9.0}, dropped_results=3), "passenger": None},
        e2e_ms_p95=None,
        system={},
        proposed=True,
        degrade_level=2,
        timing={"driver": (1763672400.123, 40.0), "passenger": (None, 1500.0)},
        publish_ts=1763672400.2,
    )
    assert perf["cameras"]["driver"]["available"] is True
    assert perf["cameras"]["driver"]["dropped_results"] == 3
    assert perf["cameras"]["driver"]["capture_ts"] == 1763672400.123
    assert perf["cameras"]["passenger"] == {
        "capture_fps": 0.0,
        "process_fps": 0.0,
        "dropped_frames": 0,
        "available": False,
        "capture_ts": None,
        "age_ms": 1500.0,
        "dropped_results": 0,
    }
    assert perf["degrade_level"] == 2 and perf["publish_ts"] == 1763672400.2
    assert set(perf["stages_ms"]) == {"driver"}


def test_degradation_lowers_passenger_first_then_yolo_never_the_driver_face() -> None:
    cfg = load_config()
    cfg = cfg.model_copy(update={"rates": cfg.rates.model_copy(update={"degrade_hold_s": 0.001})})
    app = Perception(cfg, cameras=["driver", "passenger"], options=WorkerOptions(), ws=False, mjpeg=False)
    try:
        limit = cfg.rates.degrade_e2e_p95_ms
        app._degrade(limit * 2)
        passenger = app.workers["passenger"]._persist["rates"]  # what a restarted worker gets back
        assert passenger["face_hz"] < cfg.rates.passenger_face_hz  # step 1: the passenger rate
        assert passenger["phone_hz"] == cfg.rates.phone_hz  # YOLO untouched yet
        while app.degrade.level < app.degrade.max_level:
            time.sleep(0.002)
            app._degrade(limit * 2)
        passenger = app.workers["passenger"]._persist["rates"]
        assert passenger["face_hz"] >= cfg.rates.degrade_min_passenger_face_hz
        assert passenger["phone_hz"] < cfg.rates.phone_hz  # then YOLO
        driver = app.workers["driver"]._persist["rates"]
        assert "face_hz" not in driver  # the driver face is never degraded
        assert driver["phone_hz"] == passenger["phone_hz"]
    finally:
        app.system.close()
