"""Core (P2) side of the perception boundary: everything P1 sends is valid for ``shared.contracts`` and taken by core.

Needs only ``shared`` and ``core`` (no perception runtime), so it also runs in the core job: a change of the contract
or of core's parsing that would reject P1's messages fails here, before the demo.
"""

from __future__ import annotations

from typing import Any

import pytest

from shared import contracts as c
from tests.contract.conftest import FRAME_FIXTURES, load_fixture

NOW = 1_795_000_000.0


def _lost_or_changed(src: Any, out: Any, path: str = "") -> list[str]:
    """Paths of the source JSON that are missing or different after parsing and serializing again."""
    problems: list[str] = []
    if isinstance(src, dict):
        if not isinstance(out, dict):
            return [f"changed {path}: object -> {type(out).__name__}"]
        for key, value in src.items():
            if key not in out:
                problems.append(f"lost {path}.{key}")
            else:
                problems += _lost_or_changed(value, out[key], f"{path}.{key}")
    elif isinstance(src, list):
        if not isinstance(out, list) or len(src) != len(out):
            return [f"length {path}"]
        for i, (a, b) in enumerate(zip(src, out, strict=True)):
            problems += _lost_or_changed(a, b, f"{path}[{i}]")
    elif src != out and not (isinstance(src, int | float) and isinstance(out, int | float) and float(src) == out):
        problems.append(f"changed {path}: {src!r} -> {out!r}")
    return problems


@pytest.mark.parametrize("name", FRAME_FIXTURES)
def test_p1_frame_is_a_valid_perception_frame_and_round_trips(name: str) -> None:
    raw = load_fixture(name)
    message = c.parse_perception_message(raw)
    assert isinstance(message, c.PerceptionFrame)
    assert _lost_or_changed(raw, c.to_wire(message)) == []


def test_every_other_p1_message_parses_by_its_type() -> None:
    kinds = {"ack": c.PerceptionAck, "calibration_prompt": c.CalibrationPrompt}
    messages = load_fixture("p1_messages")
    assert messages, "p1_messages.json is empty"
    for raw in messages:
        parsed = c.parse_perception_message(raw)
        assert isinstance(parsed, kinds[raw["type"]]), raw
        assert _lost_or_changed(raw, c.to_wire(parsed)) == []


def test_p1_acks_every_command_core_can_send() -> None:
    """One immediate ack per command in core_commands.json, never "error" / "not_implemented" for a valid command."""
    acks = [m for m in load_fixture("p1_messages") if m["type"] == "ack"]
    commands = load_fixture("core_commands")
    first = acks[: len(commands)]
    assert [a["cmd"] for a in first] == [cmd["cmd"] for cmd in commands]
    assert {a["status"] for a in first} <= {"ok", "started", "queued"}, first


def test_core_engine_takes_everything_p1_sends() -> None:
    from core.engine import Engine
    from core.hub import Hub
    from core.simulation import FakeSimulator

    engine = Engine(Hub(), FakeSimulator())
    for message in load_fixture("p1_messages"):
        engine.on_perception_message(message, NOW)
    for name in ("p1_frame_cameras_down", "p1_frame_strict", "p1_frame_full"):
        engine.on_perception_message(load_fixture(name), NOW)
    assert engine.invalid_messages == 0
    assert engine.frames_received == 3
    frame = engine.frame
    assert frame is not None
    # the fields core's rules read most (core/safety, core/scoring) arrive with P1's values
    assert frame.driver.head.answer == "yes"
    assert frame.passenger.present is True and frame.passenger.answer == "no"
    assert {o.seat for o in frame.occupants} == {"driver", "front_right"}
    assert {o.profile for o in frame.occupants} == {"andrei", "maria"}
    assert frame.driver.gesture == "Thumb_Up"
    assert frame.driver.phone.in_use is True


def test_core_commands_fixture_matches_the_contract() -> None:
    """core_commands.json is what P2's models serialize today: if this fails, P2 changed a command. Regenerate the
    fixtures (python tests/contract/make_fixtures.py) so the P1 side checks it handles the new form."""
    from tests.contract.make_fixtures import core_commands

    assert core_commands() == load_fixture("core_commands")
