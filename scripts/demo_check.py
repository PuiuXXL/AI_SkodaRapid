"""Guided live GO / NO-GO for every perception signal of the demo scenario (plan §4.A AS / AP), both seats.

    python scripts/demo_check.py                       # ~10 min: calibration first, then every signal (baseline)
    python scripts/demo_check.py --skip-calibration    # keep the saved calibration (profile --profile, default andrei)

Starts its own perception.main + WS endpoint (stop the platform's perception first: the cameras are exclusive), runs the
driver's gaze calibration (CAL, prompts on screen: OWL = turn the whole head, LIZARD = eyes only), checks that looking
at the road reads "road" (G), then the scene steps of scripts/scene_check.py (S1-S9, AS13 when demo.rear_seat is on, N)
plus speaking on both seats and the passenger camera covered. Every criterion maps to its AS / AP item: GO only if all
of its criteria pass; items under a demo switch that is off are reported as "off (demo.x)".
Report: docs/eval/demo-check-<date>.md. The frames (numbers only, no image) go to data/features/<stamp>_demo-check/ for
the diagnosis of every NO-GO. Nothing visual is recorded.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from scripts import scene_check as sc  # noqa: E402

#: AS / AP item -> (title, criteria as (scene, criterion prefix), demo switch or None)
SIGNALS: dict[str, tuple[str, list[tuple[str, str]], str | None]] = {
    "AS2": ("eyes: closures, blinks, squint / smile", [("S8", "2 s closures"), ("S8", "blinks"), ("S8", "squint")],
            None),
    "AS3": ("yawn", [("S6", "yawns")], None),
    "AS4": ("fatigue nod", [("S9", "slow head drop")], "nodding_triggers"),
    "R-FL3": (
        "faces big enough: before and during the run",
        [("F", "both faces"), ("F", "driver face"), ("F", "passenger face")],
        None,
    ),
    "AS5": (
        "gaze zones (calibrated)",
        [("CAL", "calibration"), ("G", "zone road"), ("S2", "left mirror"), ("S4", ">= 3 glances")],
        None,
    ),
    "AS6": ("VATS + entropy", [("S5", "gaze entropy")], None),
    "AS7": ("driver phone", [("S3", "driver phone"), ("S4", "phone NOT")], None),
    "AS8": ("head yes / no", [("S1", "head yes driver")], "head_answer"),
    "AS9": ("gestures driver", [("S3", "Thumb_Up driver"), ("S6", "Open_Palm driver"), ("S7", "Thumb_Up driver")],
            None),
    "AS10": ("identity driver", [("S1", "identity sofer")], None),
    "AS11": ("driver speaking", [("SP", "driver speaking")], None),
    "AS12": ("driver camera covered", [("S2", "covered")], None),
    "AS13": ("rear-seat glance", [("AS13", "rear_seat")], "rear_seat"),
    "AP1": ("passenger present + identity", [("S1", "identity pasager")], None),
    "AP2": ("passenger asleep / awake", [("S6", "passenger asleep"), ("S9", "passenger awake")], None),
    "AP3": ("passenger speaking", [("SP", "passenger speaking")], None),
    "AP4": ("passenger phone", [("S4", "passenger.holding_phone")], None),
    "AP5": ("passenger camera covered", [("PC", "passenger covered")], None),
    "AP6": (
        "passenger gestures / answer",
        [("S1", "head yes passenger"), ("S3", "Thumb_Up passenger"), ("S6", "Open_Palm passenger")],
        None,
    ),
    "J1": ("driver face >= 20 fps, both cameras", [("perf", "driver face")], None),
    "N": ("60 s normal driving, zero false events", [("N", "60 s normal")], None),
}


async def speaking(s: sc.Session) -> None:
    for seat, label in (("driver", "SOFER"), ("passenger", "PASAGER")):
        t0, t1, _ = await s.step(f"{label}: VORBESTE continuu 6 s (numara, povesteste)", 6.0, "SP vorbit")
        fr = s.frames(t0, t1)
        onset = next((f["ts"] - t0 for f in fr if f[seat].get("speaking")), None)
        after = [f for f in fr if onset is not None and f["ts"] - t0 >= onset]
        held = sum(bool(f[seat].get("speaking")) for f in after) / max(1, len(after))
        # onset (includes the reaction time to the prompt) and how well it is held while talking (B9 hold 800 ms)
        ok = onset is not None and onset <= 2.5 and held >= 0.8
        s.record("SP", f"{seat} speaking", ok, f"onset {onset and round(onset, 1)} s after the prompt, held {held:.0%}")
        await s.step("liniste", 2.0, "SP")


async def passenger_covered(s: sc.Session) -> None:
    t0, t1, _ = await s.step("PASAGER: ACOPERA camera pasagerului cu palma", 5.0, "PC camera pasager")
    await s.step("PASAGER: descopera camera", 3.0, "PC")
    t_off = s.first(t0, t1, lambda f: f["passenger"].get("monitoring_ok") is False)
    lat = None if t_off is None else t_off - t0
    reason = next((f["passenger"].get("monitoring_reason") for f in s.frames(t0, t1)
                   if f["passenger"].get("monitoring_reason")), None)  # fmt: skip
    # measured from the prompt (includes the reaction time): < 3 s here = < 2 s after the hand is on the lens
    detail = f"{lat and round(lat, 1)} s after the prompt, {reason}"
    s.record("PC", "passenger covered -> monitoring_ok=false", lat is not None and lat < 3.0, detail)


def _dump(session: sc.Session) -> Path:
    """The run's PerceptionFrames + prompts + steps as JSONL under data/features/ (numbers only, no pixels)."""
    import json

    out = ROOT / "data" / "features" / f"{dt.datetime.now():%Y%m%d-%H%M%S}_demo-check"
    out.mkdir(parents=True, exist_ok=True)
    (out / "frames.jsonl").write_text("\n".join(json.dumps(f) for f in session.probe.frames), encoding="utf-8")
    (out / "steps.jsonl").write_text("\n".join(json.dumps(s) for s in session.steps), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(session.results, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


ORDER = ["F", "CAL", "G", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "AS13", "SP", "PC", "N"]


def verdicts(results: list[tuple[str, str, bool, str]], demo: dict[str, bool]) -> list[tuple[str, str, str, str]]:
    """(item, title, GO / NO-GO / off / not run, details) per signal."""
    out = []
    for item, (title, crits, switch) in SIGNALS.items():
        if switch is not None and not demo.get(switch, True):
            out.append((item, title, f"off (demo.{switch})", "frame keeps the defaults"))
            continue
        found = [r for scene, prefix in crits for r in results if r[0] == scene and r[1].startswith(prefix)]
        if not found:
            out.append((item, title, "not run", ""))
            continue
        go = len(found) == len(crits) and all(r[2] for r in found)
        out.append((item, title, "GO" if go else "NO-GO", "; ".join(f"{r[1]}: {r[3]}" for r in found)))
    return out


def write_report(rows: list[tuple[str, str, str, str]], aborted: bool) -> Path:
    stamp = dt.date.today().isoformat()
    path = ROOT / "docs" / "eval" / f"demo-check-{stamp}.md"
    go = sum(r[2] == "GO" for r in rows)
    lines = [
        f"# Demo check, live, both seats ({stamp})",
        "",
        f"- GO {go}/{len(rows)}{' (ABORTED)' if aborted else ''}; scripts/demo_check.py, judged on the published "
        "PerceptionFrames; nothing recorded",
        "",
        "| item | signal | verdict | details |",
        "|---|---|---|---|",
        *[f"| {i} | {t} | {'**' + v + '**' if v == 'NO-GO' else v} | {d} |" for i, t, v, d in rows],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8767)
    p.add_argument("--profile", default="andrei", help="the driver's profile: gaze calibration at the start (CAL)")
    p.add_argument("--skip-calibration", action="store_true", help="keep the saved calibration (no CAL step)")
    args = p.parse_args(argv)
    sc.SCENES.update({"SP": speaking, "PC": passenger_covered})
    demo = yaml.safe_load((ROOT / "perception/config/perception.yaml").read_text(encoding="utf-8")).get("demo", {})
    skip = {"CAL"} if args.skip_calibration else set()
    if not demo.get("rear_seat", True):
        skip.add("AS13")  # switched off: reported as "off (demo.rear_seat)", no need to run the step
    order = [s for s in ORDER if s not in skip]
    session = asyncio.run(sc.run(order, args.port, args.profile))
    dump = _dump(session)
    rows = verdicts(session.results, demo)
    for item, title, verdict, _ in rows:
        print(f"{verdict:16s} {item:5s} {title}")
    print(f"report: {write_report(rows, session.aborted)}")
    print(f"frames (numbers only, for the diagnosis of every NO-GO): {dump}")
    return 0 if all(r[2] in ("GO",) or r[2].startswith("off") for r in rows) and not session.aborted else 1


if __name__ == "__main__":
    raise SystemExit(main())
