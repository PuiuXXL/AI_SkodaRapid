from __future__ import annotations

import random
from collections.abc import Mapping, Sequence

import pytest

from perception.config import load_config
from perception.driver_cam.eyes import EyeOutput, EyeTracker, ear_from_points
from tests.perception.driver_factory import FPS, H, W, face, frame, frames

OPEN, CLOSED = 0.30, 0.06  # EAR; baseline from the open phase ~0.30


def _tracker(calibrated: bool = True) -> EyeTracker:
    cfg = load_config().eyes
    return EyeTracker(cfg, (W, H), (OPEN, OPEN) if calibrated else None)


def _run(tracker: EyeTracker, spec: Sequence[tuple[float, Mapping[str, object]]]) -> list[EyeOutput]:
    return [tracker.update(ff) for ff in frames(spec)]


def test_ear_formula() -> None:
    ear, width = ear_from_points([(0, 0), (10, -3), (20, -3), (30, 0), (20, 3), (10, 3)])
    assert ear == pytest.approx(0.2) and width == pytest.approx(30)


def test_synthetic_face_has_requested_ear() -> None:
    out = _tracker().update(frame(0, face(ear_left=0.25, ear_right=0.20)))
    assert out.ear_left == pytest.approx(0.25, abs=1e-3)
    assert out.ear_right == pytest.approx(0.20, abs=1e-3)


def test_blink_150ms_measured() -> None:
    tracker = _tracker()
    outs = _run(tracker, [(1.0, {"ear_left": OPEN}), (0.15, {"ear_left": CLOSED}), (1.0, {"ear_left": OPEN})])
    blinks = [e for e in tracker.events if e.kind == "blink"]
    assert len(blinks) == 1
    assert blinks[0].duration_ms == pytest.approx(150, abs=1000 / FPS + 1)  # within one frame
    assert outs[-1].blink_ms == pytest.approx(150, abs=1000 / FPS + 1)
    assert max(o.closed_ms for o in outs) < 200


def test_microsleep_1500ms_closed_ms() -> None:
    tracker = _tracker()
    outs = _run(tracker, [(1.0, {"ear_left": OPEN}), (1.5, {"ear_left": CLOSED}), (0.5, {"ear_left": OPEN})])
    peak = max(o.closed_ms for o in outs)
    assert peak == pytest.approx(1500, abs=1000 / FPS * 2)
    assert [e.kind for e in tracker.events] == ["closure"]
    assert tracker.events[0].duration_ms == pytest.approx(1500, abs=1000 / FPS + 1)


def test_noise_does_not_flicker() -> None:
    rng = random.Random(3)
    tracker = _tracker()
    states = []
    for i in range(300):
        ear = OPEN * rng.uniform(0.82, 1.05)  # open eye with landmark noise, never below k_open*baseline
        states.append(tracker.update(frame(i, face(ear_left=ear))).state)
    assert set(states) == {"OPEN"}
    assert tracker.events == []


def test_single_frame_dropout_is_not_a_blink() -> None:
    tracker = _tracker()
    _run(tracker, [(1.0, {"ear_left": OPEN}), (1 / FPS, {"ear_left": CLOSED}), (1.0, {"ear_left": OPEN})])
    assert tracker.events == []  # Median3 + min_state_frames remove a one-frame glitch


def test_perclos_over_known_window() -> None:
    tracker = _tracker()
    # 20 s: open 10 s, closed 3 s (one long closure), open 7 s -> 3 / 20 = 0.15
    outs = _run(tracker, [(10.0, {"ear_left": OPEN}), (3.0, {"ear_left": CLOSED}), (7.0, {"ear_left": OPEN})])
    assert outs[-1].perclos_60s == pytest.approx(3.0 / 20.0, abs=0.01)


def test_squint_is_not_closed() -> None:
    """R-FL4: EAR ratio inside squint_ear_band + high eyeSquint -> SQUINT; no closed_ms, no PERCLOS, no blink."""
    tracker = _tracker()
    squinting = {"ear_left": OPEN * 0.58, "squint": 0.8, "blink": 0.4}  # ratio 0.58 < k_close, inside [0.5, 0.8]
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), (3.0, squinting), (2.0, {"ear_left": OPEN})])
    squint_outs = outs[round(2.2 * FPS) : round(4.8 * FPS)]
    assert {o.state for o in squint_outs} == {"SQUINT"}
    assert all(o.squint for o in squint_outs)
    assert max(o.closed_ms for o in outs) == 0
    assert outs[-1].perclos_60s == 0.0
    assert tracker.events == []


def test_same_ear_without_squint_is_closed() -> None:
    """Control for the squint test: the same low ratio with a normal eyeSquint does count as closed."""
    tracker = _tracker()
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), (3.0, {"ear_left": OPEN * 0.58, "blink": 0.7})])
    assert outs[-1].state == "CLOSED" and outs[-1].closed_ms > 2500


def test_really_closed_eye_with_squint_is_still_closed() -> None:
    tracker = _tracker()
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), (2.0, {"ear_left": CLOSED, "squint": 0.9, "blink": 0.9})])
    assert outs[-1].state == "CLOSED"  # ratio 0.2 is below the squint band


def test_blink_blendshape_confirms_closure_inside_band() -> None:
    tracker = _tracker()
    in_band = {"ear_left": OPEN * 0.72}  # between k_close (0.65) and k_open (0.80)
    outs = _run(tracker, [(1.0, {"ear_left": OPEN}), (1.0, in_band)])
    assert outs[-1].state == "OPEN"  # band alone keeps the previous state
    outs = _run(tracker, [(1.0, {**in_band, "blink": 0.9})])
    assert outs[-1].state == "CLOSED"


def test_provisional_baseline_is_marked_and_waits() -> None:
    tracker = _tracker(calibrated=False)
    outs = _run(tracker, [(3.0, {"ear_left": OPEN})])
    assert outs[0].state == "UNKNOWN" and outs[0].baseline_left is None
    assert outs[-1].baseline_provisional is True
    assert outs[-1].baseline_left == pytest.approx(OPEN, abs=0.01)
    assert outs[-1].state == "OPEN"
    calibrated = _tracker(calibrated=True).update(frame(0, face()))
    assert calibrated.baseline_provisional is False


def test_unreliable_small_eyes_give_unknown() -> None:
    tracker = _tracker()
    lost = tracker.update(
        frame(
            0, face().model_copy(update={"present": False, "landmarks": None, "blendshapes": None, "head_matrix": None})
        )
    )
    assert lost.state == "UNKNOWN" and not lost.reliable
