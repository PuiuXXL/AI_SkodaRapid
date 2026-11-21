"""Evaluate the driver eye / head / mouth detectors, or tune the Face Landmarker tracking confidence (R-FL2).

    python scripts/eval_eyes.py --name andrei                 # guided live protocol (~3 min), then the report
    python scripts/eval_eyes.py --session data/features/<s>   # re-evaluate a recorded, labelled session (replay)
    python scripts/eval_eyes.py --tune-tracking               # compare min_tracking_conf 0.5 / 0.6 / 0.7 (~30 s)
    python scripts/eval_eyes.py --ab-num-faces                # R-FL1 A/B: blink width with num_faces 1 vs 2 (~35 s)

Guided mode shows instructions with a countdown; the instruction windows become the ground-truth labels and the
session is saved under data/features/<session>/ (FeatureFrames + labels, no pixels), so it can be re-evaluated
later with --session. Reports go to docs/eval/. Replay is for evaluation only, never in the demo (R3).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import numpy.typing as npt

from perception.capture import LatestFrameCamera
from perception.config import REPO_ROOT, PerceptionConfig, load_config
from perception.driver_cam.eyes import EAR_POINTS, ear_from_points
from perception.driver_cam.face import FaceLandmarkerModel
from perception.driver_cam.pipeline import DriverPipeline, DriverState
from perception.evaluation import EvalResult, PipelineRun, evaluate, render_markdown, run_pipeline
from perception.eye_signal import measure_dip
from perception.features import FaceFeatures
from perception.labels import LabelEvent, LabelWriter, load_labels, to_intervals
from perception.log import configure_logging
from perception.overlay import draw_driver, mean_luma
from perception.perf import RateMeter, percentile
from perception.recorder import DATA_DIR, RecordingSession
from perception.replay import FeatureReplay

EVAL_DIR = REPO_ROOT / "docs" / "eval"
WINDOW = "DriveMate eval (q to abort)"
SENTENCES = (
    "Azi conduc spre Timisoara si opresc la benzinarie.",
    "Maria, cat mai avem pana ajungem la destinatie?",
    "Pune te rog ceva muzica, dar nu prea tare.",
    "Spune-i lui Mihai ca ajung pe la sapte.",
    "Unde e cea mai apropiata cafenea pe traseu?",
)


@dataclass(frozen=True)
class Step:
    prompt: str
    duration_s: float
    label: str | None = None
    kind: str = "window"  # "window" (start/end labels), "cue" (one instant label) or "keyed" (SPACE start/end)


def only_steps(steps: list[Step], labels: set[str]) -> list[Step]:
    """The first (calibration) step, then each step with one of ``labels`` and the unlabelled step after it."""
    out = steps[:1]
    for k, step in enumerate(steps[1:], start=1):
        if step.label in labels:
            out.append(step)
            if k + 1 < len(steps) and steps[k + 1].label is None:
                out.append(steps[k + 1])
    return out


def guided_protocol() -> list[Step]:
    steps = [
        Step("Priveste camera, ochii deschisi (calibrare)", 5.0),
        Step("Stai NEMISCAT si priveste camera", 10.0, "still"),
        # 5 s: people react after ~1.5-2 s (POSE_SKIP_S); ~30 deg, like a mirror check: a near-profile face loses
        # its landmarks (diag 2026-11-21)
        Step("Intoarce capul spre STANGA ta, ~30 grade (ca spre oglinda)", 5.0, "pose_left"),
        Step("Inapoi la camera", 2.0),
        Step("Ridica capul in SUS, ~20 grade", 5.0, "pose_up"),
        Step("Inapoi la camera", 2.0),
        Step("Inclina capul spre umarul STANG, ~15 grade", 5.0, "pose_tilt_left"),
        Step("Inapoi la camera", 2.0),
        Step("Inclina capul spre umarul DREPT, ~15 grade", 5.0, "pose_tilt_right"),
        Step("Inapoi la camera", 2.0),
        Step("Misca RAPID capul: stanga-dreapta, sus-jos", 6.0, "head_fast"),
        Step("Inapoi la camera, nemiscat", 3.0),
    ]
    for k in range(3):
        steps += [
            Step(f"PRIVESTE IN JOS, spre poala / telefon  ({k + 1}/3)", 3.0, "look_down"),
            Step("Inapoi la drum", 2.0),
        ]
    steps += [Step(f"CLIPESTE ACUM  ({k + 1}/10)", 2.5, "blink", "cue") for k in range(10)]
    # closures are labelled by the person: SPACE when the eyes close, SPACE when they open (instruction windows were
    # 0.5-2 s off the real closure in the diag session)
    for k in range(3):
        steps += [
            Step(
                f"Ochii DESCHISI. SPATIU exact cand INCHIZI ochii, ~2 s, SPATIU exact cand ii DESCHIZI  ({k + 1}/3)",
                8.0,
                "eyes_closed",
                "keyed",
            ),
            Step("Ochii deschisi", 2.0),
        ]
    for k in range(2):  # fatigue nodding (plan scene 9): closed eyes + the head falling forward
        steps += [
            Step(f"INCHIDE ochii, apoi lasa capul sa CADA in fata, ca atipit  ({k + 1}/2)", 5.0, "nod"),
            Step("Ridica capul, ochii deschisi", 3.0),
        ]
    for k in range(3):
        steps += [Step(f"CASCA larg, natural  ({k + 1}/3)", 6.0, "yawn"), Step("Pauza", 3.0)]
    for k, sentence in enumerate(SENTENCES):
        steps += [Step(f"Citeste cu voce tare: {sentence}", 8.0, "speaking"), Step(f"Pauza ({k + 1}/2)", 3.0)]
    for k in range(3):
        steps += [Step(f"MIJESTE ochii, ca in soare  ({k + 1}/3)", 3.0, "squint"), Step("Relaxat", 3.0)]
    for k in range(3):
        steps += [Step(f"ZAMBESTE LARG  ({k + 1}/3)", 3.0, "smile"), Step("Relaxat", 3.0)]
    steps += [
        Step("Fa un pas INAPOI de la camera", 3.0),
        Step("Ramai departe", 5.0, "step_back"),
        Step("Revino in fata camerei", 2.0),
    ]
    return steps


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:40] or "session"


def _yaml_values(cfg: PerceptionConfig) -> dict[str, Any]:
    e = cfg.eyes
    return {
        "eyes.local_ref_window_s": e.local_ref_window_s,
        "eyes.ref_floor_ratio": e.ref_floor_ratio,
        "eyes.drop_ratio": e.drop_ratio,
        "eyes.reopen_ratio": e.reopen_ratio,
        "eyes.fall_max_ms": e.fall_max_ms,
        "eyes.min_state_frames": e.min_state_frames,
        "eyes.blink_max_ms": e.blink_max_ms,
        "eyes.blendshape_closed": e.blendshape_closed,
        "eyes.unilateral_width_ratio": e.unilateral_width_ratio,
        "eyes.look_down_threshold": e.look_down_threshold,
        "eyes.pitch_down_deg": e.pitch_down_deg,
        "eyes.pitch_up_deg": e.pitch_up_deg,
        "eyes.drop_ratio_relaxed": e.drop_ratio_relaxed,
        "eyes.squint_ear_band": e.squint_ear_band,
        "eyes.closed_level_default": e.closed_level_default,
        "yawn.jaw_open_threshold": cfg.yawn.jaw_open_threshold,
        "yawn.min_duration_s": cfg.yawn.min_duration_s,
        "speaking.lip_std_threshold": cfg.speaking.lip_std_threshold,
        "speaking.min_reversals": cfg.speaking.min_reversals,
        "face.min_tracking_conf": cfg.face.min_tracking_conf,
        "face.min_face_width_px": cfg.face.min_face_width_px,
        "filters.one_euro_head": cfg.filters.one_euro_head.model_dump(),
    }


def _write_report(name: str, cfg: PerceptionConfig, meta: dict[str, Any], result: EvalResult) -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    path = EVAL_DIR / f"eyes-{_slug(name)}-{stamp}.md"
    path.write_text(
        render_markdown(f"Eye / head / mouth evaluation: {name} ({stamp})", meta, result, _yaml_values(cfg)),
        encoding="utf-8",
    )
    path.with_suffix(".json").write_text(
        json.dumps({"meta": meta, "metrics": result.metrics, "checks": result.checks}, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def _print_result(result: EvalResult) -> None:
    for key, ok in result.checks.items():
        print(f"  {'PASS' if ok else ('n/a ' if ok is None else 'FAIL')}  {key}")
    for key, value in result.metrics.items():
        print(f"     {key}: {value}")


# --- guided live ---------------------------------------------------------------------------------------


def run_guided(cfg: PerceptionConfig, name: str, only: set[str] | None = None) -> int:
    session_dir = DATA_DIR / "features" / f"{dt.datetime.now():%Y%m%d-%H%M%S}_eval-{_slug(name)}"
    session = RecordingSession(
        cfg, session_dir / "features.jsonl.gz", label=f"eval_eyes guided: {name}", gesture_hz=None
    )
    writer = LabelWriter(
        session_dir / "labels.jsonl",
        {"session": session_dir.name, "protocol": "eval_eyes guided", "zones": list(cfg.gaze.zones)},
    )
    pipeline = DriverPipeline(cfg, (session.info.width, session.info.height))
    states: list[DriverState] = []
    rate = RateMeter()
    aborted = False
    steps = guided_protocol() if not only else only_steps(guided_protocol(), only)
    total = sum(s.duration_s for s in steps)
    print(f"guided protocol: {len(steps)} steps, {total:.0f} s. Session: {session_dir}", flush=True)
    try:
        # the closures are labelled with SPACE, which only reaches the window when it has the keyboard focus (the
        # 2026-11-21 session recorded no key at all): wait for one SPACE here first, so a missing focus shows now
        while not aborted:
            step_out = session.step(timeout=0.5)
            if step_out is None:
                continue
            frame, ff = step_out
            img = draw_driver(frame.image, ff, None, fps=0.0, banner="CLICK pe aceasta fereastra, apoi apasa SPATIU")
            cv2.imshow(WINDOW, img)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                aborted = True
            elif key == ord(" "):
                print("SPACE received: the window has the keyboard, starting", flush=True)
                break
        if aborted:
            steps = []
        for idx, step in enumerate(steps):
            start = session.now()
            keyed_open = False
            if step.label and step.kind == "cue":
                writer.write(LabelEvent(t=start, label=step.label, kind="instant"))
            elif step.label and step.kind == "window":
                writer.write(LabelEvent(t=start, label=step.label, kind="start"))
            while (elapsed := session.now() - start) < step.duration_s:
                step_out = session.step(timeout=0.5)
                if step_out is None:
                    continue
                frame, ff = step_out
                state = pipeline.update(ff)
                states.append(state)
                rate.tick()
                left = step.duration_s - elapsed
                show = step.prompt if step.kind != "cue" or elapsed < 0.8 else "..."
                if step.kind == "keyed":  # visible confirmation that the key arrived
                    show += "   [SPATIU primit: INCHISI]" if keyed_open else "   [astept SPATIU]"
                banner = f"{show}   {left:3.1f}s   [{idx + 1}/{len(steps)}]"
                img = draw_driver(
                    frame.image,
                    ff,
                    state,
                    fps=rate.rate(),
                    luma=mean_luma(frame.image),
                    dark_luma=cfg.monitoring.dark_luma,
                    banner=banner,
                )
                cv2.imshow(WINDOW, img)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    aborted = True
                    break
                if key == ord(" ") and step.label and step.kind == "keyed":
                    writer.write(LabelEvent(t=session.now(), label=step.label, kind="end" if keyed_open else "start"))
                    keyed_open = not keyed_open
            if step.label and (step.kind == "window" or (step.kind == "keyed" and keyed_open)):
                writer.write(LabelEvent(t=session.now(), label=step.label, kind="end"))
            if aborted:
                break
    finally:
        writer.close()
        session.close()
        cv2.destroyAllWindows()
    if aborted:
        print("aborted; partial session kept in", session_dir)
    _, events = load_labels(session_dir / "labels.jsonl")
    run = PipelineRun(states, list(pipeline.eyes.events), list(pipeline.mouth.events))
    result = evaluate(run, to_intervals(events), cfg.eyes.blink_max_ms)
    meta = {
        "mode": "guided live",
        "session": session_dir.name,
        "camera": f"{session.info.width}x{session.info.height} {session.info.fourcc} @ {session.info.fps:.0f} fps",
        "frames": len(states),
        "aborted": aborted,
    }
    path = _write_report(name, cfg, meta, result)
    _print_result(result)
    print(f"\nreport: {path}\nre-evaluate later: python scripts/eval_eyes.py --session {session_dir}")
    return 0 if result.passed else 2


# --- recorded session (replay, evaluation only) --------------------------------------------------------


def run_session(cfg: PerceptionConfig, session_dir: Path, name: str | None) -> int:
    features = next(
        (p for p in (session_dir / "features.jsonl.gz", session_dir / "features.jsonl") if p.exists()), None
    )
    labels_path = session_dir / "labels.jsonl"
    if features is None or not labels_path.exists():
        print(f"{session_dir}: needs features.jsonl[.gz] and labels.jsonl", file=sys.stderr)
        return 1
    replay = FeatureReplay(features)
    cam = replay.meta.get("camera", {})
    run = run_pipeline(cfg, replay.frames(), (int(cam.get("width", 1280)), int(cam.get("height", 720))))
    _, events = load_labels(labels_path)
    result = evaluate(run, to_intervals(events, t_end=run.states[-1].t if run.states else None), cfg.eyes.blink_max_ms)
    meta = {"mode": "replay of a labelled session", "session": session_dir.name, "frames": len(run.states)}
    path = _write_report(name or session_dir.name, cfg, meta, result)
    _print_result(result)
    print(f"\nreport: {path}")
    return 0 if result.passed else 2


# --- R-FL2: min_tracking_conf --------------------------------------------------------------------------


@dataclass
class _TrackStats:
    frames: int = 0
    lost: int = 0
    redetections: int = 0
    jumps: int = 0
    was_lost: bool = False
    last_nose: tuple[float, float] | None = None


def _nose_and_width(face: FaceFeatures, w: int, h: int) -> tuple[tuple[float, float], float]:
    x, y, _ = face.point(1)
    return (x * w, y * h), face.width_px or 1.0


def run_tune_tracking(cfg: PerceptionConfig) -> int:
    import mediapipe as mp

    values = (0.5, 0.6, 0.7)
    phases = [
        ("Stai NEMISCAT, priveste camera", 10.0, "still"),
        ("Misca RAPID capul: stanga-dreapta, sus-jos", 10.0, "fast"),
        ("Tine capul intors MULT spre stanga", 5.0, "turned"),
    ]
    models = {v: FaceLandmarkerModel(cfg, min_tracking_conf=v) for v in values}
    stats = {(v, p[2]): _TrackStats() for v in values for p in phases}
    still_pts: dict[float, list[npt.NDArray[np.float64]]] = {v: [] for v in values}
    with LatestFrameCamera(cfg.cameras.driver, "driver") as cam:
        first = cam.wait_new(0, timeout=10.0)
        info = cam.stats().info
        if first is None or info is None:
            print("camera delivered no frame", file=sys.stderr)
            return 1
        w, h = info.width, info.height
        last_id = first.frame_id
        for prompt, duration, phase in [("Pregateste-te...", 3.0, None), *phases]:
            start = time.perf_counter()
            while (elapsed := time.perf_counter() - start) < duration:
                frame = cam.wait_new(last_id, timeout=1.0)
                if frame is None:
                    continue
                last_id = frame.frame_id
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB))
                summary = []
                for v, model in models.items():
                    face, _ = model.detect(image, frame.t_capture, w, h)
                    if phase is None:
                        continue
                    s = stats[(v, phase)]
                    s.frames += 1
                    if not face.present:
                        s.lost += 1
                        s.was_lost, s.last_nose = True, None
                    else:
                        nose, width = _nose_and_width(face, w, h)
                        if s.was_lost:
                            s.redetections += 1
                        elif (
                            s.last_nose and np.hypot(nose[0] - s.last_nose[0], nose[1] - s.last_nose[1]) > 0.15 * width
                        ):
                            s.jumps += 1
                        s.was_lost, s.last_nose = False, nose
                        if phase == "still":
                            pts = np.array([face.point(i)[:2] for i in (33, 263, 1)]) * (w, h) / width * 100.0
                            still_pts[v].append(pts)
                    summary.append(f"{v}: lost {s.lost} redet {s.redetections} jumps {s.jumps}")
                img = frame.image.copy()
                banner = f"{prompt}  {duration - elapsed:3.1f}s"
                cv2.putText(img, banner, (20, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3, cv2.LINE_AA)
                for k, line in enumerate(summary):
                    cv2.putText(img, line, (20, 30 + 26 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80, 255, 80), 2)
                cv2.imshow(WINDOW, img)
                if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                    break
    cv2.destroyAllWindows()
    for model in models.values():
        model.close()

    rows: list[dict[str, Any]] = []
    for v in values:
        jitter = None
        if len(still_pts[v]) > 10:
            arr = np.stack(still_pts[v])  # frames x 3 points x 2 coords, in % of face width
            jitter = round(float(arr.std(axis=0).mean()), 3)
        fast = [stats[(v, p)] for p in ("fast", "turned")]
        row: dict[str, Any] = {
            "min_tracking_conf": v,
            "jitter_still_pct_face_width": jitter,
            "lost_frames_fast_turned": sum(s.lost for s in fast),
            "redetections_fast_turned": sum(s.redetections for s in fast),
            "jumps_fast_turned": sum(s.jumps for s in fast),
            "frames_fast_turned": sum(s.frames for s in fast),
            "lost_still": stats[(v, "still")].lost,
            "ms_p50": round(models[v].latency.p50(), 2),
        }
        row["score"] = row["redetections_fast_turned"] + row["jumps_fast_turned"] + 0.1 * row["lost_frames_fast_turned"]
        rows.append(row)
    best = min(rows, key=lambda r: (r["score"], r["jitter_still_pct_face_width"] or 0.0))
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    path = EVAL_DIR / f"tracking-conf-{dt.date.today().isoformat()}.md"
    header = list(rows[0])
    lines = [
        f"# Face Landmarker min_tracking_conf (R-FL2), {dt.date.today().isoformat()}",
        "",
        f"Camera {w}x{h} @ {info.fps:.0f} fps. Three Face Landmarker instances on the **same live frames**, "
        "differing only in `min_tracking_conf`. Phases: 10 s still, 10 s fast head movements, 5 s head turned far.",
        "",
        "- *jitter*: std of eye corners (33, 263) and nose tip (1) in the still phase, % of face width "
        "(lower = steadier)",
        "- *redetections*: face lost then found again; *jumps*: nose moves > 15% of the face width between frames",
        "- *score* = redetections + jumps + 0.1 x lost frames (fast + turned phases); lower is better",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    lines += ["| " + " | ".join(str(r[k]) for k in header) + " |" for r in rows]
    lines += [
        "",
        f"**Proposed:** `face.min_tracking_conf: {best['min_tracking_conf']}` "
        f"(current yaml: {cfg.face.min_tracking_conf}).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    for r in rows:
        print(r)
    print(f"\nproposed min_tracking_conf: {best['min_tracking_conf']} (yaml: {cfg.face.min_tracking_conf})")
    print(f"report: {path}")
    return 0


# --- R-FL1: num_faces = 1 vs 2 (MediaPipe internal smoothing) ------------------------------------------


def _ears(face: FaceFeatures, w: int, h: int) -> tuple[float, float]:
    out = []
    for side in ("left", "right"):
        pts = [face.point(i) for i in EAR_POINTS[side]]
        out.append(ear_from_points([(x * w, y * h) for x, y, _ in pts])[0])
    return out[0], out[1]


def run_ab_num_faces(cfg: PerceptionConfig, blinks: int = 10) -> int:
    """Two Face Landmarkers on the SAME live frames, num_faces=1 vs 2; blink width at 50 % of the raw EAR dip."""
    import mediapipe as mp

    variants = (1, 2)
    models = {n: FaceLandmarkerModel(cfg, num_faces=n) for n in variants}
    series: dict[int, list[tuple[float, float, float, float]]] = {n: [] for n in variants}  # t, earL, earR, blink
    cues: list[float] = []
    phases: list[tuple[str, float, str | None]] = [
        ("Pregateste-te, priveste camera", 3.0, None),
        ("Ochii deschisi, nemiscat", 3.0, None),
    ]
    phases += [(f"CLIPESTE ACUM  ({k + 1}/{blinks})", 2.5, "cue") for k in range(blinks)]
    with LatestFrameCamera(cfg.cameras.driver, "driver") as cam:
        first = cam.wait_new(0, timeout=10.0)
        info = cam.stats().info
        if first is None or info is None:
            print("camera delivered no frame", file=sys.stderr)
            return 1
        w, h = info.width, info.height
        last_id = first.frame_id
        t_origin = time.perf_counter()
        frames_seen = 0
        aborted = False
        for prompt, duration, kind in phases:
            start = time.perf_counter()
            if kind == "cue":
                cues.append(start - t_origin)
            while (elapsed := time.perf_counter() - start) < duration:
                frame = cam.wait_new(last_id, timeout=1.0)
                if frame is None:
                    continue
                last_id = frame.frame_id
                frames_seen += 1
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB))
                t = frame.t_capture - t_origin
                for n, model in models.items():
                    face, _ = model.detect(image, frame.t_capture, w, h)
                    if face.present and face.blendshapes is not None:
                        el, er = _ears(face, w, h)
                        bs = face.blendshapes
                        series[n].append((t, el, er, (bs["eyeBlinkLeft"] + bs["eyeBlinkRight"]) / 2))
                img = frame.image.copy()
                show = prompt if kind != "cue" or elapsed < 0.8 else "..."
                cv2.putText(
                    img,
                    f"{show}  {duration - elapsed:3.1f}s",
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
        span = time.perf_counter() - t_origin
    cv2.destroyAllWindows()
    latency = {n: (round(m.latency.p50(), 2), round(m.latency.p95(), 2)) for n, m in models.items()}
    for model in models.values():
        model.close()

    def widths(n: int, cue: float) -> dict[str, float | None]:
        rows = series[n]
        pre = [r for r in rows if cue - 2.0 <= r[0] < cue - 0.3]
        win = [r for r in rows if cue - 0.3 <= r[0] < cue + 1.5]
        out: dict[str, float | None] = {}
        for k, name in ((1, "L"), (2, "R")):
            ref = percentile([r[k] for r in pre], 90) if pre else float("nan")
            shape = measure_dip([r[0] for r in win], [r[k] for r in win], ref) if win and pre else None
            out[f"w50_{name}"] = round(shape.width_ms, 0) if shape and shape.width_ms else None
            out[f"depth_{name}"] = round(shape.depth, 3) if shape else None
        openness = [1.0 - r[3] for r in win]
        ref_b = percentile([1.0 - r[3] for r in pre], 90) if pre else float("nan")
        shape_b = measure_dip([r[0] for r in win], openness, ref_b) if win and pre else None
        out["w50_eyeBlink"] = round(shape_b.width_ms, 0) if shape_b and shape_b.width_ms else None
        return out

    table = []
    for k, cue in enumerate(cues):
        row: dict[str, Any] = {"blink": k + 1}
        for n in variants:
            for key, val in widths(n, cue).items():
                row[f"n{n}_{key}"] = val
        table.append(row)

    def med(key: str) -> float | None:
        vals = [r[key] for r in table if r.get(key) is not None]
        return round(statistics.median(vals), 1) if vals else None

    summary = {
        f"n{n}": {
            "w50_ear_L_ms_median": med(f"n{n}_w50_L"),
            "w50_ear_R_ms_median": med(f"n{n}_w50_R"),
            "w50_eyeBlink_ms_median": med(f"n{n}_w50_eyeBlink"),
            "depth_L_median": med(f"n{n}_depth_L"),
            "frames_with_face": len(series[n]),
            "latency_ms_p50_p95": latency[n],
        }
        for n in variants
    }
    fps = round(frames_seen / span, 1) if span > 0 else None
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    path = EVAL_DIR / f"num-faces-ab-{dt.date.today().isoformat()}.md"
    header = list(table[0]) if table else []
    lines = [
        f"# Face Landmarker num_faces 1 vs 2 (R-FL1), {dt.date.today().isoformat()}",
        "",
        f"Camera {w}x{h} @ {info.fps:.0f} fps reported, {fps} fps processed (both models on every frame). "
        f"Two Face Landmarker instances on the **same live frames**, differing only in `num_faces`. "
        f"{len(cues)} cued blinks. Width = time below 50 % of the raw EAR dip (interpolated); ref = p90 of EAR "
        "in the 2 s before the cue. Blink duration in humans is ~100-400 ms (Schiffman 2001; Caffier et al. 2003).",
        "",
        "## Summary",
        "",
        "```",
        *[f"{k}: {v}" for k, v in summary.items()],
        "```",
        "",
        "## Per blink",
        "",
    ]
    if header:
        lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join("-" if r[k] is None else str(r[k]) for k in header) + " |" for r in table]
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    for variant, values in summary.items():
        print(variant, values)
    print(f"processed fps: {fps}\nreport: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="laptop", help="report name (no personal data needed)")
    p.add_argument("--session", type=Path, default=None, help="evaluate a recorded labelled session (replay)")
    p.add_argument("--tune-tracking", action="store_true")
    p.add_argument("--ab-num-faces", action="store_true", help="R-FL1 A/B: num_faces 1 vs 2 on the same frames")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--only", nargs="*", default=None, help="guided: only these labels (e.g. eyes_closed nod squint)")
    args = p.parse_args(argv)
    configure_logging("WARNING", json=False)
    cfg = load_config(args.config)
    if args.tune_tracking:
        return run_tune_tracking(cfg)
    if args.ab_num_faces:
        return run_ab_num_faces(cfg)
    if args.session:
        return run_session(cfg, args.session, args.name if args.name != "laptop" else None)
    return run_guided(cfg, args.name, set(args.only) if args.only else None)


if __name__ == "__main__":
    raise SystemExit(main())
