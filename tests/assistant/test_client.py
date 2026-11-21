"""Tests for assistant.client.AssistantClient (pipeline, 2.5 s deadline, fallbacks, streaming)."""

import pytest

from assistant.client import AssistantClient, system_prompt
from assistant.llm import OfflineProvider
from p3_helpers import FakeProvider, load_scene

NOW = 1763672400.0

GOOD_ANSWER = {"actions": [
    {"type": "speak", "to": "passenger", "text": "Maria, poți să-i povestești tu?"},
    {"type": "delegate", "to_person": "Maria", "task": "tell_story"},
    {"type": "speak", "to": "driver", "text": "Andrei, ochii pe drum."},
]}


@pytest.mark.asyncio
async def test_llm_answer_is_validated_and_returned():
    event, state = load_scene("scene4_passenger_phone")
    client = AssistantClient(FakeProvider(GOOD_ANSWER))
    actions = await client.handle_event(event, state, now=NOW)
    assert [a.type for a in actions] == ["speak", "delegate", "speak"]
    assert all(a.source == "LLM" for a in actions)
    assert client.last_result.source == "LLM"


@pytest.mark.asyncio
async def test_timeout_uses_fallback(monkeypatch):
    from assistant.settings import get_config

    monkeypatch.setitem(get_config()["llm"], "timeout_s", 0.05)  # restored after the test
    event, state = load_scene("scene4_passenger_phone")
    client = AssistantClient(FakeProvider(GOOD_ANSWER, delay_s=0.5))
    actions = await client.handle_event(event, state, now=NOW)
    assert client.last_result.reason == "timeout"
    assert actions and all(a.source == "RULE" for a in actions)


@pytest.mark.asyncio
async def test_no_key_runs_offline():
    event, state = load_scene("scene6_fatigue")
    client = AssistantClient(OfflineProvider())
    actions = await client.handle_event(event, state, now=NOW)
    assert client.last_result.reason == "no_llm"
    assert actions[0].type == "ask" and actions[0].expects == "kss"


@pytest.mark.asyncio
async def test_director_switch_off_uses_fallback():
    event, state = load_scene("scene4_passenger_phone")
    state.safety.llm_enabled = False
    provider = FakeProvider(GOOD_ANSWER)
    client = AssistantClient(provider)
    await client.handle_event(event, state, now=NOW)
    assert client.last_result.reason == "llm_disabled" and not provider.calls


@pytest.mark.asyncio
async def test_policy_block_never_calls_llm():
    event, state = load_scene("scene8_p1_alarm")
    provider = FakeProvider(GOOD_ANSWER)
    client = AssistantClient(provider)
    actions = await client.handle_event(event, state, now=NOW)
    assert [a.type for a in actions] == ["stay_silent"] and not provider.calls


@pytest.mark.asyncio
async def test_invalid_actions_fall_back():
    event, state = load_scene("scene4_passenger_phone")
    client = AssistantClient(FakeProvider({"actions": [{"type": "unlock_doors"}]}))
    actions = await client.handle_event(event, state, now=NOW)
    assert client.last_result.reason == "all_rejected"
    assert actions and actions[0].source == "RULE"


@pytest.mark.asyncio
async def test_invalid_json_falls_back():
    event, state = load_scene("scene5_disengagement")
    client = AssistantClient(FakeProvider("not json"))
    await client.handle_event(event, state, now=NOW)
    assert client.last_result.reason == "invalid_json"


@pytest.mark.asyncio
async def test_llm_error_falls_back():
    event, state = load_scene("scene5_disengagement")
    client = AssistantClient(FakeProvider({}, error=True))
    actions = await client.handle_event(event, state, now=NOW)
    assert client.last_result.reason == "llm_error" and actions


@pytest.mark.asyncio
async def test_refusal_is_deterministic():
    event, state = load_scene("scene6_refusal")
    provider = FakeProvider(GOOD_ANSWER)
    actions = await AssistantClient(provider).handle_event(event, state, now=NOW)
    assert not provider.calls
    assert actions[0].clip_id == "refusal_ack" and actions[1].reason == "driver_refused"


@pytest.mark.asyncio
async def test_streaming_hands_speech_early_and_marks_it():
    event, state = load_scene("scene4_passenger_phone")
    early = []
    client = AssistantClient(FakeProvider(GOOD_ANSWER, chunk=7))
    actions = await client.handle_event(event, state, on_early_speech=early.append, now=NOW)
    assert [a.text for a in early] == ["Maria, poți să-i povestești tu?", "Andrei, ochii pe drum."]
    assert [a.streamed for a in actions] == [True, False, True]


@pytest.mark.asyncio
async def test_memory_feeds_the_next_summary():
    _, state = load_scene("scene3_message")
    provider = FakeProvider({"actions": [{"type": "stay_silent", "reason": "nothing_to_add"}]})
    client = AssistantClient(provider)
    await client.handle_event({"type": "driver_speech", "data": {"text": "Ce mai face Mihai?"}}, state, now=NOW)
    await client.handle_event({"type": "driver_speech", "data": {"text": "Bine."}}, state, now=NOW + 1)
    assert "driver: Ce mai face Mihai?" in provider.calls[-1][1]


def test_system_prompt_is_filled():
    prompt = system_prompt()
    assert "{language_name}" not in prompt and "Romanian" in prompt and "15 words" in prompt


@pytest.mark.asyncio
async def test_silence_on_a_direct_request_is_replaced():
    """The driver spoke to the assistant: a lone stay_silent is not an acceptable answer."""
    _, state = load_scene("scene3_message")
    client = AssistantClient(FakeProvider({"actions": [{"type": "stay_silent", "reason": "nothing_to_add"}]}))
    actions = await client.handle_event({"type": "driver_speech", "data": {"text": "amintește-mi ceva"}}, state, now=NOW)
    assert client.last_result.reason == "silent_on_request"
    assert actions[0].type == "speak" and actions[0].source == "RULE"


@pytest.mark.asyncio
async def test_refusal_silence_is_kept():
    _, state = load_scene("scene3_message")
    client = AssistantClient(FakeProvider({"actions": [{"type": "stay_silent", "reason": "driver_refused"}]}))
    actions = await client.handle_event({"type": "driver_speech", "data": {"text": "nu mă mai bate la cap"}}, state, now=NOW)
    assert [a.reason for a in actions] == ["driver_refused"] and client.last_result.source == "LLM"


def test_short_error_keeps_code_and_status():
    from assistant.client import _short_error

    assert _short_error(Exception("Gemini API error 429: 429 RESOURCE_EXHAUSTED. {'error': ...}")) == "429 RESOURCE_EXHAUSTED"
    assert _short_error(Exception("Gemini API error 503: 503 UNAVAILABLE. overloaded")) == "503 UNAVAILABLE"
