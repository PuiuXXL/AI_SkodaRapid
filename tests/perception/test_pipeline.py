from __future__ import annotations

from pathlib import Path

import pytest

from perception.config import load_config
from perception.evaluation import evaluate, run_pipeline
from perception.labels import Interval, load_labels, to_intervals
from perception.recorder import DATA_DIR, FeatureWriter
from perception.replay import FeatureReplay
from tests.perception.driver_factory import FPS, H, W, frames, rotation_matrix

OPEN, CLOSED = 0.30, 0.06
NOD_SIGN = 1.0  # rotation_matrix pitch sign of a head going DOWN


def _synthetic_session() -> tuple[list[tuple[float, dict[str, object]]], list[Interval]]:
    """A labelled session in the shape of the guided protocol, with the matching ground truth."""
    spec: list[tuple[float, dict[str, object]]] = []
    labels: list[Interval] = []
    t = 0.0

    def add(duration: float, label: str | None = None, cue: bool = False, **kw: object) -> None:
        nonlocal t
        spec.append((duration, {"ear_left": OPEN, **kw}))
        if label and cue:
            labels.append(Interval(label, t, t))
        elif label:
            labels.append(Interval(label, t, t + duration))
        t += duration

    add(3.0)  # baseline
    add(5.0, "still", matrix=rotation_matrix())
    add(3.0, "pose_left", matrix=rotation_matrix(yaw=25))
    add(3.0, "pose_up", matrix=rotation_matrix(pitch=-15))
    add(3.0, "pose_tilt_left", matrix=rotation_matrix(roll=-15))
    add(1.0, matrix=rotation_matrix())
    for _ in range(10):  # blink 0.2 s after the cue, lasting 150 ms
        add(0.2, "blink", cue=True)
        add(0.15, ear_left=CLOSED, blink=0.9)
        add(2.15)
    for _ in range(3):
        add(2.0, "eyes_closed", ear_left=CLOSED, blink=0.9)
        add(3.0)
    for _ in range(2):  # fatigue nod: eyes closed, the head falls forward ~25 deg in 1.5 s
        start = t
        add(1.0, ear_left=CLOSED, blink=0.9, matrix=rotation_matrix())
        for k in range(1, 7):
            add(0.25, ear_left=CLOSED, blink=0.9, matrix=rotation_matrix(pitch=NOD_SIGN * 4.0 * k))
        labels.append(Interval("nod", start, t))
        add(3.0, matrix=rotation_matrix())
    for _ in range(3):
        add(1.0)
        add(3.0, "yawn", jaw=0.85, lip_gap=0.25)
        add(2.0)
    for _ in range(2):  # speaking: lip gap oscillation
        start = t
        for k in range(60):
            add(0.12, lip_gap=0.06 if k % 2 else 0.01, jaw=0.15)
        labels.append(Interval("speaking", start, t))
        add(2.0)
    for label in ("squint", "smile"):
        for _ in range(3):
            add(3.0, label, ear_left=OPEN * 0.58, squint=0.8, blink=0.35)
            add(3.0)
    add(5.0, "step_back", width_px=160.0)
    return spec, labels


def test_synthetic_labelled_session_passes_exit_criteria(tmp_path: Path) -> None:
    cfg = load_config()
    spec, labels = _synthetic_session()
    path = tmp_path / "features.jsonl.gz"
    with FeatureWriter(path, {"camera": {"width": W, "height": H, "fps": FPS}}) as writer:
        for ff in frames(spec):
            writer.write(ff)
    replay = FeatureReplay(path)  # record -> replay -> pipeline, exactly like eval_eyes --session
    run = run_pipeline(cfg, replay.frames(), (W, H), ear_baseline=(OPEN, OPEN))
    result = evaluate(run, labels, cfg.eyes.blink_max_ms)
    failed = {k: v for k, v in result.checks.items() if v is False}
    assert not failed, (failed, result.metrics)
    assert all(v is not None for v in result.checks.values())
    m = result.metrics
    assert m["blink_detection_pct"] == 100.0
    assert m["blink_ms_median"] == pytest.approx(150, abs=40)
    assert m["closures_detected"] == 3 and m["closed_ms_error_mean"] < 100
    assert m["nods_detected"] == 2  # nodding on the raw pitch (the filtered one lags a slow drop)
    assert m["closed_detect_latency_ms_median"] < 300  # eyes closed -> CLOSED (plan §8 budget)
    assert m["squint_smile_reported_closed"] == 0
    assert m["pose_left_sign_ok"] and m["pose_up_sign_ok"] and m["pose_tilt_left_sign_ok"]


