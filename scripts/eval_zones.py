"""Evaluate the gaze zones (AS5) on the laptop camera with post-it targets, or compare MobileGaze crops.

    python scripts/eval_zones.py --name andrei                 # guided live (~5 min): every zone 5x owl + 5x lizard
    python scripts/eval_zones.py --session data/features/<s>   # re-evaluate a recorded zone session (replay)
    python scripts/eval_zones.py --session data/features/<s> --sweep   # k / reject / weights / zone_min_frames grid
    python scripts/eval_zones.py --ab-crop                     # MobileGaze crop 1.0 vs 1.2 on the same frames (~40 s)

The live mode needs a calibrated profile (scripts/calibrate.py --name <profile>). Trials come in random order (seed
saved); each prompt opens a labelled window (``zone`` = "<zone>:<mode>") followed by "back to the road". The session
(FeatureFrames + labels + a copy of the calibration, no pixels) is saved in data/features/<stamp>_zones-<name>/, so
it can be re-evaluated with --session. Reports go to docs/eval/. Replay is for evaluation only, never in the demo (R3).
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

from perception.calibration import ZONE_PROMPTS, Calibration, profile_path
from perception.capture import LatestFrameCamera
from perception.config import REPO_ROOT, PerceptionConfig, load_config
from perception.driver_cam.face import FaceLandmarkerModel
from perception.driver_cam.gaze_model import MobileGazeModel, driver_gaze
from perception.driver_cam.gaze_zones import zone_head_angles
from perception.driver_cam.pipeline import DriverPipeline
from perception.labels import ZONE_LABEL, LabelEvent, LabelWriter, load_labels, to_intervals
from perception.log import configure_logging
from perception.overlay import draw_driver, mean_luma
from perception.perf import RateMeter
from perception.recorder import DATA_DIR, RecordingSession
from perception.replay import FeatureReplay
from perception.zone_evaluation import (
    ZoneEvalResult,
    ZoneReplay,
    ZoneSeries,
    ZoneTrial,
    evaluate_zones,
    reclassify,
    render_zone_markdown,
    run_zone_pipeline,
    trials_from_intervals,
)

EVAL_DIR = REPO_ROOT / "docs" / "eval"
WINDOW = "DriveMate zone eval (q to abort)"
TRIAL_S = 2.5
BACK_S = 1.5
MODE_TEXT = {"owl": "cu CAPUL", "lizard": "doar cu OCHII"}


def _yaml_values(cfg: PerceptionConfig) -> dict[str, Any]:
    g = cfg.gaze
    return {
        "gaze.crop_expand": g.crop_expand,
        "gaze.max_age_ms": g.max_age_ms,
        "gaze.k": g.k,
        "gaze.feature_weights": g.feature_weights.model_dump(),
        "gaze.std_floor": g.std_floor.model_dump(),
        "gaze.reject_factor": g.reject_factor,
        "gaze.loo_exclude_s": g.loo_exclude_s,
        "gaze.min_conf": g.min_conf,
        "gaze.zone_min_frames": g.zone_min_frames,
        "gaze.away_margin_deg": g.away_margin_deg,
        "filters.one_euro_gaze": cfg.filters.one_euro_gaze.model_dump(),
        "rates.gaze_hz": cfg.rates.gaze_hz,
    }


def _write(name: str, cfg: PerceptionConfig, meta: dict[str, Any], result: ZoneEvalResult) -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    path = EVAL_DIR / f"zones-{name}-{stamp}.md"
    zones = list(cfg.gaze.zones)
    title = f"Gaze zone evaluation: {name} ({stamp})"
    path.write_text(render_zone_markdown(title, meta, result, zones, _yaml_values(cfg)), encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "meta": meta,
                "metrics": result.metrics,
                "checks": result.checks,
                "confusion": result.confusion,
                "trials": result.trials,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def _print(result: ZoneEvalResult) -> None:
    for key, ok in result.checks.items():
        print(f"  {'PASS' if ok else ('n/a ' if ok is None else 'FAIL')}  {key}")
    for key, value in result.metrics.items():
        print(f"     {key}: {value}")


def _cal_meta(cal: Calibration) -> dict[str, Any]:
    return {"calibration": cal.name, "calibration_loo": cal.loo_accuracy(), "tau": round(cal.model.tau, 3)}


# --- guided live -------------------------------------------------------------------------------------------


def trial_plan(cfg: PerceptionConfig, reps: int, seed: int) -> list[tuple[str, str]]:
    trials = [("road", "owl")] * reps
    trials += [(z, m) for z in cfg.gaze.zones if z != "road" for m in ("owl", "lizard") for _ in range(reps)]
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(trials))
    return [trials[i] for i in order]


def run_live(cfg: PerceptionConfig, name: str, profile: str, reps: int, seed: int) -> int:
    cal_path = profile_path(profile)
    if not cal_path.exists():
        print(f"no calibration for '{profile}': run scripts/calibrate.py --name {profile}", file=sys.stderr)
        return 1
    cal = Calibration.load(cfg, cal_path)
    session_dir = DATA_DIR / "features" / f"{dt.datetime.now():%Y%m%d-%H%M%S}_zones-{name}"
    session = RecordingSession(cfg, session_dir / "features.jsonl.gz", label=f"eval_zones: {name}", gesture_hz=None)
    shutil.copyfile(cal_path, session_dir / "calibration.json")  # the session stays re-evaluable if the profile changes
    info = session.info
    trials = trial_plan(cfg, reps, seed)
    writer = LabelWriter(
        session_dir / "labels.jsonl",
        {"session": session_dir.name, "protocol": "eval_zones guided", "seed": seed, "profile": profile},
    )
    pipeline = DriverPipeline(cfg, (info.width, info.height), cal.ear_baseline, cal.model)
    series = ZoneSeries()
    rate = RateMeter()
    steps: list[tuple[str, float, str | None]] = [("Priveste DRUMUL", 3.0, None)]
    for zone, mode in trials:
        text = ZONE_PROMPTS[zone] if zone == "road" else f"{ZONE_PROMPTS[zone]} - {MODE_TEXT[mode]}"
        steps += [(text, TRIAL_S, f"{zone}:{mode}"), ("Inapoi la DRUM", BACK_S, None)]
    total = sum(s[1] for s in steps)
    print(f"zone eval: {len(trials)} trials, ~{total / 60:.1f} min. Session: {session_dir}", flush=True)
    aborted = False
    try:
        for k, (text, duration, value) in enumerate(steps):
            start = session.now()
            if value is not None:
                writer.write(LabelEvent(t=start, label=ZONE_LABEL, kind="state", value=value))
                print(f"[{k + 1}/{len(steps)}] {text}", flush=True)
            while (elapsed := session.now() - start) < duration:
                out = session.step(timeout=0.5)
                if out is None:
                    continue
                frame, ff = out
                st = pipeline.update(ff)
                rate.tick()
                head = zone_head_angles(st.head.yaw, st.head.raw_yaw, st.head.raw_pitch)
                series.add(st.t, st.gaze.zone, head, (st.gaze.gaze_yaw, st.gaze.gaze_pitch))
                banner = f"{text}   {duration - elapsed:3.1f}s   [{k + 1}/{len(steps)}]"
                img = draw_driver(
                    frame.image,
                    ff,
                    st,
                    fps=rate.rate(),
                    luma=mean_luma(frame.image),
                    dark_luma=cfg.monitoring.dark_luma,
                    banner=banner,
                )
                cv2.imshow(WINDOW, img)
                if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                    aborted = True
                    break
            if value is not None:
                writer.write(LabelEvent(t=session.now(), label=ZONE_LABEL, kind="state", value=None))
            if aborted:
                break
    finally:
        writer.close()
        session.close()
        cv2.destroyAllWindows()
    _, events = load_labels(session_dir / "labels.jsonl")
    result = evaluate_zones(series, trials_from_intervals(to_intervals(events)), list(cfg.gaze.zones))
    meta = {
        "mode": "guided live",
        "session": session_dir.name,
        "camera": f"{info.width}x{info.height} {info.fourcc} @ {info.fps:.0f} fps",
        "trials": len(trials),
        "seed": seed,
        "aborted": aborted,
        **_cal_meta(cal),
    }
    path = _write(name, cfg, meta, result)
    _print(result)
    print(f"\nreport: {path}\nre-evaluate / sweep: python scripts/eval_zones.py --session {session_dir} --sweep")
    return 0 if result.passed else 2


# --- recorded session + sweep ----------------------------------------------------------------------------------


def _load_session(cfg: PerceptionConfig, session_dir: Path) -> tuple[Calibration, ZoneReplay, list[ZoneTrial]]:
    replay_src = FeatureReplay(next(session_dir.glob("features.jsonl*")))
    cam = replay_src.meta["camera"]
    cal = Calibration.load(cfg, session_dir / "calibration.json")
    replay = run_zone_pipeline(cfg, replay_src.frames(), (cam["width"], cam["height"]), cal)
    _, events = load_labels(session_dir / "labels.jsonl")
    return cal, replay, trials_from_intervals(to_intervals(events))


def _variant(cfg: PerceptionConfig, k: int, reject: float, eye_look: float, min_frames: int) -> PerceptionConfig:
    g = cfg.gaze
    weights = g.feature_weights.model_copy(update={"eye_look": eye_look})
    update = {"k": k, "reject_factor": reject, "feature_weights": weights, "zone_min_frames": min_frames}
    gaze = g.model_copy(update=update)
    return cfg.model_copy(update={"gaze": gaze})


def _score(res: ZoneEvalResult) -> float:
    m = res.metrics
    latency = (m.get("latency_ms_median") or 1000.0) / 1000.0
    return (
        (m.get("owl_accuracy") or 0.0)
        + (m.get("lizard_accuracy") or 0.0)
        - (m.get("unknown_pct") or 0.0) / 100.0
        - 0.01 * (m.get("road_vs_mirror_left_frames") or 0)
        - (m.get("passenger_vs_mirror_right_pct") or 0.0) / 100.0
        - max(0.0, latency - 0.3)
    )


def run_session(cfg: PerceptionConfig, session_dir: Path, sweep: bool) -> int:
    cal, replay, trials = _load_session(cfg, session_dir)
    zones = list(cfg.gaze.zones)
    name = session_dir.name.split("_zones-")[-1] + "-replay"
    result = evaluate_zones(replay.series, trials, zones)
    meta = {"mode": "replay (evaluation only, never in the demo)", "session": session_dir.name, **_cal_meta(cal)}
    path = _write(name, cfg, meta, result)
    _print(result)
    print(f"\nreport: {path}")
    if not sweep:
        return 0 if result.passed else 2

    rows = []
    grid = itertools.product((3, 5, 7), (1.2, 1.5, 2.0, 3.0), (0.25, 0.5, 1.0), (2, 3, 4))
    t0 = time.perf_counter()
    for k, reject, eye_look, min_frames in grid:
        variant = _variant(cfg, k, reject, eye_look, min_frames)
        res = evaluate_zones(reclassify(variant, cal, replay), trials, zones)
        rows.append(((k, reject, eye_look, min_frames), res))
    rows.sort(key=lambda r: (not r[1].passed, -_score(r[1])))
    print(f"sweep: {len(rows)} variants in {time.perf_counter() - t0:.0f} s")
    lines = [
        f"# Gaze zone parameter sweep: {session_dir.name} ({dt.date.today().isoformat()})",
        "",
        "Re-classification of the same recorded features (one session: **check the winner on a second live "
        "session before trusting it**). Sorted by: all criteria pass, then owl + lizard accuracy - unknown share - "
        "confusion and latency penalties.",
        "",
        "| k | reject_factor | eye_look weight | zone_min_frames | pass | owl | lizard | unknown % | road-mirrorL | "
        "pass-mirrorR % | latency ms |",
        "|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for (k, reject, eye_look, min_frames), res in rows[:25]:
        m = res.metrics
        lines.append(
            f"| {k} | {reject} | {eye_look} | {min_frames} | {'yes' if res.passed else 'no'} | "
            f"{m.get('owl_accuracy')} | {m.get('lizard_accuracy')} | {m.get('unknown_pct')} | "
            f"{m.get('road_vs_mirror_left_frames')} | {m.get('passenger_vs_mirror_right_pct')} | "
            f"{m.get('latency_ms_median')} |"
        )
    best = rows[0][0]
    lines += [
        "",
        f"Current yaml: k {cfg.gaze.k}, reject_factor {cfg.gaze.reject_factor}, eye_look "
        f"{cfg.gaze.feature_weights.eye_look}, zone_min_frames {cfg.gaze.zone_min_frames}.",
        f"Best: k {best[0]}, reject_factor {best[1]}, eye_look {best[2]}, zone_min_frames {best[3]}.",
        "",
    ]
    sweep_path = EVAL_DIR / f"zones-sweep-{name}-{dt.date.today().isoformat()}.md"
    sweep_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[6:16]))
    print(f"\nsweep report: {sweep_path}")
    return 0


# --- MobileGaze crop A/B -------------------------------------------------------------------------------------


def run_ab_crop(cfg: PerceptionConfig, variants: tuple[float, ...] = (1.0, 1.2)) -> int:
    """Two crops of the SAME live frames: jitter with the gaze still, and zone separation (Fisher ratio vs road)."""
    import mediapipe as mp

    from perception.driver_cam.face import face_box_px

    face_model = FaceLandmarkerModel(cfg)
    models = {v: MobileGazeModel(cfg, crop_expand=v) for v in variants}
    phases: list[tuple[str, float, str | None]] = [("Pregateste-te: priveste DRUMUL (in fata)", 3.0, None)]
    phases += [("NEMISCAT, privirea pe DRUM", 8.0, "road")]
    for zone in ("mirror_left", "mirror_right", "lap", "cluster"):
        phases += [(f"{ZONE_PROMPTS[zone]} (cu capul si ochii)", 4.0, zone), ("Inapoi la DRUM", 2.0, None)]
    rows: dict[float, list[tuple[str, float, float]]] = {v: [] for v in variants}  # label, yaw, pitch
    with LatestFrameCamera(cfg.cameras.driver, "driver") as cam:
        first = cam.wait_new(0, timeout=10.0)
        info = cam.stats().info
        if first is None or info is None:
            print("camera delivered no frame", file=sys.stderr)
            return 1
        w, h = info.width, info.height
        last_id = first.frame_id
        aborted = False
        for prompt, duration, label in phases:
            start = time.perf_counter()
            while (elapsed := time.perf_counter() - start) < duration:
                frame = cam.wait_new(last_id, timeout=1.0)
                if frame is None:
                    continue
                last_id = frame.frame_id
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB))
                face, _ = face_model.detect(image, frame.t_capture, w, h)
                box = face_box_px(face, w, h)
                if label is not None and elapsed >= 1.0 and box is not None and not face.too_small:
                    for v, model in models.items():
                        raw = model.estimate(frame.image, box)
                        if raw is not None:
                            yaw, pitch = driver_gaze(raw)
                            rows[v].append((label, yaw, pitch))
                img = frame.image.copy()
                cv2.putText(
                    img,
                    f"{prompt}  {duration - elapsed:3.1f}s",
                    (20, h - 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (255, 255, 255),
                    3,
                    cv2.LINE_AA,
                )
                cv2.imshow(WINDOW, img)
                if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                    aborted = True
                    break
            if aborted:
                break
    cv2.destroyAllWindows()
    face_model.close()

    def stats(v: float) -> dict[str, Any]:
        by: dict[str, np.ndarray] = {}
        for label in ("road", "mirror_left", "mirror_right", "lap", "cluster"):
            pts = [(y, p) for lab, y, p in rows[v] if lab == label]
            if pts:
                by[label] = np.asarray(pts)
        out: dict[str, Any] = {"frames": len(rows[v]), "latency_ms_p50": round(models[v].latency.p50(), 2)}
        if "road" in by:
            out["still_std_yaw"] = round(float(by["road"][:, 0].std()), 2)
            out["still_std_pitch"] = round(float(by["road"][:, 1].std()), 2)
        fisher: list[float] = []
        for label, arr in by.items():
            out[f"{label}_median"] = (round(float(np.median(arr[:, 0])), 1), round(float(np.median(arr[:, 1])), 1))
            if label != "road" and "road" in by:
                road = by["road"]
                d = np.linalg.norm(np.median(arr, axis=0) - np.median(road, axis=0))
                spread = float(np.sqrt(arr.std(axis=0) ** 2 + road.std(axis=0) ** 2).mean())
                out[f"{label}_fisher"] = round(float(d / max(spread, 1e-6)), 2)
                fisher.append(float(d) / max(spread, 1e-6))
        out["fisher_mean"] = round(float(statistics.mean(fisher)), 2) if fisher else None
        return out

    results = {v: stats(v) for v in variants}
    best = max(variants, key=lambda v: results[v].get("fisher_mean") or 0.0)
    stamp = dt.date.today().isoformat()
    lines = [
        f"# MobileGaze crop A/B ({stamp})",
        "",
        f"Camera {w}x{h}. Same live frames through MobileGaze with the face box scaled by {variants}. "
        "Angles in the driver convention (yaw > 0 = left, pitch > 0 = up). Still = std over the 8 s road window "
        "(first second skipped); Fisher = |median(zone) - median(road)| / sqrt(std_zone^2 + std_road^2) (mean of the "
        "yaw / pitch spreads). yakhyo/gaze-estimation crops the detector box with no expansion (1.0).",
        "",
        "| metric | " + " | ".join(f"crop {v}" for v in variants) + " |",
        "|---|" + "---:|" * len(variants),
    ]
    keys = sorted({k for r in results.values() for k in r})
    for key in keys:
        lines.append(f"| {key} | " + " | ".join(str(results[v].get(key, "-")) for v in variants) + " |")
    lines += ["", f"**Best separation: crop_expand {best}.** aborted: {aborted}", ""]
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    path = EVAL_DIR / f"gaze-crop-{stamp}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"report: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--name", help="guided live evaluation with this name (report docs/eval/zones-<name>-<date>.md)")
    mode.add_argument("--session", type=Path, help="re-evaluate a recorded zone session")
    mode.add_argument("--ab-crop", action="store_true", help="MobileGaze crop 1.0 vs 1.2 on the same live frames")
    p.add_argument("--profile", help="calibration profile (default: --name)")
    p.add_argument("--reps", type=int, default=5, help="trials per zone and mode (default 5)")
    p.add_argument("--seed", type=int, default=None, help="trial order seed (default: from the clock, saved)")
    p.add_argument("--sweep", action="store_true", help="with --session: parameter grid on the recorded features")
    p.add_argument("--config", type=Path)
    args = p.parse_args(argv)
    configure_logging("WARNING", json=False)
    cfg = load_config(args.config)
    if args.ab_crop:
        return run_ab_crop(cfg)
    if args.session:
        return run_session(cfg, args.session, args.sweep)
    seed = args.seed if args.seed is not None else int(time.time()) % 100000
    return run_live(cfg, args.name, args.profile or args.name, args.reps, seed)


if __name__ == "__main__":
    raise SystemExit(main())
