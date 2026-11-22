"""Manual LLM test: run scene fixtures through the real assistant and print the result.

Used for the Friday-night check "primul apel LLM cu acțiuni validate" and for
tuning the prompt during rehearsals.

Run (from the repo root, with LLM_PROVIDER / LLM_API_KEY / LLM_MODEL in .env)::

    .venv/Scripts/python -m assistant.dev.try_llm                     # all scenes
    .venv/Scripts/python -m assistant.dev.try_llm scene4_passenger_phone
    .venv/Scripts/python -m assistant.dev.try_llm --say "Pune ceva muzică"

For each scene it prints: the state summary sent to the LLM, the accepted actions,
the rejected ones with the reason, the source (LLM / RULE) and the latencies
(time to first token, total) that the plan targets (< 2 s to first speech).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time

from assistant.client import AssistantClient
from assistant.contract import Event, State
from assistant.settings import REPO_ROOT, llm_settings
from assistant.summary import summarize

FIXTURES = REPO_ROOT / "tests" / "assistant" / "fixtures"


def _merge(base: dict, overrides: dict) -> dict:
    """Recursive dict merge (lists replaced)."""
    out = dict(base)
    for key, value in overrides.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load(scene: str) -> tuple[str, Event, State]:
    """Return ``(description, event, state)`` for a scene fixture."""
    base = json.loads((FIXTURES / "state_example.json").read_text(encoding="utf-8"))
    data = json.loads((FIXTURES / "scenes" / f"{scene}.json").read_text(encoding="utf-8"))
    return data["description"], Event.model_validate(data["event"]), State.model_validate(_merge(base, data["state_overrides"]))  # noqa: E501


async def run(scenes: list[str], say: str | None) -> None:
    """Run the given scenes (or one free utterance) and print the results."""
    settings = llm_settings()
    print(f"Provider: {settings.provider} | model: {settings.model or '-'} | key set: {bool(settings.api_key)}")
    client = AssistantClient()
    if say:
        base = json.loads((FIXTURES / "state_example.json").read_text(encoding="utf-8"))
        jobs = [("free utterance", Event(type="driver_speech", ts=time.time(), data={"text": say}), State.model_validate(base))]  # noqa: E501
    else:
        jobs = [load(name) for name in scenes]
    for description, event, state in jobs:
        client.reset()
        print("\n" + "=" * 78 + f"\n{description}\n" + "-" * 78)
        print(summarize(state, event))
        actions = await client.handle_event(event, state, now=event.ts)
        info = client.last_result
        print("-" * 78)
        if info.error:
            print(f"LLM error: {info.error}")
        print(f"source={info.source} reason={info.reason} total={info.latency_ms:.0f} ms "
              f"ttft={info.llm_ttft_ms and round(info.llm_ttft_ms)} ms llm_total={info.llm_total_ms and round(info.llm_total_ms)} ms")  # noqa: E501
        for action in actions:
            print("  ACCEPTED", action.model_dump_json(exclude_none=True, exclude_defaults=True))
        for raw, reason in info.rejected:
            print("  REJECTED", reason, raw)


def main() -> None:
    """Command-line entry point."""
    # Windows consoles default to cp1252, which cannot print Romanian diacritics.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run scene fixtures through the DriveMate assistant.")
    parser.add_argument("scenes", nargs="*", help="scene names (default: all)")
    parser.add_argument("--say", help="a free driver utterance instead of scenes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    scenes = args.scenes or sorted(p.stem for p in (FIXTURES / "scenes").glob("*.json"))
    asyncio.run(run(scenes, args.say))


if __name__ == "__main__":
    main()
