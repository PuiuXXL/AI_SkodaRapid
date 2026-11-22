"""Phase-1 fixes of the answer quality (baseline: docs/eval/llm-baseline-2026-11-22.md).

* a held action (needs a "yes") without a question gets the confirmation question instead of "n-am înțeles";
* an answer cut by ``max_output_tokens`` is reported as ``truncated``; an LLM failure on a direct request
  says "mi-a scăpat", not "n-am înțeles" (the driver was understood);
* "mulțumesc" is answered at once, without the LLM and without "Te mai ajut cu ceva?";
* a numeric preference (volume) reaches core as a number;
* the LLM summary carries the alerts, so "de ce m-ai alertat?" is not invented;
* pytest never calls the real LLM, even with a key in .env.
"""

from __future__ import annotations

from typing import Optional

import pytest

from assistant.client import AssistantClient
from assistant.llm.base import LLMResult, TextCallback
from assistant.settings import get_texts
from assistant.summary import summarize
from p3_helpers import FakeProvider, make_state

NOW = 1763672400.0


def _speech(text: str) -> dict:
    return {"type": "driver_speech", "data": {"text": text}}


def _fb(key: str) -> str:
    return get_texts()["fallback"][key]


class CutProvider(FakeProvider):
    """The model stopped at max_output_tokens: half a JSON object."""

    async def generate(self, system: str, user: str, on_text: Optional[TextCallback] = None) -> LLMResult:
        self.calls.append((system, user))
        return LLMResult(text='{"actions": [{"', ttft_ms=1.0, total_ms=2.0, finish_reason="MAX_TOKENS")


# --- held actions without a question ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_held_read_message_gets_its_question():
    """'Citește-mi mesajele' with Maria on board: read_message waits for a yes, so it must be asked."""
    client = AssistantClient(FakeProvider({"actions": [{"type": "read_message", "msg_id": "m17"}]}))
    actions = await client.handle_event(_speech("Citește-mi mesajele."), make_state(), now=NOW)
    assert client.last_result.reason == "ok" and client.last_result.source == "LLM"
    held = [a for a in actions if a.needs_confirmation]
    asks = [a for a in actions if a.type == "ask"]
    assert [a.type for a in held] == ["read_message"]
    assert len(asks) == 1 and asks[0].question == "Mesaj de la Mihai. Îl citesc tare?"
    assert asks[0].expects == "yes_no" and asks[0].source == "RULE"


@pytest.mark.asyncio
async def test_held_stop_and_reminder_get_their_questions():
    stop = AssistantClient(FakeProvider({"actions": [{"type": "suggest_stop", "poi_id": "omv_km42"}]}))
    actions = await stop.handle_event(_speech("Hai să oprim la OMV."), make_state(), now=NOW)
    assert [a.question for a in actions if a.type == "ask"] == ["Oprim la OMV?"]

    reminder = AssistantClient(FakeProvider({"actions": [
        {"type": "create_reminder", "task": "o cafea", "trigger": {"type": "stop_at_category", "category": "cafe"}}]}))
    actions = await reminder.handle_event(_speech("Amintește-mi de cafea."), make_state(), now=NOW)
    assert [a.question for a in actions if a.type == "ask"] == ["Notat: o cafea, la prima cafenea. Bine?"]


@pytest.mark.asyncio
async def test_question_from_the_llm_is_kept():
    """The LLM asked itself: no second question."""
    answer = {"actions": [{"type": "ask", "to": "driver", "question": "Îl citesc?", "expects": "yes_no"},
                          {"type": "read_message", "msg_id": "m17"}]}
    actions = await AssistantClient(FakeProvider(answer)).handle_event(_speech("Am mesaje?"), make_state(), now=NOW)
    assert [a.question for a in actions if a.type == "ask"] == ["Îl citesc?"]


@pytest.mark.asyncio
async def test_message_alone_is_read_without_question():
    """Nobody else in the car: read_message is not held, nothing to ask."""
    state = make_state(passenger={"present": False},
                       occupants=[{"id": 1, "seat": "driver", "source": "cam_driver", "profile": "andrei"}])
    client = AssistantClient(FakeProvider({"actions": [{"type": "read_message", "msg_id": "m17"}]}))
    actions = await client.handle_event(_speech("Citește-mi mesajele."), state, now=NOW)
    assert "read_message" in [a.type for a in actions if not a.needs_confirmation]
    assert not any(a.type == "ask" and a.reason != "follow_up" for a in actions)


