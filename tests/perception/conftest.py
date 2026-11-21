"""Shared pytest setup for P1 perception tests.

Markers (registered here, so the shared repo config stays untouched):
  * ``models``: needs downloaded model files in perception/models/ (skipped in CI)
  * ``camera``: needs a real camera (skipped in CI)
  * ``realdata``: needs a recorded, labelled session in data/features/ (local only, never committed). Skipped
    automatically when there is none, so a fresh clone and CI pass without deselecting it.

CI runs: ``python -m pytest tests/perception -m "not models and not camera"``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `import perception` work with plain `pytest` too, not only `python -m pytest`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_FEATURES_DIR = _REPO_ROOT / "data" / "features"


def has_real_session() -> bool:
    """At least one recorded session with labels in data/features/."""
    return _FEATURES_DIR.is_dir() and any((d / "labels.jsonl").exists() for d in _FEATURES_DIR.iterdir())


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "models: needs model files in perception/models/ (skipped in CI)")
    config.addinivalue_line("markers", "camera: needs a real camera (skipped in CI)")
    config.addinivalue_line(
        "markers", "realdata: needs a recorded labelled session in data/features (auto-skipped without one)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if has_real_session():
        return
    skip = pytest.mark.skip(reason="no recorded labelled session in data/features (run scripts/eval_eyes.py)")
    for item in items:
        if "realdata" in item.keywords:
            item.add_marker(skip)
