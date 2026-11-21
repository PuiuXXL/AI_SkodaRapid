"""Gaze calibration: protocol, discarded reaction time, road x3, excluded frames, repeat, save / load, quick merge."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from perception.calibration import Calibration, CalibrationRun, CalibStep, build_steps, profile_path
from perception.config import PerceptionConfig, load_config
from perception.driver_cam.pipeline import DriverPipeline
from tests.perception.driver_factory import FPS, H, W
from tests.perception.zone_factory import calibrate_synthetic, zone_frame


@pytest.fixture(scope="module")
def cfg() -> PerceptionConfig:
    return load_config()


def test_protocol_owl_and_lizard_road_three_times(cfg: PerceptionConfig) -> None:
    c = cfg.gaze.calibration
    steps = build_steps(cfg)
    recorded = [s for s in steps if s.zone is not None]
    first = [(s.zone, s.mode) for s in recorded][:3]
    assert first == [("road", "owl"), ("mirror_left", "owl"), ("mirror_left", "lizard")]
    assert len(recorded) == 1 + 2 * (len(cfg.gaze.zones) - 1)
    road = next(s for s in recorded if s.zone == "road")
    other = next(s for s in recorded if s.zone == "lap")
    assert road.duration_s == pytest.approx(c.road_factor * other.duration_s)
    assert all(s.zone is None for s in steps[1::2])  # "back to the road" between recorded steps
    passenger = next(s for s in recorded if s.zone == "passenger")
    assert "PASAGER" in passenger.prompt
    assert len({s.segment for s in recorded}) == len(recorded)


def test_quick_protocol_is_road_and_mirrors(cfg: PerceptionConfig) -> None:
    quick = [s for s in build_steps(cfg, quick=True) if s.zone is not None]
    assert {s.zone for s in quick} == set(cfg.gaze.calibration.quick_zones)
    total = sum(s.duration_s for s in build_steps(cfg, quick=True))
    assert total <= 16.0  # ~15 s


def test_synthetic_calibration_discards_reaction_time(cfg: PerceptionConfig) -> None:
    cal, run = calibrate_synthetic(cfg, seed=5)
    c = cfg.gaze.calibration
    per_zone = run.summary()["per_zone"]
    expected = (c.s_per_zone - c.discard_s) * FPS
    assert per_zone["lap"] == pytest.approx(2 * expected, abs=4)  # owl + lizard
    assert per_zone["road"] == pytest.approx((c.s_per_zone * c.road_factor - c.discard_s) * FPS, abs=3)
    assert (cal.loo_accuracy()["all"] or 0.0) >= 0.95 and not cal.missing
    assert cal.ear_baseline == pytest.approx((0.30, 0.30), abs=0.01)  # p90 of the road EAR
    assert set(cal.ear_ref_by_zone) == set(cfg.gaze.zones)


def _run(cfg: PerceptionConfig, steps: list[CalibStep], frame_for) -> CalibrationRun:  # type: ignore[no-untyped-def]
    pipeline = DriverPipeline(cfg, (W, H))
    run = CalibrationRun(cfg, (W, H), "t", steps=steps)
    i = 0
    while not run.done:
        ff = frame_for(i, run.current)
        run.update(ff, pipeline.update(ff))
        i += 1
    return run


def test_untrustworthy_frames_are_excluded_and_the_step_repeated(cfg: PerceptionConfig) -> None:
    steps = [CalibStep("road", "owl", "road", 1.0, 0), CalibStep("lap", "owl", "lap", 1.0, 1)]
    rng = np.random.default_rng(0)

    def frame_for(i: int, step: CalibStep):  # type: ignore[no-untyped-def]
        zone = step.zone or "road"
        return zone_frame(i, zone, "owl", rng, width_px=200.0 if zone == "lap" else 300.0)  # lap: R-FL3

    run = _run(cfg, steps, frame_for)
    assert run.rejected.get("face_too_small", 0) > 0
    assert "lap" not in run.summary()["per_zone"]
    assert any(s.prompt.startswith("DIN NOU") for s in run.steps)  # repeated once
    assert run.missing == ["lap:owl"]


def test_closed_eyes_are_not_collected(cfg: PerceptionConfig) -> None:
    steps = [CalibStep("road", "owl", "road", 4.0, 0)]
    rng = np.random.default_rng(1)

    def frame_for(i: int, step: CalibStep):  # type: ignore[no-untyped-def]
        # ~0.7 s closure once the provisional EAR baseline exists (eyes.baseline_min_s)
        return zone_frame(i, "road", "owl", rng, closed=80 <= i < 100)

    run = _run(cfg, steps, frame_for)
    assert run.rejected.get("eyes_closed", 0) > 0
    assert run.summary()["per_zone"]["road"] < (4.0 - cfg.gaze.calibration.discard_s) * FPS - 10


def test_save_load_round_trip(cfg: PerceptionConfig, tmp_path: Path) -> None:
    cal, _ = calibrate_synthetic(cfg, seed=6)
    path = cal.save(tmp_path / "calibration.json")
    loaded = Calibration.load(cfg, path)
    assert loaded.zones == cal.zones and loaded.ear_baseline == pytest.approx(cal.ear_baseline)
    probe = zone_frame(5, "mirror_rear", "lizard")
    pipe_a = DriverPipeline(cfg, (W, H), None, cal.model)
    pipe_b = DriverPipeline(cfg, (W, H), None, loaded.model)
    for i in range(20):
        ff = zone_frame(i, "mirror_rear", "lizard")
        a, b = pipe_a.update(ff), pipe_b.update(ff)
    assert a.gaze.zone == b.gaze.zone == "mirror_rear" and probe.gaze is not None
    assert loaded.model.tau == pytest.approx(cal.model.tau, rel=1e-3)  # samples saved with 5 decimals


def test_quick_recalibration_replaces_road_and_mirrors_only(cfg: PerceptionConfig) -> None:
    full, _ = calibrate_synthetic(cfg, seed=7)
    quick, _ = calibrate_synthetic(cfg, seed=8, quick=True)
    merged = full.merged_with(cfg, quick)
    quick_zones = set(cfg.gaze.calibration.quick_zones)
    for zone in cfg.gaze.zones:
        n_merged = merged.zones.count(zone)
        assert n_merged == (quick.zones.count(zone) if zone in quick_zones else full.zones.count(zone))
    kept = {s for s, z in zip(full.segments, full.zones, strict=True) if z not in quick_zones}
    assert len(set(merged.segments)) == len(kept) + len(set(quick.segments))  # quick segments renumbered


def test_profile_name_is_validated() -> None:
    assert profile_path("andrei").parts[-3:] == ("profiles", "andrei", "calibration.json")
    with pytest.raises(ValueError):
        profile_path("../etc")
