"""Live check of the passenger camera (AP1-AP5) and of camera monitoring on both cameras (AS12 / AP5).

    python scripts/eval_passenger.py                 # guided, ~2.5 min, two people (driver seat + passenger seat)
    python scripts/eval_passenger.py --skip dark     # without the lights-off step

Runs ``perception.main`` itself (both camera processes, every module) in a background thread and reads the frames
it publishes, so what is checked is exactly what core would receive. A window shows the passenger camera (the
worker's MJPEG frame) and the current instruction. Each step is scored on the frames inside it, after a reaction
time; the image statistics of the camera monitor (luma, contrast, sharpness) are logged per step, so the
``monitoring.*`` image thresholds can be tuned on the real cameras instead of synthetic images.

Checks:
* AP1 present: passenger in view -> ``passenger.present`` and an ``occupants`` entry (front_right);
  absent: leaves the frame -> not present within ``monitoring.face_lost_s`` + 1 s;
* AP3 speaking while reading aloud; AP4 ``holding_phone`` with a phone in the hand;
* AP2 asleep: eyes closed -> ``awake = false`` after ``passenger.asleep_closed_s``; head dropped -> sooner
  (``asleep_closed_head_s``);
* AP5 / AS12 monitoring: a covered lens -> ``monitoring_ok = false`` with ``occluded`` / ``too_dark`` within 3 s,
  on the passenger and on the driver camera; lights off -> ``too_dark`` (or ``occluded``).

Writes docs/eval/passenger-<date>.md (+ .json). Records nothing: no images, no features.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contextlib

import cv2
import numpy as np

from perception.config import REPO_ROOT, PerceptionConfig, load_config
from perception.main import Perception
from perception.worker import WorkerOptions

EVAL_DIR = REPO_ROOT / "docs" / "eval"
WINDOW = "DriveMate passenger eval (q to abort)"
REACTION_S = 1.5  # people need ~1.5 s to follow an instruction
SENTENCE = "Pasager: citeste cu voce tare: 'Mai avem mult pana la benzinarie? Mi-e cam foame.'"


@dataclass
class Step:
    key: str | None
    prompt: str
    duration_s: float


def protocol(cfg: PerceptionConfig, skip: set[str]) -> list[Step]:
    p = cfg.passenger
    steps = [
        Step(None, "Pasager: asaza-te in fata camerei pasagerului, priveste inainte", 4.0),
        Step("present", "Pasager: stai normal, ochii deschisi", 8.0),
        Step("speaking", SENTENCE, 8.0),
        Step(None, "Pasager: liniste, ochii deschisi", 3.0),
        Step(
            "asleep",
            f"Pasager: INCHIDE ochii si tine-i inchisi ({p.asleep_closed_s + 3:.0f} s), capul drept",
            p.asleep_closed_s + 3.0,
        ),
        Step(None, "Pasager: deschide ochii", 4.0),
        Step(
            "asleep_head",
            "Pasager: INCHIDE ochii si lasa capul sa CADA in fata, ca atipit",
            p.asleep_closed_head_s + 3.0,
        ),
        Step(None, "Pasager: ridica capul, ochii deschisi", 4.0),
        Step("phone", "Pasager: tine TELEFONUL in mana si uita-te la el", 8.0),
        Step(None, "Pasager: lasa telefonul jos", 3.0),
        Step("absent", "Pasager: IESI din cadru (apleaca-te in afara camerei)", cfg.monitoring.face_lost_s + 5.0),
        Step(None, "Pasager: revino in fata camerei", 4.0),
        Step("covered_passenger", "ACOPERA obiectivul camerei PASAGERULUI cu palma", 6.0),
        Step(None, "Descopera camera pasagerului", 4.0),
        Step("covered_driver", "ACOPERA obiectivul camerei SOFERULUI cu palma", 6.0),
        Step(None, "Descopera camera soferului", 4.0),
        Step("dark", "STINGE lumina din camera (sau acopera sursa de lumina)", 8.0),
        Step(None, "Aprinde lumina la loc", 5.0),
    ]
    return [s for s in steps if s.key not in skip]


@dataclass
class Window:
    key: str
    start: float  # time.time()
    end: float
    frames: list[dict[str, Any]] = field(default_factory=list)
    image_stats: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {"driver": [], "passenger": []})


class Runtime:
    """``perception.main`` in a background thread; frames are collected as they are published."""

    def __init__(self, cfg: PerceptionConfig) -> None:
        self.frames: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.app = Perception(
            cfg,
            cameras=["driver", "passenger"],
            options=WorkerOptions(),
            ws=False,
            mjpeg=False,
            print_frames=True,
            out=self._collect,
        )
        self._loop = asyncio.new_event_loop()
        self._task: asyncio.Task[None] | None = None
        self._thread = threading.Thread(target=self._run, name="perception", daemon=True)

    def _collect(self, line: str) -> None:
        if line.startswith("{"):
            with self._lock:
                self.frames.append(json.loads(line))

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self.app.run(seconds=0.0))
        with contextlib.suppress(asyncio.CancelledError):
            self._loop.run_until_complete(self._task)

    def start(self) -> Runtime:
        self._thread.start()
        for w in self.app.workers.values():
            w.want_jpeg(True)
        return self

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return self.frames[-1] if self.frames else None

    def since(self, t_wall: float) -> list[dict[str, Any]]:
        with self._lock:
            return [f for f in self.frames if f["perf"]["publish_ts"] >= t_wall]

    def stop(self) -> None:
        if self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)
        self._thread.join(timeout=30)


def _scored(win: Window) -> list[dict[str, Any]]:
    return [f for f in win.frames if f["perf"]["publish_ts"] >= win.start + REACTION_S]


def _pct(frames: list[dict[str, Any]], pred: Any) -> float | None:
    return round(100.0 * sum(1 for f in frames if pred(f)) / len(frames), 1) if frames else None


def _first(win: Window, pred: Any) -> float | None:
    """Seconds from the step start to the first frame where ``pred`` holds."""
    return next((round(f["perf"]["publish_ts"] - win.start, 2) for f in win.frames if pred(f)), None)


def _reason(f: dict[str, Any], camera: str) -> str | None:
    return (f.get(camera) or {}).get("monitoring_reason")


def score(cfg: PerceptionConfig, wins: dict[str, Window]) -> tuple[dict[str, Any], dict[str, bool | None]]:
    p, mon = cfg.passenger, cfg.monitoring
    m: dict[str, Any] = {}
    checks: dict[str, bool | None] = {}

    def present(f: dict[str, Any]) -> bool:
        return bool(f["passenger"].get("present")) and any(o["seat"] == "front_right" for o in f["occupants"])

    if (w := wins.get("present")) is not None:
        m["present_pct"] = _pct(_scored(w), present)
        checks["AP1_present"] = m["present_pct"] is not None and m["present_pct"] >= 95.0
    if (w := wins.get("absent")) is not None:
        t = _first(w, lambda f: not f["passenger"].get("present"))
        m["absent_after_s"] = t
        checks["AP1_absent"] = t is not None and t <= mon.face_lost_s + REACTION_S + 1.0
    if (w := wins.get("speaking")) is not None:
        m["speaking_pct"] = _pct(_scored(w), lambda f: f["passenger"].get("speaking"))
        checks["AP3_speaking"] = m["speaking_pct"] is not None and m["speaking_pct"] >= 50.0
    if (w := wins.get("asleep")) is not None:
        t = _first(w, lambda f: f["passenger"].get("present") and f["passenger"].get("awake") is False)
        m["asleep_after_s"] = t
        m["asleep_eyes_closed_s_max"] = max((f["passenger"].get("eyes_closed_s") or 0.0 for f in w.frames), default=0)
        checks["AP2_asleep"] = t is not None and t <= p.asleep_closed_s + REACTION_S + 1.5
        m["asleep_present_pct"] = _pct(_scored(w), present)
    if (w := wins.get("asleep_head")) is not None:
        t = _first(w, lambda f: f["passenger"].get("present") and f["passenger"].get("awake") is False)
        m["asleep_head_after_s"] = t
        checks["AP2_head_drop"] = t is not None and t <= p.asleep_closed_head_s + REACTION_S + 1.5
    if (w := wins.get("phone")) is not None:
        m["holding_phone_pct"] = _pct(_scored(w), lambda f: f["passenger"].get("holding_phone"))
        checks["AP4_phone"] = m["holding_phone_pct"] is not None and m["holding_phone_pct"] >= 50.0
    blocked = ("occluded", "too_dark", "no_frames", "frozen")
    for key, cam in (("covered_passenger", "passenger"), ("covered_driver", "driver")):
        if (w := wins.get(key)) is not None:
            t = _first(w, lambda f, c=cam: _reason(f, c) in blocked)
            m[f"{key}_after_s"] = t
            m[f"{key}_reasons"] = sorted({str(_reason(f, cam)) for f in _scored(w)})
            checks[f"AS12_{key}"] = t is not None and t <= 3.0 + REACTION_S
    if (w := wins.get("dark")) is not None:
        reasons = {cam: sorted({str(_reason(f, cam)) for f in _scored(w)}) for cam in ("driver", "passenger")}
        m["dark_reasons"] = reasons
        checks["AP5_dark"] = any(r in ("too_dark", "occluded") for r in reasons["passenger"]) or None
    return m, checks


def _stats_table(wins: dict[str, Window]) -> list[str]:
    lines = [
        "| step | camera | luma p50 | std p50 | sharpness p50 | reasons |",
        "|---|---|---|---|---|---|",
    ]
    for key, w in wins.items():
        for cam, rows in w.image_stats.items():
            rows = [r for r in rows if r.get("luma") is not None]
            if not rows:
                continue

            def med(k: str, rows: list[dict[str, Any]] = rows) -> str:
                vals = [r[k] for r in rows if r.get(k) is not None]
                return f"{statistics.median(vals):.1f}" if vals else "-"

            reasons = sorted({str(r.get("reason")) for r in rows})
            lines.append(
                f"| {key} | {cam} | {med('luma')} | {med('std')} | {med('sharpness')} | {', '.join(reasons)} |"
            )
    return lines


def _write_report(cfg: PerceptionConfig, wins: dict[str, Window], m: dict[str, Any], checks: dict[str, Any]) -> Path:
    stamp = dt.date.today().isoformat()
    path = EVAL_DIR / f"passenger-{stamp}.md"
    mon, p = cfg.monitoring, cfg.passenger
    lines = [
        f"# Passenger camera (AP1-AP5) and camera monitoring (AS12), {stamp}",
        "",
        "Generated by `scripts/eval_passenger.py`: the frames `perception.main` published during a guided protocol "
        f"(both cameras), each step scored after {REACTION_S} s reaction time.",
        "",
        f"- cameras: driver `{cfg.cameras.driver.device}`, passenger `{cfg.cameras.passenger.device}`",
        f"- passenger.asleep_closed_s {p.asleep_closed_s}, asleep_closed_head_s {p.asleep_closed_head_s}, "
        f"head_drop_deg {p.head_drop_deg}; monitoring.face_lost_s {mon.face_lost_s}, occluded_std_max "
        f"{mon.occluded_std_max}, blur_var_min {mon.blur_var_min}, dark_luma {mon.dark_luma}",
        "",
        "## Checks",
        "",
    ]
    lines += [f"- {'PASS' if ok else ('n/a' if ok is None else 'FAIL')} {k}" for k, ok in checks.items()]
    lines += ["", "## Metrics", ""] + [f"- {k}: {v}" for k, v in m.items()]
    lines += ["", "## Image statistics per step (camera monitor)", "", *_stats_table(wins), ""]
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps({"metrics": m, "checks": checks}, indent=2), encoding="utf-8")
    return path


def _show(rt: Runtime, banner: str, sub: str) -> bool:
    jpeg = rt.app.workers["passenger"].latest_jpeg
    img = None
    if jpeg:
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        img = np.zeros((360, 640, 3), np.uint8)
    img = cv2.resize(img, (960, int(960 * img.shape[0] / img.shape[1])))
    cv2.rectangle(img, (0, 0), (img.shape[1], 70), (0, 0, 0), -1)
    cv2.putText(img, banner[:90], (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, sub[:110], (12, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 255, 80), 1, cv2.LINE_AA)
    cv2.imshow(WINDOW, img)
    return (cv2.waitKey(30) & 0xFF) in (ord("q"), 27)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--skip", nargs="*", default=[], help="step keys to leave out (e.g. dark)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    rt = Runtime(cfg).start()
    wins: dict[str, Window] = {}
    aborted = False
    try:
        t_ready = time.monotonic() + 60.0
        while time.monotonic() < t_ready:  # models load in both camera processes
            f = rt.latest()
            if f and all(f["perf"]["cameras"].get(c, {}).get("available") for c in ("driver", "passenger")):
                break
            if _show(rt, "Pornesc camerele si modelele ...", ""):
                return 1
        steps = protocol(cfg, set(args.skip))
        print(f"{len(steps)} steps, {sum(s.duration_s for s in steps):.0f} s", flush=True)
        for idx, step in enumerate(steps):
            start = time.time()
            win = Window(step.key, start, start + step.duration_s) if step.key else None
            while (left := start + step.duration_s - time.time()) > 0:
                f = rt.latest() or {}
                ps = f.get("passenger") or {}
                sub = (
                    f"present={ps.get('present')} awake={ps.get('awake')} closed={ps.get('eyes_closed_s')}s "
                    f"speaking={ps.get('speaking')} phone={ps.get('holding_phone')} "
                    f"mon P={ps.get('monitoring_reason')} D={(f.get('driver') or {}).get('monitoring_reason')}"
                )
                if win is not None:
                    for cam in ("driver", "passenger"):
                        msg = rt.app.workers[cam].latest or {}
                        if msg.get("kind") == "frame":
                            win.image_stats[cam].append(dict(msg.get("monitoring") or {}))
                if _show(rt, f"[{idx + 1}/{len(steps)}] {step.prompt}  {left:3.0f}s", sub):
                    aborted = True
                    break
            if win is not None:
                win.frames = [f for f in rt.since(win.start) if f["perf"]["publish_ts"] < win.end]
                wins[win.key] = win
            if aborted:
                break
    finally:
        cv2.destroyAllWindows()
        rt.stop()
    m, checks = score(cfg, wins)
    path = _write_report(cfg, wins, m, checks)
    for k, ok in checks.items():
        print(f"  {'PASS' if ok else ('n/a ' if ok is None else 'FAIL')}  {k}")
    for k, v in m.items():
        print(f"     {k}: {v}")
    print(f"\nreport: {path}")
    return 0 if all(v is not False for v in checks.values()) and not aborted else 2


if __name__ == "__main__":
    raise SystemExit(main())
