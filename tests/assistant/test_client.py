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
    from assistant.settings import cfg

    prompt = system_prompt()
    limit = cfg("speech", "max_words_to_driver")
    assert "{language_name}" not in prompt and "{max_words}" not in prompt and "Romanian" in prompt
    assert f"at most {limit} words IN TOTAL" in prompt


def test_word_limit_counts_the_whole_text():
    """The limit applies to the whole speak text (all sentences), as the prompt says."""
    from assistant.actions import validate_actions
    from assistant.settings import cfg

    event, state = load_scene("scene4_passenger_phone")
    limit = int(cfg("speech", "max_words_to_driver"))
    ok = " ".join(["Bine."] * limit)
    too_long = " ".join(["Bine."] * (limit + 1))
    checked = validate_actions([{"type": "speak", "to": "driver", "text": ok},
                                {"type": "speak", "to": "driver", "text": too_long}], state, event, source="LLM")
    assert [a.text for a in checked.accepted] == [ok]
    assert [r.reason for r in checked.rejected] == ["too_many_words"]


@pytest.mark.asyncio
async def test_silence_on_a_direct_request_is_replaced():
    """The driver spoke to the assistant: a lone stay_silent is not an acceptable answer."""
    _, state = load_scene("scene3_message")
    client = AssistantClient(FakeProvider({"actions": [{"type": "stay_silent", "reason": "nothing_to_add"}]}))
    actions = await client.handle_event({"type": "driver_speech", "data": {"text": "amintește-mi ceva"}}, state, now=NOW)
    assert client.last_result.reason == "silent_on_request"
    # "Scuze, n-am înțeles. Poți repeta?" ends with "?": it is an ask, so the driver can repeat without the name.
    assert actions[0].type == "ask" and actions[0].expects == "free" and actions[0].source == "RULE"


@pytest.mark.asyncio
async def test_spoken_question_opens_the_dialog_window():
    """A speak ending with "?" reaches core as an ask (dialog window), also when streamed early."""
    _, state = load_scene("scene3_message")
    answer = {"actions": [{"type": "speak", "to": "driver", "text": "Salut, Andrei! Sunt bine. Cu ce te pot ajuta?"}]}
    early = []
    client = AssistantClient(FakeProvider(answer, chunk=9))
    actions = await client.handle_event({"type": "driver_speech", "data": {"text": "salut ce mai faci"}}, state,
                                        on_early_speech=early.append, now=NOW)
    assert [(a.type, a.expects, a.question, a.streamed) for a in actions] == [
        ("ask", "free", "Salut, Andrei! Sunt bine. Cu ce te pot ajuta?", True)]
    assert early[0].type == "ask" and early[0].question == actions[0].question


@pytest.mark.asyncio
async def test_refusal_silence_is_kept():
    _, state = load_scene("scene3_message")
    client = AssistantClient(FakeProvider({"actions": [{"type": "stay_silent", "reason": "driver_refused"}]}))
    actions = await client.handle_event({"type": "driver_speech", "data": {"text": "nu mă mai bate la cap"}}, state, now=NOW)
    assert [a.reason for a in actions] == ["driver_refused"] and client.last_result.source == "LLM"


class RetryProvider(FakeProvider):
    """Fails the first call with an LLMError; ``generate_retry`` answers (or fails too)."""

    name = "retry-fake"

    def __init__(self, answer, transient=True, retry_fails=False, stream_before_error=None):
        """Args:
            transient: ``LLMError.transient`` of the first failure.
            retry_fails: The retry raises a transient error too.
            stream_before_error: Text fed to ``on_text`` before the first failure.
        """
        super().__init__(answer)
        self.transient = transient
        self.retry_fails = retry_fails
        self.stream_before_error = stream_before_error
        self.retries = 0

    @property
    def retry_label(self):
        """Pretend backup model name."""
        return "backup-model"

    async def generate(self, system, user, on_text=None):
        """First attempt: always fails (after optional streamed text)."""
        from assistant.llm import LLMError

        self.calls.append((system, user))
        if self.stream_before_error and on_text is not None:
            on_text(self.stream_before_error)
        raise LLMError("Gemini API error 503: 503 UNAVAILABLE. overloaded", transient=self.transient)

    async def generate_retry(self, system, user, on_text=None):
        """Second attempt: answers like FakeProvider, unless ``retry_fails``."""
        from assistant.llm import LLMError

        self.retries += 1
        if self.retry_fails:
            raise LLMError("Gemini API error 429: 429 RESOURCE_EXHAUSTED.", transient=True)
        return await super().generate(system, user, on_text)


