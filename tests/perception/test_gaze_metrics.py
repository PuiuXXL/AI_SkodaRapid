"""Off-road time (mirror rule, unknown freezes), VATS, gaze entropy, lap pattern on known zone sequences."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from perception.config import PerceptionConfig, load_config
from perception.driver_cam.gaze_metrics import GazeMetrics, GazeMetricsOutput

FPS = 30.0


@pytest.fixture(scope="module")
def cfg() -> PerceptionConfig:
    return load_config()


def play(
    m: GazeMetrics, spec: Sequence[tuple[str, float]], t0: float = 0.0, hands: bool | None = None
) -> list[GazeMetricsOutput]:
    out = []
    i = 0
    for zone, seconds in spec:
        for _ in range(round(seconds * FPS)):
            out.append(m.update(t0 + i / FPS, zone, hands))
            i += 1
    return out


def test_off_road_glance_counts_and_resets_on_road(cfg: PerceptionConfig) -> None:
    m = GazeMetrics(cfg)
    out = play(m, [("road", 1.0), ("cluster", 1.0), ("road", 1.0)])
    peak = max(o.off_road_ms for o in out)
    assert peak == pytest.approx(1000, abs=40)
    assert out[-1].off_road_ms == 0.0
    assert out[-1].vats_60s == 1  # one off-road glance < 2 s


def test_short_mirror_glance_is_not_off_road(cfg: PerceptionConfig) -> None:
    m = GazeMetrics(cfg)
    out = play(m, [("road", 0.5), ("mirror_left", 1.5), ("road", 0.5)])
    assert max(o.off_road_ms for o in out) == 0.0
    assert out[-1].vats_60s == 0


def test_long_mirror_glance_counts_from_its_start(cfg: PerceptionConfig) -> None:
    m = GazeMetrics(cfg)
    limit_s = cfg.gaze.mirror_glance_max_ms / 1000.0
    out = play(m, [("road", 0.5), ("mirror_right", limit_s + 0.5)])
    assert out[round((0.5 + limit_s - 0.2) * FPS)].off_road_ms == 0.0  # still a mirror check
    assert out[-1].off_road_ms == pytest.approx((limit_s + 0.5) * 1000, abs=60)  # whole glance once past the limit


def test_unknown_freezes_the_counter(cfg: PerceptionConfig) -> None:
    m = GazeMetrics(cfg)
    out = play(m, [("road", 0.5), ("infotainment", 0.5), ("unknown", 1.0), ("infotainment", 0.5)])
    frozen = out[round(1.5 * FPS)].off_road_ms
    assert frozen == pytest.approx(500, abs=40)  # did not grow while unknown, did not reset
    assert out[-1].off_road_ms == pytest.approx(1000, abs=70)


def test_off_road_run_spans_several_off_road_zones(cfg: PerceptionConfig) -> None:
    m = GazeMetrics(cfg)
    out = play(m, [("road", 0.5), ("cluster", 0.6), ("infotainment", 0.6), ("road", 0.5)])
    assert max(o.off_road_ms for o in out) == pytest.approx(1200, abs=70)
    assert out[-1].vats_60s == 1  # one run, not two glances


def test_vats_counts_short_runs_in_the_window_only(cfg: PerceptionConfig) -> None:
    m = GazeMetrics(cfg)
    spec = [("road", 1.0), ("lap", 0.8)] * 4 + [("road", 1.0), ("cluster", 3.0), ("road", 1.0)]
    out = play(m, spec)
    assert out[-1].vats_60s == 4  # the 3 s glance is too long for VATS
    later = play(m, [("road", cfg.gaze.window_s + 1.0)], t0=len(out) / FPS)
    assert later[-1].vats_60s == 0


def test_entropy(cfg: PerceptionConfig) -> None:
    m = GazeMetrics(cfg)
    out = play(m, [("road", 5.0)])
    assert out[-1].entropy_60s == pytest.approx(0.0, abs=1e-6)
    m = GazeMetrics(cfg)
    out = play(m, [("road", 2.0), ("cluster", 2.0), ("lap", 2.0), ("infotainment", 2.0)])
    assert out[-1].entropy_60s == pytest.approx(2.0, abs=0.05)  # 4 equal zones = 2 bits
    m = GazeMetrics(cfg)
    assert play(m, [("unknown", 1.0)])[-1].entropy_60s is None


def test_lap_pattern_repeated_glances(cfg: PerceptionConfig) -> None:
    lap = cfg.phone.lap_pattern
    m = GazeMetrics(cfg)
    out = play(m, [("road", 1.0), ("lap", 0.5)] * (lap.min_glances - 1) + [("road", 1.0)])
    assert not out[-1].lap_pattern
    out = play(m, [("lap", 0.5)], t0=len(out) / FPS)
    assert out[-1].lap_pattern


def test_lap_pattern_one_long_glance(cfg: PerceptionConfig) -> None:
    m = GazeMetrics(cfg)
    out = play(m, [("road", 1.0), ("lap", cfg.phone.lap_pattern.long_glance_s + 0.3)])
    assert out[-1].lap_pattern


def test_lap_pattern_needs_hands_not_seen(cfg: PerceptionConfig) -> None:
    m = GazeMetrics(cfg)
    out = play(m, [("road", 1.0), ("lap", cfg.phone.lap_pattern.long_glance_s + 0.3)], hands=True)
    assert not out[-1].lap_pattern
