"""Tests for scripts/core_command.py: every command line becomes a valid ``command`` message."""

from __future__ import annotations

import pytest

from scripts import core_command as cc
from shared import contracts as c


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["scene", "8"], {"cmd": "scene", "value": 8}),
        (["speed", "90"], {"cmd": "speed", "value": 90.0}),
        (["time", "20"], {"cmd": "time_scale", "value": 20.0}),
        (["llm", "off"], {"cmd": "llm", "on": False}),
        (["debug", "on"], {"cmd": "debug", "on": True}),
        (["stop"], {"cmd": "stop_at_next_poi"}),
        (["reset"], {"cmd": "reset"}),
        (["end"], {"cmd": "end_trip"}),
        (["message", "Mihai", "Unde", "ești?"],
         {"cmd": "fake_message", "value": {"from": "Mihai", "app": "whatsapp", "text": "Unde ești?"}}),
        (["rear", "ioana", "child"], {"cmd": "declare_occupant", "value": {"profile": "ioana", "role": "child"}}),
    ],
)
def test_build_command(words: list[str], expected: dict[str, object]) -> None:
    message = cc.build_command(words)
    assert message == {"type": "command", **expected}
    assert isinstance(c.parse_browser_message(message), c.UiCommand)


@pytest.mark.parametrize("words", [["fly"], ["scene"], ["llm", "maybe"], []])
def test_bad_command_line(words: list[str]) -> None:
    with pytest.raises(SystemExit):
        cc.build_command(words)


def test_watch_lines() -> None:
    last: dict[str, object] = {}
    state = {"type": "state", "state": c.to_wire(c.State())}
    assert cc.describe(state, last) is not None
    assert cc.describe(state, last) is None  # nothing changed: no line
    alarm = {"type": "alarm", "id": "a1", "clip_url": "/sounds/clips/alarm_andrei.mp3", "level": "P1"}
    assert "alarm_andrei" in (cc.describe(alarm, last) or "")
    event = {"type": "event", "event": c.to_wire(c.Event(type="visual_cue", explanation="Telefon în mână 1,0 s"))}
    assert "visual_cue: Telefon" in (cc.describe(event, last) or "")
