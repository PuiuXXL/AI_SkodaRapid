"""Evaluate the interaction modules: head yes / no (AS8), gestures (AS9), driver phone (AS7), silence outside windows.

    python scripts/eval_interaction.py --name andrei                     # guided live protocol (~6.5 min) + report
    python scripts/eval_interaction.py --session data/features/<s>       # re-score a recorded session (replay)
    python scripts/eval_interaction.py --synthetic [--seed 7]            # synthetic streams with known truth

Protocol: 10 x "yes" nod, 10 x "no" shake, 10 x each gesture (thumb up, thumb down, open palm), each inside a dialog
window; the phone in 5 situations (call at the ear, texting in the hand, in the lap, the passenger's phone coming from
the right = must NOT count, no phone); 30 s of free movement outside any window (mirror checks, talking, an unsolicited
nod) = must give no answer. Live mode records FeatureFrames + labels (never pixels) under data/features/<session>/, so
the run can be re-scored with --session. A session without these labels (e.g. an eval_eyes session) gets the
diagnostics only: answers outside windows, answers per labelled activity with a window forced open, phone vote vs. a
`phone` label. Reports: docs/eval/interaction-<name>-<date>.md / .json. Replay is never used in the demo (R3).

Module settings come from perception/config/pending/modules.yaml (until they move into perception.yaml).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import re
import shutil
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from perception.config import REPO_ROOT, PerceptionConfig, load_config
from perception.driver_cam.head_answer import HeadAnswerConfig, HeadAnswerDetector
from perception.features import HandFeatures, PhoneBox
from perception.hands import HandsConfig, HandTracker
from perception.labels import Interval, LabelEvent, LabelWriter, load_labels, to_intervals
from perception.log import configure_logging
from perception.phone import PhoneConfig, PhoneResult, PhoneTracker

EVAL_DIR = REPO_ROOT / "docs" / "eval"
PENDING = REPO_ROOT / "perception" / "config" / "pending" / "modules.yaml"
WINDOW = "DriveMate interaction eval (q to abort)"
FPS = 30.0
Box = tuple[float, float, float, float]

ANSWERS = ("yes", "no")
GESTURES = ("Thumb_Up", "Thumb_Down", "Open_Palm")
PHONE = ("phone_call", "phone_hand", "phone_lap", "phone_passenger", "phone_none")
PHONE_EXPECTED: dict[str, str | None] = {  # expected usage; None = must NOT count as the driver's phone
    "phone_call": "call",
    "phone_hand": "hand",
    "phone_lap": "lap",
    "phone_passenger": None,
    "phone_none": None,
}
PROMPTS = {  # no diacritics: OpenCV's putText cannot draw them
    "yes": "Raspunde DA din cap (da din cap sus-jos)",
    "no": "Raspunde NU din cap (clatina capul stanga-dreapta)",
    "Thumb_Up": "Arata DEGETUL MARE in SUS spre camera",
    "Thumb_Down": "Arata DEGETUL MARE in JOS spre camera",
    "Open_Palm": "Arata PALMA deschisa spre camera",
    "phone_call": "Telefonul la URECHE, ca la un apel",
    "phone_hand": "Scrie pe telefon, tinut in MANA, sub fata",
    "phone_lap": "Telefonul in POALA: uita-te la el de cateva ori",
    "phone_passenger": "PASAGERUL tine un telefon in dreapta ta (tu nu)",
    "phone_none": "Fara telefon: mainile pe volan",
    "free": "Miscari libere: oglinzi, vorbeste, da din cap NEINTREBAT",
}
ANSWER_GRACE_S = 0.5  # an answer may land just after the window
PHONE_SETTLE_S = 2.0  # phone trials are scored after the vote had time to settle


# --- configuration ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ModuleConfigs:
    hands: HandsConfig = field(default_factory=HandsConfig)
    head_answer: HeadAnswerConfig = field(default_factory=HeadAnswerConfig)
    phone: PhoneConfig = field(default_factory=PhoneConfig)


def load_module_configs(path: Path) -> ModuleConfigs:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    return ModuleConfigs(
        hands=HandsConfig.from_mapping(data.get("hands") or {}),
        head_answer=HeadAnswerConfig.from_mapping(data.get("head_answer") or {}),
        phone=PhoneConfig.from_mapping(data.get("phone") or {}),
    )


# --- protocol -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    prompt: str
    duration_s: float
    expect: str | None = None  # trial kind (label "trial_<expect>"); None = rest / transition
    dialog: bool = False  # a dialog window is open during the step


def protocol(seed: int) -> list[Step]:
    rng = random.Random(seed)
    answers = [a for a in ANSWERS for _ in range(10)]
    gestures = [g for g in GESTURES for _ in range(10)]
    rng.shuffle(answers)
    rng.shuffle(gestures)
    steps = [Step("Priveste camera, stai normal", 5.0)]
    for a in answers:
        steps += [Step(PROMPTS[a], 4.0, a, dialog=True), Step("Pauza, priveste drumul", 2.0)]
    for g in gestures:
        steps += [Step(PROMPTS[g], 4.0, g, dialog=True), Step("Lasa mana jos", 2.0)]
    for ph in PHONE:
        steps += [Step(PROMPTS[ph], 8.0, ph), Step("Lasa telefonul deoparte", 3.0)]
    steps.append(Step(PROMPTS["free"], 30.0, "free"))
    return steps


# --- the modules on a stream ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """Per-frame module inputs (from a recorded / live FeatureFrame + DriverPipeline, or synthetic)."""

    t: float
    yaw: float | None
    pitch: float | None
    eyes_open: bool | None
    hands: list[HandFeatures] | None
    phones: list[PhoneBox] | None
    face_box: Box | None
    lap_pattern: bool = False


@dataclass
class Trace:
    times: list[float] = field(default_factory=list)
    answers: list[str | None] = field(default_factory=list)
    gestures: list[str | None] = field(default_factory=list)
    phone: list[PhoneResult] = field(default_factory=list)
    in_window: list[bool] = field(default_factory=list)
    ms: dict[str, list[float]] = field(default_factory=lambda: {"head_answer": [], "hands": [], "phone": []})


class ModuleRunner:
    """Head answer + hands + phone for the driver, fed one :class:`Sample` at a time."""

    def __init__(self, cfgs: ModuleConfigs, frame_size: tuple[int, int]) -> None:
        self.frame_size = frame_size
        self.head = HeadAnswerDetector(cfgs.head_answer, seat="driver")
        self.hands = HandTracker(cfgs.hands)
        self.phone = PhoneTracker(cfgs.phone)
        self.trace = Trace()

    def open_window(self, until: float) -> None:
        self.head.open_window(True, to="driver", until=until)
        self.hands.set_dialog(True, until=until)

    def step(self, s: Sample) -> tuple[str | None, str | None, PhoneResult]:
        hr = self.hands.update(s.t, s.hands, self.frame_size, s.face_box)
        ar = self.head.update(s.t, s.yaw, s.pitch, s.eyes_open)
        pr = self.phone.update(s.t, s.phones, face_box=s.face_box, hands=hr.hands, lap_pattern=s.lap_pattern)
        tr = self.trace
        tr.times.append(s.t)
        tr.answers.append(ar.answer)
        tr.gestures.append(hr.gesture)
        tr.phone.append(pr)
        tr.in_window.append(ar.active)
        tr.ms["head_answer"].append(ar.ms)
        tr.ms["hands"].append(hr.ms)
        tr.ms["phone"].append(pr.ms)
        return ar.answer, hr.gesture, pr


def run_modules(
    samples: Iterable[Sample], windows: Sequence[tuple[float, float]], cfgs: ModuleConfigs, frame_size: tuple[int, int]
) -> Trace:
    runner = ModuleRunner(cfgs, frame_size)
    pending = sorted(windows)
    k = 0
    for s in samples:
        while k < len(pending) and pending[k][0] <= s.t:
            if s.t < pending[k][1]:
                runner.open_window(pending[k][1])
            k += 1
        runner.step(s)
    return runner.trace


# --- scoring ------------------------------------------------------------------------------------------------


def rising_edges(times: Sequence[float], values: Sequence[str | None]) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    prev: str | None = None
    for t, v in zip(times, values, strict=True):
        if v is not None and v != prev:
            out.append((t, v))
        prev = v
    return out


def trials(intervals: Sequence[Interval]) -> list[tuple[str, Interval]]:
    return [(i.label.removeprefix("trial_"), i) for i in intervals if i.label.startswith("trial_")]


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)], 3)


@dataclass
class Report:
    metrics: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)
    trials: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def score(trace: Trace, intervals: Sequence[Interval]) -> Report:
    rep = Report()
    answer_events = rising_edges(trace.times, trace.answers)
    gesture_events = rising_edges(trace.times, trace.gestures)
    per_kind: dict[str, list[bool]] = {}
    latencies: dict[str, list[float]] = {"answer": [], "gesture": []}
    for kind, iv in trials(intervals):
        row: dict[str, Any] = {"kind": kind, "start": round(iv.start, 2), "end": round(iv.end, 2)}
        if kind in ANSWERS or kind in GESTURES:
            events = answer_events if kind in ANSWERS else gesture_events
            hit = next(((t, v) for t, v in events if iv.start <= t <= iv.end + ANSWER_GRACE_S), None)
            row["detected"] = hit[1] if hit else None
            row["latency_s"] = round(hit[0] - iv.start, 3) if hit else None
            row["correct"] = hit is not None and hit[1] == kind
            if hit is not None and row["correct"]:
                latencies["answer" if kind in ANSWERS else "gesture"].append(hit[0] - iv.start)
        elif kind in PHONE:
            lo = iv.start + min(PHONE_SETTLE_S, (iv.end - iv.start) / 2)
            states = [p for t, p in zip(trace.times, trace.phone, strict=True) if lo <= t <= iv.end]
            in_use = sum(p.in_use for p in states) / len(states) if states else 0.0
            usages = Counter(p.usage for p in states if p.in_use)
            usage = usages.most_common(1)[0][0] if usages else None
            expected = PHONE_EXPECTED[kind]
            row.update(in_use_frac=round(in_use, 3), usage=usage, foreign_seen=any(p.foreign for p in states))
            row["correct"] = (in_use >= 0.5 and usage == expected) if expected else in_use < 0.5
        elif kind == "free":
            row["answers"] = sum(1 for t, _ in answer_events if iv.start <= t <= iv.end)
            row["gestures"] = sum(1 for t, _ in gesture_events if iv.start <= t <= iv.end)
            row["correct"] = row["answers"] == 0
        else:
            continue
        per_kind.setdefault(kind, []).append(bool(row["correct"]))
        rep.trials.append(row)

    outside = [(t, v) for (t, v) in answer_events if not _in_any(t, intervals, "dialog", ANSWER_GRACE_S)]
    rep.metrics["answers_outside_window"] = len(outside)
    rep.checks["no_answer_outside_window"] = not outside
    for kind, ok in per_kind.items():
        rep.metrics[f"{kind}_correct"] = f"{sum(ok)}/{len(ok)}"
        pct = 100.0 * sum(ok) / len(ok)
        rep.metrics[f"{kind}_pct"] = round(pct, 1)
        if kind in ANSWERS or kind in GESTURES:
            rep.checks[f"{kind}_ge_90pct"] = pct >= 90.0
        elif kind in PHONE or kind == "free":
            rep.checks[kind] = all(ok)
    rep.metrics["answer_latency_median_s"] = _median(latencies["answer"])
    rep.metrics["gesture_latency_median_s"] = _median(latencies["gesture"])
    for name, values in trace.ms.items():
        rep.metrics[f"{name}_ms_p95"] = _p95(values)
    return rep


def _in_any(t: float, intervals: Sequence[Interval], label: str, grace: float = 0.0) -> bool:
    return any(i.label == label and i.start <= t <= i.end + grace for i in intervals)


def diagnostics(
    samples: Sequence[Sample], intervals: Sequence[Interval], cfgs: ModuleConfigs, frame_size: tuple[int, int]
) -> dict[str, Any]:
    """Window forced open over the whole stream: answers / gestures per labelled activity; phone vs `phone` label."""
    if not samples:
        return {}
    t0, t1 = samples[0].t, samples[-1].t + 1.0
    forced = run_modules(samples, [(t0, t1)], cfgs, frame_size)
    answers = rising_edges(forced.times, forced.answers)
    gestures = rising_edges(forced.times, forced.gestures)
    activities = [i for i in intervals if i.end > i.start and not i.label.startswith("trial_") and i.label != "dialog"]
    per_label: dict[str, dict[str, Any]] = {}
    for iv in activities:
        d = per_label.setdefault(iv.label, {"segments": 0, "seconds": 0.0, "answers": 0, "gestures": 0})
        d["segments"] += 1
        d["seconds"] = round(d["seconds"] + iv.end - iv.start, 1)
        d["answers"] += sum(1 for t, _ in answers if iv.start <= t <= iv.end)
        d["gestures"] += sum(1 for t, _ in gestures if iv.start <= t <= iv.end)
    unlabelled = [t for t, _ in answers if not any(i.start <= t <= i.end for i in activities)]
    out: dict[str, Any] = {
        "forced_window_answers_total": len(answers),
        "forced_window_answers_per_min": round(60.0 * len(answers) / max(1e-9, t1 - 1.0 - t0), 2),
        "forced_window_answers_unlabelled": len(unlabelled),
        "forced_window_gestures_total": len(gestures),
        "by_label": per_label,
    }
    phone_labels = [i for i in intervals if i.label == "phone"]
    if phone_labels:
        normal = run_modules(samples, [], cfgs, frame_size)
        pairs = list(zip(normal.times, normal.phone, strict=True))
        inside = [p.in_use for t, p in pairs if _in_any(t, phone_labels, "phone")]
        outside = [p.in_use for t, p in pairs if not _in_any(t, phone_labels, "phone")]
        out["phone_label_in_use_frac"] = round(sum(inside) / len(inside), 3) if inside else None
        out["phone_outside_label_in_use_frac"] = round(sum(outside) / len(outside), 3) if outside else None
    return out


# --- synthetic streams ----------------------------------------------------------------------------------------

SYN_SIZE = (1280, 720)
SYN_FACE: Box = (540.0, 150.0, 200.0, 240.0)


def _hand(cx: float, cy: float, gesture: str | None, score: float) -> HandFeatures:
    w, h = SYN_SIZE
    pts = [((cx + 12 * (i % 5 - 2)) / w, (cy + 12 * (i // 5 - 2)) / h, 0.0) for i in range(21)]
    return HandFeatures(handedness="Right", score=0.95, gesture=gesture, gesture_score=score, landmarks=pts)


def _box(cx: float, cy: float, score: float) -> PhoneBox:
    return PhoneBox(x1=cx - 30, y1=cy - 55, x2=cx + 30, y2=cy + 55, score=round(score, 3))


def synthetic(steps: Sequence[Step], seed: int) -> tuple[list[Sample], list[Interval]]:
    """Synthetic module inputs with known truth: reaction times, amplitudes, noise, blinks, detector misses."""
    rng = random.Random(seed)
    samples: list[Sample] = []
    intervals: list[Interval] = []
    t0 = 0.0
    frame = 0
    next_blink = rng.uniform(2.0, 5.0)
    for step in steps:
        motion = _motion(step.expect, rng)
        n = round(step.duration_s * FPS)
        for i in range(n):
            t = t0 + i / FPS
            tau = t - t0
            dyaw, dpitch, hand, phone_spec, lap = motion(tau)
            if t >= next_blink + 0.15:
                next_blink = t + rng.uniform(2.0, 5.0)
            eyes = not (next_blink <= t < next_blink + 0.15)
            yaw = 2.0 + 2.0 * math.sin(2 * math.pi * 0.07 * t) + dyaw + rng.gauss(0, 0.2)
            pitch = -3.0 + dpitch + rng.gauss(0, 0.2)
            hands = None
            if frame % 3 == 0:  # Gesture Recognizer at ~10 Hz (recorded cadence)
                hands = [] if hand is None else [hand] if rng.random() > 0.05 else [_hand(640, 300, None, 0.0)]
            phones = None
            if frame % 6 == 0:  # YOLO at 5 Hz
                phones = []
                if phone_spec is not None and rng.random() < phone_spec[2]:
                    phones.append(_box(phone_spec[0], phone_spec[1], rng.uniform(0.5, 0.9)))
                elif rng.random() < 0.05:  # sporadic false detection
                    phones.append(_box(rng.uniform(300, 1000), rng.uniform(300, 650), rng.uniform(0.4, 0.6)))
            samples.append(Sample(round(t, 4), yaw, pitch, eyes, hands, phones, SYN_FACE, lap))
            frame += 1
        t1 = t0 + n / FPS
        if step.expect is not None:
            intervals.append(Interval(f"trial_{step.expect}", t0, t1))
        if step.dialog:
            intervals.append(Interval("dialog", t0, t1))
        t0 = t1
    return samples, intervals


Motion = Callable[[float], tuple[float, float, HandFeatures | None, tuple[float, float, float] | None, bool]]


def _motion(expect: str | None, rng: random.Random) -> Motion:
    """Per-step behaviour: (d_yaw, d_pitch, hand, phone (cx, cy, detection prob), lap pattern) at time tau."""
    react, amp, freq = rng.uniform(0.5, 1.1), rng.uniform(5.0, 10.0), rng.uniform(1.8, 3.0)
    cycles, hold, g_score = rng.uniform(1.5, 2.5), rng.uniform(1.0, 1.8), rng.uniform(0.75, 0.95)

    def osc(tau: float) -> float:
        x = tau - react
        return amp * math.sin(2 * math.pi * freq * x) if 0 <= x < cycles / freq else 0.0

    def still(tau: float) -> tuple[float, float, HandFeatures | None, tuple[float, float, float] | None, bool]:
        return 0.0, 0.0, None, None, False

    if expect == "yes":
        return lambda tau: (0.15 * osc(tau), osc(tau), None, None, False)
    if expect == "no":
        return lambda tau: (osc(tau), 0.15 * osc(tau), None, None, False)
    if expect in GESTURES:
        g = expect

        def gesture(tau: float) -> tuple[float, float, HandFeatures | None, tuple[float, float, float] | None, bool]:
            shown = react <= tau < react + hold
            return 0.0, 0.0, _hand(700, 300, g, g_score) if shown else None, None, False

        return gesture
    if expect == "phone_call":
        return lambda tau: (0.0, 0.0, _hand(720, 320, None, 0.0), (700.0, 280.0, 0.85), False)
    if expect == "phone_hand":
        return lambda tau: (0.0, -8.0, _hand(605, 600, None, 0.0), (600.0, 560.0, 0.85), False)
    if expect == "phone_lap":
        return lambda tau: (0.0, -15.0 if int(tau) % 3 == 0 else 0.0, None, None, tau >= 2.5)
    if expect == "phone_passenger":
        return lambda tau: (0.0, 0.0, _hand(250, 540, None, 0.0), (250.0, 500.0, 0.9), False)
    if expect == "free":

        def free(tau: float) -> tuple[float, float, HandFeatures | None, tuple[float, float, float] | None, bool]:
            yaw = 30.0 if 3.0 <= tau < 3.8 else -35.0 if 8.0 <= tau < 8.9 else 0.0  # mirror checks
            pitch = -20.0 * min(1.0, (tau - 12.0) / 4.0) if 12.0 <= tau < 18.0 else 0.0  # slow head drop
            if 18.0 <= tau < 24.0:
                pitch += 1.0 * math.sin(2 * math.pi * 4.0 * tau)  # talking
            if 26.0 <= tau < 26.8:
                pitch += 8.0 * math.sin(2 * math.pi * 2.5 * (tau - 26.0))  # unsolicited nod: no window -> nothing
            return yaw, pitch, None, None, False

        return free
    return still


# --- recorded sessions ----------------------------------------------------------------------------------------


def session_samples(cfg: PerceptionConfig, session_dir: Path) -> tuple[list[Sample], tuple[int, int], dict[str, Any]]:
    from perception.calibration import Calibration
    from perception.driver_cam.face import face_box_px
    from perception.driver_cam.pipeline import DriverPipeline
    from perception.replay import FeatureReplay

    replay = FeatureReplay(session_dir / "features.jsonl.gz")
    cam = replay.meta["camera"]
    size = (int(cam["width"]), int(cam["height"]))
    cal_path = session_dir / "calibration.json"
    cal = Calibration.load(cfg, cal_path) if cal_path.exists() else None
    pipeline = DriverPipeline(cfg, size, cal.ear_baseline if cal else None, cal.model if cal else None)
    samples: list[Sample] = []
    for ff in replay.frames():
        st = pipeline.update(ff)
        eyes = (st.eyes.state != "CLOSED") if st.eyes.reliable else None
        box = face_box_px(ff.face, *size)
        samples.append(
            Sample(ff.t, st.head.raw_yaw, st.head.raw_pitch, eyes, ff.hands, ff.phones, box, st.gaze.lap_pattern)
        )
    meta = {"session": session_dir.name, "camera": f"{size[0]}x{size[1]}", "calibrated": cal is not None}
    return samples, size, meta


def evaluate_stream(
    samples: list[Sample], intervals: list[Interval], cfgs: ModuleConfigs, size: tuple[int, int]
) -> Report:
    windows = [(i.start, i.end) for i in intervals if i.label == "dialog"]
    rep = score(run_modules(samples, windows, cfgs, size), intervals)
    rep.diagnostics = diagnostics(samples, intervals, cfgs, size)
    if not trials(intervals):
        rep.notes.append(
            "No interaction trials in this session (not recorded with this protocol): only the diagnostics apply. "
            "With no dialog window, any answer is a false one."
        )
    if not any(s.hands for s in samples):
        rep.notes.append("No hands recorded in this session: gestures and the in-hand phone geometry are not tested.")
    return rep


def run_session(cfg: PerceptionConfig, cfgs: ModuleConfigs, session_dir: Path, name: str, out_dir: Path) -> int:
    labels = session_dir / "labels.jsonl"
    samples, size, meta = session_samples(cfg, session_dir)
    events = load_labels(labels)[1] if labels.exists() else []
    t_end = samples[-1].t if samples else None
    rep = evaluate_stream(samples, to_intervals(events, t_end), cfgs, size)
    meta.update(mode="replay", frames=len(samples))
    path = write_report(name, meta, rep, cfgs, out_dir)
    print_report(rep, path)
    return 0 if rep.passed else 2


def run_synthetic(cfgs: ModuleConfigs, seed: int, name: str, out_dir: Path) -> int:
    steps = protocol(seed)
    samples, intervals = synthetic(steps, seed)
    rep = evaluate_stream(samples, intervals, cfgs, SYN_SIZE)
    rep.notes.append(
        "Synthetic streams: angles, hands and boxes generated with known truth (reaction 0.5-1.1 s, nod amplitude "
        "+-5-10 deg at 1.8-3 Hz, 5 % gesture flicker, 85 % YOLO recall, 5 % false boxes). Checks the logic, not the "
        "models: run the live protocol at integration."
    )
    meta = {"mode": "synthetic", "seed": seed, "frames": len(samples), "duration_s": round(samples[-1].t, 1)}
    path = write_report(name, meta, rep, cfgs, out_dir)
    print_report(rep, path)
    return 0 if rep.passed else 2


# --- live (guided) --------------------------------------------------------------------------------------------


def run_live(
    cfg: PerceptionConfig, cfgs: ModuleConfigs, name: str, seed: int, profile: str | None, out_dir: Path
) -> int:
    import cv2

    from perception.calibration import Calibration, profile_path
    from perception.driver_cam.face import face_box_px
    from perception.driver_cam.pipeline import DriverPipeline
    from perception.overlay import draw_driver, mean_luma
    from perception.recorder import DATA_DIR, RecordingSession

    session_dir = DATA_DIR / "features" / f"{dt.datetime.now():%Y%m%d-%H%M%S}_interaction-{_slug(name)}"
    session = RecordingSession(
        cfg, session_dir / "features.jsonl.gz", label=f"eval_interaction guided: {name}", gesture_hz=cfg.rates.gaze_hz
    )
    cal = None
    if profile:
        cal_path = profile_path(profile)
        if cal_path.exists():
            cal = Calibration.load(cfg, cal_path)
            shutil.copyfile(cal_path, session_dir / "calibration.json")  # lap pattern re-scorable on replay
        else:
            print(f"no calibration for '{profile}': the lap situation cannot be detected", file=sys.stderr)
    size = (session.info.width, session.info.height)
    writer = LabelWriter(
        session_dir / "labels.jsonl", {"session": session_dir.name, "protocol": "eval_interaction guided", "seed": seed}
    )
    pipeline = DriverPipeline(cfg, size, cal.ear_baseline if cal else None, cal.model if cal else None)
    runner = ModuleRunner(cfgs, size)
    steps = protocol(seed)
    print(f"guided protocol: {len(steps)} steps, {sum(s.duration_s for s in steps):.0f} s. Session: {session_dir}")
    aborted = False
    try:
        for idx, step in enumerate(steps):
            start = session.now()
            if step.expect:
                writer.write(LabelEvent(t=start, label=f"trial_{step.expect}", kind="start"))
            if step.dialog:
                writer.write(LabelEvent(t=start, label="dialog", kind="start"))
                runner.open_window(start + step.duration_s)
            while (elapsed := session.now() - start) < step.duration_s:
                out = session.step(timeout=0.5)
                if out is None:
                    continue
                frame, ff = out
                st = pipeline.update(ff)
                eyes = (st.eyes.state != "CLOSED") if st.eyes.reliable else None
                box = face_box_px(ff.face, *size)
                sample = Sample(
                    ff.t, st.head.raw_yaw, st.head.raw_pitch, eyes, ff.hands, ff.phones, box, st.gaze.lap_pattern
                )
                answer, gesture, phone = runner.step(sample)
                live = f"ans={answer or '-'} gest={gesture or '-'} phone={phone.usage if phone.in_use else '-'}"
                banner = f"{step.prompt}  {step.duration_s - elapsed:3.1f}s [{idx + 1}/{len(steps)}]  {live}"
                img = draw_driver(
                    frame.image, ff, st, fps=0.0, luma=mean_luma(frame.image), dark_luma=cfg.monitoring.dark_luma,
                    banner=banner,
                )
                cv2.imshow(WINDOW, img)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    aborted = True
                    break
            end = session.now()
            if step.dialog:
                writer.write(LabelEvent(t=end, label="dialog", kind="end"))
            if step.expect:
                writer.write(LabelEvent(t=end, label=f"trial_{step.expect}", kind="end"))
            if aborted:
                break
    finally:
        writer.close()
        session.close()
        cv2.destroyAllWindows()
    if aborted:
        print("aborted; partial session kept in", session_dir)
    code = run_session(cfg, cfgs, session_dir, name, out_dir)
    print(f"re-score later: python scripts/eval_interaction.py --session {session_dir}")
    return code


# --- report ---------------------------------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "run"


def render_markdown(name: str, meta: dict[str, Any], rep: Report, cfgs: ModuleConfigs) -> str:
    lines = [f"# Interaction eval: {name} ({dt.date.today().isoformat()})", ""]
    lines += [f"- **{k}**: {v}" for k, v in meta.items()]
    lines += ["", f"**Result: {'PASS' if rep.passed else 'FAIL'}**", "", "## Checks", "", "| check | ok |", "|---|---|"]
    lines += [f"| {k} | {'yes' if v else '**no**'} |" for k, v in rep.checks.items()] or ["| (none) | |"]
    lines += ["", "## Metrics", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rep.metrics.items()]
    if rep.trials:
        lines += ["", "## Trials", "", "| kind | start | detected / usage | latency s | correct |"]
        lines.append("|---|---|---|---|---|")
        for tr in rep.trials:
            what = tr.get("detected") or tr.get("usage") or tr.get("answers", "-")
            if "in_use_frac" in tr:
                what = f"{tr.get('usage') or '-'} (in use {tr['in_use_frac']:.0%})"
            lines.append(
                f"| {tr['kind']} | {tr['start']} | {what} | {tr.get('latency_s') or '-'} | "
                f"{'yes' if tr['correct'] else '**no**'} |"
            )
    if rep.diagnostics:
        lines += ["", "## Diagnostics (dialog window forced open over the whole stream)", ""]
        by_label = rep.diagnostics.get("by_label", {})
        lines += [f"- **{k}**: {v}" for k, v in rep.diagnostics.items() if k != "by_label"]
        if by_label:
            lines += ["", "| activity | segments | s | answers | gestures |", "|---|---|---|---|---|"]
            lines += [
                f"| {k} | {v['segments']} | {v['seconds']} | {v['answers']} | {v['gestures']} |"
                for k, v in by_label.items()
            ]
    lines += ["", "## Notes", ""] + [f"- {n}" for n in rep.notes]
    lines += ["", "## Module settings (pending modules.yaml)", "", "```json", json.dumps(asdict(cfgs), indent=1), "```"]
    return "\n".join(lines) + "\n"


def write_report(name: str, meta: dict[str, Any], rep: Report, cfgs: ModuleConfigs, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"interaction-{_slug(name)}-{dt.date.today().isoformat()}"
    md = out_dir / f"{stem}.md"
    md.write_text(render_markdown(name, meta, rep, cfgs), encoding="utf-8")
    payload = {"meta": meta, "passed": rep.passed, **asdict(rep), "config": asdict(cfgs)}
    (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    return md


def print_report(rep: Report, path: Path) -> None:
    for k, v in rep.metrics.items():
        print(f"  {k:32s} {v}")
    for k, v in rep.diagnostics.items():
        if k != "by_label":
            print(f"  {k:32s} {v}")
    print(f"  {'RESULT':32s} {'PASS' if rep.passed else 'FAIL'}  ({sum(rep.checks.values())}/{len(rep.checks)} checks)")
    print(f"report: {path}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default=None, help="report name (no personal data needed)")
    p.add_argument("--session", type=Path, default=None, help="re-score a recorded session (replay)")
    p.add_argument("--synthetic", action="store_true", help="synthetic streams with known truth (no camera)")
    p.add_argument("--seed", type=int, default=7, help="trial order / synthetic noise")
    p.add_argument("--profile", default=None, help="live: gaze calibration profile (needed for the lap situation)")
    p.add_argument("--out-dir", type=Path, default=EVAL_DIR)
    p.add_argument("--config", type=Path, default=None, help="perception.yaml")
    p.add_argument("--modules-config", type=Path, default=PENDING)
    args = p.parse_args(argv)
    configure_logging("WARNING", json=False)
    cfgs = load_module_configs(args.modules_config)
    if args.synthetic:
        return run_synthetic(cfgs, args.seed, args.name or f"synthetic-seed{args.seed}", args.out_dir)
    cfg = load_config(args.config)
    if args.session:
        return run_session(cfg, cfgs, args.session, args.name or args.session.name, args.out_dir)
    return run_live(cfg, cfgs, args.name or "laptop", args.seed, args.profile, args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
