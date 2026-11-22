"""Offline "provider": no network, always defers to the fixed fallback texts.

Selected automatically when ``.env`` has no ``LLM_API_KEY`` / ``LLM_MODEL``, or
when ``LLM_PROVIDER=offline``. It lets anyone (including the jury) run DriveMate
without a key: the assistant still speaks with the texts from
``assistant/config/texts.<language>.yaml`` and safety is unaffected.
"""

from __future__ import annotations

from assistant.llm.base import LLMError, LLMProvider, LLMResult, TextCallback


class OfflineProvider(LLMProvider):
    """Provider that never calls a model."""

    name = "offline"

    @property
    def available(self) -> bool:
        """Always False: the client goes straight to the fallback texts."""
        return False

    async def generate(self, system: str, user: str, on_text: TextCallback | None = None) -> LLMResult:
        """Always raise :class:`LLMError` (should not be called; ``available`` is False)."""
        raise LLMError("offline provider: no LLM configured")
