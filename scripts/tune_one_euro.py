"""Tune the One Euro filter for the head angles, per axis, on a recorded labelled session (Casiez et al., CHI 2012).

    python scripts/tune_one_euro.py --session data/features/<session>

Procedure (the 1€ paper's two criteria, per axis on the raw MediaPipe angles): min_cutoff sets the jitter at rest,
beta the lag in fast motion. A grid over both; the pair with the lowest jitter on neutral still frames whose lag
during fast head movements (label ``head_fast``) is at most --max-lag-ms wins (Casiez' manual recipe, beta = 0 then
raise beta, reaches the same trade-off by hand).

Metrics:
* jitter = frame-to-frame noise, std(consecutive differences) / sqrt(2), on neutral frames of the ``still`` window
  (eyes OPEN, not speaking, not yawning): insensitive to the slow real drift of a "still" head, which the old
  metric (plain std) measured instead (raw and filtered were equal).
* lag = the time shift that best aligns the filtered with the raw angle (cross-correlation) during ``head_fast``.

Writes docs/eval/one-euro-<date>.md with the grid and the proposed yaml block. Never changes the yaml itself.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from perception.config import REPO_ROOT, load_config
from perception.driver_cam.head import euler_from_matrix
from perception.driver_cam.pipeline import DriverPipeline
from perception.evaluation import STILL_SKIP_S, neutral_jitter
from perception.filters import OneEuroFilter
from perception.labels import load_labels, to_intervals
from perception.replay import FeatureReplay

EVAL_DIR = REPO_ROOT / "docs" / "eval"
AXES = ("yaw", "pitch", "roll")
MIN_CUTOFFS = (0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)
BETAS = (0.0, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0)


def run_filter(t: np.ndarray, x: np.ndarray, valid: np.ndarray, mc: float, beta: float, dc: float) -> np.ndarray:
    f = OneEuroFilter(mc, beta, dc)
    out = np.full_like(x, np.nan)
    for k in range(len(t)):
        if not valid[k]:
            f.reset()
            continue
        out[k] = f.update(float(t[k]), float(x[k]))
    return out


def lag_ms(t: np.ndarray, raw: np.ndarray, filt: np.ndarray, mask: np.ndarray, max_ms: float = 400.0) -> float:
    """Shift (ms) of ``filt`` behind ``raw`` minimising their squared difference inside ``mask`` (1 kHz resample)."""
    tt, r, f = t[mask], raw[mask], filt[mask]
    ok = np.isfinite(r) & np.isfinite(f)
    tt, r, f = tt[ok], r[ok], f[ok]
    if len(tt) < 10:
        return float("nan")
    grid = np.arange(tt[0], tt[-1], 0.001)
    rg, fg = np.interp(grid, tt, r), np.interp(grid, tt, f)
    best, best_err = 0, float("inf")
    for shift in range(0, int(max_ms) + 1, 2):
        err = float(np.mean((fg[shift:] - rg[: len(rg) - shift]) ** 2)) if shift else float(np.mean((fg - rg) ** 2))
        if err < best_err:
            best, best_err = shift, err
    return float(best)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--session", type=Path, required=True)
    p.add_argument("--max-lag-ms", type=float, default=50.0)
    args = p.parse_args(argv)
    cfg = load_config()
    replay = FeatureReplay(args.session / "features.jsonl.gz")
    frames = list(replay.frames())
    cam = replay.meta.get("camera", {})
    pipeline = DriverPipeline(cfg, (int(cam.get("width", 1280)), int(cam.get("height", 720))))
    states = [pipeline.update(ff) for ff in frames]
    _, events = load_labels(args.session / "labels.jsonl")
    intervals = to_intervals(events, t_end=frames[-1].t)

    t = np.asarray([ff.t for ff in frames])
    valid = np.asarray([ff.face.head_matrix is not None for ff in frames])
    raw = {a: np.full(len(frames), np.nan) for a in AXES}
    for k, ff in enumerate(frames):
        if ff.face.head_matrix is not None:
            raw["pitch"][k], raw["yaw"][k], raw["roll"][k] = euler_from_matrix(ff.face.head_matrix)
    still = np.zeros(len(t), dtype=bool)
    fast = np.zeros(len(t), dtype=bool)
    for w in intervals:
        if w.label == "still":
            still |= (t >= w.start + STILL_SKIP_S) & (t < w.end)
        elif w.label == "head_fast":
            fast |= (t >= w.start) & (t < w.end)
    neutral = still & np.asarray([s.eyes.state == "OPEN" and not s.speaking and not s.yawn for s in states], dtype=bool)
    if neutral.sum() < 30 or fast.sum() < 30:
        print("session needs a 'still' and a 'head_fast' window", file=sys.stderr)
        return 1

    dc = cfg.filters.one_euro.d_cutoff
    lines = [
        f"# One Euro tuning for head angles, {dt.date.today().isoformat()}",
        "",
        f"Session `{args.session.name}`: {int(neutral.sum())} neutral still frames, {int(fast.sum())} head_fast "
        f"frames. Lowest jitter with lag <= {args.max_lag_ms} ms (criterion: jitter < 1 deg).",
        "",
        "jitter = std(consecutive differences) / sqrt(2) on neutral still frames; lag = best alignment "
        "shift of filtered vs raw during head_fast.",
        "",
    ]
    proposal: dict[str, tuple[float, float]] = {}
    for axis in AXES:
        x = raw[axis]
        raw_jitter = neutral_jitter(t.tolist(), x.tolist(), neutral.tolist())
        cur = getattr(cfg.filters.one_euro_head, axis)
        current = run_filter(t, x, valid, cur.min_cutoff, cur.beta, dc)
        lines += [
            f"## {axis}",
            "",
            f"raw jitter {raw_jitter:.3f} deg; current yaml ({cur.min_cutoff}, "
            f"{cur.beta}): jitter {neutral_jitter(t.tolist(), current.tolist(), neutral.tolist()):.3f} deg, "
            f"lag {lag_ms(t, x, current, fast):.0f} ms",
            "",
            "| min_cutoff | beta | jitter deg | lag ms |",
            "|---|---|---|---|",
        ]
        # Casiez trade-off on a grid: jitter at rest (min_cutoff) vs lag in motion (beta). Pick the lowest jitter
        # whose lag on head_fast stays within --max-lag-ms (ties: lower lag).
        candidates: list[tuple[float, float, float, float]] = []
        for mc in MIN_CUTOFFS:
            for beta in BETAS:
                y = run_filter(t, x, valid, mc, beta, dc)
                j, lg = neutral_jitter(t.tolist(), y.tolist(), neutral.tolist()), lag_ms(t, x, y, fast)
                candidates.append((mc, beta, j, lg))
                if beta == 0.0 or lg <= args.max_lag_ms:
                    lines.append(f"| {mc} | {beta} | {j:.3f} | {lg:.0f} |")
        ok = [c for c in candidates if c[3] <= args.max_lag_ms] or candidates
        mc_best, beta_best, _, _ = min(ok, key=lambda c: (round(c[2], 3), c[3]))
        y = run_filter(t, x, valid, mc_best, beta_best, dc)
        j, lg = neutral_jitter(t.tolist(), y.tolist(), neutral.tolist()), lag_ms(t, x, y, fast)
        proposal[axis] = (mc_best, beta_best)
        lines += [
            "",
            f"**Proposed {axis}:** min_cutoff {mc_best}, beta {beta_best} -> jitter {j:.3f} deg, lag {lg:.0f} ms",
            "",
        ]
        print(
            f"{axis}: raw jitter {raw_jitter:.3f}; proposed mc={mc_best} beta={beta_best}: "
            f"jitter {j:.3f}, lag {lg:.0f} ms"
        )
    lines += ["## Proposed yaml", "", "```yaml", "  one_euro_head:"]
    lines += [f"    {a}: {{ min_cutoff: {mc}, beta: {b}, d_cutoff: {dc} }}" for a, (mc, b) in proposal.items()]
    lines += ["```", ""]
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    path = EVAL_DIR / f"one-euro-{dt.date.today().isoformat()}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
