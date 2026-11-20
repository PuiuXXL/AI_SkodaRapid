"""Tests for assistant.summary (about ten lines) and assistant.music (cabin-aware choices)."""

from assistant import music
from assistant.summary import summarize
from p3_helpers import load_scene, make_state


def test_summary_is_short_and_has_the_essentials():
    event, state = load_scene("scene4_passenger_phone")
    text = summarize(state, event)
    lines = text.splitlines()
    assert len(lines) <= 12
    assert "passenger_showing_phone" in text
    assert "holding phone" in text
    assert "m17 whatsapp from Mihai" in text
    assert "omv_km42" in text


def test_disengagement_candidates_are_energetic():
    found = music.candidates(make_state())
    assert found and all(t.energy >= 4 for t in found)


def test_child_on_board_means_kid_safe_only():
    state = make_state(occupants=[
        {"id": 1, "seat": "driver", "profile": "andrei"},
        {"id": 3, "seat": "rear", "profile": "ioana", "role": "child"},
    ])
    found = music.candidates(state)
    assert found and all(t.kid_safe for t in found)


def test_passenger_asleep_lowers_volume():
    assert music.volume_for(make_state(passenger={"awake": False})) < music.volume_for(make_state())
