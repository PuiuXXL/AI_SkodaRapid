"""Tests for assistant.fallback: every event type gets a valid fixed answer (plan C9)."""

import pytest

from assistant.actions import validate_actions
from assistant.contract import Event
from assistant.fallback import BUILDERS, build_fallback
from assistant.textutil import word_count
from p3_helpers import load_scene, make_state, scene_names


@pytest.mark.parametrize("name", scene_names())
def test_fallback_actions_are_valid_and_short(name):
    event, state = load_scene(name)
    raw = build_fallback(event, state)
    result = validate_actions(raw, state, event, source="RULE")
    # Scenes where the LLM is vetoed (P1) may legitimately produce rejected speech:
    if state.safety.level not in ("P0", "P1", "P2"):
        assert not result.rejected, result.rejected
    for action in result.accepted:
        assert action.source == "RULE"
        spoken = action.text or action.question or ""
        if action.to in (None, "driver"):
            assert word_count(spoken) <= 15


def test_every_builder_handles_the_example_state():
    state = make_state(safety={"level": "P3"})
    for event_type in BUILDERS:
        build_fallback(Event(type=event_type, data={"msg_id": "m17", "text": "ok", "explanation": "x"}), state)


def test_passenger_phone_delegates_to_maria():
    event, state = load_scene("scene4_passenger_phone")
    raw = build_fallback(event, state)
    assert raw[0]["text"].startswith("Maria")
    assert raw[1] == {"type": "delegate", "to_person": "Maria", "task": "tell_story"}
    assert "Andrei" in raw[2]["text"]


def test_refusal_uses_the_pregenerated_clip():
    event, state = load_scene("scene6_refusal")
    raw = build_fallback(event, state)
    assert raw[0]["clip_id"] == "refusal_ack"
    assert raw[1] == {"type": "stay_silent", "reason": "driver_refused"}


def test_stop_with_reminder_task():
    event, state = load_scene("scene6_stop")
    question = build_fallback(event, state)[0]["question"]
    assert question == "Oprim la OMV peste 12 km? Iei și lichidul de parbriz."