@pytest.mark.asyncio
async def test_transient_error_is_retried_on_backup():
    event, state = load_scene("scene4_passenger_phone")
    provider = RetryProvider(GOOD_ANSWER)
    client = AssistantClient(provider)
    actions = await client.handle_event(event, state, now=NOW)
    assert provider.retries == 1
    assert client.last_result.source == "LLM" and client.last_result.reason == "ok"
    assert client.last_result.retry == "503 UNAVAILABLE -> backup-model"
    assert [a.type for a in actions] == ["speak", "delegate", "speak"]


@pytest.mark.asyncio
async def test_permanent_error_is_not_retried():
    event, state = load_scene("scene4_passenger_phone")
    provider = RetryProvider(GOOD_ANSWER, transient=False)
    client = AssistantClient(provider)
    actions = await client.handle_event(event, state, now=NOW)
    assert provider.retries == 0 and client.last_result.reason == "llm_error" and actions[0].source == "RULE"


@pytest.mark.asyncio
async def test_no_retry_without_enough_time_left(monkeypatch):
    from assistant.settings import get_config

    monkeypatch.setitem(get_config()["llm"], "retry", {"enabled": True, "min_remaining_s": 99})
    event, state = load_scene("scene4_passenger_phone")
    provider = RetryProvider(GOOD_ANSWER)
    client = AssistantClient(provider)
    await client.handle_event(event, state, now=NOW)
    assert provider.retries == 0 and client.last_result.reason == "llm_error"


@pytest.mark.asyncio
async def test_retry_disabled_in_config(monkeypatch):
    from assistant.settings import get_config

    monkeypatch.setitem(get_config()["llm"], "retry", {"enabled": False})
    event, state = load_scene("scene4_passenger_phone")
    provider = RetryProvider(GOOD_ANSWER)
    await AssistantClient(provider).handle_event(event, state, now=NOW)
    assert provider.retries == 0


@pytest.mark.asyncio
async def test_failed_retry_falls_back_with_its_error():
    event, state = load_scene("scene4_passenger_phone")
    provider = RetryProvider(GOOD_ANSWER, retry_fails=True)
    client = AssistantClient(provider)
    actions = await client.handle_event(event, state, now=NOW)
    assert provider.retries == 1 and client.last_result.reason == "llm_error"
    assert client.last_result.error == "429 RESOURCE_EXHAUSTED" and actions[0].source == "RULE"


@pytest.mark.asyncio
async def test_no_retry_after_speech_was_streamed():
    """The driver must never hear an answer twice: no retry once a sentence went to TTS."""
    event, state = load_scene("scene4_passenger_phone")
    partial = '{"actions": [{"type": "speak", "to": "driver", "text": "Andrei, ochii pe drum."},'
    provider = RetryProvider(GOOD_ANSWER, stream_before_error=partial)
    early = []
    client = AssistantClient(provider)
    await client.handle_event(event, state, on_early_speech=early.append, now=NOW)
    assert len(early) == 1 and provider.retries == 0 and client.last_result.reason == "llm_error"


@pytest.mark.asyncio
async def test_retry_streams_with_a_fresh_watcher():
    """Partial text from the failed attempt (no complete action) does not confuse the retry's stream."""
    event, state = load_scene("scene4_passenger_phone")
    provider = RetryProvider(GOOD_ANSWER, stream_before_error='{"actions": [{"type": "spe')
    provider.chunk = 7
    early = []
    client = AssistantClient(provider)
    actions = await client.handle_event(event, state, on_early_speech=early.append, now=NOW)
    assert provider.retries == 1
    assert [a.text for a in early] == ["Maria, poți să-i povestești tu?", "Andrei, ochii pe drum."]
    assert [a.streamed for a in actions] == [True, False, True]


def test_backup_model_from_env_overrides_config(monkeypatch):
    from assistant.settings import llm_settings

    monkeypatch.setenv("LLM_BACKUP_MODEL", "gemini-test-backup")
    assert llm_settings().backup_model == "gemini-test-backup"
    monkeypatch.delenv("LLM_BACKUP_MODEL")
    assert llm_settings().backup_model == "gemini-3.1-flash-lite"


def test_short_error_keeps_code_and_status():
    from assistant.client import _short_error

    assert _short_error(Exception("Gemini API error 429: 429 RESOURCE_EXHAUSTED. {'error': ...}")) == "429 RESOURCE_EXHAUSTED"
    assert _short_error(Exception("Gemini API error 503: 503 UNAVAILABLE. overloaded")) == "503 UNAVAILABLE"
    # The model name is now part of the message; it must not change the short form.
    assert _short_error(Exception("Gemini API error 503 (gemini-2.5-flash): 503 UNAVAILABLE.")) == "503 UNAVAILABLE"
