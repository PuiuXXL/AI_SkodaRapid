"""Per-driver gaze zone calibration (AS5): owl + lizard per zone -> profiles/<name>/calibration.json.

    python scripts/calibrate.py --name andrei            # full calibration (~1 min 10 s)
    python scripts/calibrate.py --name andrei --quick    # ~15 s: road + mirrors only, merged into the profile
    python scripts/calibrate.py --name andrei --from-session data/features/<stamp>_calib-andrei   # rebuild offline

Follow the prompt on screen (also printed in the terminal): OWL = turn the head to the target, LIZARD = keep the
head towards the road and move only the eyes. Between targets look back at the road. The same flow runs inside the
perception runtime when core sends the ``calibrate`` command (perception/calibration.py).

The calibration file holds per-person features, not images (gitignored). The FeatureFrames of the run are saved in
data/features/<stamp>_calib-<name>/ (no pixels) so the calibration can be rebuilt with --from-session.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from perception.calibration import Calibration, CalibrationRun, CalibStep, profile_path
from perception.config import PerceptionConfig, load_config
from perception.driver_cam.pipeline import DriverPipeline
from perception.labels import ZONE_LABEL, LabelEvent, LabelWriter, load_labels, to_intervals
from perception.log import configure_logging
from perception.overlay import draw_driver, mean_luma
from perception.perf import RateMeter
from perception.recorder import DATA_DIR, RecordingSession
from perception.replay import FeatureReplay

WINDOW = "DriveMate calibration (q to abort)"


def _report(cal: Calibration, run: CalibrationRun | None, path: Path) -> None:
    print(f"\nsaved: {path}")
    if run is not None:
        print(f"samples: {run.summary()}")
    acc = cal.loo_accuracy()
    print(f"blocked-LOO accuracy: owl {acc['owl']}  lizard {acc['lizard']}  all {acc['all']}   tau {cal.model.tau:.3f}")
    print(f"EAR baseline (road, p90): {cal.ear_baseline}")
    print("LOO confusion (rows = target):")
    for zone, row in cal.loo_confusion().items():
        print(f"  {zone:13s} " + "  ".join(f"{k}:{v}" for k, v in sorted(row.items(), key=lambda kv: -kv[1])))
    for warning in cal.warnings():
        print(f"WARNING: {warning}")


def _finish(cfg: PerceptionConfig, run: CalibrationRun, name: str, quick: bool) -> int:
    try:
        cal = run.result()
        if quick:
            cal = Calibration.load(cfg, profile_path(name)).merged_with(cfg, cal)
    except ValueError as exc:
        print(f"calibration failed: {exc}  ({run.summary()})", file=sys.stderr)
        return 2
    _report(cal, run, cal.save())
    return 0 if not cal.missing else 2


def run_live(cfg: PerceptionConfig, name: str, quick: bool) -> int:
    if quick and not profile_path(name).exists():
        print(f"--quick needs an existing profile: {profile_path(name)}", file=sys.stderr)
        return 1
    session_dir = DATA_DIR / "features" / f"{dt.datetime.now():%Y%m%d-%H%M%S}_calib-{name}{'-quick' if quick else ''}"
    session = RecordingSession(cfg, session_dir / "features.jsonl.gz", label=f"calibrate: {name}", gesture_hz=None)
    info = session.info
    writer = LabelWriter(session_dir / "labels.jsonl", {"session": session_dir.name, "protocol": "calibrate"})
    pipeline = DriverPipeline(cfg, (info.width, info.height))
    camera = {"width": info.width, "height": info.height, "fps": info.fps, "backend": info.backend}
    run = CalibrationRun(cfg, (info.width, info.height), name, quick=quick, camera=camera)
    total = sum(s.duration_s for s in run.steps)
    print(f"calibration '{name}'{' (quick)' if quick else ''}: {len(run.steps)} steps, ~{total:.0f} s", flush=True)
    rate = RateMeter()
    last_step = -1
    open_label: str | None = None
    aborted = False
    try:
        while not run.done:
            out = session.step(timeout=0.5)
            if out is None:
                continue
            frame, ff = out
            state = pipeline.update(ff)
            prompt = run.update(ff, state)
            rate.tick()
            if prompt is not None and prompt.step != last_step:
                last_step = prompt.step
                if open_label is not None:
                    writer.write(LabelEvent(t=ff.t, label=ZONE_LABEL, kind="state", value=None))
                    open_label = None
                if prompt.zone is not None:
                    open_label = f"{prompt.zone}:{prompt.mode}"
                    writer.write(LabelEvent(t=ff.t, label=ZONE_LABEL, kind="state", value=open_label))
                print(f"[{prompt.step}/{prompt.steps}] {prompt.text}", flush=True)
            banner = f"{prompt.text}  {prompt.remaining_s:3.1f}s" if prompt is not None else "gata"
            img = draw_driver(
                frame.image,
                ff,
                state,
                fps=rate.rate(),
                luma=mean_luma(frame.image),
                banner=banner,
                dark_luma=cfg.monitoring.dark_luma,
            )
            cv2.imshow(WINDOW, img)
            if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                aborted = True
                break
        if open_label is not None:
            writer.write(LabelEvent(t=session.now(), label=ZONE_LABEL, kind="state", value=None))
    finally:
        writer.close()
        session.close()
        cv2.destroyAllWindows()
    if aborted:
        print("aborted: nothing saved (the FeatureFrames are in", session_dir, ")")
        return 1
    print(f"session: {session_dir}")
    return _finish(cfg, run, name, quick)


def run_from_session(cfg: PerceptionConfig, name: str, session_dir: Path, quick: bool) -> int:
    """Rebuild a calibration from a recorded calibration session (replay: development only, never in the demo)."""
    replay = FeatureReplay(next(session_dir.glob("features.jsonl*")))
    cam = replay.meta["camera"]
    _, events = load_labels(session_dir / "labels.jsonl")
    windows = [iv for iv in to_intervals(events) if iv.label == ZONE_LABEL and iv.value]
    steps = [
        CalibStep(iv.value.split(":")[0], iv.value.split(":")[1], iv.value, iv.end - iv.start, k)
        for k, iv in enumerate(windows)
        if iv.value
    ]
    pipeline = DriverPipeline(cfg, (cam["width"], cam["height"]))
    run = CalibrationRun(cfg, (cam["width"], cam["height"]), name, quick=quick, steps=[], camera=cam)
    discard = cfg.gaze.calibration.discard_s
    for ff in replay.frames():
        state = pipeline.update(ff)
        for iv, step in zip(windows, steps, strict=True):
            if iv.start + discard <= ff.t < iv.end:
                run.collect(ff, state, step)
                break
    return _finish(cfg, run, name, quick)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="profile name (letters, digits, - or _)")
    p.add_argument("--quick", action="store_true", help="~15 s: road + mirrors, merged into the existing profile")
    p.add_argument("--from-session", type=Path, help="rebuild from a recorded calibration session")
    p.add_argument("--config", type=Path)
    args = p.parse_args(argv)
    configure_logging("WARNING", json=False)
    cfg = load_config(args.config)
    try:
        profile_path(args.name)
    except ValueError as exc:
        p.error(str(exc))
    if args.from_session:
        return run_from_session(cfg, args.name, args.from_session, args.quick)
    return run_live(cfg, args.name, args.quick)


if __name__ == "__main__":
    raise SystemExit(main())
