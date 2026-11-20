"""Evaluate the driver detectors against ground-truth labels (guided live protocol or a labelled session).

Labels (perception/labels.py intervals) used here:
  blink (instant cue) · eyes_closed · yawn · speaking · squint · smile · still · pose_left · pose_up ·
  pose_tilt_left · step_back

Ground truth comes from people (a key press, or reacting to an on-screen cue), so it carries ~100-300 ms of human
timing error. Matching windows below are sized for that, and closure durations are compared, not frame indices.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from perception.config import PerceptionConfig
from perception.driver_cam.eyes import EyeEvent
from perception.driver_cam.mouth import MouthEvent
from perception.driver_cam.pipeline import DriverPipeline, DriverState
from perception.features import FeatureFrame
from perception.labels import Interval

__all__ = ["CRITERIA", "EvalResult", "PipelineRun", "evaluate", "render_markdown", "run_pipeline"]

# a cued blink counts if a detected blink/closure starts within [cue - BEFORE, cue + AFTER]
BLINK_MATCH_BEFORE_S = 0.3
BLINK_MATCH_AFTER_S = 1.0
STILL_SKIP_S = 1.0  # ignore the first second of the "still" window (settling)

CRITERIA = {
    "blink_detection": "blinks detected >= 95%",
    "false_alarms": "false closures <= 1 per minute",
    "closed_2s": "2 s closures detected 100%, closed_ms error < 100 ms",
    "squint_smile": "squint / smile reported as closed: 0",
    "yawn_detection": "yawns detected >= 90%",
    "no_false_yawn_speaking": "no yawn while speaking",
    "angle_jitter": "angle jitter < 1 deg with the head still",
    "face_too_small": "face_too_small shown when stepping back",
}


@dataclass
class PipelineRun:
    states: list[DriverState]
    eye_events: list[EyeEvent]
    mouth_events: list[MouthEvent]

    @property
    def duration_s(self) -> float:
        return self.states[-1].t - self.states[0].t if len(self.states) > 1 else 0.0


def run_pipeline(
    cfg: PerceptionConfig,
    frames: Iterable[FeatureFrame],
    frame_size: tuple[int, int],
    ear_baseline: tuple[float, float] | None = None,
) -> PipelineRun:
    pipeline = DriverPipeline(cfg, frame_size, ear_baseline)
    states = [pipeline.update(ff) for ff in frames]
    return PipelineRun(states, list(pipeline.eyes.events), list(pipeline.mouth.events))


@dataclass
class EvalResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, bool | None] = field(default_factory=dict)  # None = not measured in this session
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(v for v in self.checks.values() if v is not None)


def _of(intervals: Sequence[Interval], label: str) -> list[Interval]:
    return [i for i in intervals if i.label == label]


def _overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 <= b1 and b0 <= a1


def _states_in(states: Sequence[DriverState], start: float, end: float) -> list[DriverState]:
    """States in the half-open window [start, end): the frame at ``end`` already belongs to the next step."""
    return [s for s in states if start <= s.t < end]


def evaluate(run: PipelineRun, intervals: Sequence[Interval], blink_max_ms: float) -> EvalResult:
    res = EvalResult()
    m = res.metrics
    minutes = max(run.duration_s / 60.0, 1e-9)

    # --- blinks -------------------------------------------------------------------------------------------
    cues = _of(intervals, "blink")
    used: set[int] = set()
    matched_ms: list[float] = []
    for cue in cues:
        for k, ev in enumerate(run.eye_events):
            if k in used:
                continue
            if cue.start - BLINK_MATCH_BEFORE_S <= ev.start <= cue.start + BLINK_MATCH_AFTER_S:
                used.add(k)
                matched_ms.append(ev.duration_ms)
                break
    if cues:
        m["blinks_cued"] = len(cues)
        m["blinks_detected"] = len(matched_ms)
        m["blink_detection_pct"] = round(100 * len(matched_ms) / len(cues), 1)
        m["blink_ms_median"] = round(statistics.median(matched_ms), 1) if matched_ms else None
        res.checks["blink_detection"] = len(matched_ms) / len(cues) >= 0.95
    else:
        res.checks["blink_detection"] = None

    # --- closures -----------------------------------------------------------------------------------------
    closed_windows = _of(intervals, "eyes_closed")
    errors: list[float] = []
    detected = 0
    for win in closed_windows:
        hits = [e for e in run.eye_events if e.kind == "closure" and _overlaps(e.start, e.end, win.start, win.end)]
        if hits:
            detected += 1
            longest = max(hits, key=lambda e: e.duration_ms)
            errors.append(abs(longest.duration_ms - (win.end - win.start) * 1000.0))
    if closed_windows:
        m["closures_labelled"] = len(closed_windows)
        m["closures_detected"] = detected
        m["closed_ms_error_mean"] = round(statistics.mean(errors), 1) if errors else None
        m["closed_ms_error_max"] = round(max(errors), 1) if errors else None
        res.checks["closed_2s"] = detected == len(closed_windows) and bool(errors) and statistics.mean(errors) < 100
    else:
        res.checks["closed_2s"] = None

    # --- false closures (closures outside closed / yawn windows) ------------------------------------------
    allowed = closed_windows + _of(intervals, "yawn")
    false_closures = [
        e
        for e in run.eye_events
        if e.kind == "closure" and not any(_overlaps(e.start, e.end, w.start - 0.5, w.end + 0.5) for w in allowed)
    ]
    m["false_closures"] = len(false_closures)
    m["false_closures_per_min"] = round(len(false_closures) / minutes, 2)
    res.checks["false_alarms"] = len(false_closures) / minutes <= 1.0
    m["blinks_spontaneous"] = sum(1 for k, e in enumerate(run.eye_events) if e.kind == "blink" and k not in used)

    # --- squint / smile reported as closed ----------------------------------------------------------------
    squint_wins = _of(intervals, "squint") + _of(intervals, "smile")
    if squint_wins:
        as_closed_events = [
            e
            for e in run.eye_events
            if e.kind == "closure" and any(_overlaps(e.start, e.end, w.start, w.end) for w in squint_wins)
        ]
        long_closed_frames = [
            s
            for w in squint_wins
            for s in _states_in(run.states, w.start, w.end)
            if s.eyes.state == "CLOSED" and s.eyes.closed_ms > blink_max_ms
        ]
        squint_frames = [s for w in squint_wins for s in _states_in(run.states, w.start, w.end)]
        m["squint_smile_reported_closed"] = len(as_closed_events)
        m["squint_smile_closed_frames"] = len(long_closed_frames)
        m["squint_smile_squint_state_pct"] = round(
            100 * sum(s.eyes.state == "SQUINT" for s in squint_frames) / max(len(squint_frames), 1), 1
        )
        res.checks["squint_smile"] = not as_closed_events and not long_closed_frames
    else:
        res.checks["squint_smile"] = None

    # --- yawns --------------------------------------------------------------------------------------------
    yawn_wins = _of(intervals, "yawn")
    if yawn_wins:
        yawn_hits = sum(any(_overlaps(e.start, e.end, w.start, w.end) for e in run.mouth_events) for w in yawn_wins)
        m["yawns_labelled"] = len(yawn_wins)
        m["yawns_detected"] = yawn_hits
        res.checks["yawn_detection"] = yawn_hits / len(yawn_wins) >= 0.9
    else:
        res.checks["yawn_detection"] = None
    speak_wins = _of(intervals, "speaking")
    if speak_wins:
        false_yawns = [
            e for e in run.mouth_events if any(_overlaps(e.start, e.end, w.start, w.end) for w in speak_wins)
        ]
        speak_frames = [s for w in speak_wins for s in _states_in(run.states, w.start + 0.5, w.end)]
        m["false_yawns_while_speaking"] = len(false_yawns)
        m["speaking_detected_pct"] = round(100 * sum(s.speaking for s in speak_frames) / max(len(speak_frames), 1), 1)
        res.checks["no_false_yawn_speaking"] = not false_yawns
    else:
        res.checks["no_false_yawn_speaking"] = None
    if yawn_wins:
        yawn_frames = [s for w in yawn_wins for s in _states_in(run.states, w.start, w.end)]
        m["speaking_during_yawn_pct"] = round(100 * sum(s.speaking for s in yawn_frames) / max(len(yawn_frames), 1), 1)

    # --- head: jitter when still, axis signs --------------------------------------------------------------
    still = _of(intervals, "still")
    if still:
        frames_still = [
            s for w in still for s in _states_in(run.states, w.start + STILL_SKIP_S, w.end) if s.head.yaw is not None
        ]
        if len(frames_still) > 10:
            jitter = {
                axis: round(statistics.pstdev([getattr(s.head, axis) for s in frames_still]), 3)
                for axis in ("yaw", "pitch", "roll")
            }
            m["angle_jitter_deg"] = jitter
            res.checks["angle_jitter"] = max(jitter.values()) < 1.0
            m["too_small_pct_when_close"] = round(
                100 * sum(s.face.too_small for s in frames_still) / len(frames_still), 1
            )
        else:
            res.checks["angle_jitter"] = None
    else:
        res.checks["angle_jitter"] = None
    for label, axis, sign in (("pose_left", "yaw", 1), ("pose_up", "pitch", 1), ("pose_tilt_left", "roll", 1)):
        wins = _of(intervals, label)
        vals = [getattr(s.head, axis) for w in wins for s in _states_in(run.states, w.start + 0.8, w.end)]
        vals = [v for v in vals if v is not None]
        if vals:
            med = statistics.median(vals)
            m[f"{label}_{axis}_median"] = round(med, 1)
            m[f"{label}_sign_ok"] = med * sign > 5.0

    # --- R-FL3 ----------------------------------------------------------------------------------------------
    back = _of(intervals, "step_back")
    if back:
        frames_back = [s for w in back for s in _states_in(run.states, w.start + 1.0, w.end) if s.face.present]
        pct = 100 * sum(s.face.too_small for s in frames_back) / max(len(frames_back), 1)
        m["too_small_pct_step_back"] = round(pct, 1)
        m["face_width_px_step_back_median"] = (
            round(statistics.median(s.face.width_px for s in frames_back if s.face.width_px), 1)
            if frames_back
            else None
        )
        res.checks["face_too_small"] = pct >= 50.0
    else:
        res.checks["face_too_small"] = None

    widths = [s.face.width_px for s in run.states if s.face.width_px]
    m["face_width_px_median"] = round(statistics.median(widths), 1) if widths else None
    m["face_present_pct"] = round(100 * sum(s.face.present for s in run.states) / max(len(run.states), 1), 1)
    m["duration_s"] = round(run.duration_s, 1)
    m["frames"] = len(run.states)
    res.notes.append(
        "Ground truth is human timing (cue reaction / key press, ~100-300 ms). closed_ms error compares durations."
    )
    return res


def render_markdown(title: str, meta: dict[str, Any], result: EvalResult, yaml_values: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    for key, value in meta.items():
        lines.append(f"- **{key}:** {value}")
    lines += ["", "## Exit criteria", "", "| Criterion | Result |", "|---|---|"]
    for key, text in CRITERIA.items():
        verdict = result.checks.get(key)
        mark = "PASS" if verdict else ("not measured" if verdict is None else "**FAIL**")
        lines.append(f"| {text} | {mark} |")
    lines += ["", "## Metrics", "", "| Metric | Value |", "|---|---|"]
    for key, value in result.metrics.items():
        lines.append(f"| {key} | {value} |")
    lines += ["", "## Thresholds used (perception.yaml)", "", "```yaml"]
    for key, value in yaml_values.items():
        lines.append(f"{key}: {value}")
    lines += ["```", "", "## Notes", ""] + [f"- {n}" for n in result.notes] + [""]
    return "\n".join(lines)
