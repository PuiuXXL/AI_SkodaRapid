"""Gaze zone features, kNN with blocked-LOO rejection, away, zone tracker, and the pipeline end to end."""

from __future__ import annotations

import numpy as np
import pytest

from perception.config import PerceptionConfig, load_config
from perception.driver_cam.gaze_zones import (
    FEATURE_GROUPS,
    FEATURES,
    GazeFeatureBuilder,
    ZoneModel,
    ZoneResult,
    ZoneTracker,
    iris_offset,
)
from perception.driver_cam.pipeline import DriverPipeline
from perception.features import FeatureFrame
from tests.perception.driver_factory import H, W, face, frame
from tests.perception.zone_factory import ZONES, calibrate_synthetic, zone_frame


@pytest.fixture(scope="module")
def cfg() -> PerceptionConfig:
    return load_config()


@pytest.fixture(scope="module")
def calibration(cfg: PerceptionConfig):  # type: ignore[no-untyped-def]
    cal, _ = calibrate_synthetic(cfg, seed=3)
    return cal


def test_feature_groups_cover_every_feature_once() -> None:
    idx = sorted(i for group in FEATURE_GROUPS.values() for i in group)
    assert idx == list(range(len(FEATURES))) and len(FEATURES) == 14


def test_iris_offset_signs() -> None:
    left = frame(0, face(iris=(0.2, 0.0)))  # image right = the driver's left
    up = frame(0, face(iris=(0.0, 0.15)))
    for side in ("left", "right"):
        x, y, width = iris_offset(left, side, W, H) or (0.0, 0.0, 0.0)
        assert x == pytest.approx(0.2, abs=1e-3) and y == pytest.approx(0.0, abs=1e-3) and width == pytest.approx(50)
        x, y, _ = iris_offset(up, side, W, H) or (0.0, 0.0, 0.0)
        assert y == pytest.approx(0.15, abs=1e-3)


def test_builder_rejects_untrustworthy_frames(cfg: PerceptionConfig) -> None:
    b = GazeFeatureBuilder(cfg, (W, H))

    def why(ff: FeatureFrame, head: float | None = 0.0, gaze: tuple[float, float] | None = (0.0, 0.0)) -> str | None:
        assert (b.build(ff, head, head, gaze) is None) == (b.last_reason is not None)
        return b.last_reason

    ok = frame(0, face())
    assert why(ok) is None
    assert why(frame(0, face(width_px=200.0))) == "face_too_small"  # R-FL3
    assert why(frame(0, face().model_copy(update={"conf": 0.3}))) == "low_conf"  # R-FL2
    assert why(ok, head=None) == "head_unknown"
    assert why(ok, gaze=None) == "no_gaze"
    squint = frame(0, face(0.18, squint=0.8))  # R-FL4: squinted eyes stay valid
    assert b.build(squint, 0.0, 0.0, (0.0, 0.0)) is not None


def test_builder_uses_the_reliable_eye_only(cfg: PerceptionConfig) -> None:
    b = GazeFeatureBuilder(cfg, (W, H))
    turned = frame(0, face(width_right=12.0, iris=(0.1, 0.0)))  # right eye foreshortened below min width
    x = b.build(turned, 0.0, 0.0, (0.0, 0.0))
    assert x is not None and x[12] == pytest.approx(0.1, abs=1e-3)


def _clusters(n_per: int, seed: int, spread: float = 1.0) -> tuple[np.ndarray, list[str], list[int], list[float]]:
    rng = np.random.default_rng(seed)
    centres = rng.normal(0, 20, (8, len(FEATURES)))
    centres[:, 4:12] = rng.uniform(0, 0.8, (8, 8))
    centres[:, 12:] = rng.uniform(-0.3, 0.3, (8, 2))
    scale = np.array([1, 1, 2, 2, *([0.03] * 8), 0.01, 0.01]) * spread
    x, zones, segs, times = [], [], [], []
    for z, c in enumerate(centres):
        walk = np.cumsum(rng.normal(0, 0.3, (n_per, len(FEATURES))), axis=0) * scale  # correlated in time
        x.append(c + walk + rng.normal(0, 1, (n_per, len(FEATURES))) * scale)
        zones += [ZONES[z]] * n_per
        segs += [z] * n_per
        times += [k / 30.0 for k in range(n_per)]
    return np.vstack(x), zones, segs, times


def test_knn_separates_synthetic_clusters(cfg: PerceptionConfig) -> None:
    x, zones, segs, times = _clusters(60, seed=0)
    model = ZoneModel.fit(x, zones, segs, cfg, times)
    test_x, test_zones, _, _ = _clusters(20, seed=0)  # same centres, fresh noise
    got = [model.classify(v).zone for v in test_x]
    assert np.mean([g == z for g, z in zip(got, test_zones, strict=True)]) >= 0.95


