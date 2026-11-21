"""Diagnose the eye / head / mouth detectors on a recorded, labelled session (replay, development only).

    python scripts/diag_eyes.py --session data/features/<session>

Writes, under data/diag/<session>/ (local only, gitignored with the rest of data/):
  * overview_NN.png: 30 s pages with raw EAR left/right, EAR / local reference (bilateral) with drop_ratio / reopen_ratio, eyeBlink,
    eyeSquint, eyeLookDown, head pitch raw/filtered, the labels and the detected states;
  * blinks.png, closures.png, false_closures.png, squint_smile.png, look_down.png: one zoomed panel per event;
  * diag.md: the tables and the three answers (blink width raw vs filtered, cause of false closures, real fps).

No pixels are involved: everything comes from the FeatureFrames (perception/features.py) and the labels.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from perception.config import REPO_ROOT, PerceptionConfig, load_config
from perception.driver_cam.eyes import EyeEvent
from perception.driver_cam.head import euler_from_matrix
from perception.driver_cam.pipeline import DriverPipeline, DriverState
from perception.evaluation import BLINK_MATCH_AFTER_S, BLINK_MATCH_BEFORE_S, STILL_SKIP_S
from perception.eye_signal import measure_dip
from perception.features import FeatureFrame
from perception.labels import Interval, load_labels, to_intervals
from perception.replay import FeatureReplay

DIAG_DIR = REPO_ROOT / "data" / "diag"
PAGE_S = 30.0
LABEL_COLORS = {
    "blink": "tab:red",
    "eyes_closed": "tab:purple",
    "squint": "tab:orange",
    "smile": "gold",
    "look_down": "tab:brown",
    "speaking": "tab:green",
    "yawn": "tab:pink",
    "still": "lightgrey",
    "head_fast": "tab:cyan",
    "pose_left": "tab:blue",
    "pose_up": "tab:blue",
    "pose_tilt_left": "tab:blue",
    "pose_tilt_right": "tab:blue",
    "step_back": "grey",
}
STATE_COLORS = {"CLOSED": "black", "SQUINT": "tab:orange", "UNKNOWN": "lightgrey"}


# --- per-frame series --------------------------------------------------------------------------------------


@dataclass
class Series:
    t: np.ndarray
    frame_id: np.ndarray
    present: np.ndarray
    ear_l: np.ndarray
    ear_r: np.ndarray
    base_l: np.ndarray
    base_r: np.ndarray
    ratio: np.ndarray  # bilateral eye signal the detector sees (max over reliable eyes, local reference)
    r_l: np.ndarray  # EAR / local reference, per eye
    r_r: np.ndarray
    blink: np.ndarray
    squint: np.ndarray
    look_down: np.ndarray
    pitch_raw: np.ndarray
    yaw_raw: np.ndarray
    roll_raw: np.ndarray
    pitch: np.ndarray
    yaw: np.ndarray
    roll: np.ndarray
    state: list[str]
    speaking: np.ndarray

    def mask(self, t0: float, t1: float) -> np.ndarray:
        return (self.t >= t0) & (self.t < t1)


def _f(v: float | None) -> float:
    return float("nan") if v is None else float(v)


_COLS = (
    "ear_l",
    "ear_r",
    "base_l",
    "base_r",
    "ratio",
    "blink",
    "squint",
    "look_down",
    "pitch_raw",
    "yaw_raw",
    "roll_raw",
    "pitch",
    "yaw",
    "roll",
)


def build_series(frames: Sequence[FeatureFrame], states: Sequence[DriverState]) -> Series:
    cols: dict[str, list[float]] = {k: [] for k in _COLS}
    for ff, st in zip(frames, states, strict=True):
        e, h = st.eyes, st.head
        cols["ear_l"].append(_f(e.ear_left))
        cols["ear_r"].append(_f(e.ear_right))
        cols["base_l"].append(_f(e.ref_left))
        cols["base_r"].append(_f(e.ref_right))
        cols["ratio"].append(_f(e.ratio))
        bs = ff.face.blendshapes or {}
        present = ff.face.present
        cols["blink"].append((bs.get("eyeBlinkLeft", 0) + bs.get("eyeBlinkRight", 0)) / 2 if present else np.nan)
        cols["squint"].append(max(bs.get("eyeSquintLeft", 0), bs.get("eyeSquintRight", 0)) if present else np.nan)
        cols["look_down"].append(
            (bs.get("eyeLookDownLeft", 0) + bs.get("eyeLookDownRight", 0)) / 2 if present else np.nan
        )
        if ff.face.head_matrix is not None:
            p, y, r = euler_from_matrix(ff.face.head_matrix)
        else:
            p = y = r = float("nan")
        cols["pitch_raw"].append(p)
        cols["yaw_raw"].append(y)
        cols["roll_raw"].append(r)
        cols["pitch"].append(_f(h.pitch))
        cols["yaw"].append(_f(h.yaw))
        cols["roll"].append(_f(h.roll))
    arr = {k: np.asarray(v, dtype=float) for k, v in cols.items()}
    r_l = np.asarray([_f(st.eyes.ratio_left) for st in states])
    r_r = np.asarray([_f(st.eyes.ratio_right) for st in states])
    return Series(
        t=np.asarray([ff.t for ff in frames]),
        frame_id=np.asarray([ff.frame_id for ff in frames]),
        present=np.asarray([ff.face.present for ff in frames]),
        r_l=r_l,
        r_r=r_r,
        state=[st.eyes.state for st in states],
        speaking=np.asarray([st.speaking for st in states]),
        **arr,
    )


# --- helpers ------------------------------------------------------------------------------------------------


def _of(intervals: Sequence[Interval], *labels: str) -> list[Interval]:
    return [i for i in intervals if i.label in labels]


def _overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 <= b1 and b0 <= a1


def _nanp(values: np.ndarray, q: float) -> float:
    v = values[np.isfinite(values)]
    return float(np.percentile(v, q)) if v.size else float("nan")


def _nanmean(values: np.ndarray) -> float:
    v = values[np.isfinite(values)]
    return float(v.mean()) if v.size else float("nan")


def _rank(value: float, population: np.ndarray) -> float:
    """Percentile rank (0-100) of ``value`` in ``population``."""
    pop = population[np.isfinite(population)]
    if not pop.size or not np.isfinite(value):
        return float("nan")
    return float(100.0 * (pop < value).mean())


def _r(v: float | None, nd: int = 1) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    return f"{v:.{nd}f}"


def _runs(mask: np.ndarray, t: np.ndarray) -> list[tuple[float, float]]:
    """(start, end) times of the True runs of ``mask``."""
    out: list[tuple[float, float]] = []
    start = None
    for k, m in enumerate(mask):
        if m and start is None:
            start = t[k]
        elif not m and start is not None:
            out.append((start, t[k]))
            start = None
    if start is not None:
        out.append((start, t[-1]))
    return out


# --- analyses -----------------------------------------------------------------------------------------------


def fps_report(s: Series, meta: dict[str, Any]) -> dict[str, Any]:
    dt = np.diff(s.t)
    dframes = np.diff(s.frame_id)
    span = float(s.t[-1] - s.t[0])
    cam = meta.get("camera", {})
    return {
        "camera_reported": f"{cam.get('width')}x{cam.get('height')} {cam.get('fourcc')} @ {cam.get('fps')} fps",
        "processed_fps": round(float(len(s.t) - 1) / float(span), 2) if span > 0 else None,
        "camera_fps_from_frame_ids": round(float(s.frame_id[-1] - s.frame_id[0]) / float(span), 2)
        if span > 0
        else None,
        "dt_ms_p5": round(float(np.percentile(dt, 5)) * 1000, 1),
        "dt_ms_p50": round(float(np.percentile(dt, 50)) * 1000, 1),
        "dt_ms_p95": round(float(np.percentile(dt, 95)) * 1000, 1),
        "gaps_over_100ms": int((dt > 0.1).sum()),
        "camera_frames_skipped": int((dframes - 1).clip(min=0).sum()),
    }


def _pre_ref(t: np.ndarray, v: np.ndarray, t0: float, fallback: float) -> float:
    m = (t >= t0 - 2.0) & (t < t0)
    ref = _nanp(v[m], 90)
    return ref if np.isfinite(ref) else fallback


def _match_cues(cues: Sequence[Interval], events: Sequence[EyeEvent]) -> list[EyeEvent | None]:
    """Same matching rule as perception/evaluation.py."""
    used: set[int] = set()
    out: list[EyeEvent | None] = []
    for cue in cues:
        hit = None
        for k, ev in enumerate(events):
            if k not in used and cue.start - BLINK_MATCH_BEFORE_S <= ev.start <= cue.start + BLINK_MATCH_AFTER_S:
                used.add(k)
                hit = ev
                break
        out.append(hit)
    return out


def blink_table(s: Series, cues: Sequence[Interval], events: Sequence[EyeEvent], drop_ratio: float) -> list[dict[str, Any]]:
    rows = []
    for cue, hit in zip(cues, _match_cues(cues, events), strict=True):
        t0, t1 = cue.start - BLINK_MATCH_BEFORE_S, cue.start + 1.5
        m = s.mask(t0, t1)
        t = s.t[m]
        row: dict[str, Any] = {"cue_t": round(cue.start, 2)}
        for side, ear in (("L", s.ear_l), ("R", s.ear_r)):
            ref = _pre_ref(s.t, ear, cue.start - BLINK_MATCH_BEFORE_S, _nanmean(ear[m]))
            shape = measure_dip(list(t), list(ear[m]), ref)
            row[f"min_{side}"] = round(shape.minimum / ref, 3) if shape else None
            row[f"raw_w50_{side}_ms"] = round(shape.width_ms, 0) if shape and shape.width_ms else None
            row[f"below50_{side}"] = shape.frames_below_half if shape else None
        ratio = s.ratio[m]
        ok = np.isfinite(ratio)
        ref_r = _pre_ref(s.t, s.ratio, cue.start - BLINK_MATCH_BEFORE_S, 1.0)
        shape_r = measure_dip(list(t[ok]), list(ratio[ok]), ref_r) if ok.sum() >= 3 else None
        row["det_min_ratio"] = round(float(np.nanmin(ratio)), 3) if ok.any() else None
        row["det_w50_ms"] = round(shape_r.width_ms, 0) if shape_r and shape_r.width_ms else None
        row["reaches_drop"] = bool(ok.any() and np.nanmin(ratio) < drop_ratio)
        row["detected"] = hit.kind if hit else "no"
        row["detected_ms"] = round(hit.duration_ms, 0) if hit else None
        row["frames_in_window"] = int(m.sum())
        rows.append(row)
    return rows


def closure_table(s: Series, wins: Sequence[Interval], events: Sequence[EyeEvent]) -> list[dict[str, Any]]:
    rows = []
    for w in wins:
        m = s.mask(w.start - 0.5, w.end + 2.0)
        t = s.t[m]
        r = np.fmin(s.r_l[m], s.r_r[m])
        ok = np.isfinite(r)
        shape = measure_dip(list(t[ok]), list(r[ok]), _pre_ref(s.t, np.fmin(s.r_l, s.r_r), w.start, 1.0))
        hits = [e for e in events if e.kind == "closure" and _overlaps(e.start, e.end, w.start, w.end)]
        longest = max(hits, key=lambda e: e.duration_ms) if hits else None
        rows.append(
            {
                "label_t": round(w.start, 2),
                "label_ms": round((w.end - w.start) * 1000),
                "raw_w50_ms": round(shape.width_ms) if shape and shape.width_ms else None,
                "raw_down_delay_ms": round((shape.t_down - w.start) * 1000) if shape and shape.t_down else None,
                "raw_up_after_label_ms": round((shape.t_up - w.end) * 1000) if shape and shape.t_up else None,
                "detected_start_delay_ms": round((longest.start - w.start) * 1000) if longest else None,
                "detected_ms": round(longest.duration_ms) if longest else None,
                "pieces": len(hits),
            }
        )
    return rows


def false_closures(
    s: Series, intervals: Sequence[Interval], events: Sequence[EyeEvent], cfg: PerceptionConfig
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    allowed = _of(intervals, "eyes_closed", "yawn")
    fc = [
        e
        for e in events
        if e.kind == "closure" and not any(_overlaps(e.start, e.end, w.start - 0.5, w.end + 0.5) for w in allowed)
    ]
    labelled = [i for i in intervals if i.end > i.start and i.label not in ("zone",)]
    in_any = np.zeros_like(s.t, dtype=bool)
    for i in labelled:
        in_any |= s.mask(i.start - 0.5, i.end + 0.5)
    normal = (~in_any) & np.asarray([st == "OPEN" for st in s.state])
    pop = {k: getattr(s, k)[normal] for k in ("look_down", "pitch_raw", "squint", "blink")}
    p95_down = _nanp(pop["look_down"], 95)
    p5_pitch = _nanp(pop["pitch_raw"], 5)
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for e in fc:
        m = s.mask(e.start, max(e.end, e.start + 0.05))
        labels = sorted({i.label for i in labelled if _overlaps(e.start, e.end, i.start, i.end)})
        vals = {k: _nanmean(getattr(s, k)[m]) for k in ("look_down", "pitch_raw", "squint", "blink", "r_l", "r_r")}
        if "look_down" in labels:
            cat = "look_down (labelled)"
        elif labels and labels[0] in ("squint", "smile"):
            cat = f"{labels[0]} (labelled)"
        elif vals["look_down"] >= p95_down:
            cat = "look_down (eyeLookDown > p95)"
        elif vals["pitch_raw"] <= p5_pitch:
            cat = "pitch down (< p5)"
        elif cfg.eyes.squint_ear_band[0] <= max(vals["r_l"], vals["r_r"]) and vals["blink"] < cfg.eyes.blendshape_closed:
            cat = "squint-like (ratio in band, eyeBlink low)"
        elif labels:
            cat = f"during {'/'.join(labels)}"
        else:
            cat = "other"
        counts[cat] = counts.get(cat, 0) + 1
        rows.append(
            {
                "t": round(e.start, 2),
                "ms": round(e.duration_ms),
                "labels": ",".join(labels) or "-",
                "eyeLookDown": round(vals["look_down"], 2),
                "rank_lookdown": round(_rank(vals["look_down"], pop["look_down"])),
                "pitch": round(vals["pitch_raw"], 1),
                "rank_pitch": round(_rank(vals["pitch_raw"], pop["pitch_raw"])),
                "eyeSquint": round(vals["squint"], 2),
                "eyeBlink": round(vals["blink"], 2),
                "r_L": round(vals["r_l"], 2),
                "r_R": round(vals["r_r"], 2),
                "category": cat,
            }
        )
    return rows, counts


def window_table(s: Series, wins: Sequence[Interval], events: Sequence[EyeEvent], cfg: PerceptionConfig) -> list[dict[str, Any]]:
    low, high = cfg.eyes.squint_ear_band
    rows = []
    for w in wins:
        m = s.mask(w.start, w.end)
        states = [st for st, k in zip(s.state, m, strict=True) if k]
        ratio = s.ratio[m]
        squint = s.squint[m]
        in_band = (s.blink[m] < cfg.eyes.blendshape_closed) & (ratio >= low) & (ratio <= high)
        closures = [e for e in events if e.kind == "closure" and _overlaps(e.start, e.end, w.start, w.end)]
        rows.append(
            {
                "label": w.label,
                "t": round(w.start, 2),
                "closed_pct": round(100 * states.count("CLOSED") / max(len(states), 1)),
                "squint_state_pct": round(100 * states.count("SQUINT") / max(len(states), 1)),
                "closures": len(closures),
                "ratio_min": _r(_nanp(ratio, 0), 2),
                "ratio_p50": _r(_nanp(ratio, 50), 2),
                "r_L_p50": _r(_nanp(s.r_l[m], 50), 2),
                "r_R_p50": _r(_nanp(s.r_r[m], 50), 2),
                "eyeSquint_p50": _r(_nanp(squint, 50), 2),
                "eyeBlink_p50": _r(_nanp(s.blink[m], 50), 2),
                "eyeLookDown_p50": _r(_nanp(s.look_down[m], 50), 2),
                "pitch_p50": _r(_nanp(s.pitch_raw[m], 50), 1),
                "rfl4_band_pct": round(100 * float(in_band.mean())) if m.any() else None,
                "ratio_below_band_pct": round(100 * float((ratio < low).mean())) if m.any() else None,
            }
        )
    return rows


def head_report(s: Series, intervals: Sequence[Interval], reopen_ratio: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    still = _of(intervals, "still")
    if still:
        m = np.zeros_like(s.t, dtype=bool)
        for w in still:
            m |= s.mask(w.start + STILL_SKIP_S, w.end)
        neutral = m & np.asarray([st == "OPEN" for st in s.state]) & ~s.speaking & (s.ratio >= reopen_ratio)
        for name, mask in (("still_all", m), ("still_neutral", neutral)):
            out[name] = {
                "frames": int(mask.sum()),
                **{
                    f"{axis}_std_{kind}": round(float(np.nanstd(getattr(s, axis + suffix)[mask])), 3)
                    for axis in ("yaw", "pitch", "roll")
                    for kind, suffix in (("raw", "_raw"), ("filtered", ""))
                },
            }
        # does pitch move with the eye openness inside the still window? (eyelids pulling the head mesh)
        ok = m & np.isfinite(s.pitch_raw) & np.isfinite(s.ratio)
        if ok.sum() > 10:
            out["still_corr_pitch_vs_ratio"] = round(float(np.corrcoef(s.pitch_raw[ok], s.ratio[ok])[0, 1]), 3)
            blinkish = ok & (s.ratio < reopen_ratio)
            out["still_pitch_raw_mean_open_vs_blink"] = (
                round(float(np.nanmean(s.pitch_raw[ok & ~blinkish])), 2),
                round(float(np.nanmean(s.pitch_raw[blinkish])), 2) if blinkish.any() else None,
            )
    poses = {}
    for label in ("pose_left", "pose_up", "pose_tilt_left", "pose_tilt_right", "look_down", "head_fast"):
        wins = _of(intervals, label)
        if not wins:
            continue
        m = np.zeros_like(s.t, dtype=bool)
        for w in wins:
            m |= s.mask(w.start + 0.8, w.end)
        poses[label] = {axis: round(_nanp(getattr(s, axis + "_raw")[m], 50), 1) for axis in ("yaw", "pitch", "roll")}
    out["pose_medians_raw"] = poses
    return out


def speaking_report(s: Series, wins: Sequence[Interval]) -> list[dict[str, Any]]:
    rows = []
    for w in wins:
        m = s.mask(w.start, w.end)
        t, sp = s.t[m], s.speaking[m]
        first = t[sp][0] - w.start if sp.any() else None
        gaps = [b - a for a, b in _runs(~sp, t)] if sp.any() else []
        inner = [g for g in gaps[1:]] if gaps else []
        rows.append(
            {
                "t": round(w.start, 2),
                "first_speaking_s": round(first, 2) if first is not None else None,
                "coverage_pct": round(100 * float(sp.mean())) if m.any() else None,
                "gaps": len(inner),
                "gap_ms_p50": round(statistics.median(inner) * 1000) if inner else None,
                "gap_ms_max": round(max(inner) * 1000) if inner else None,
            }
        )
    return rows


# --- plots --------------------------------------------------------------------------------------------------


def _shade_states(ax: Any, s: Series, t0: float, t1: float) -> None:
    m = s.mask(t0, t1)
    t = s.t[m]
    states = np.asarray(s.state, dtype=object)[m]
    for name, color in STATE_COLORS.items():
        for a, b in _runs(states == name, t):
            ax.axvspan(a, b, color=color, alpha=0.15 if name != "CLOSED" else 0.25, lw=0)


def _label_bands(ax: Any, intervals: Sequence[Interval], t0: float, t1: float) -> None:
    names = sorted({i.label for i in intervals if i.label in LABEL_COLORS})
    for row, name in enumerate(names):
        for i in intervals:
            if i.label != name or i.end < t0 or i.start > t1:
                continue
            if i.end > i.start:
                ax.barh(row, i.end - i.start, left=i.start, color=LABEL_COLORS[name], height=0.7)
            else:
                ax.plot([i.start], [row], marker="v", color=LABEL_COLORS[name])
    ax.set_yticks(range(len(names)), names, fontsize=7)
    ax.set_ylim(-0.6, max(len(names), 1) - 0.4)


def plot_overview(
    s: Series, intervals: Sequence[Interval], events: Sequence[EyeEvent], cfg: PerceptionConfig, out: Path
) -> list[Path]:
    paths = []
    e = cfg.eyes
    t_start, t_end = s.t[0], s.t[-1]
    page = 0
    t0 = t_start
    while t0 < t_end:
        t1 = t0 + PAGE_S
        m = s.mask(t0, t1)
        fig, axes = plt.subplots(
            5, 1, figsize=(22, 13), sharex=True, gridspec_kw={"height_ratios": [2, 2, 1.5, 1.5, 1.4]}
        )
        t = s.t[m]
        ax = axes[0]
        ax.plot(t, s.ear_l[m], lw=0.9, label="EAR left (raw)")
        ax.plot(t, s.ear_r[m], lw=0.9, label="EAR right (raw)")
        ax.plot(t, s.base_l[m], lw=0.6, ls="--", color="tab:blue")
        ax.plot(t, s.base_r[m], lw=0.6, ls="--", color="tab:orange")
        ax.set_ylabel("EAR")
        ax.legend(loc="upper right", fontsize=7)
        ax = axes[1]
        ax.plot(t, s.r_l[m], lw=0.6, alpha=0.6, label="EAR/ref left")
        ax.plot(t, s.r_r[m], lw=0.6, alpha=0.6, label="EAR/ref right")
        ax.plot(t, s.ratio[m], lw=1.2, color="black", label="bilateral ratio (detector input)")
        ax.axhline(e.drop_ratio, color="red", lw=0.7, ls="--", label="drop_ratio")
        ax.axhline(e.reopen_ratio, color="green", lw=0.7, ls="--", label="reopen_ratio")
        ax.axhline(e.drop_ratio_relaxed, color="tab:brown", lw=0.5, ls=":", label="relaxed")
        ax.axhspan(*e.squint_ear_band, color="tab:orange", alpha=0.05)
        _shade_states(ax, s, t0, t1)
        ax.set_ylim(0, 1.4)
        ax.set_ylabel("ratio")
        ax.legend(loc="upper right", fontsize=7, ncol=3)
        ax = axes[2]
        ax.plot(t, s.blink[m], lw=0.9, label="eyeBlink")
        ax.plot(t, s.squint[m], lw=0.9, label="eyeSquint")
        ax.plot(t, s.look_down[m], lw=0.9, label="eyeLookDown")
        ax.axhline(e.blendshape_closed, color="tab:blue", lw=0.5, ls=":")
        ax.set_ylim(0, 1)
        ax.legend(loc="upper right", fontsize=7, ncol=3)
        ax = axes[3]
        ax.plot(t, s.pitch_raw[m], lw=0.6, alpha=0.7, label="pitch raw")
        ax.plot(t, s.pitch[m], lw=1.1, label="pitch One Euro")
        ax.plot(t, s.roll_raw[m], lw=0.6, alpha=0.6, label="roll raw")
        ax.set_ylabel("deg")
        ax.legend(loc="upper right", fontsize=7, ncol=3)
        ax = axes[4]
        _label_bands(ax, intervals, t0, t1)
        for ev in events:
            if ev.end >= t0 and ev.start <= t1:
                for a in axes[:2]:
                    a.axvspan(ev.start, ev.end, color="red" if ev.kind == "closure" else "tab:purple", alpha=0.12, lw=0)
        for i in intervals:
            if i.label == "blink" and t0 <= i.start <= t1:
                for a in axes[:3]:
                    a.axvline(i.start, color="tab:red", lw=0.6, ls=":")
        axes[-1].set_xlabel("t (s)")
        axes[-1].set_xlim(t0, t1)
        fig.suptitle(f"{out.name}  {t0:.0f}-{t1:.0f} s   (grey: SQUINT/UNKNOWN, dark: CLOSED, red span: closure event)")
        fig.tight_layout()
        path = out / f"overview_{page:02d}.png"
        fig.savefig(path, dpi=80)
        plt.close(fig)
        paths.append(path)
        page += 1
        t0 = t1
    return paths


def plot_windows(
    s: Series, windows: Sequence[tuple[float, float, str]], cfg: PerceptionConfig, path: Path
) -> Path | None:
    if not windows:
        return None
    cols = min(5, len(windows))
    rows = (len(windows) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.0 * rows), squeeze=False)
    for ax, (t0, t1, title) in zip(axes.flat, windows, strict=False):
        m = s.mask(t0, t1)
        t = s.t[m]
        ax.plot(t, s.r_l[m], ".-", ms=3, lw=0.8, label="L raw")
        ax.plot(t, s.r_r[m], ".-", ms=3, lw=0.8, label="R raw")
        ax.plot(t, s.ratio[m], "-", lw=1.4, color="black", label="bilateral")
        ax.plot(t, s.blink[m], lw=0.8, color="tab:blue", alpha=0.5, label="eyeBlink")
        ax.plot(t, s.squint[m], lw=0.8, color="tab:orange", alpha=0.5, label="eyeSquint")
        ax.plot(t, s.look_down[m], lw=0.8, color="tab:brown", alpha=0.5, label="eyeLookDown")
        ax.axhline(cfg.eyes.drop_ratio, color="red", lw=0.6, ls="--")
        ax.axhline(cfg.eyes.reopen_ratio, color="green", lw=0.6, ls="--")
        _shade_states(ax, s, t0, t1)
        ax.set_ylim(0, 1.3)
        ax.set_title(title, fontsize=8)
        ax.tick_params(labelsize=7)
    for ax in list(axes.flat)[len(windows) :]:
        ax.axis("off")
    axes.flat[0].legend(fontsize=6, loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=80)
    plt.close(fig)
    return path


# --- report -------------------------------------------------------------------------------------------------


def md_table(rows: Sequence[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["(none)"]
    keys = list(rows[0])
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    lines += ["| " + " | ".join("-" if r[k] is None else str(r[k]) for k in keys) + " |" for r in rows]
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--session", type=Path, required=True)
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--no-plots", action="store_true")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    session = args.session
    features = next((q for q in (session / "features.jsonl.gz", session / "features.jsonl") if q.exists()), None)
    if features is None or not (session / "labels.jsonl").exists():
        print(f"{session}: needs features.jsonl[.gz] and labels.jsonl", file=sys.stderr)
        return 1
    replay = FeatureReplay(features)
    frames = list(replay.frames())
    cam = replay.meta.get("camera", {})
    pipeline = DriverPipeline(cfg, (int(cam.get("width", 1280)), int(cam.get("height", 720))))
    states = [pipeline.update(ff) for ff in frames]
    events = list(pipeline.eyes.events)
    _, label_events = load_labels(session / "labels.jsonl")
    intervals = to_intervals(label_events, t_end=frames[-1].t)
    s = build_series(frames, states)

    out = DIAG_DIR / session.name
    out.mkdir(parents=True, exist_ok=True)
    fps = fps_report(s, replay.meta)
    cues = _of(intervals, "blink")
    blinks = blink_table(s, cues, events, cfg.eyes.drop_ratio)
    closures = closure_table(s, _of(intervals, "eyes_closed"), events)
    fc_rows, fc_counts = false_closures(s, intervals, events, cfg)
    sq_rows = window_table(s, _of(intervals, "squint", "smile"), events, cfg)
    ld_rows = window_table(s, _of(intervals, "look_down"), events, cfg)
    head = head_report(s, intervals, cfg.eyes.reopen_ratio)
    speak = speaking_report(s, _of(intervals, "speaking"))

    raw_w = [r[f"raw_w50_{side}_ms"] for r in blinks for side in "LR" if r[f"raw_w50_{side}_ms"]]
    med_w = [r["det_w50_ms"] for r in blinks if r["det_w50_ms"]]
    det_w = [r["detected_ms"] for r in blinks if r["detected_ms"]]
    answers = {
        "a_blink_width_raw_ms_median": statistics.median(raw_w) if raw_w else None,
        "a_blink_width_detector_input_ms_median": statistics.median(med_w) if med_w else None,
        "a_blink_detected_ms_median": statistics.median(det_w) if det_w else None,
        "a_blinks_reaching_drop_ratio": f"{sum(r['reaches_drop'] for r in blinks)}/{len(blinks)}",
        "a_blinks_detected": f"{sum(r['detected'] != 'no' for r in blinks)}/{len(blinks)}",
        "b_false_closures": sum(fc_counts.values()),
        "b_false_closures_by_category": fc_counts,
        "c_processed_fps": fps["processed_fps"],
        "c_camera_fps_from_frame_ids": fps["camera_fps_from_frame_ids"],
    }

    plots: list[Path] = []
    if not args.no_plots:
        plots += plot_overview(s, intervals, events, cfg, out)
        for name, wins in (
            ("blinks.png", [(c.start - 0.4, c.start + 1.3, f"cue {c.start:.1f}s") for c in cues]),
            (
                "closures.png",
                [(w.start - 0.7, w.end + 1.5, f"closed {w.start:.1f}s") for w in _of(intervals, "eyes_closed")],
            ),
            (
                "false_closures.png",
                [(r["t"] - 0.7, r["t"] + r["ms"] / 1000 + 0.7, f"{r['t']}s {r['category']}") for r in fc_rows],
            ),
            (
                "squint_smile.png",
                [(w.start - 0.5, w.end + 0.5, f"{w.label} {w.start:.1f}s") for w in _of(intervals, "squint", "smile")],
            ),
            (
                "look_down.png",
                [(w.start - 0.5, w.end + 0.5, f"look_down {w.start:.1f}s") for w in _of(intervals, "look_down")],
            ),
        ):
            path = plot_windows(s, wins, cfg, out / name)
            if path:
                plots.append(path)

    lines = [f"# Eye diagnostics: {session.name}", "", f"- frames: {len(frames)}, events: {len(events)}", ""]
    lines += ["## Answers", "", "```", *[f"{k}: {v}" for k, v in answers.items()], "```", ""]
    lines += ["## Frame rate", "", "```", *[f"{k}: {v}" for k, v in fps.items()], "```", ""]
    lines += ["## Cued blinks (raw = per-eye EAR; w50 = width at 50 % of the dip, interpolated)", "", *md_table(blinks)]
    lines += ["", "## Labelled 2 s closures", "", *md_table(closures)]
    lines += ["", "## False closures (rank = percentile vs normal open frames)", "", *md_table(fc_rows)]
    lines += ["", "## Squint / smile windows", "", *md_table(sq_rows)]
    lines += ["", "## Look-down windows", "", *md_table(ld_rows)]
    lines += ["", "## Head", "", "```", *[f"{k}: {v}" for k, v in head.items()], "```"]
    lines += ["", "## Speaking windows", "", *md_table(speak)]
    lines += ["", "## Plots", "", *[f"- {q.name}" for q in plots], ""]
    (out / "diag.md").write_text("\n".join(lines), encoding="utf-8")

    for k, v in answers.items():
        print(f"{k}: {v}")
    print("fps:", fps)
    print(f"\nreport: {out / 'diag.md'}  ({len(plots)} plots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
