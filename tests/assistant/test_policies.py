"""Tests for assistant.policies (veto P0-P2, muted, conversation, 1 proactive / 30 s)."""

from assistant.contract import Event
from assistant.policies import Policies
from p3_helpers import load_scene, make_state

NOW = 1763672400.0


def test_safety_veto_at_p1():
    event, state = load_scene("scene8_p1_alarm")
    assert Policies().check(event, state, NOW).reason == "safety_veto"


def test_muted_blocks_proactive_but_not_contact_reply():
    policies = Policies()
    event, state = load_scene("scene6_muted_proactive")
    assert policies.check(event, state, NOW).reason == "muted"
    event, state = load_scene("scene6_contact_reply")
    assert policies.check(event, state, NOW).allowed


def test_mute_expires():
    _, state = load_scene("scene6_muted_proactive")
    later = state.assistant.muted_until + 1
    assert Policies().check(Event(type="disengagement_high"), state, later).allowed


def test_conversation_blocks_comfort_not_cause():
    event, state = load_scene("scene4_conversation")
    assert Policies().check(event, state, NOW).reason == "conversation"
    assert Policies().check(Event(type="cause_detected"), state, NOW).allowed


def test_one_proactive_intervention_per_30s():
    policies = Policies()
    state = make_state()
    event = Event(type="disengagement_high")
    assert policies.check(event, state, NOW).allowed
    policies.record(event, NOW)
    assert policies.check(event, state, NOW + 10).reason == "rate_limited"
    assert policies.check(Event(type="driver_speech"), state, NOW + 10).allowed  # driver-initiated
    assert policies.check(event, state, NOW + 31).allowed
