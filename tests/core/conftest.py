"""pytest configuration for the P2 core tests: puts the repository root on ``sys.path`` so ``import shared`` and
``import core`` work no matter where pytest is started from."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
