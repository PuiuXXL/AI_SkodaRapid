from __future__ import annotations

import random
import statistics

import pytest

from perception.filters import Debounce, Hysteresis, Median3, MedianFilter, OneEuroFilter, RollingWindow


def test_one_euro_smooths_at_rest_and_follows_a_step() -> None:
    rng = random.Random(0)
    f = OneEuroFilter(min_cutoff=1.0, beta=0.05)
    raw, out = [], []
    for i in range(90):  # 3 s still at 10 deg with 0.5 deg noise
        x = 10 + rng.gauss(0, 0.5)
        raw.append(x)
        out.append(f.update(i / 30, x))
    assert statistics.pstdev(out[30:]) < statistics.pstdev(raw[30:]) / 2
    for i in range(90, 120):  # fast 30 deg turn
        y = f.update(i / 30, 40.0)
    assert y == pytest.approx(40.0, abs=1.0)  # catches up within 1 s


def test_one_euro_ignores_duplicate_timestamps() -> None:
    f = OneEuroFilter(1.0, 0.0)
    f.update(0.0, 1.0)
    assert f.update(0.0, 100.0) == 1.0


def test_median3_removes_single_spikes() -> None:
    m = Median3()
    out = [m.update(x) for x in [1, 1, 9, 1, 1, 0, 0, 0]]
    assert out == [1, 1, 1, 1, 1, 1, 0, 0]
    with pytest.raises(ValueError):
        MedianFilter(4)


def test_hysteresis_needs_min_frames_and_reports_transition_time() -> None:
    h = Hysteresis(low=0.65, high=0.80, min_frames=2)
    seq = [0.9, 0.5, 0.9, 0.5, 0.5, 0.7, 0.75, 0.85, 0.9]
    states = [h.update(i / 30, v) for i, v in enumerate(seq)]
    assert states == [False, False, False, False, True, True, True, True, False]
    assert h.t_change == pytest.approx(7 / 30)  # first frame of the opening run


def test_hysteresis_band_noise_does_not_toggle() -> None:
    rng = random.Random(1)
    h = Hysteresis(0.65, 0.80, 2)
    flips = 0
    prev = False
    for i in range(300):
        state = h.update(i / 30, rng.uniform(0.67, 0.78))  # noise inside the band
        flips += state != prev
        prev = state
    assert flips == 0


def test_debounce() -> None:
    d = Debounce(min_ms=1500)
    assert not d.update(0.0, True)
    assert not d.update(1.4, True)
    assert d.update(1.5, True)
    assert not d.update(1.6, False)
    assert not d.update(1.7, True)


def test_rolling_window_time_weighted_fraction_and_stats() -> None:
    w = RollingWindow(60.0)
    for i in range(600):  # 20 s at 30 fps, closed during 2..5 s
        t = i / 30
        w.add(t, 1.0 if 2.0 <= t < 5.0 else 0.0)
    assert w.fraction() == pytest.approx(3.0 / (599 / 30), abs=0.01)
    w2 = RollingWindow(1.0)
    for i in range(100):
        w2.add(i / 30, float(i % 2))
    assert w2.span_s <= 1.0
    assert w2.p50() in (0.0, 1.0) and w2.p95() == 1.0
    assert w2.std() == pytest.approx(0.5, abs=0.02)