def test_microsleep_flag_never_set_by_p1() -> None:
    cfg = load_config()
    spec = [(1.0, {"ear_left": OPEN}), (3.0, {"ear_left": CLOSED, "blink": 0.9})]
    run = run_pipeline(cfg, frames(spec), (W, H), ear_baseline=(OPEN, OPEN))
    assert max(s.eyes.closed_ms for s in run.states) > 2500
    assert not any(s.eyes.microsleep for s in run.states)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _latest_real_session() -> Path | None:
    root = DATA_DIR / "features"
    if not root.exists():
        return None
    sessions = sorted(
        # full guided protocol only (a short ``eval_eyes --only`` re-run has no blinks / squints to check)
        (d for d in root.iterdir() if "eval" in d.name and '"squint"' in _read(d / "labels.jsonl")),
        key=lambda d: d.name,
    )
    return sessions[-1] if sessions else None


@pytest.mark.realdata
@pytest.mark.xfail(
    reason="hard squint (EAR ratio 0.35-0.49, eyeBlink 0.52-0.54) looks like a closure by geometry, blendshape and "
    "the eye CNN; no threshold separates it on all sessions (docs/eval/eyes-laptop-cnn-2026-11-21.md, Diagnosis)",
    strict=False,
)
def test_latest_real_eval_session_meets_minimums() -> None:
    session = _latest_real_session()
    if session is None:
        pytest.skip("no recorded eval session in data/features (run scripts/eval_eyes.py)")
    cfg = load_config()
    replay = FeatureReplay(session / "features.jsonl.gz")
    cam = replay.meta["camera"]
    run = run_pipeline(cfg, replay.frames(), (cam["width"], cam["height"]))
    _, events = load_labels(session / "labels.jsonl")
    result = evaluate(run, to_intervals(events), cfg.eyes.blink_max_ms)
    # regression bar for a real session (the full exit criteria are in the eval report)
    assert result.checks.get("squint_smile") is not False, result.metrics
    assert result.checks.get("false_alarms") is not False, result.metrics
    assert result.metrics.get("blink_detection_pct", 100) >= 90, result.metrics


def test_looking_down_at_the_lap_is_not_a_nod() -> None:
    """Head down 25 deg in 0.5 s: with the lids lowered by the gaze (ratio ~0.6, eyeLookDown high) it is a glance at
    the lap, not fatigue; only with the eyes CLOSED is it a nod (live: every look-down was a nod before)."""
    cfg = load_config()

    def run(eyes: dict[str, object]) -> bool:
        # the lids go first (a closure cannot start during a head movement), then the head falls
        spec: list[tuple[float, dict[str, object]]] = [(3.0, {"ear_left": OPEN, "matrix": rotation_matrix()})]
        spec.append((0.8, {**eyes, "matrix": rotation_matrix()}))
        spec += [(0.1, {**eyes, "matrix": rotation_matrix(pitch=NOD_SIGN * 5.0 * k)}) for k in range(1, 6)]
        spec.append((2.0, {**eyes, "matrix": rotation_matrix(pitch=NOD_SIGN * 25.0)}))
        run = run_pipeline(cfg, frames(spec), (W, H), ear_baseline=(OPEN, OPEN))
        return any(s.head.nodding for s in run.states)

    assert run({"ear_left": OPEN * 0.6, "look_down": 0.8, "blink": 0.3}) is False
    assert run({"ear_left": CLOSED, "blink": 0.9}) is True
