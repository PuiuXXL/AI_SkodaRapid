"""Evaluate gaze zones against a guided, labelled session (``scripts/eval_zones.py``).

Labels: ``zone`` windows with ``value = "<zone>:<mode>"`` (owl = head turned, lizard = eyes only), one per trial,
written when the prompt appears. People react ~0.3-0.8 s after the prompt, so every trial is measured from its
**movement onset** (first frame where the raw head or the smoothed gaze moved away from the level of the 0.5 s
before the prompt), not from the prompt:

* frame confusion matrix and per-trial accuracy (majority zone of the frames from onset + ``SETTLE_S`` to the end),
  separately for owl and lizard;
* watched confusions: road <-> mirror_left (must be zero) and passenger <-> mirror_right (<= 5 % of the frames);
* latency: onset -> first frame where the stable zone equals the target (the zone tracker's delay included);
* signs: mirror_left owl -> head yaw and gaze yaw > 0 (driver's left); lap -> gaze pitch < 0 (down).

The same functions run on a recorded session (``--session``) and on a parameter sweep (``--sweep``), where only the
zone classifier is re-run on the stored per-frame features.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from perception.calibration import Calibration
from perception.config import PerceptionConfig
from perception.driver_cam.gaze_zones import ZoneTracker, zone_head_angles
from perception.driver_cam.pipeline import DriverPipeline
from perception.features import FeatureFrame
from perception.labels import Interval

__all__ = [
    "CRITERIA",
    "ZoneEvalResult",
    "ZoneReplay",
    "ZoneSeries",
    "ZoneTrial",
    "evaluate_zones",
    "reclassify",
    "render_zone_markdown",
    "run_zone_pipeline",
    "trials_from_intervals",
]

SETTLE_S = 0.3  # frames this long after the onset are not scored for accuracy (the eyes are still travelling)
BASELINE_S = 0.5  # level before the prompt
ONSET_HEAD_DEG = 4.0
ONSET_GAZE_DEG = 8.0  # MobileGaze is noisier than the head pose
MAX_REACTION_S = 1.5  # no onset within this -> onset = prompt + median reaction of the other trials

CRITERIA = {
    "owl_accuracy": "owl accuracy >= 95 %",
    "lizard_accuracy": "lizard accuracy >= 90 %",
    "road_vs_mirror_left": "road <-> mirror_left confusions: 0",
    "passenger_vs_mirror_right": "passenger <-> mirror_right confusions <= 5 %",
    "latency": "zone changed < 300 ms after the gaze moved (median)",
}


@dataclass(frozen=True)
class ZoneTrial:
    zone: str
    mode: str
    start: float
    end: float


def trials_from_intervals(intervals: Sequence[Interval]) -> list[ZoneTrial]:
    out = []
    for iv in intervals:
        if iv.label != "zone" or not iv.value or iv.end <= iv.start:
            continue
        zone, _, mode = iv.value.partition(":")
        out.append(ZoneTrial(zone, mode or "owl", iv.start, iv.end))
    return sorted(out, key=lambda tr: tr.start)


@dataclass
class ZoneSeries:
    """Per-frame zone output plus the raw signals used for the movement onset."""

    t: list[float] = field(default_factory=list)
    zone: list[str] = field(default_factory=list)
    head_yaw: list[float | None] = field(default_factory=list)
    head_pitch: list[float | None] = field(default_factory=list)
    gaze_yaw: list[float | None] = field(default_factory=list)
    gaze_pitch: list[float | None] = field(default_factory=list)

    def add(
        self,
        t: float,
        zone: str,
        head: tuple[float | None, float | None],
        gaze: tuple[float | None, float | None],
    ) -> None:
        self.t.append(t)
        self.zone.append(zone)
        self.head_yaw.append(head[0])
        self.head_pitch.append(head[1])
        self.gaze_yaw.append(gaze[0])
        self.gaze_pitch.append(gaze[1])


@dataclass
class ZoneEvalResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, bool | None] = field(default_factory=dict)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    trials: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(v for v in self.checks.values() if v is not None)


def _median(values: Sequence[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def _onset(s: ZoneSeries, trial: ZoneTrial) -> float | None:
    t = np.asarray(s.t)
    before = np.where((t >= trial.start - BASELINE_S) & (t < trial.start))[0]
    window = np.where((t >= trial.start) & (t < min(trial.end, trial.start + MAX_REACTION_S)))[0]
    if len(before) == 0 or len(window) == 0:
        return None
    signals = (
        (s.head_yaw, ONSET_HEAD_DEG),
        (s.head_pitch, ONSET_HEAD_DEG),
        (s.gaze_yaw, ONSET_GAZE_DEG),
        (s.gaze_pitch, ONSET_GAZE_DEG),
    )
    levels = [(_median([sig[i] for i in before]), sig, thr) for sig, thr in signals]
    for i in window:
        for level, sig, thr in levels:
            v = sig[i]
            if level is not None and v is not None and abs(v - level) > thr:
                return float(t[i])
    return None


def evaluate_zones(s: ZoneSeries, trials: Sequence[ZoneTrial], zones: Sequence[str]) -> ZoneEvalResult:
    res = ZoneEvalResult()
    m = res.metrics
    t = np.asarray(s.t)
    onsets: list[float | None] = []
    for tr in trials:
        onsets.append(tr.start if tr.zone == "road" else _onset(s, tr))
    reactions = [o - tr.start for o, tr in zip(onsets, trials, strict=True) if o is not None and tr.zone != "road"]
    reaction = statistics.median(reactions) if reactions else 0.5
    confusion: dict[str, dict[str, int]] = {z: {} for z in zones}
    latencies: list[float] = []
    correct = {"owl": 0, "lizard": 0}
    total = {"owl": 0, "lizard": 0}
    unknown_frames = scored_frames = 0
    for tr, onset in zip(trials, onsets, strict=True):
        start = onset if onset is not None else tr.start + reaction
        idx = np.where((t >= start + SETTLE_S) & (t < tr.end))[0]
        if len(idx) == 0:
            continue
        got = [s.zone[i] for i in idx]
        row = confusion.setdefault(tr.zone, {})
        for z in got:
            row[z] = row.get(z, 0) + 1
        scored_frames += len(got)
        unknown_frames += sum(z == "unknown" for z in got)
        majority = max(set(got), key=got.count)
        ok = majority == tr.zone
        total[tr.mode] = total.get(tr.mode, 0) + 1
        correct[tr.mode] = correct.get(tr.mode, 0) + int(ok)
        latency = None
        if tr.zone != "road" and onset is not None:
            hit = np.where((t >= onset) & (t < tr.end) & (np.asarray(s.zone, dtype=object) == tr.zone))[0]
            if len(hit):
                latency = float(t[hit[0]] - onset)
                latencies.append(latency)
        res.trials.append(
            {
                "zone": tr.zone,
                "mode": tr.mode,
                "majority": majority,
                "ok": ok,
                "reaction_s": round(onset - tr.start, 3) if onset is not None else None,
                "latency_s": round(latency, 3) if latency is not None else None,
            }
        )
    res.confusion = confusion

    for mode, key, bar in (("owl", "owl_accuracy", 0.95), ("lizard", "lizard_accuracy", 0.90)):
        if total.get(mode):
            acc = correct[mode] / total[mode]
            m[f"{mode}_trials"] = total[mode]
            m[key] = round(acc, 3)
            res.checks[key] = acc >= bar
        else:
            res.checks[key] = None

    def frames_as(a: str, b: str) -> int:
        return confusion.get(a, {}).get(b, 0)

    def frames_of(a: str) -> int:
        return sum(confusion.get(a, {}).values())

    if frames_of("road") and frames_of("mirror_left"):
        n = frames_as("road", "mirror_left") + frames_as("mirror_left", "road")
        m["road_vs_mirror_left_frames"] = n
        res.checks["road_vs_mirror_left"] = n == 0
    else:
        res.checks["road_vs_mirror_left"] = None
    if frames_of("passenger") and frames_of("mirror_right"):
        share = max(
            frames_as("passenger", "mirror_right") / frames_of("passenger"),
            frames_as("mirror_right", "passenger") / frames_of("mirror_right"),
        )
        m["passenger_vs_mirror_right_pct"] = round(100 * share, 1)
        res.checks["passenger_vs_mirror_right"] = share <= 0.05
    else:
        res.checks["passenger_vs_mirror_right"] = None
    if latencies:
        m["latency_ms_median"] = round(1000 * statistics.median(latencies), 1)
        m["latency_ms_p90"] = round(1000 * float(np.percentile(latencies, 90)), 1)
        m["latency_trials"] = len(latencies)
        res.checks["latency"] = statistics.median(latencies) < 0.3
    else:
        res.checks["latency"] = None
    m["reaction_ms_median"] = round(1000 * reaction, 1)
    m["onsets_found"] = f"{sum(o is not None for o in onsets)}/{len(trials)}"
    m["unknown_pct"] = round(100 * unknown_frames / max(scored_frames, 1), 1)
    m["per_zone_accuracy"] = {z: round(frames_as(z, z) / frames_of(z), 3) for z in zones if frames_of(z)}

    # --- signs ------------------------------------------------------------------------------------------
    def window_values(zone: str, mode: str | None, values: list[float | None]) -> list[float | None]:
        out: list[float | None] = []
        for tr, onset in zip(trials, onsets, strict=True):
            if tr.zone != zone or (mode is not None and tr.mode != mode):
                continue
            start = (onset if onset is not None else tr.start + reaction) + SETTLE_S
            out += [values[i] for i in np.where((t >= start) & (t < tr.end))[0]]
        return out

    hy = _median(window_values("mirror_left", "owl", s.head_yaw))
    gy = _median(window_values("mirror_left", None, s.gaze_yaw))
    gp = _median(window_values("lap", None, s.gaze_pitch))
    m["mirror_left_owl_head_yaw_median"] = round(hy, 1) if hy is not None else None
    m["mirror_left_gaze_yaw_median"] = round(gy, 1) if gy is not None else None
    m["lap_gaze_pitch_median"] = round(gp, 1) if gp is not None else None
    m["sign_ok"] = bool(hy is not None and gy is not None and gp is not None and hy > 0 and gy > 0 and gp < 0)
    m["frames"] = len(s.t)
    m["duration_s"] = round(s.t[-1] - s.t[0], 1) if len(s.t) > 1 else 0.0
    res.notes.append(
        f"Trials scored from the movement onset (head > {ONSET_HEAD_DEG} deg or gaze > {ONSET_GAZE_DEG} deg away from "
        f"the {BASELINE_S} s before the prompt) + {SETTLE_S} s; latency = onset -> first frame with the target zone."
    )
    return res


def render_zone_markdown(
    title: str, meta: dict[str, Any], result: ZoneEvalResult, zones: Sequence[str], yaml_values: dict[str, Any]
) -> str:
    lines = [f"# {title}", ""]
    lines += [f"- **{k}:** {v}" for k, v in meta.items()]
    lines += ["", "## Exit criteria", "", "| Criterion | Result |", "|---|---|"]
    for key, text in CRITERIA.items():
        verdict = result.checks.get(key)
        mark = "PASS" if verdict else ("not measured" if verdict is None else "**FAIL**")
        lines.append(f"| {text} | {mark} |")
    lines += ["", "## Metrics", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in result.metrics.items()]
    cols = [*zones, "away", "unknown"]
    lines += ["", "## Confusion matrix (frames; rows = target, columns = detected)", ""]
    lines.append("| target \\ detected | " + " | ".join(cols) + " |")
    lines.append("|---|" + "---:|" * len(cols))
    for z in zones:
        row = result.confusion.get(z, {})
        lines.append(f"| {z} | " + " | ".join(str(row.get(c, 0)) for c in cols) + " |")
    lines += ["", "## Trials", "", "| # | zone | mode | detected (majority) | ok | reaction s | latency s |"]
    lines.append("|---:|---|---|---|---|---:|---:|")
    for k, tr in enumerate(result.trials, 1):
        lines.append(
            f"| {k} | {tr['zone']} | {tr['mode']} | {tr['majority']} | {'yes' if tr['ok'] else '**no**'} | "
            f"{tr['reaction_s'] if tr['reaction_s'] is not None else '-'} | "
            f"{tr['latency_s'] if tr['latency_s'] is not None else '-'} |"
        )
    lines += ["", "## Values used (perception.yaml)", "", "```yaml"]
    lines += [f"{k}: {v}" for k, v in yaml_values.items()]
    lines += ["```", "", "## Notes", ""] + [f"- {n}" for n in result.notes] + [""]
    return "\n".join(lines)


# --- replay helpers (recorded sessions and the parameter sweep; development / evaluation only, never in the demo) ---


@dataclass
class ZoneReplay:
    """Per-frame output of one pipeline pass, with the zone features kept so the classifier can be re-run cheaply."""

    series: ZoneSeries
    features: list[np.ndarray | None]
    eyes_closed: list[bool]


def run_zone_pipeline(
    cfg: PerceptionConfig, frames: Iterable[FeatureFrame], frame_size: tuple[int, int], calibration: Calibration
) -> ZoneReplay:
    pipeline = DriverPipeline(cfg, frame_size, calibration.ear_baseline, calibration.model)
    out = ZoneReplay(ZoneSeries(), [], [])
    for ff in frames:
        st = pipeline.update(ff)
        head = zone_head_angles(st.head.yaw, st.head.raw_yaw, st.head.raw_pitch)
        out.series.add(st.t, st.gaze.zone, head, (st.gaze.gaze_yaw, st.gaze.gaze_pitch))
        out.features.append(pipeline.last_zone_features)
        out.eyes_closed.append(st.eyes.state == "CLOSED")
    return out


def reclassify(cfg: PerceptionConfig, calibration: Calibration, replay: ZoneReplay) -> ZoneSeries:
    """Zone series for another yaml variant (k, weights, reject factor, zone_min_frames) on the same features."""
    model = Calibration.from_samples(
        cfg,
        calibration.name,
        calibration.samples,
        calibration.zones,
        calibration.modes,
        calibration.segments,
        calibration.times,
    ).model
    tracker = ZoneTracker(cfg.gaze.zone_min_frames, cfg.eyes.blink_max_ms / 1000.0)
    s = replay.series
    out = ZoneSeries()
    for i, t in enumerate(s.t):
        x, closed = replay.features[i], replay.eyes_closed[i]
        result = model.classify(x) if x is not None and not closed else None
        zone = tracker.update(t, result, eyes_closed=closed)
        out.add(t, zone, (s.head_yaw[i], s.head_pitch[i]), (s.gaze_yaw[i], s.gaze_pitch[i]))
    return out
