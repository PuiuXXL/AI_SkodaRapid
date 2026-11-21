"""HeadAnswerDetector (AS8): yes / no on synthetic angle series; nothing outside the window or on a slow drop."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from pathlib import Path

import pytest

from perception.driver_cam.head_answer import HeadAnswerConfig, HeadAnswerDetector, HeadAnswerResult

SESSION = Path(__file__).resolve().parents[2] / "data" / "features" / "20261121-012736_eval-laptop"
FPS = 30.0
Signal = Callable[[float], float]


def zero(_: float) -> float:
    return 0.0


def osc(start: float, amp: float = 8.0, freq: float = 2.5, cycles: float = 2.0) -> Signal:
    """amp * sin over ``cycles`` periods from ``start`` (amp = half the peak-to-peak swing)."""

    def f(t: float) -> float:
        if start <= t < start + cycles / freq:
            return amp * math.sin(2 * math.pi * freq * (t - start))
        return 0.0

    return f


def run(
    det: HeadAnswerDetector,
    duration: float,
    yaw: Signal = zero,
    pitch: Signal = zero,
    eyes: Callable[[float], bool | None] = lambda _: True,
    noise: float = 0.2,
    seed: int = 0,
) -> list[tuple[float, HeadAnswerResult]]:
    rng = random.Random(seed)
    out = []
    for i in range(round(duration * FPS)):
        t = i / FPS
        out.append((t, det.update(t, yaw(t) + rng.gauss(0, noise), pitch(t) + rng.gauss(0, noise), eyes(t))))
    return out


def answers(results: list[tuple[float, HeadAnswerResult]]) -> list[tuple[float, str]]:
    """Rising edges of the answer."""
    found: list[tuple[float, str]] = []
    prev = None
    for t, r in results:
        if r.answer is not None and r.answer != prev:
            found.append((t, r.answer))
        prev = r.answer
    return found


def opened(until: float = 100.0) -> HeadAnswerDetector:
    det = HeadAnswerDetector()
    assert det.open_window(True, to="driver", until=until)
    return det


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError):
        HeadAnswerConfig(dominance_ratio=0.5)
    with pytest.raises(ValueError, match="unknown"):
        HeadAnswerConfig.from_mapping({"window": 1.2})


def test_pitch_oscillation_is_yes() -> None:
    found = answers(run(opened(), 4.0, pitch=osc(1.0)))
    assert len(found) == 1
    t, answer = found[0]
    assert answer == "yes"
    assert 1.0 < t < 1.0 + 1.2


def test_yaw_oscillation_is_no() -> None:
    found = answers(run(opened(), 4.0, yaw=osc(1.0, amp=10.0, freq=2.0)))
    assert [a for _, a in found] == ["no"]


def test_nothing_outside_the_window() -> None:
    det = HeadAnswerDetector()  # never opened
    results = run(det, 6.0, pitch=osc(1.0), yaw=osc(3.5))
    assert answers(results) == []
    assert not any(r.active for _, r in results)


def test_window_for_the_other_seat_is_ignored() -> None:
    det = HeadAnswerDetector(seat="driver", person_id=1)
    assert not det.open_window(True, to="passenger", until=10.0)
    assert answers(run(det, 4.0, pitch=osc(1.0))) == []
    assert det.open_window(True, to=1, until=10.0)  # addressed by occupant id
    assert answers(run(det, 4.0, pitch=osc(1.0))) != []


def test_slow_head_drop_gives_nothing() -> None:
    def drop(t: float) -> float:  # 20 deg down over 3 s, held, then slowly back up
        if t < 1.0:
            return 0.0
        if t < 4.0:
            return -20.0 * (t - 1.0) / 3.0
        if t < 6.0:
            return -20.0
        return -20.0 + 20.0 * min(1.0, (t - 6.0) / 3.0)

    assert answers(run(opened(), 10.0, pitch=drop)) == []


def test_single_step_and_single_turn_give_nothing() -> None:
    def step(t: float) -> float:  # fast 15 deg drop, held
        return -15.0 if t >= 1.0 else 0.0

    def mirror(t: float) -> float:  # look at the left mirror for 0.8 s and back
        return 30.0 if 1.0 <= t < 1.8 else 0.0

    assert answers(run(opened(), 4.0, pitch=step)) == []
    assert answers(run(opened(), 4.0, yaw=mirror)) == []


def test_small_amplitude_is_ignored() -> None:
    assert answers(run(opened(), 4.0, pitch=osc(1.0, amp=2.0, cycles=3))) == []


def test_slow_oscillation_is_not_an_answer() -> None:
    # 0.4 Hz sway: two crossings take 2.5 s > window_s
    assert answers(run(opened(), 8.0, pitch=osc(1.0, amp=8.0, freq=0.4, cycles=2))) == []


def test_nod_with_closed_eyes_is_ignored_but_a_blink_is_not() -> None:
    closed = answers(run(opened(), 4.0, pitch=osc(1.0), eyes=lambda t: not 0.9 <= t < 2.0))
    assert closed == []
    blink = answers(run(opened(), 4.0, pitch=osc(1.0), eyes=lambda t: not 1.25 <= t < 1.4))
    assert [a for _, a in blink] == ["yes"]


def test_unknown_eye_state_counts_as_open() -> None:
    assert [a for _, a in answers(run(opened(), 4.0, pitch=osc(1.0), eyes=lambda _: None))] == ["yes"]


def test_window_expires_at_until() -> None:
    det = opened(until=2.0)
    results = run(det, 4.0, pitch=osc(2.5))
    assert answers(results) == []
    assert all(r.active for t, r in results if t < 2.0)
    assert not any(r.active for t, r in results if t >= 2.0)


def test_answer_disappears_when_the_window_closes() -> None:
    det = opened(until=2.2)
    results = run(det, 3.0, pitch=osc(1.0))
    assert any(r.answer == "yes" for t, r in results if t < 2.2)
    assert all(r.answer is None for t, r in results if t >= 2.2)


def test_answer_is_held_then_counting_restarts() -> None:
    det = opened()
    results = run(det, 6.0, pitch=osc(1.0), yaw=osc(3.5, amp=10.0, freq=2.0))
    found = answers(results)
    assert [a for _, a in found] == ["yes", "no"]
    t_yes = found[0][0]
    held = [r.answer for t, r in results if t_yes <= t < t_yes + 1.5]
    assert set(held) == {"yes"}


def test_diagonal_motion_gives_nothing() -> None:
    # head circles: pitch and yaw oscillate with the same amplitude -> no axis dominates
    def yaw(t: float) -> float:
        return 8.0 * math.cos(2 * math.pi * 2.0 * (t - 1.0)) if 1.0 <= t < 2.5 else 0.0

    assert answers(run(opened(), 4.0, yaw=yaw, pitch=osc(1.0, amp=8.0, freq=2.0, cycles=3))) == []


def test_lost_face_resets_without_false_answers() -> None:
    det = opened()
    out = []
    for i in range(round(4 * FPS)):
        t = i / FPS
        if 1.0 <= t < 1.6:
            out.append((t, det.update(t, None, None, True)))
        else:
            out.append((t, det.update(t, 0.0 if t < 1.0 else 20.0, 0.0 if t < 1.0 else -10.0, True)))
    assert answers(out) == []


def test_result_fields() -> None:
    results = run(opened(), 2.0, pitch=osc(1.0))
    r = results[-1][1]
    assert r.active and r.ms >= 0.0
    assert r.to_dict()["answer"] in ("yes", None)
    assert max(res.crossings_pitch for _, res in results) >= 2


@pytest.mark.realdata
@pytest.mark.slow
def test_no_answer_outside_the_window_on_a_real_session() -> None:
    """Replay of the eval_eyes laptop session (head turns, tilts, yawns, speech): the detector stays silent with the
    window closed, and with the window open it stays silent while the person sits still."""
    if not (SESSION / "features.jsonl.gz").exists():
        pytest.skip("session 20261121-012736_eval-laptop not available")
    from perception.config import load_config
    from perception.driver_cam.pipeline import DriverPipeline
    from perception.labels import load_labels, to_intervals
    from perception.replay import FeatureReplay

    cfg = load_config()
    replay = FeatureReplay(SESSION / "features.jsonl.gz")
    cam = replay.meta["camera"]
    pipeline = DriverPipeline(cfg, (cam["width"], cam["height"]))
    closed, always = HeadAnswerDetector(), HeadAnswerDetector()
    always.open_window(True)
    _, events = load_labels(SESSION / "labels.jsonl")
    still = [i for i in to_intervals(events) if i.label == "still"]
    n_closed = 0
    open_answers: list[float] = []
    prev = None
    for ff in replay.frames():
        st = pipeline.update(ff)
        eyes = None if not st.eyes.reliable else st.eyes.state != "CLOSED"
        if closed.update(ff.t, st.head.raw_yaw, st.head.raw_pitch, eyes).answer is not None:
            n_closed += 1
        a = always.update(ff.t, st.head.raw_yaw, st.head.raw_pitch, eyes).answer
        if a is not None and a != prev:
            open_answers.append(ff.t)
        prev = a
    assert n_closed == 0
    assert still and not any(s.start <= t <= s.end for s in still for t in open_answers)
