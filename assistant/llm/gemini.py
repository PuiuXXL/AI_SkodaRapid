"""Google Gemini provider (team decision: Gemini Flash through Google AI Studio).

Uses the official Google Gen AI SDK (``google-genai``):

* streaming (``generate_content_stream``) so the first sentence can go to TTS
  before the whole answer is generated (plan D1, D4);
* structured output: ``response_mime_type="application/json"`` plus a JSON schema
  that only allows the action types of plan section 6;
* "thinking" reduced to a minimum (``llm.thinking_budget`` / ``llm.thinking_level``)
  because latency matters more than reasoning depth here.

Key and model come from ``.env`` (``LLM_API_KEY``, ``LLM_MODEL``). The key is
created for free at https://aistudio.google.com ("Get API key").
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from assistant.llm.base import LLMError, LLMProvider, LLMResult, TextCallback
from assistant.settings import cfg

log = logging.getLogger("drivemate.assistant.llm.gemini")

_ACTION_TYPES = [
    "speak", "ask", "suggest_media", "play_media", "stop_media", "read_message",
    "reply_message", "create_reminder", "complete_reminder", "suggest_stop",
    "delegate", "show_on_screen", "set_preference", "stay_silent",
]

_STR = {"type": "string"}
_TO = {"type": "string", "enum": ["driver", "passenger", "rear", "all"]}

#: Fields of each action type (plan section 6), all required. One JSON schema
#: branch per type keeps small models from putting a value in the wrong field
#: (e.g. ``value`` instead of ``text`` in ``reply_message``).
ACTION_FIELDS: dict[str, dict[str, Any]] = {
    "speak": {"to": _TO, "text": _STR},
    "ask": {"to": _TO, "question": _STR, "expects": {"type": "string", "enum": ["yes_no", "kss", "free"]}},
    "suggest_media": {"track_id": _STR, "reason": _STR},
    "play_media": {"track_id": _STR},
    "stop_media": {},
    "read_message": {"msg_id": _STR},
    "reply_message": {"msg_id": _STR, "text": _STR},
    "create_reminder": {
        "task": _STR,
        "trigger": {
            "type": "object",
            "properties": {"type": {"type": "string", "enum": ["stop_at_category"]}, "category": _STR},
            "required": ["type", "category"],
        },
    },
    "complete_reminder": {"reminder_id": _STR},
    "suggest_stop": {"poi_id": _STR},
    "delegate": {"to_person": _STR, "task": _STR},
    "show_on_screen": {"text": _STR, "target": {"type": "string", "enum": ["passenger"]}},
    "set_preference": {"key": _STR, "value": _STR},
    "stay_silent": {"reason": _STR},
}
assert list(ACTION_FIELDS) == _ACTION_TYPES  # keep both lists in sync with plan section 6


def _branch(action_type: str) -> dict[str, Any]:
    """Schema of one action type: ``type`` first (lets streamed speech be checked early)."""
    fields = ACTION_FIELDS[action_type]
    return {
        "type": "object",
        "properties": {"type": {"type": "string", "enum": [action_type]}, **fields},
        "required": ["type", *fields],
    }


#: JSON schema imposed on the model's answer (plan section 6).
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "maxItems": 3,
            "items": {"anyOf": [_branch(t) for t in _ACTION_TYPES]},
        }
    },
    "required": ["actions"],
}


class GeminiProvider(LLMProvider):
    """LLM provider backed by a Gemini model."""

    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        """Create the SDK client.

        Args:
            api_key: Google AI Studio API key (``LLM_API_KEY``).
            model: Model name, e.g. a Gemini Flash model (``LLM_MODEL``).
        """
        self.model = model
        # No SDK-level retries: a retry would blow the 2.5 s budget; the client
        # falls back to fixed texts instead. The HTTP timeout is a safety net only.
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=10_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    @staticmethod
    def _build_config_kwargs() -> dict[str, Any]:
        """Generation settings from ``assistant.yaml`` (temperature, tokens, thinking)."""
        kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_json_schema": RESPONSE_SCHEMA,
            "temperature": float(cfg("llm", "temperature", default=0.4)),
            "max_output_tokens": int(cfg("llm", "max_output_tokens", default=400)),
        }
        budget = cfg("llm", "thinking_budget", default=None)
        level = cfg("llm", "thinking_level", default=None)
        if level is not None:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=level)
        elif budget is not None:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=int(budget))
        return kwargs

    def _build_config(self, system: str | None = None) -> types.GenerateContentConfig:
        """Full request config, optionally with the system prompt."""
        return types.GenerateContentConfig(system_instruction=system, **self._build_config_kwargs())

    async def generate(self, system: str, user: str, on_text: Optional[TextCallback] = None) -> LLMResult:
        """Stream one answer from Gemini.

        Args:
            system: System prompt.
            user: State summary for the event.
            on_text: Called with the accumulated text after each chunk.

        Returns:
            The complete JSON text with timing information.

        Raises:
            LLMError: Wrapped SDK / network error (auth, quota, invalid model...).
        """
        started = time.perf_counter()
        ttft_ms: Optional[float] = None
        parts: list[str] = []
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self.model, contents=user, config=self._build_config(system),
            )
            async for chunk in stream:
                piece = chunk.text or ""
                if not piece:
                    continue
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - started) * 1000
                parts.append(piece)
                if on_text is not None:
                    on_text("".join(parts))
        except genai_errors.APIError as exc:
            raise LLMError(f"Gemini API error {getattr(exc, 'code', '?')}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - network/HTTP library errors vary; all mean "fall back"
            raise LLMError(f"Gemini call failed: {type(exc).__name__}: {exc}") from exc
        total_ms = (time.perf_counter() - started) * 1000
        return LLMResult(text="".join(parts), ttft_ms=ttft_ms, total_ms=total_ms)

    async def warm_up(self) -> None:
        """Send one tiny request so the first real answer is not slowed by TLS setup."""
        try:
            await self.generate("Return {\"actions\": []}.", "warm-up")
        except LLMError as exc:
            log.warning("Gemini warm-up failed: %s", exc)
