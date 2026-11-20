"""pytest configuration for the P3 assistant tests.

* Puts the repository root on ``sys.path`` so ``import assistant`` works no matter
  where pytest is started from. Helpers live in ``p3_helpers.py``.
* Points the music module at ``fixtures/media_catalog_test.json`` (20 synthetic
  tracks, including kid_safe ones) so the tests do not depend on the real catalog,
  which changes whenever the team adds or removes mp3 files.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_CATALOG = Path(__file__).resolve().parent / "fixtures" / "media_catalog_test.json"


@pytest.fixture(autouse=True)
def _test_media_catalog(monkeypatch):
    """Use the synthetic test catalog for every test (restored afterwards)."""
    from assistant import music
    from assistant.settings import get_config

    monkeypatch.setitem(get_config()["music"], "catalog", str(TEST_CATALOG))
    music.load_catalog.cache_clear()
    yield
    music.load_catalog.cache_clear()
