from __future__ import annotations

import random
from collections.abc import Mapping, Sequence

import pytest

from perception.config import load_config
from perception.driver_cam.eyes import EyeOutput, EyeTracker, ear_from_points
from tests.perception.driver_factory import FPS, H, W, face, frame, frames, rotation_matrix

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
    assert blinks[0].duration_ms == pytest.approx(150, abs=40)  # 50 % width, interpolated between frames
    assert outs[-1].blink_ms == pytest.approx(150, abs=40)
    assert max(o.closed_ms for o in outs) < 200


def test_closure_2s_closed_ms() -> None:
    tracker = _tracker()
    closed = {"ear_left": CLOSED, "blink": 0.8}
    outs = _run(tracker, [(1.0, {"ear_left": OPEN}), (2.0, closed), (0.5, {"ear_left": OPEN})])
    assert max(o.closed_ms for o in outs) == pytest.approx(2000, abs=100)
    assert outs[round(2.9 * FPS)].long_closure
    (ev,) = tracker.events
    assert ev.kind == "closure" and ev.duration_ms == pytest.approx(2000, abs=100)


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
        ear = OPEN * rng.uniform(0.82, 1.05)  # open eye with landmark noise, never below drop_ratio x reference
        states.append(tracker.update(frame(i, face(ear_left=ear))).state)
    assert set(states) == {"OPEN"}
    assert tracker.events == []


def test_single_frame_dropout_is_not_a_blink() -> None:
    tracker = _tracker()
    _run(tracker, [(1.0, {"ear_left": OPEN}), (1 / FPS, {"ear_left": CLOSED}), (1.0, {"ear_left": OPEN})])
    assert tracker.events == []  # min_state_frames: one frame below the threshold is a glitch


def test_perclos_p80_over_known_window() -> None:
    tracker = _tracker()
    # 20 s: open 10 s, closed 3 s (one long closure), open 7 s -> 3 / 20 = 0.15 with the eyes >= 80 % closed
    closed = {"ear_left": CLOSED, "blink": 0.9}
    outs = _run(tracker, [(10.0, {"ear_left": OPEN}), (3.0, closed), (7.0, {"ear_left": OPEN})])
    assert outs[-1].perclos_60s == pytest.approx(3.0 / 20.0, abs=0.01)


def test_perclos_p80_ignores_half_closed_lids() -> None:
    """P80 is separate from the blink threshold: lids at ~60 % (sleepy look, squint) do not count."""
    tracker = _tracker()
    outs = _run(tracker, [(5.0, {"ear_left": OPEN}), (5.0, {"ear_left": OPEN * 0.62})])
    assert outs[-1].perclos_60s == 0.0


def test_squint_is_not_closed() -> None:
    """R-FL4: lids lowered into the squint band but not meeting (eyeBlink low): no closure event, no PERCLOS,
    closed_ms never reaches blink_max_ms, and the state settles on SQUINT."""
    tracker = _tracker()
    squinting = {"ear_left": OPEN * 0.58, "squint": 0.8, "blink": 0.4}
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), (3.0, squinting), (2.0, {"ear_left": OPEN})])
    settled = outs[round(2.6 * FPS) : round(4.8 * FPS)]
    assert {o.state for o in settled} == {"SQUINT"}
    assert max(o.closed_ms for o in outs) < tracker.cfg.blink_max_ms
    assert outs[-1].perclos_60s == 0.0
    assert [e for e in tracker.events if e.kind == "closure"] == []


def test_same_ear_with_strong_eyeblink_is_closed() -> None:
    """Control for the squint test: the same ratio with the lids clearly meeting (strong eyeBlink) is closed."""
    tracker = _tracker()
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), (3.0, {"ear_left": OPEN * 0.58, "blink": 0.7})])
    assert outs[-1].state == "CLOSED" and outs[-1].closed_ms > 2500


def test_really_closed_eye_with_squint_is_still_closed() -> None:
    tracker = _tracker()
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), (2.0, {"ear_left": CLOSED, "squint": 0.9, "blink": 0.9})])
    assert outs[-1].state == "CLOSED"  # ratio 0.2 is below the squint band


def _ramp(start: float, end: float, seconds: float, **extra: object) -> list[tuple[float, Mapping[str, object]]]:
    n = round(seconds * FPS)
    return [(1 / FPS, {"ear_left": start + (end - start) * (k + 1) / n, **extra}) for k in range(n)]


def test_slow_drowsy_closure_with_lids_meeting_is_closed() -> None:
    tracker = _tracker()
    low = {"ear_left": OPEN * 0.35, "blink": 0.6}
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), *_ramp(OPEN, OPEN * 0.35, 1.0, blink=0.6), (2.0, low)])
    assert outs[-1].state == "CLOSED"


