"""LLM providers for the assistant.

Only Google Gemini is implemented (team decision); :class:`OfflineProvider` is used
when no key / model is configured, so the project always runs.

Use :func:`make_provider` instead of instantiating providers directly.
"""

from __future__ import annotations

import logging

from assistant.llm.base import LLMError, LLMProvider, LLMResult
from assistant.llm.offline import OfflineProvider
from assistant.settings import LLMSettings, llm_settings

log = logging.getLogger("drivemate.assistant.llm")

__all__ = ["LLMError", "LLMProvider", "LLMResult", "OfflineProvider", "make_provider"]


def make_provider(settings: LLMSettings | None = None) -> LLMProvider:
    """Create the provider configured in ``.env`` / ``assistant.yaml``.

    Args:
        settings: Explicit settings (tests); defaults to :func:`llm_settings`.

    Returns:
        A :class:`~assistant.llm.gemini.GeminiProvider` when ``LLM_PROVIDER=gemini``
        and both ``LLM_API_KEY`` and ``LLM_MODEL`` are set; otherwise an
        :class:`OfflineProvider` (the reason is logged once).
    """
    settings = settings or llm_settings()
    if settings.provider == "gemini" and settings.usable:
        from assistant.llm.gemini import GeminiProvider  # imported lazily: heavy SDK

        return GeminiProvider(api_key=settings.api_key, model=settings.model,
                              backup_model=settings.backup_model or None)
    if settings.provider not in ("gemini", "offline"):
        log.warning("LLM_PROVIDER=%r is not supported (only 'gemini'); running offline.", settings.provider)
    elif settings.provider == "gemini":
        missing = [name for name, value in (("LLM_API_KEY", settings.api_key), ("LLM_MODEL", settings.model)) if not value]  # noqa: E501
        log.warning("LLM disabled: %s missing in .env; using fixed fallback texts.", " and ".join(missing))
    return OfflineProvider()
