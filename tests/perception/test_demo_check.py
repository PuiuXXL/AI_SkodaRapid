"""scripts/demo_check.py: criteria -> AS / AP verdicts (no camera)."""

from __future__ import annotations

from scripts.demo_check import ORDER, SIGNALS, verdicts
from scripts.scene_check import SCENES


def test_every_signal_criterion_comes_from_a_scene_that_runs() -> None:
    scenes = set(SCENES) | {"SP", "PC", "perf"}
    assert {scene for _, crits, _ in SIGNALS.values() for scene, _ in crits} <= scenes
    assert set(ORDER) <= scenes


def test_verdicts_go_no_go_off_and_not_run() -> None:
    results = [
        ("S8", "2 s closures, closed_ms continuous (+-100 ms)", True, "3/3"),
        ("S8", "blinks 9/10", True, "10/10"),
        ("S8", "squint / smile reported closed: 0", False, "1/6"),
        ("S6", "yawns 3/3", True, "3/3"),
    ]
    rows = {r[0]: r[2] for r in verdicts(results, {"rear_seat": False})}
    assert rows["AS2"] == "NO-GO" and rows["AS3"] == "GO"
    assert rows["AS13"] == "off (demo.rear_seat)" and rows["AP4"] == "not run"
