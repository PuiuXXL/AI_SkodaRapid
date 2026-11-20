"""Shared pytest setup for P1 perception tests.

Markers (registered here, so the shared repo config stays untouched):
  * ``models``: needs downloaded model files in perception/models/ (skipped in CI)
  * ``camera``: needs a real camera (skipped in CI)

  * ``data``: needs a recorded session in data/features/ (skipped in CI)

CI runs: ``python -m pytest tests/perception -m "not models and not camera and not data"``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `import perception` work with plain `pytest` too, not only `python -m pytest`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "models: needs model files in perception/models/ (skipped in CI)")
    config.addinivalue_line("markers", "camera: needs a real camera (skipped in CI)")
    config.addinivalue_line("markers", "data: needs a recorded session in data/features (skipped in CI)")
