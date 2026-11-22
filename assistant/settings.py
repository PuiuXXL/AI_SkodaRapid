"""Configuration and secrets loader for the P3 assistant.

Everything configurable in ``assistant/`` is read through this module:

* ``assistant/config/assistant.yaml`` - thresholds, limits, lists (no secrets);
* ``assistant/config/texts.<language>.yaml`` - fixed spoken texts (fallbacks, clips);
* the repo-root ``.env`` file - secrets: ``LLM_PROVIDER``, ``LLM_API_KEY``,
  ``LLM_MODEL``, phone numbers, KDE Connect device id, ``CORE_URL``.

The plan (DriveMate-PLAN-FINAL.md, section 8) forbids thresholds in code, so every
other module asks this one instead of hard-coding values.

Values are cached after the first read; tests call :func:`reload` after changing
files or environment variables.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

#: Absolute path of the repository root (the folder that contains ``assistant/``).
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

#: Folder with the YAML configuration files of the assistant.
CONFIG_DIR: Path = Path(__file__).resolve().parent / "config"

# Load the repo-root .env once, without overriding variables already set in the
# environment (so a shell export or a test monkeypatch always wins).
load_dotenv(REPO_ROOT / ".env", override=False)


def resolve_path(relative: str | Path) -> Path:
    """Return an absolute path for a path written relative to the repo root.

    Args:
        relative: A path such as ``"assistant/data/media_catalog.json"``. Absolute
            paths are returned unchanged.

    Returns:
        The absolute :class:`~pathlib.Path`.
    """
    path = Path(relative)
    return path if path.is_absolute() else REPO_ROOT / path


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """Return the parsed ``assistant/config/assistant.yaml`` (cached).

    Returns:
        The whole configuration as nested dictionaries / lists.
    """
    with open(CONFIG_DIR / "assistant.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@lru_cache(maxsize=1)
def get_texts() -> dict[str, Any]:
    """Return the fixed texts for the configured language (cached).

    The file is ``assistant/config/texts.<language>.yaml`` where ``language`` comes
    from ``assistant.yaml``. Falls back to Romanian if the file does not exist.

    Returns:
        A dictionary with the ``fallback`` and ``clips`` groups.
    """
    language = get_config().get("language", "ro")
    path = CONFIG_DIR / f"texts.{language}.yaml"
    if not path.exists():
        path = CONFIG_DIR / "texts.ro.yaml"
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def cfg(*keys: str, default: Any = None) -> Any:
    """Read one nested value from ``assistant.yaml``.

    Example: ``cfg("llm", "timeout_s")`` returns ``2.5``.

    Args:
        *keys: The path of keys inside the YAML document.
        default: Value returned when any key along the path is missing.

    Returns:
        The configured value, or ``default``.
    """
    node: Any = get_config()
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


@dataclass(frozen=True)
class LLMSettings:
    """Resolved LLM connection settings.

    Attributes:
        provider: ``"gemini"`` or ``"offline"`` (fixed texts only).
        api_key: The Gemini API key from ``.env``, or ``""`` when missing.
        model: The model name (e.g. a Gemini Flash model), or ``""`` when missing.
        backup_model: Model used for the one retry after a temporary error (503, 429),
            or ``""`` to retry on ``model``.
    """

    provider: str
    api_key: str
    model: str
    backup_model: str = ""

    @property
    def usable(self) -> bool:
        """True when a real LLM call can be attempted (provider, key and model set)."""
        return self.provider != "offline" and bool(self.api_key) and bool(self.model)


def llm_settings() -> LLMSettings:
    """Resolve the LLM settings from ``.env`` first, then ``assistant.yaml``.

    ``.env`` variables: ``LLM_PROVIDER`` (``gemini``), ``LLM_API_KEY``, ``LLM_MODEL``,
    optional ``LLM_BACKUP_MODEL``. Empty variables fall back to ``llm.default_provider`` /
    ``llm.default_model`` / ``llm.backup_model``.

    Returns:
        The :class:`LLMSettings` (never raises; missing values are empty strings).
    """
    provider = (os.getenv("LLM_PROVIDER") or cfg("llm", "default_provider", default="gemini")).strip().lower()
    api_key = (os.getenv("LLM_API_KEY") or "").strip()
    model = (os.getenv("LLM_MODEL") or cfg("llm", "default_model", default="") or "").strip()
    backup_model = (os.getenv("LLM_BACKUP_MODEL") or cfg("llm", "backup_model", default="") or "").strip()
    if os.getenv("PYTEST_CURRENT_TEST") and not os.getenv("DRIVEMATE_LLM_LIVE"):
        # Tests never call the real LLM, even with a key in .env: the answers would depend on the
        # network and on the model (tests/core/test_assistant_link.py failed that way). Tests that
        # need an LLM inject a fake provider; DRIVEMATE_LLM_LIVE=1 allows real calls on purpose.
        provider = "offline"
    return LLMSettings(provider=provider, api_key=api_key, model=model, backup_model=backup_model)


def poi_categories() -> list[str]:
    """Return the valid POI categories for reminders (plan K1).

    Reads the categories used in ``simulator/stops.json`` (owned by P4) when that
    file exists; otherwise uses the temporary list ``reminders.poi_categories``
    from ``assistant.yaml``.

    Returns:
        A sorted list of category names such as ``["cafe", "fuel", ...]``.
    """
    stops_file = REPO_ROOT / "simulator" / "stops.json"
    if stops_file.exists():
        try:
            data = json.loads(stops_file.read_text(encoding="utf-8"))
            stops = data.get("stops", data) if isinstance(data, dict) else data
            found = {stop.get("category") for stop in stops if isinstance(stop, dict)}
            found.discard(None)
            if found:
                return sorted(found)
        except (OSError, ValueError, AttributeError):
            pass  # malformed or unexpected format: use the configured list
    return sorted(cfg("reminders", "poi_categories", default=[]))


def reload() -> None:
    """Forget cached configuration so the next read sees changed files (tests)."""
    get_config.cache_clear()
    get_texts.cache_clear()
