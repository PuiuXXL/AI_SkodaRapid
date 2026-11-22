"""Provider-independent LLM interface.

A provider receives the system prompt and the state summary and returns the raw
JSON text of ``{"actions": [...]}``. Streaming is supported through an optional
``on_text`` callback that receives the accumulated text after every chunk, which
lets the client start TTS on the first complete sentence (plan D1, D4).

Deadlines (2.5 s) are enforced by the client, not by the provider. On a temporary
failure (:attr:`LLMError.transient`) the client may call :meth:`LLMProvider.generate_retry`
once, inside the same deadline (Gemini then uses its backup model).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

#: Callback type: receives the full text generated so far (not just the new chunk).
TextCallback = Callable[[str], None]


class LLMError(Exception):
    """Any provider failure (network, auth, quota, invalid model). Triggers the fallback.

    Attributes:
        transient: True when the same request may succeed a moment later (server
            overloaded, rate limit); the client then retries once if time allows.
    """

    def __init__(self, message: str, transient: bool = False) -> None:
        """Args:
            message: Description of the failure (shown in logs, shortened in the event log).
            transient: See the class attributes.
        """
        super().__init__(message)
        self.transient = transient


@dataclass
class LLMResult:
    """Raw answer of a provider.

    Attributes:
        text: The generated JSON text.
        ttft_ms: Milliseconds until the first chunk (plan J1: ``llm_ttft_ms``).
        total_ms: Milliseconds until the answer was complete (``llm_total_ms``).
        finish_reason: Why the model stopped, when the provider says it (Gemini:
            ``"STOP"``, ``"MAX_TOKENS"``...). ``"MAX_TOKENS"`` = the JSON was cut.
    """

    text: str
    ttft_ms: float | None = None
    total_ms: float | None = None
    finish_reason: str | None = None


class LLMProvider(ABC):
    """Base class of every LLM provider."""

    #: Short name written in logs and in ``integrations.llm`` (e.g. ``"gemini"``).
    name: str = "base"

    @property
    def available(self) -> bool:
        """True if this provider can make real calls (False for the offline one)."""
        return True

    @abstractmethod
    async def generate(self, system: str, user: str, on_text: TextCallback | None = None) -> LLMResult:
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

    @property
    def retry_label(self) -> str:
        """What :meth:`generate_retry` calls, for logs (e.g. the backup model name)."""
        return self.name

    async def generate_retry(self, system: str, user: str, on_text: TextCallback | None = None) -> LLMResult:
        """Second attempt after a transient :class:`LLMError` (same arguments as :meth:`generate`).

        The default simply calls :meth:`generate` again; providers with a backup
        model override it.
        """
        return await self.generate(system, user, on_text)

    async def warm_up(self) -> None:
        """Open the connection once at start-up (plan section 8 rule 5). Optional."""
        return None
