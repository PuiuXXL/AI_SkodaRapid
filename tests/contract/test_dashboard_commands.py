"""Dashboard (P4) -> core (P2) on ``/ws/ui``: what the dashboard's buttons send in Live mode.

``fixtures/dashboard_ui_messages.json`` is shared by both sides: the dashboard's own test
(dashboard/tests/dashboard.test.tsx) asserts that ``liveMessage(name, args, state)`` produces exactly each
``message``; here each message must be valid for P2's contract (``parse_browser_message``), use a command core knows
(``UI_COMMANDS``) and be taken by core's engine. A renamed command on either side fails one of the two tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from shared import contracts as c
from tests.contract.conftest import load_fixture

CASES: list[dict[str, Any]] = load_fixture("dashboard_ui_messages")
NOW = 1_795_000_000.0


@pytest.mark.parametrize("case", CASES, ids=[f"{k}-{case['name']}" for k, case in enumerate(CASES)])
def test_dashboard_message_is_valid_for_the_contract(case: dict[str, Any]) -> None:
    message = c.parse_browser_message({**case["message"], "ts": NOW})
    if isinstance(message, c.UiCommand):
        assert message.cmd in c.UI_COMMANDS, f"{message.cmd} is not a command core knows"
    else:
        assert isinstance(message, c.UiSpeech) and message.final and message.addressed and message.text


def test_every_core_command_has_a_dashboard_control() -> None:
    """Each command in ``UI_COMMANDS`` is reachable from a dashboard button (the fixture covers all of them)."""
    sent = {case["message"]["cmd"] for case in CASES if case["message"]["type"] == "command"}
    assert sent == set(c.UI_COMMANDS)


def test_core_engine_takes_every_dashboard_message() -> None:
    from core.engine import Engine
    from core.hub import Hub
    from core.simulation import FakeSimulator

    engine = Engine(Hub(), FakeSimulator())
    for case in CASES:
        engine.on_browser_message({**case["message"], "ts": NOW}, NOW)
    assert engine.invalid_messages == 0
    assert engine.state.safety.llm_enabled is True  # the fixture's last "llm" command switches it back on
    assert [o.role for o in engine.declared] == []  # the child declared by set_child was removed again (id 3)


def test_the_stop_music_button_uses_words_the_assistant_stops_playback_on() -> None:
    """There is no "stop media" command in the contract: the button sends speech that P3 treats as a stop request."""
    fallback = pytest.importorskip("assistant.fallback")
    text = next(case["message"]["text"] for case in CASES if case["name"] == "stop_media")
    state = c.State()
    state.media.playing = True
    assert fallback.stop_media_request(text, state)
