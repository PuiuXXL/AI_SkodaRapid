"""Zone evaluation on a synthetic labelled session (replay -> pipeline -> confusion, accuracy, latency, signs)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from perception.config import PerceptionConfig, load_config
from perception.features import FeatureFrame
from perception.labels import Interval
from perception.recorder import DATA_DIR
from perception.zone_evaluation import evaluate_zones, reclassify, run_zone_pipeline, trials_from_intervals
from tests.perception.driver_factory import FPS, H, W
from tests.perception.zone_factory import ZONES, calibrate_synthetic, zone_frame

REACTION_S = 0.4
TRIAL_S = 2.5
BACK_S = 1.5


def synthetic_session(seed: int = 0) -> tuple[list[FeatureFrame], list[Interval]]:
    """Every zone x mode once in random order; the person reacts 0.4 s after each prompt."""
    rng = np.random.default_rng(seed)
    trials = [(z, m) for z in ZONES for m in ("owl", "lizard")]
    rng.shuffle(trials)
    frames: list[FeatureFrame] = []
    intervals: list[Interval] = []
    i = 0

    def add(zone: str, mode: str, seconds: float) -> None:
        nonlocal i
        for _ in range(round(seconds * FPS)):
            frames.append(zone_frame(i, zone, mode, rng))
            i += 1

    add("road", "owl", 3.0)
    for zone, mode in trials:
        start = i / FPS
        add("road", "owl", REACTION_S)
        add(zone, mode, TRIAL_S - REACTION_S)
        intervals.append(Interval("zone", start, i / FPS, f"{zone}:{mode}"))
        add("road", "owl", BACK_S)
    return frames, intervals


@pytest.fixture(scope="module")
def cfg() -> PerceptionConfig:
    return load_config()


def test_trials_from_intervals() -> None:
    trials = trials_from_intervals([Interval("zone", 1.0, 3.0, "lap:lizard"), Interval("still", 0.0, 1.0)])
    assert len(trials) == 1 and trials[0].zone == "lap" and trials[0].mode == "lizard"


@pytest.mark.slow
def test_synthetic_session_passes_and_measures_latency(cfg: PerceptionConfig) -> None:
    cal, _ = calibrate_synthetic(cfg, seed=1)
    frames, intervals = synthetic_session(seed=2)
    replay = run_zone_pipeline(cfg, frames, (W, H), cal)
    res = evaluate_zones(replay.series, trials_from_intervals(intervals), list(cfg.gaze.zones))
    m = res.metrics
    assert res.passed, (res.checks, m)
    assert m["owl_accuracy"] == 1.0 and m["lizard_accuracy"] == 1.0
    assert m["road_vs_mirror_left_frames"] == 0 and m["passenger_vs_mirror_right_pct"] == 0.0
    # zone_min_frames at 30 fps (+ one frame for the onset itself)
    assert m["latency_ms_median"] <= 1000 * (cfg.gaze.zone_min_frames + 1) / FPS + 1
    assert m["reaction_ms_median"] == pytest.approx(1000 * REACTION_S, abs=40)
    assert m["sign_ok"] is True
    assert sum(res.confusion["road"].values()) > 0


@pytest.mark.slow
def test_reclassify_reproduces_the_pipeline_and_reacts_to_parameters(cfg: PerceptionConfig) -> None:
    cal, _ = calibrate_synthetic(cfg, seed=3)
    frames, intervals = synthetic_session(seed=4)
    replay = run_zone_pipeline(cfg, frames, (W, H), cal)
    same = reclassify(cfg, cal, replay)
    assert same.zone == replay.series.zone
    slow = cfg.model_copy(update={"gaze": cfg.gaze.model_copy(update={"zone_min_frames": 9})})
    trials = trials_from_intervals(intervals)
    fast_ms = evaluate_zones(same, trials, list(cfg.gaze.zones)).metrics["latency_ms_median"]
    slow_ms = evaluate_zones(reclassify(slow, cal, replay), trials, list(cfg.gaze.zones)).metrics["latency_ms_median"]
    assert slow_ms > fast_ms


def _latest_zone_session() -> Path | None:
    root = DATA_DIR / "features"
    sessions = sorted(p for p in root.glob("*_zones-*") if (p / "labels.jsonl").exists()) if root.exists() else []
    return sessions[-1] if sessions else None


@pytest.mark.realdata
@pytest.mark.slow
def test_latest_real_zone_session_replays() -> None:
    session = _latest_zone_session()
    if session is None or not (session / "calibration.json").exists():
        pytest.skip("no recorded zone eval session in data/features (run scripts/eval_zones.py)")
    from perception.calibration import Calibration
    from perception.labels import load_labels, to_intervals
    from perception.replay import FeatureReplay

    cfg = load_config()
    replay_src = FeatureReplay(session / "features.jsonl.gz")
    cam = replay_src.meta["camera"]
    cal = Calibration.load(cfg, session / "calibration.json")
    replay = run_zone_pipeline(cfg, replay_src.frames(), (cam["width"], cam["height"]), cal)
    _, events = load_labels(session / "labels.jsonl")
    res = evaluate_zones(replay.series, trials_from_intervals(to_intervals(events)), list(cfg.gaze.zones))
    # regression bar for a real session (the exit criteria are in the eval report)
    assert res.metrics.get("owl_accuracy", 0) >= 0.8, res.metrics
