"""Tests for assistant.actions (plan section 6: allowed actions, levels, limits, confirmation)."""

from assistant.actions import validate_actions
from p3_helpers import make_state


def _one(raw, state=None, event=None):
    """Validate a single raw action; return (accepted, rejected_reasons)."""
    result = validate_actions([raw], state or make_state(), event)
    return result.accepted, [r.reason for r in result.rejected]


def test_unknown_action_type_is_rejected():
    accepted, reasons = _one({"type": "open_window"})
    assert not accepted and reasons[0].startswith("schema:")


def test_speak_to_driver_over_15_words_is_rejected():
    text = "unu doi trei patru cinci sase sapte opt noua zece unsprezece doisprezece treisprezece paisprezece cincisprezece saisprezece"
    accepted, reasons = _one({"type": "speak", "to": "driver", "text": text})
    assert reasons == ["too_many_words"]


def test_short_speak_is_accepted_and_marked_llm():
    accepted, _ = _one({"type": "speak", "to": "driver", "text": "Andrei, ochii pe drum."})
    assert accepted[0].source == "LLM" and accepted[0].needs_confirmation is False


def test_media_not_allowed_at_p3():
    state = make_state(safety={"level": "P3"})
    _, reasons = _one({"type": "play_media", "track_id": "t14"}, state)
    assert reasons == ["not_allowed_at_P3"]


def test_delegate_only_at_p3():
    _, reasons = _one({"type": "delegate", "to_person": "Maria", "task": "tell_story"})  # example is P4
    assert reasons == ["not_allowed_at_P4"]
    accepted, _ = _one({"type": "delegate", "to_person": "Maria", "task": "tell_story"}, make_state(safety={"level": "P3"}))
    assert accepted


def test_delegate_to_absent_person_is_rejected():
    state = make_state(safety={"level": "P3"})
    _, reasons = _one({"type": "delegate", "to_person": "Ioana", "task": "x"}, state)
    assert reasons == ["person_not_in_car"]


def test_stay_silent_allowed_even_at_p1():
    accepted, _ = _one({"type": "stay_silent", "reason": "x"}, make_state(safety={"level": "P1"}))
    assert accepted


def test_speak_rejected_at_p1():
    _, reasons = _one({"type": "speak", "to": "driver", "text": "Salut"}, make_state(safety={"level": "P1"}))
    assert reasons == ["not_allowed_at_P1"]


def test_reply_needs_existing_replyable_message_and_confirmation():
    accepted, _ = _one({"type": "reply_message", "msg_id": "m17", "text": "Ajung la 18:40."})
    assert accepted[0].needs_confirmation is True
    _, reasons = _one({"type": "reply_message", "msg_id": "m99", "text": "x"})
    assert reasons == ["unknown_message"]


def test_read_message_needs_confirmation_only_with_passengers():
    accepted, _ = _one({"type": "read_message", "msg_id": "m17"})
    assert accepted[0].needs_confirmation is True  # Maria is present
    alone = make_state(passenger={"present": False})
    accepted, _ = _one({"type": "read_message", "msg_id": "m17"}, alone)
    assert accepted[0].needs_confirmation is False


def test_reminder_category_must_exist():
    ok = {"type": "create_reminder", "task": "lichid", "trigger": {"type": "stop_at_category", "category": "fuel"}}
    bad = {"type": "create_reminder", "task": "lichid", "trigger": {"type": "stop_at_category", "category": "spaceport"}}
    assert _one(ok)[0][0].needs_confirmation is True
    assert _one(bad)[1] == ["unknown_category"]


def test_suggest_stop_only_poi_proposed_by_rule():
    assert _one({"type": "suggest_stop", "poi_id": "omv_km42"})[0]  # = state.trip.next_poi
    assert _one({"type": "suggest_stop", "poi_id": "lukoil_km80"})[1] == ["poi_not_proposed_by_rule"]


def test_suggest_media_must_be_a_current_candidate():
    accepted, _ = _one({"type": "suggest_media", "track_id": "t16", "reason": "disengagement"})  # electronic, energy 5
    assert accepted and accepted[0].needs_confirmation
    _, reasons = _one({"type": "suggest_media", "track_id": "t01", "reason": "disengagement"})  # lofi, energy 1
    assert reasons == ["track_not_a_candidate"]


def test_set_preference_limits():
    assert _one({"type": "set_preference", "key": "volume", "value": "0.5"})[0]
    assert _one({"type": "set_preference", "key": "volume", "value": "3"})[1] == ["preference_out_of_range"]
    assert _one({"type": "set_preference", "key": "brakes", "value": "off"})[1] == ["unknown_preference"]


def test_max_three_actions():
    raw = [{"type": "speak", "to": "driver", "text": f"Fraza {i}."} for i in range(5)]
    result = validate_actions(raw, make_state())
    assert len(result.accepted) == 3
    assert [r.reason for r in result.rejected] == ["over_max_actions"] * 2
    assert result.accepted_indexes == [0, 1, 2]
