"""pytest configuration for the P2 core tests: puts the repository root on ``sys.path`` so ``import shared`` and
``import core`` work no matter where pytest is started from.

Every test also runs with P3's assistant offline and with an empty profiles folder for it, so the results do not
depend on the laptop: a ``LLM_API_KEY`` in ``.env`` would otherwise make ``AssistantClient()`` call Gemini instead of
using the fixed texts the tests expect, and a real ``profiles/andrei/profile.json`` would change the assistant's
interaction preferences (``assistant/preferences.py``).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _assistant_offline_and_isolated(monkeypatch, tmp_path):
    """No LLM call and no repo profile for P3's assistant (skipped when P3's code is not importable)."""
    monkeypatch.setenv("LLM_PROVIDER", "offline")
    try:
        from assistant import preferences
    except Exception:  # noqa: BLE001 - core runs without the assistant; nothing to isolate then
        yield
        return
    profiles = tmp_path / "assistant-profiles"
    profiles.mkdir()
    monkeypatch.setattr(preferences, "PROFILES_DIR", profiles)
    preferences.store.reset()
    yield
    preferences.store.reset()
