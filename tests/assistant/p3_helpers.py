"""Shared test helpers for the P3 assistant (imported by the test files as ``p3_helpers``).

The name is unique on purpose: other roles keep their own tests in tests/<module>/,
so a generic name such as ``helpers`` could clash on ``sys.path``.

Fixtures (roluri/P3: "Stările din tests/assistant/fixtures/*.json"):

* ``fixtures/state_example.json`` - the full example state of plan section 7;
* ``fixtures/scenes/<name>.json`` - one demo situation each: an ``event`` plus
  ``state_overrides`` deep-merged on top of the example state.

Fake LLM providers let the client be tested without network or key.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant.contract import Event, State  # noqa: E402
from assistant.llm.base import LLMError, LLMProvider, LLMResult, TextCallback  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def deep_merge(base: dict, overrides: dict) -> dict:
    """Return ``base`` with ``overrides`` merged recursively (lists are replaced)."""
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def base_state_dict() -> dict:
    """The example state of plan section 7, as a plain dict."""
    return json.loads((FIXTURES / "state_example.json").read_text(encoding="utf-8"))


def make_state(**overrides: Any) -> State:
    """Example state with keyword overrides deep-merged (``make_state(safety={"level": "P1"})``)."""
    return State.model_validate(deep_merge(base_state_dict(), overrides))


def load_scene(name: str) -> tuple[Event, State]:
    """Load ``fixtures/scenes/<name>.json`` as ``(event, state)``."""
    scene = json.loads((FIXTURES / "scenes" / f"{name}.json").read_text(encoding="utf-8"))
    state = State.model_validate(deep_merge(base_state_dict(), scene["state_overrides"]))
    return Event.model_validate(scene["event"]), state


def scene_names() -> list[str]:
    """Names of all scene fixtures (file stems)."""
    return sorted(p.stem for p in (FIXTURES / "scenes").glob("*.json"))


class FakeProvider(LLMProvider):
    """LLM provider returning a fixed JSON answer, optionally streamed in chunks / slowly."""

    name = "fake"

    def __init__(self, answer: Any, delay_s: float = 0.0, chunk: int = 0, error: bool = False) -> None:
        """Args:
            answer: dict (serialised to JSON) or raw string returned by the "model".
            delay_s: Seconds to wait before answering (to test the 2.5 s deadline).
            chunk: If > 0, stream the answer in chunks of this many characters.
            error: If True, raise :class:`LLMError` instead of answering.
        """
        self.answer = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        self.delay_s = delay_s
        self.chunk = chunk
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system: str, user: str, on_text: Optional[TextCallback] = None) -> LLMResult:
        """Return the configured answer (see constructor)."""
        self.calls.append((system, user))
        if self.error:
            raise LLMError("fake failure")
        await asyncio.sleep(self.delay_s)
        if on_text is not None and self.chunk:
            for end in range(self.chunk, len(self.answer) + self.chunk, self.chunk):
                on_text(self.answer[:end])
        return LLMResult(text=self.answer, ttft_ms=1.0, total_ms=2.0)