def test_slow_drift_without_lids_meeting_is_not_closed() -> None:
    tracker = _tracker()
    low = {"ear_left": OPEN * 0.55, "blink": 0.3}
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), *_ramp(OPEN, OPEN * 0.55, 1.0, blink=0.3), (2.0, low)])
    assert "CLOSED" not in {o.state for o in outs}


def test_looking_down_with_eyes_only_is_not_closed() -> None:
    """Lizard glance to the lap: EAR drops, eyeLookDown high, head still -> relaxed threshold, not closed."""
    tracker = _tracker()
    down = {"look_down": 0.7}
    spec = [
        (2.0, {"ear_left": OPEN, **down}),
        *_ramp(OPEN, OPEN * 0.5, 0.3, **down),
        (3.0, {"ear_left": OPEN * 0.5, **down}),
    ]
    outs = _run(tracker, spec)
    assert "CLOSED" not in {o.state for o in outs}
    assert outs[-1].relaxed
    assert tracker.events == []


def test_looking_down_with_the_head_is_not_closed() -> None:
    """Owl glance to the lap: head pitch goes to -25 deg while EAR falls fast (the lids follow the head)."""
    tracker = _tracker()
    spec: list[tuple[float, Mapping[str, object]]] = [(2.0, {"ear_left": OPEN})]
    n = round(0.3 * FPS)
    for k in range(n):  # head and lids move together
        frac = (k + 1) / n
        spec.append((1 / FPS, {"ear_left": OPEN * (1 - 0.6 * frac), "matrix": rotation_matrix(pitch=25 * frac)}))
    spec.append((3.0, {"ear_left": OPEN * 0.4, "matrix": rotation_matrix(pitch=25)}))
    outs = _run(tracker, spec)
    assert "CLOSED" not in {o.state for o in outs}
    assert [e for e in tracker.events if e.kind == "closure"] == []


def test_real_closure_while_looking_down_is_still_closed() -> None:
    """Relaxed is stricter, not blind: a full closure while the head is down (and still) is detected."""
    tracker = _tracker()
    down = {"matrix": rotation_matrix(pitch=25)}
    outs = _run(tracker, [(5.0, {"ear_left": OPEN * 0.8, **down}), (2.0, {"ear_left": CLOSED, "blink": 0.8, **down})])
    assert outs[-1].relaxed
    assert outs[-1].state == "CLOSED" and outs[-1].closed_ms > 1500


def test_one_eye_closed_is_not_closed() -> None:
    """Bilateral rule: both eyes reliable, only one closes (wink, landmark glitch) -> not closed."""
    tracker = _tracker()
    wink = {"ear_left": CLOSED, "ear_right": OPEN, "blink": 0.5}
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), (2.0, wink)])
    assert "CLOSED" not in {o.state for o in outs}


def test_head_turned_only_the_wide_eye_decides() -> None:
    """The foreshortened eye (head turned) is unreliable; the wide one closing is enough."""
    tracker = _tracker()
    turned = {"width_right": 25.0}
    spec = [
        (2.0, {"ear_left": OPEN, "ear_right": OPEN, **turned}),
        (2.0, {"ear_left": CLOSED, "ear_right": OPEN, "blink": 0.8, **turned}),
    ]
    outs = _run(tracker, spec)
    assert outs[-1].state == "CLOSED"


def test_local_reference_follows_a_lower_open_level() -> None:
    """Open-eye EAR drifts lower (head a bit lower): after a few seconds the eye is OPEN again, not stuck closed."""
    tracker = _tracker()  # calibrated at OPEN
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), (8.0, {"ear_left": OPEN * 0.78})])
    assert outs[-1].state == "OPEN"
    assert outs[-1].ref_left == pytest.approx(OPEN * 0.78, abs=0.01)
    assert outs[-1].ratio == pytest.approx(1.0, abs=0.05)


def test_local_reference_never_below_the_floor() -> None:
    tracker = _tracker()
    outs = _run(tracker, [(2.0, {"ear_left": OPEN}), (10.0, {"ear_left": CLOSED, "blink": 0.9})])
    floor = tracker.cfg.ref_floor_ratio * OPEN
    assert outs[-1].ref_left == pytest.approx(floor, abs=0.005)
    assert outs[-1].state == "CLOSED"  # a closure longer than the window stays closed


def test_blink_event_has_shape_metrics() -> None:
    tracker = _tracker()
    _run(tracker, [(1.0, {"ear_left": OPEN}), (0.2, {"ear_left": CLOSED, "blink": 0.8}), (1.0, {"ear_left": OPEN})])
    (ev,) = tracker.events
    assert ev.kind == "blink"
    assert ev.min_ratio == pytest.approx(CLOSED / OPEN, abs=0.02)
    assert ev.reopen_ms is not None and 0 < ev.reopen_ms < 200
    assert ev.close_speed is not None and ev.close_speed > 0


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
