"""Tests for assistant.preferences (talkativeness, follow_up, answer_length) and where they act.

Value order: assistant.yaml defaults -> profiles/<driver>/profile.json -> a confirmed
``set_preference`` by voice (this trip only). The ``_isolated_profiles`` fixture from
conftest.py gives an empty temporary ``profiles/`` folder.
"""

import json
import os

import pytest

from assistant import preferences
from assistant.actions import validate_actions
from assistant.answers import InputEvent
from assistant.client import AssistantClient, system_prompt
from assistant.contract import Action, Event
from assistant.dialog import DialogManager
from assistant.policies import Policies
from assistant.summary import summarize
from p3_helpers import FakeProvider, load_scene, make_state

NOW = 1763672400.0


def write_profile(profiles_dir, prefs, profile="andrei"):
    """Write ``profiles/<profile>/profile.json`` the way the dashboard does (only the fields used here)."""
    folder = profiles_dir / profile
    folder.mkdir(exist_ok=True)
    (folder / "profile.json").write_text(json.dumps({"name": "Andrei", "preferences": prefs}), encoding="utf-8")


def set_pref(key, value):
    """A ``set_preference`` action as it leaves the dialog manager."""
    return Action(type="set_preference", key=key, value=value)


# ----------------------------------------------------------------- where values come from


def test_defaults_without_profile():
    assert preferences.effective(make_state()) == {
        "talkativeness": "normal", "follow_up": "always", "answer_length": "normal"}


def test_profile_overrides_defaults(_isolated_profiles):
    write_profile(_isolated_profiles, {"talkativeness": "low", "answer_length": "short", "volume": 0.4})
    prefs = preferences.effective(make_state())
    assert prefs["talkativeness"] == "low" and prefs["answer_length"] == "short" and prefs["follow_up"] == "always"


def test_invalid_profile_values_are_ignored(_isolated_profiles):
    write_profile(_isolated_profiles, {"talkativeness": "chatty", "follow_up": 3})
    assert preferences.effective(make_state())["talkativeness"] == "normal"
    assert preferences.effective(make_state())["follow_up"] == "always"


def test_broken_profile_file_falls_back_to_defaults(_isolated_profiles):
    (_isolated_profiles / "andrei").mkdir()
    (_isolated_profiles / "andrei" / "profile.json").write_text("{not json", encoding="utf-8")
    assert preferences.effective(make_state())["answer_length"] == "normal"


def test_profile_change_is_seen_without_restart(_isolated_profiles):
    write_profile(_isolated_profiles, {"follow_up": "always"})
    state = make_state()
    assert preferences.follow_up_enabled(state)
    path = _isolated_profiles / "andrei" / "profile.json"
    write_profile(_isolated_profiles, {"follow_up": "never"})
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 5))  # make sure the mtime changes on fast file systems
    assert not preferences.follow_up_enabled(state)


def test_voice_change_wins_over_profile_and_reset_forgets_it(_isolated_profiles):
    write_profile(_isolated_profiles, {"answer_length": "normal"})
    state = make_state()
    assert preferences.store.apply(set_pref("answer_length", "short"), state)
    assert preferences.effective(state)["answer_length"] == "short"
    preferences.store.reset()
    assert preferences.effective(state)["answer_length"] == "normal"


def test_voice_change_is_per_driver():
    andrei = make_state()
    other = make_state(occupants=[{"id": 1, "seat": "driver", "profile": "mihai"}])
    preferences.store.apply(set_pref("talkativeness", "low"), andrei)
    assert preferences.effective(andrei)["talkativeness"] == "low"
    assert preferences.effective(other)["talkativeness"] == "normal"


@pytest.mark.parametrize("key,value", [("volume", 0.3), ("talkativeness", "loud"), ("music_genre", "rock")])
def test_apply_ignores_keys_and_values_it_does_not_own(key, value):
    assert not preferences.store.apply(set_pref(key, value), make_state())


# ----------------------------------------------------------------- talkativeness -> policies


