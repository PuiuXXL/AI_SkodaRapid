"""Guided live check of the demo scenes on BOTH seats (P1): PASS / FAIL per scene from the real PerceptionFrames.

    python scripts/scene_check.py                 # all scenes (driver at the C615, passenger at the LifeCam)
    python scripts/scene_check.py --only S3 S8    # a subset

Before: profiles enrolled on both cameras (scripts/enroll_face.py --name X --camera driver|passenger) and the driver
calibrated (scripts/calibrate.py --name X). The script starts its own WS endpoint and perception.main against it (not
core, not port 8000), shows the instructions in a window (no camera image; click it once so SPACE reaches it) and
judges every scene on the frames P1 publishes. Report: docs/eval/scene-check-<date>.md. Nothing is recorded.

S1 identities < 3 s + "yes" nod in the dialog window (both seats) | S2 left mirror without off_road x10, camera covered
-> monitoring_ok=false < 2 s | S3 driver phone < 1 s (SPACE), thumbs up in the window (both) | S4 3 glances at the
passenger + passenger.holding_phone, not the driver's phone | S5 gaze entropy falls over 30 s fixed | S6 yawns 3/3,
open palm (both), passenger asleep < 12 s | S8 2 s closures with continuous closed_ms (+-100 ms), blinks 9/10, squint
/ smile never a closure | S9 slow head drop with closed eyes 5/5, passenger awake again | N 60 s of normal driving:
zero false phone / gesture / answer / posture / closure / nod events. Plus: driver face >= 20 fps.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import itertools
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import yaml  # noqa: E402

from scripts.ws_probe import Probe, _kill_tree  # noqa: E402

WINDOW = "scene check (nothing is recorded)"
Frame = dict[str, Any]


class Session:
    def __init__(self, probe: Probe) -> None:
        self.probe = probe
        self.results: list[tuple[str, str, bool, str]] = []  # scene, criterion, ok, detail
        self.aborted = False
        self.steps: list[dict[str, Any]] = []  # every prompt with its time window (for --dump)

    # --- UI -------------------------------------------------------------------------------------------------------

    def _show(self, lines: list[str], colour: tuple[int, int, int] = (0, 220, 255)) -> list[float]:
        img = np.zeros((90 + 46 * len(lines), 1180, 3), np.uint8)
        for i, text in enumerate(lines):
            cv2.putText(img, text, (20, 60 + 46 * i), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2, cv2.LINE_AA)
        cv2.imshow(WINDOW, img)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            self.aborted = True
        return [time.time()] if key == ord(" ") else []

    async def step(self, prompt: str, seconds: float, who: str = "") -> tuple[float, float, list[float]]:
        """Show ``prompt`` for ``seconds``; returns (start, end, SPACE times) in time.time() (= frame ``ts``)."""
        t0, keys = time.time(), []
        while not self.aborted and time.time() - t0 < seconds:
            status = self._status()
            keys += self._show([who, prompt, f"{seconds - (time.time() - t0):4.1f} s", status])
            await asyncio.sleep(0.03)
        self.steps.append({"who": who, "prompt": prompt, "t0": t0, "t1": time.time(), "keys": keys})
        return t0, time.time(), keys

    async def wait_space(self, prompt: str) -> None:
        while not self.aborted and not self._show([prompt, "(click pe fereastra, apoi SPATIU)"]):
            await asyncio.sleep(0.03)

    def _status(self) -> str:
        f = self.probe.frames[-1] if self.probe.frames else None
        if f is None:
            return "waiting for frames..."
        d, p = f["driver"], f["passenger"]
        return (f"zone {d['gaze']['zone']}  eyes {d['eyes'].get('state')}  phone {d['phone']['in_use']}  "
                f"gest {d.get('gesture')}/{p.get('gesture')}  pass awake {p.get('awake')}")  # fmt: skip

    # --- frames ---------------------------------------------------------------------------------------------------

    def frames(self, t0: float, t1: float) -> list[Frame]:
        return [f for f in self.probe.frames if t0 <= f["ts"] <= t1]

    def first(self, t0: float, t1: float, pred: Callable[[Frame], bool]) -> float | None:
        return next((f["ts"] for f in self.frames(t0, t1) if pred(f)), None)

    def record(self, scene: str, criterion: str, ok: bool, detail: str) -> None:
        self.results.append((scene, criterion, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {scene} {criterion}: {detail}", flush=True)

    async def dialog(self, to: str, seconds: float = 7.0) -> None:
        await self.probe.send({"cmd": "dialog_window", "open": True, "to": to, "until": time.time() + seconds})


def _seat(f: Frame, seat: str) -> dict[str, Any] | None:
    return next((o for o in f["occupants"] if o["seat"] == seat), None)


def _posture_any(block: dict[str, Any]) -> bool:
    return any((block.get("posture") or {}).values())


# --- scenes ---------------------------------------------------------------------------------------------------------


async def s1(s: Session) -> None:
    await s.step("AMANDOI: iesiti din cadrul camerelor", 5.0, "S1 identitati")
    t0, t1, _ = await s.step("AMANDOI: intrati in cadru si priviti camera", 8.0, "S1 identitati")
    for seat, cam in (("driver", "sofer"), ("front_right", "pasager")):

        def seen(f: Frame, seat: str = seat) -> bool:
            return _seat(f, seat) is not None

        def known(f: Frame, seat: str = seat) -> bool:
            return (_seat(f, seat) or {}).get("profile") is not None

        t_face, t_id = s.first(t0, t1, seen), s.first(t0, t1, known)
        lat = None if t_face is None or t_id is None else t_id - t_face
        prof = next(((_seat(f, seat) or {}).get("profile") for f in reversed(s.frames(t0, t1)) if _seat(f, seat)), None)
        s.record("S1", f"identity {cam} < 3 s", lat is not None and lat < 3.0, f"{lat and round(lat, 2)} s, {prof}")
    answers: list[tuple[str, str, Callable[[Frame], Any]]] = [
        ("driver", "SOFER", lambda f: f["driver"]["head"]["answer"]),
        ("passenger", "PASAGER", lambda f: f["passenger"].get("answer")),
    ]
    for to, label, get in answers:
        await s.dialog(to)
        t0, t1, _ = await s.step(f"{label}: raspunde DA din cap (da din cap de 2-3 ori)", 7.0, "S1 dialog")
        got = [get(f) for f in s.frames(t0, t1) if get(f)]
        s.record("S1", f"head yes {to}", "yes" in got, f"answers {sorted(set(got))}")


async def s2(s: Session) -> None:
    clean, seen = 0, 0
    for k in range(10):
        t0, _, _ = await s.step(f"SOFER: priveste OGLINDA STANGA ~1 s ({k + 1}/10)", 2.0, "S2 oglinda")
        _, t1, _ = await s.step("SOFER: inapoi la drum", 2.0, "S2 oglinda")
        fr = s.frames(t0, t1)
        clean += all(f["driver"]["gaze"]["off_road_ms"] == 0 for f in fr)
        seen += any(f["driver"]["gaze"]["zone"] == "mirror_left" for f in fr)
    s.record("S2", "left mirror without off_road x10", clean == 10, f"{clean}/10 clean, mirror_left seen {seen}/10")
    t0, t1, _ = await s.step("SOFER: ACOPERA camera soferului cu palma", 6.0, "S2 camera acoperita")
    await s.step("SOFER: descopera camera", 3.0, "S2 camera acoperita")
    t_cover = s.first(t0, t1, lambda f: not f["driver"].get("face_conf"))
    t_mon = s.first(t0, t1, lambda f: f["driver"].get("monitoring_ok") is False)
    lat = None if t_cover is None or t_mon is None else t_mon - t_cover
    reason = next(
        (f["driver"].get("monitoring_reason") for f in s.frames(t0, t1) if f["driver"].get("monitoring_reason")), None
    )
    s.record(
        "S2",
        "covered -> monitoring_ok=false < 2 s",
        lat is not None and lat < 2.0,
        f"{lat and round(lat, 2)} s, {reason}",
    )


async def s3(s: Session) -> None:
    t0, t1, keys = await s.step("SOFER: duce TELEFONUL la ureche, SPATIU cand e la ureche", 8.0, "S3 telefon")
    t_key = keys[0] if keys else None
    t_det = s.first(t_key or t0, t1, lambda f: f["driver"]["phone"]["in_use"]) if t_key else None
    lat = None if t_key is None or t_det is None else max(0.0, t_det - t_key)
    src = next((f["driver"]["phone"].get("source") for f in s.frames(t0, t1) if f["driver"]["phone"]["in_use"]), None)
    s.record(
        "S3",
        "driver phone < 1 s",
        lat is not None and lat < 1.0,
        f"{lat and round(lat, 2)} s, source {src}, key {bool(t_key)}",
    )
    await s.step("SOFER: lasa telefonul jos, mainile pe volan", 3.0, "S3")
    await _gesture(s, "S3", "Thumb_Up", "DEGETUL MARE SUS (like)")


async def _gesture(s: Session, scene: str, gesture: str, text: str) -> None:
    for to, label in (("driver", "SOFER"), ("passenger", "PASAGER")):
        await s.dialog(to)
        t0, t1, _ = await s.step(f"{label}: {text}, tine 1 s", 7.0, f"{scene} gest")
        got = {f[to].get("gesture") for f in s.frames(t0, t1)} - {None}
        s.record(scene, f"{gesture} {to}", gesture in got, f"gestures {sorted(got)}")
        await s.step("mainile jos", 2.0, scene)


async def s4(s: Session) -> None:
    t0, t1, _ = await s.step("PASAGER: tine TELEFONUL si arata-l soferului; SOFER: priveste de 3 ori spre pasager",
                             16.0, "S4 pasager cu telefon")  # fmt: skip
    fr = s.frames(t0, t1)
    zones = [f["driver"]["gaze"]["zone"] for f in fr]
    glances = sum(1 for a, b in itertools.pairwise(zones) if b == "passenger" and a != "passenger")
    holding = sum(bool(f["passenger"].get("holding_phone")) for f in fr) / max(1, len(fr))
    drivers = sum(bool(f["driver"]["phone"]["in_use"]) for f in fr)
    s.record("S4", ">= 3 glances at the passenger", glances >= 3, f"{glances} glances")
    s.record("S4", "passenger.holding_phone", holding >= 0.3, f"{holding:.0%} of frames")
    s.record("S4", "phone NOT the driver's", drivers == 0, f"driver phone in_use frames {drivers}")


async def s5(s: Session) -> None:
    _, t_mid, _ = await s.step("SOFER: priveste pe rand prin TOATE zonele (oglinzi, bord, ecran, pasager)", 20.0, "S5")
    _, t1, _ = await s.step("SOFER: priveste FIX drumul", 30.0, "S5 privire fixa")
    ent = [f["driver"]["gaze"].get("entropy_60s") for f in s.frames(t_mid - 1.0, t1)]
    start = next((e for e in ent if e is not None), None)
    end = next((e for e in reversed(ent) if e is not None), None)
    s.record("S5", "gaze entropy falls (30 s fixed)", start is not None and end is not None and end < start,
             f"{start} -> {end}")  # fmt: skip


async def s6(s: Session) -> None:
    hits = 0
    for k in range(3):
        t0, t1, _ = await s.step(f"SOFER: CASCA larg, natural ({k + 1}/3)", 6.0, "S6 cascat")
        await s.step("pauza", 3.0, "S6")
        hits += any(f["driver"]["yawn"] for f in s.frames(t0, t1 + 3.0))
    s.record("S6", "yawns 3/3", hits == 3, f"{hits}/3")
    await _gesture(s, "S6", "Open_Palm", "PALMA DESCHISA spre camera")
    t0, t1, _ = await s.step("PASAGER: INCHIDE ochii si lasa capul usor, ca adormit", 16.0, "S6 pasager adormit")
    t_closed = s.first(t0, t1, lambda f: f["passenger"].get("eyes_closed_s", 0) > 0)
    t_sleep = s.first(t0, t1, lambda f: f["passenger"].get("awake") is False)
    lat = None if t_closed is None or t_sleep is None else t_sleep - t_closed
    s.record("S6", "passenger asleep < 12 s", lat is not None and lat < 12.0, f"{lat and round(lat, 1)} s")
    t0, t1, _ = await s.step("PASAGER: DESCHIDE ochii, priveste camera", 6.0, "S9 pasager treaz")
    awake = s.first(t0, t1, lambda f: f["passenger"].get("awake") is True and f["passenger"].get("present"))
    s.record("S9", "passenger awake again", awake is not None, f"{awake and round(awake - t0, 1)} s")


async def s8(s: Session) -> None:
    ok_n, details = 0, []
    for k in range(3):
        await s.step(f"SOFER: ochii deschisi, pregateste-te ({k + 1}/3)", 2.0, "S8 inchideri")
        t0, _, _ = await s.step("SOFER: INCHIDE OCHII ACUM", 2.0, "S8 inchideri")
        _, t1, _ = await s.step("SOFER: DESCHIDE ochii", 2.0, "S8 inchideri")
        closed = [f for f in s.frames(t0, t1) if f["driver"]["eyes"].get("state") == "CLOSED"]
        ms = [f["driver"]["eyes"]["closed_ms"] for f in closed]
        mono = all(b >= a for a, b in itertools.pairwise(ms))
        span = (closed[-1]["ts"] - closed[0]["ts"]) * 1000.0 + ms[0] if closed else 0.0
        good = bool(closed) and mono and abs(max(ms) - span) <= 100.0 and 1500 <= max(ms) <= 3000
        ok_n += good
        details.append(f"{max(ms) if ms else 0} ms{'' if mono else ' RESET'}")
    s.record("S8", "2 s closures, closed_ms continuous (+-100 ms)", ok_n == 3, ", ".join(details))
    hits = 0
    for k in range(10):
        t0, t1, _ = await s.step(f"SOFER: CLIPESTE ACUM ({k + 1}/10)", 2.5, "S8 clipit")
        counts = [f["driver"]["eyes"].get("blink_count", 0) for f in s.frames(t0 - 0.2, t0 + 1.4)]
        hits += bool(counts) and max(counts) > min(counts)
    s.record("S8", "blinks 9/10", hits >= 9, f"{hits}/10")
    bad = 0
    for what in ("MIJESTE ochii, ca in soare", "ZAMBESTE LARG"):
        for k in range(3):
            t0, t1, _ = await s.step(f"SOFER: {what} ({k + 1}/3)", 3.0, "S8 mijit / zambet")
            await s.step("relaxat", 2.0, "S8")
            bad += any(f["driver"]["eyes"].get("long_closure") for f in s.frames(t0, t1))
    s.record("S8", "squint / smile reported closed: 0", bad == 0, f"{bad}/6 windows with a closure")


async def s9(s: Session) -> None:
    hits = 0
    for k in range(5):
        t0, t1, _ = await s.step(
            f"SOFER: INCHIDE ochii si lasa capul sa CADA incet in fata ({k + 1}/5)", 5.0, "S9 cadere cap"
        )
        await s.step("SOFER: ridica capul, ochii deschisi", 3.0, "S9")
        hits += any(f["driver"]["head"]["nodding"] for f in s.frames(t0, t1 + 1.0))
    s.record("S9", "slow head drop with closed eyes 5/5", hits == 5, f"{hits}/5")


async def normal(s: Session) -> None:
    t0, t1, _ = await s.step("AMANDOI: condus normal 60 s: oglinzi, vorbiti, FARA telefon, FARA gesturi", 60.0, "N")
    checks: dict[str, Callable[[Frame], bool]] = {
        "driver phone": lambda f: f["driver"]["phone"]["in_use"],
        "driver gesture": lambda f: f["driver"].get("gesture") is not None,
        "driver answer": lambda f: f["driver"]["head"]["answer"] is not None,
        "driver posture": lambda f: _posture_any(f["driver"]),
        "driver closure": lambda f: f["driver"]["eyes"].get("long_closure"),
        "driver nod": lambda f: f["driver"]["head"]["nodding"],
        "passenger phone": lambda f: f["passenger"].get("holding_phone"),
        "passenger gesture": lambda f: f["passenger"].get("gesture") is not None,
        "passenger answer": lambda f: f["passenger"].get("answer") is not None,
        "passenger posture": lambda f: _posture_any(f["passenger"]),
    }
    fr = s.frames(t0, t1)
    events = {name: sum(1 for a, b in itertools.pairwise(fr) if fn(b) and not fn(a)) for name, fn in checks.items()}
    bad = {k: v for k, v in events.items() if v}
    s.record("N", "60 s normal driving: zero false events", not bad, f"{bad or 'none'}")


SCENES: dict[str, Callable[[Session], Any]] = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6, "S8": s8,
                                               "S9": s9, "N": normal}  # fmt: skip


async def run(only: list[str], port: int) -> Session:
    import websockets

    probe = Probe()
    cfg = yaml.safe_load((ROOT / "perception/config/perception.yaml").read_text(encoding="utf-8"))
    cfg["output"]["ws_url"] = f"ws://localhost:{port}/ws/perception"
    tmp = Path(tempfile.mkdtemp(prefix="scene_check_"))
    (tmp / "perception.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    session = Session(probe)
    async with websockets.serve(probe.handler, "localhost", port):
        proc = subprocess.Popen(
            [sys.executable, "-m", "perception.main", "--no-mjpeg", "--config", str(tmp / "perception.yaml"),
             "--log-level", "WARNING"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        try:
            await asyncio.wait_for(probe.connected.wait(), timeout=40)
            while not session.aborted and not all(
                (probe.frames[-1]["perf"]["cameras"].get(c) or {}).get("available") for c in ("driver", "passenger")
            ) if probe.frames else True:  # fmt: skip
                session._show(["pornesc camerele si modelele..."])
                await asyncio.sleep(0.2)
            await session.wait_space("Gata. Click pe fereastra si apasa SPATIU pentru start")
            t_start = time.time()
            for name in only:
                if session.aborted:
                    break
                await SCENES[name](session)
            fps = [f["perf"]["cameras"]["driver"]["process_fps"] for f in session.frames(t_start, time.time())
                   if f["perf"]["cameras"].get("driver", {}).get("available")]  # fmt: skip
            cap = [f["perf"]["cameras"]["driver"]["capture_fps"] for f in session.frames(t_start, time.time())
                   if f["perf"]["cameras"].get("driver", {}).get("available")]  # fmt: skip
            if fps:
                med = statistics.median(fps)
                detail = f"process {med:.1f} fps (min {min(fps):.1f}), capture {statistics.median(cap):.1f} fps"
                session.record("perf", "driver face >= 20 fps (both cameras)", med >= 20.0, detail)
        finally:
            cv2.destroyAllWindows()
            _kill_tree(proc.pid)
            shutil.rmtree(tmp, ignore_errors=True)
    return session


def write_report(session: Session, only: list[str]) -> Path:
    stamp = dt.date.today().isoformat()
    path = ROOT / "docs" / "eval" / f"scene-check-{stamp}.md"
    ok = sum(r[2] for r in session.results)
    lines = [
        f"# Scene check, live, both seats ({stamp})",
        "",
        f"- scenes run: {' '.join(only)}{' (ABORTED)' if session.aborted else ''}; "
        f"criteria passed {ok}/{len(session.results)}",
        "- driver: Logi C615 (1080p30 capture, 720p processing); passenger: LifeCam HD-6000 (720p30, 10 Hz)",
        "- judged on the PerceptionFrames P1 publishes (scripts/scene_check.py); nothing recorded",
        "",
        "| scene | criterion | result | detail |",
        "|---|---|---|---|",
        *[
            f"| {sc} | {crit} | {'PASS' if good else '**FAIL**'} | {detail} |"
            for sc, crit, good, detail in session.results
        ],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", choices=list(SCENES), default=None)
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--dump", type=Path, default=None, help="also write the received frames (JSONL, numbers only)")
    args = p.parse_args(argv)
    only = args.only or list(SCENES)
    session = asyncio.run(run(only, args.port))
    if args.dump is not None:  # diagnosis only: PerceptionFrame numbers, no image
        args.dump.write_text("\n".join(json.dumps(f) for f in session.probe.frames), encoding="utf-8")
        steps = "\n".join(json.dumps(s) for s in session.steps)
        args.dump.with_suffix(".steps.jsonl").write_text(steps, encoding="utf-8")
    path = write_report(session, only)
    print(f"report: {path}")
    return 0 if session.results and all(r[2] for r in session.results) and not session.aborted else 1


if __name__ == "__main__":
    raise SystemExit(main())
