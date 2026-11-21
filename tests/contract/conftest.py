"""Contract tests of the perception (P1) <-> core (P2) boundary, on golden JSON messages (tests/contract/fixtures/).

* ``test_core_reads_p1.py`` needs only ``shared`` + ``core`` (runs in the core job too): every message P1 sends is
  parsed by P2's contract and taken by core's engine without loss.
* ``test_p1_speaks_contract.py`` needs the perception runtime: P1 still produces exactly the golden messages, handles
  every command core sends, and announces every field the contract does not declare yet.

Regenerate the fixtures with ``python tests/contract/make_fixtures.py`` after a deliberate change, and tell the other
side (CONTRACT texts: docs/perception.md §9).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FRAME_FIXTURES = ("p1_frame_full", "p1_frame_strict", "p1_frame_cameras_down")


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