def test_low_talkativeness_spaces_comfort_suggestions():
    state = make_state()
    preferences.store.apply(set_pref("talkativeness", "low"), state)
    policies = Policies()
    event = Event(type="disengagement_high")
    policies.record(event, NOW)
    assert policies.check(event, state, NOW + 60).reason == "rate_limited"  # low = 120 s
    assert policies.check(event, state, NOW + 121).allowed


def test_high_talkativeness_allows_comfort_sooner():
    state = make_state()
    preferences.store.apply(set_pref("talkativeness", "high"), state)
    policies = Policies()
    event = Event(type="disengagement_high")
    policies.record(event, NOW)
    assert policies.check(event, state, NOW + 16).allowed  # high = 15 s (normal would be 30 s)


def test_talkativeness_never_delays_cause_or_fatigue():
    state = make_state()
    preferences.store.apply(set_pref("talkativeness", "low"), state)
    policies = Policies()
    policies.record(Event(type="disengagement_high"), NOW)
    assert policies.check(Event(type="cause_detected"), state, NOW + 31).allowed
    assert policies.check(Event(type="fatigue_high"), state, NOW + 31).allowed


# ----------------------------------------------------------------- follow_up -> client


@pytest.mark.asyncio
async def test_follow_up_never_skips_the_question():
    _, state = load_scene("scene3_message")
    answer = {"actions": [{"type": "speak", "to": "driver", "text": "Mai ai 40 de minute."}]}
    client = AssistantClient(FakeProvider(answer))
    event = {"type": "driver_speech", "data": {"text": "cât mai avem"}}
    with_question = await client.handle_event(event, state, now=NOW)
    assert [a.reason for a in with_question if a.type == "ask"] == ["follow_up"]

    preferences.store.apply(set_pref("follow_up", "never"), state)
    without = await client.handle_event(event, state, now=NOW + 1)
    assert [a.type for a in without] == ["speak"]


@pytest.mark.asyncio
async def test_client_reset_forgets_voice_preferences():
    state = make_state()
    preferences.store.apply(set_pref("follow_up", "never"), state)
    AssistantClient(FakeProvider({"actions": []})).reset()
    assert preferences.follow_up_enabled(state)


# ----------------------------------------------------------------- answer_length -> summary / prompt


def test_summary_tells_the_llm_the_preferences(_isolated_profiles):
    write_profile(_isolated_profiles, {"answer_length": "short", "talkativeness": "low"})
    text = summarize(make_state(), Event(type="driver_speech", data={"text": "salut"}))
    assert "Driver preferences: talkativeness low, answers short (aim for at most 12 words)" in text
    assert "follow-up question always" in text


def test_normal_length_has_no_extra_word_target():
    text = summarize(make_state(), Event(type="driver_speech", data={"text": "salut"}))
    assert "answers normal," in text and "aim for" not in text


def test_short_answers_keep_the_hard_limit_only():
    """A 20-word LLM sentence is still accepted with answer_length short (target, not a new hard limit)."""
    state = make_state()
    preferences.store.apply(set_pref("answer_length", "short"), state)
    text = " ".join(["cuvânt"] * 20)
    assert validate_actions([{"type": "speak", "to": "driver", "text": text}], state).accepted


def test_prompt_lists_the_new_preference_keys():
    prompt = system_prompt()
    assert "answer_length (short/normal)" in prompt and "follow_up (always/never" in prompt


# ----------------------------------------------------------------- voice: set_preference -> Bine? -> da


@pytest.mark.parametrize("key,value,ok", [("answer_length", "short", True), ("follow_up", "never", True),
                                          ("talkativeness", "high", True), ("answer_length", "tiny", False)])
def test_set_preference_validation(key, value, ok):
    checked = validate_actions([{"type": "set_preference", "key": key, "value": value}], make_state())
    assert bool(checked.accepted) is ok
    if ok:
        assert checked.accepted[0].needs_confirmation  # only volume runs without "Bine?"


