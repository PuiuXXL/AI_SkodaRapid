"""Guided live GO / NO-GO for every perception signal of the demo scenario (plan §4.A AS / AP), both seats.

    python scripts/demo_check.py              # ~8 min: driver at the C615, a colleague at the LifeCam
    python scripts/demo_check.py --port 8767

Runs the scene steps of scripts/scene_check.py (S1-S9, AS13, N) plus two short steps (speaking on both seats, the
passenger camera covered) against its own perception.main + WS endpoint, then maps every criterion to its AS / AP item:
an item is GO only if all of its criteria pass. Items under a demo switch that is off are reported as "off (demo.x)".
Report: docs/eval/demo-check-<date>.md. Nothing is recorded (no image, no video).
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
    "AS5": ("gaze zones", [("S2", "left mirror"), ("S4", ">= 3 glances")], None),
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
        t0, t1, _ = await s.step(f"{label}: VORBESTE continuu 5 s (numara, povesteste)", 5.0, "SP vorbit")
        fr = s.frames(t0 + 1.0, t1)
        share = sum(bool(f[seat].get("speaking")) for f in fr) / max(1, len(fr))
        s.record("SP", f"{seat} speaking", share >= 0.6, f"{share:.0%} of frames after 1 s")
        await s.step("liniste", 2.0, "SP")


async def passenger_covered(s: sc.Session) -> None:
    t0, t1, _ = await s.step("PASAGER: ACOPERA camera pasagerului cu palma", 5.0, "PC camera pasager")
    await s.step("PASAGER: descopera camera", 3.0, "PC")
    t_off = s.first(t0, t1, lambda f: f["passenger"].get("monitoring_ok") is False)
    lat = None if t_off is None else t_off - t0
    reason = next((f["passenger"].get("monitoring_reason") for f in s.frames(t0, t1)
                   if f["passenger"].get("monitoring_reason")), None)  # fmt: skip
    # measured from the prompt (includes the reaction time): < 3 s here = < 2 s after the hand is on the lens
    s.record("PC", "passenger covered -> monitoring_ok=false", lat is not None and lat < 3.0, f"{lat and round(lat, 1)} s"
             f" after the prompt, {reason}")  # fmt: skip


ORDER = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "AS13", "SP", "PC", "N"]


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
    args = p.parse_args(argv)
    sc.SCENES.update({"SP": speaking, "PC": passenger_covered})
    session = asyncio.run(sc.run(ORDER, args.port))
    demo = yaml.safe_load((ROOT / "perception/config/perception.yaml").read_text(encoding="utf-8")).get("demo", {})
    rows = verdicts(session.results, demo)
    for item, title, verdict, _ in rows:
        print(f"{verdict:16s} {item:5s} {title}")
    print(f"report: {write_report(rows, session.aborted)}")
    return 0 if all(r[2] in ("GO",) or r[2].startswith("off") for r in rows) and not session.aborted else 1


if __name__ == "__main__":
    raise SystemExit(main())