# --- LLM failures on a direct request --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cut_answer_is_reported_as_truncated():
    client = AssistantClient(CutProvider({}))
    actions = await client.handle_event(_speech("Unde e o farmacie?"), make_state(), now=NOW)
    assert client.last_result.reason == "truncated"
    assert [a.question for a in actions] == [_fb("llm_hiccup")]
    assert actions[0].type == "ask" and actions[0].source == "RULE"


@pytest.mark.asyncio
async def test_llm_error_on_speech_says_it_was_our_fault():
    client = AssistantClient(FakeProvider({}, error=True))
    actions = await client.handle_event(_speech("Ce oraș urmează?"), make_state(), now=NOW)
    assert client.last_result.reason == "llm_error"
    assert [a.question for a in actions] == [_fb("llm_hiccup")]


@pytest.mark.asyncio
async def test_no_llm_still_says_not_understood():
    """Without any LLM the request really cannot be handled: the old text stays."""
    from assistant.llm import OfflineProvider

    client = AssistantClient(OfflineProvider())
    actions = await client.handle_event(_speech("Ce oraș urmează?"), make_state(), now=NOW)
    assert client.last_result.reason == "no_llm"
    assert [a.question for a in actions] == [_fb("not_understood")]


# --- thanks ----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Mulțumesc mult.", "Mersi!", "Mulțumesc, DriveMate."])
async def test_thanks_is_answered_without_the_llm(text):
    provider = FakeProvider({"actions": [{"type": "stay_silent", "reason": "nothing_to_add"}]})
    client = AssistantClient(provider)
    actions = await client.handle_event(_speech(text), make_state(), now=NOW)
    assert not provider.calls and client.last_result.reason == "deterministic"
    assert [(a.type, a.text) for a in actions] == [("speak", _fb("thanks"))]  # no "Te mai ajut cu ceva?"


@pytest.mark.asyncio
async def test_thanks_with_a_request_goes_to_the_llm():
    provider = FakeProvider({"actions": [{"type": "speak", "to": "driver", "text": "Mai ai 20 de minute."}]})
    await AssistantClient(provider).handle_event(_speech("Mulțumesc, cât mai am?"), make_state(), now=NOW)
    assert provider.calls


# --- preferences -----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_volume_from_the_llm_is_a_number():
    """Gemini's schema sends every value as a string; core applies the volume only for a number."""
    client = AssistantClient(FakeProvider({"actions": [{"type": "set_preference", "key": "volume", "value": "0.3"}]}))
    actions = await client.handle_event(_speech("Dă volumul la 30 de procente, te rog."),
                                        make_state(media={"playing": True}), now=NOW)
    pref = next(a for a in actions if a.type == "set_preference")
    assert pref.value == 0.3 and isinstance(pref.value, float)


# --- summary ---------------------------------------------------------------------------------------------------------


def test_summary_states_when_there_is_no_alert():
    text = summarize(make_state(), _event("De ce m-ai alertat?"))
    assert "Alerts: none active, none recorded" in text


def test_summary_carries_the_active_alert_and_the_last_closure():
    state = make_state(safety={"level": "P3", "alert": "eyes_closing",
                               "drowsiness": {"episodes_10min": 2, "last_episode_ms": 1600.0,
                                              "last_episode_ts": 1763672340.123}})
    text = summarize(state, _event("De ce m-ai alertat?"))
    assert "active eyes_closing (P3)" in text
    assert "eyes closed 1.6 s, 60 s ago" in text and "2 such closures in 10 min" in text


def _event(text: str):
    from assistant.contract import Event

    return Event.model_validate(_speech(text))


# --- tests never call the real LLM -----------------------------------------------------------------------------------


def test_pytest_runs_offline(monkeypatch):
    from assistant.settings import llm_settings

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gemini-test")
    monkeypatch.delenv("DRIVEMATE_LLM_LIVE", raising=False)
    assert not llm_settings().usable
    monkeypatch.setenv("DRIVEMATE_LLM_LIVE", "1")
    assert llm_settings().usable