def test_confirmed_voice_preference_is_released_but_applied_only_by_the_executor():
    """DialogManager releases the action after "da"; core records it after its own check (AssistantLink._preference)."""
    state = make_state()
    held = validate_actions([
        {"type": "set_preference", "key": "answer_length", "value": "short"},
        {"type": "ask", "to": "driver", "question": "Răspund mai scurt. Bine?", "expects": "yes_no"},
    ], state).accepted
    dialog = DialogManager()
    dialog.register(held, NOW)
    result = dialog.handle([InputEvent("voice", "da", NOW + 1)], NOW + 1, state=state)
    assert [a.type for a in result.execute] == ["set_preference"]
    assert preferences.effective(state)["answer_length"] == "normal"  # not yet: core has not executed it
    assert preferences.store.apply(result.execute[0], state)
    assert preferences.effective(state)["answer_length"] == "short"


def test_refused_voice_preference_is_not_recorded():
    state = make_state()
    held = validate_actions([
        {"type": "set_preference", "key": "follow_up", "value": "never"},
        {"type": "ask", "to": "driver", "question": "Nu mai întreb asta. Bine?", "expects": "yes_no"},
    ], state).accepted
    dialog = DialogManager()
    dialog.register(held, NOW)
    dialog.handle([InputEvent("voice", "nu", NOW + 1)], NOW + 1, state=state)
    assert preferences.follow_up_enabled(state)


# ----------------------------------------------------------------- voice commands without the LLM


@pytest.mark.parametrize("text,expected", [
    ("Copilot, răspunde-mi mai scurt te rog", ("answer_length", "short")),
    ("răspunsuri mai scurte", ("answer_length", "short")),
    ("răspunde normal", ("answer_length", "normal")),
    ("nu mă mai întreba dacă mai vreau ceva", ("follow_up", "never")),
    ("întreabă-mă dacă mai vreau ceva", ("follow_up", "always")),
    ("vorbește mai rar", ("talkativeness", "low")),
    ("nu-mi mai propune atâtea", ("talkativeness", "low")),
    ("propune mai des", ("talkativeness", "high")),
    ("pune muzică", None),
    ("mai încet", None),
    ("cât mai avem până ajungem", None),
    ("spune-mi pe scurt ce mesaje am", None),
    ("răspunde mai scurt " + "foarte " * 12, None),  # long utterances go to the LLM
])
def test_voice_command_phrases(text, expected):
    assert preferences.voice_command(text) == expected


@pytest.mark.asyncio
async def test_known_phrase_is_answered_without_the_llm():
    """Even with a working LLM, "răspunde mai scurt" gets the fixed "Bine?" at once (no LLM call)."""
    _, state = load_scene("scene3_message")
    provider = FakeProvider({"actions": [{"type": "speak", "to": "driver", "text": "nu trebuia chemat"}]})
    client = AssistantClient(provider)
    actions = await client.handle_event({"type": "driver_speech", "data": {"text": "răspunde mai scurt"}}, state,
                                        now=NOW)
    assert provider.calls == [] and client.last_result.reason == "deterministic"
    assert [(a.type, a.key, a.value, a.needs_confirmation) for a in actions][0] == (
        "set_preference", "answer_length", "short", True)
    assert actions[1].type == "ask" and actions[1].question == "Răspund mai scurt. Bine?"


@pytest.mark.asyncio
async def test_known_phrase_works_offline_and_says_when_nothing_changes():
    from assistant.llm import OfflineProvider

    state = make_state()
    client = AssistantClient(OfflineProvider())
    event = {"type": "driver_speech", "data": {"text": "nu mă mai întreba dacă mai vreau ceva"}}
    first = await client.handle_event(event, state, now=NOW)
    assert first[0].type == "set_preference" and first[0].value == "never"
    preferences.store.apply(first[0], state)  # core executed it after "da"
    again = await client.handle_event(event, state, now=NOW + 1)
    assert [a.type for a in again] == ["speak"] and again[0].text == "E deja așa."  # follow_up never: no question


def test_every_voice_command_has_a_confirmation_text():
    from assistant.settings import cfg, get_texts

    confirm = get_texts()["fallback"]["preference_confirm"]
    for command in cfg("driver_preferences", "voice_commands"):
        question = confirm[command["key"]][command["value"]]
        assert question.endswith("Bine?") and len(question.split()) <= 12