def test_far_sample_is_unknown_or_away(cfg: PerceptionConfig) -> None:
    x, zones, segs, times = _clusters(60, seed=1)
    model = ZoneModel.fit(x, zones, segs, cfg, times)
    inside = x[0].copy()
    inside[4:12] += 5.0  # blendshapes far off, head inside the calibrated range -> unknown
    assert model.classify(inside).zone == "unknown"
    beyond = x[0].copy()
    beyond[0] = model.head_range[1] + cfg.gaze.away_margin_deg + 10  # head far beyond the calibrated yaw
    beyond[2] += 60
    res = model.classify(beyond)
    assert res.zone == "away" and res.nearest is not None


def test_blocked_loo_tau_is_larger_than_frame_loo(cfg: PerceptionConfig) -> None:
    x, zones, segs, times = _clusters(60, seed=2)
    blocked = ZoneModel.fit(x, zones, segs, cfg, times)
    frame_loo = ZoneModel.fit(x, zones, list(range(len(x))), cfg, times)  # every sample its own segment
    assert blocked.tau > frame_loo.tau


def test_constant_feature_uses_the_std_floor(cfg: PerceptionConfig) -> None:
    x, zones, segs, times = _clusters(30, seed=4)
    x[:, 4] = 0.1  # constant blendshape
    model = ZoneModel.fit(x, zones, segs, cfg, times)
    assert model.std[4] == pytest.approx(cfg.gaze.std_floor.eye_look)
    probe = x[0].copy()
    probe[4] = 0.12
    assert np.isfinite(model.classify(probe).distance or 0.0)


def test_zone_tracker_needs_min_frames_and_holds_through_blinks() -> None:
    tr = ZoneTracker(min_frames=3, blink_hold_s=0.5)

    def res(z: str) -> ZoneResult:
        return ZoneResult(z, 0.9, 0.1, z)

    for i in range(5):
        tr.update(i / 30, res("road"))
    assert tr.zone == "road"
    assert tr.update(5 / 30, res("lap")) == "road"
    assert tr.update(6 / 30, res("lap")) == "road"
    assert tr.update(7 / 30, res("lap")) == "lap"
    assert tr.update(8 / 30, res("cluster")) == "lap"  # one stray frame does not switch
    assert tr.update(9 / 30, res("lap")) == "lap"
    for i in range(10, 22):  # 0.4 s blink: zone held
        assert tr.update(i / 30, None, eyes_closed=True) == "lap"
    for i in range(22, 30):  # closed past 0.5 s -> unknown
        tr.update(i / 30, None, eyes_closed=True)
    assert tr.zone == "unknown"


def test_zone_tracker_holds_the_zone_through_short_unknown_stretches() -> None:
    tr = ZoneTracker(min_frames=3, blink_hold_s=0.5, unknown_hold_s=0.6)
    unsure = ZoneResult("unknown", 0.4, 2.0, "road")
    for i in range(5):
        tr.update(i / 30, ZoneResult("road", 0.9, 0.1, "road"))
    for i in range(5, 20):  # 0.5 s of classifier "unknown": road holds
        assert tr.update(i / 30, unsure) == "road"
    assert tr.update(20 / 30, ZoneResult("road", 0.9, 0.1, "road")) == "road"
    for i in range(21, 60):  # 1.3 s unknown: reported once the hold (+ min_frames) has passed
        tr.update(i / 30, unsure)
    assert tr.zone == "unknown"


def test_pipeline_classifies_every_zone_and_mode(cfg: PerceptionConfig, calibration) -> None:  # type: ignore[no-untyped-def]
    assert calibration.loo_accuracy()["all"] >= 0.95 and not calibration.warnings()
    pipe = DriverPipeline(cfg, (W, H), calibration.ear_baseline, calibration.model)
    rng = np.random.default_rng(11)
    i, wrong = 0, []
    for zone in ZONES:
        for mode in ("owl", "lizard"):
            for _ in range(30):
                st = pipe.update(zone_frame(i, zone, mode, rng))
                i += 1
            if st.gaze.zone != zone:
                wrong.append((zone, mode, st.gaze.zone))
            assert st.gaze.source == ("face" if st.gaze.zone != "unknown" else None)
    assert not wrong


def test_pipeline_reports_unknown_for_a_too_small_face(cfg: PerceptionConfig, calibration) -> None:  # type: ignore[no-untyped-def]
    pipe = DriverPipeline(cfg, (W, H), None, calibration.model)
    for i in range(30):
        st = pipe.update(zone_frame(i, "mirror_left", "owl", width_px=200.0))
    assert st.gaze.zone == "unknown" and st.gaze.reason == "face_too_small" and st.gaze.conf == 0.0


def test_pipeline_without_calibration_is_unknown(cfg: PerceptionConfig) -> None:
    pipe = DriverPipeline(cfg, (W, H))
    for i in range(10):
        st = pipe.update(zone_frame(i, "lap", "owl"))
    assert st.gaze.zone == "unknown" and not st.gaze.calibrated and st.gaze.gaze_pitch is not None
