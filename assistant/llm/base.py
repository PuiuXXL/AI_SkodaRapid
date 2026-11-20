"""Provider-independent LLM interface.

A provider receives the system prompt and the state summary and returns the raw
JSON text of ``{"actions": [...]}``. Streaming is supported through an optional
``on_text`` callback that receives the accumulated text after every chunk, which
lets the client start TTS on the first complete sentence (plan D1, D4).

Deadlines (2.5 s) are enforced by the client, not by the provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

#: Callback type: receives the full text generated so far (not just the new chunk).
TextCallback = Callable[[str], None]


class LLMError(Exception):
    """Any provider failure (network, auth, quota, invalid model). Triggers the fallback."""


@dataclass
class LLMResult:
    """Raw answer of a provider.

    Attributes:
        text: The generated JSON text.
        ttft_ms: Milliseconds until the first chunk (plan J1: ``llm_ttft_ms``).
        total_ms: Milliseconds until the answer was complete (``llm_total_ms``).
    """

    text: str
    ttft_ms: Optional[float] = None
    total_ms: Optional[float] = None


class LLMProvider(ABC):
    """Base class of every LLM provider."""

    #: Short name written in logs and in ``integrations.llm`` (e.g. ``"gemini"``).
    name: str = "base"

    @property
    def available(self) -> bool:
        """True if this provider can make real calls (False for the offline one)."""
        return True

    @abstractmethod
    async def generate(self, system: str, user: str, on_text: Optional[TextCallback] = None) -> LLMResult:
        """Generate the JSON answer for one event.

        Args:
            system: The system prompt (rules, action list, examples).
            user: The state summary for this event.
            on_text: Optional streaming callback (accumulated text).

        Returns:
            The :class:`LLMResult`.

        Raises:
            LLMError: On any failure; the client then uses the fallback texts.
        """

    async def warm_up(self) -> None:
        """Open the connection once at start-up (plan section 8 rule 5). Optional."""
        return None
