"""Batch evaluation of the assistant on free driver requests (P3 plan, phase 0: the baseline).

Every case of ``assistant/dev/eval_cases.yaml`` goes through the REAL assistant pipeline
(``AssistantClient.handle_event``: policies -> LLM -> validation -> fallback), repeated
``--repeat`` times because the LLM is not deterministic. Each run is classified:

* ``ok``                  the answer has the expected actions / words and the expected source;
* ``wrong``               the LLM answered, but not what the case expects (details in the report);
* ``fallback:<reason>``   the driver got a fixed text instead of the LLM: ``truncated`` (the model
  stopped at ``max_output_tokens``, often because its "thinking" used them), ``invalid_json``,
  ``silent_on_request``, ``timeout``, ``llm_error``, ``all_rejected``, ``policy:*``.

The YouTube search is stubbed by default (it is not what is measured and it costs 1-5 s);
``--real-search`` uses the real one. Nothing is spoken and nothing reaches core.

Run (from the repo root, LLM key in .env)::

    .venv/Scripts/python -m assistant.dev.eval_llm                       # all cases, 2 runs each
    .venv/Scripts/python -m assistant.dev.eval_llm --repeat 3 --label after-fix
    .venv/Scripts/python -m assistant.dev.eval_llm --only eta hungry      # ids or groups

Writes ``docs/eval/llm-<label>-<date>.json`` (every run) and ``.md`` (summary + failures).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from assistant import media_search
from assistant.client import AssistantClient
from assistant.contract import Event, State
from assistant.llm import make_provider
from assistant.llm.base import LLMProvider, LLMResult, TextCallback
from assistant.settings import REPO_ROOT, cfg, llm_settings
from assistant.textutil import normalize

CASES_FILE = Path(__file__).resolve().parent / "eval_cases.yaml"
BASE_STATE = REPO_ROOT / "tests" / "assistant" / "fixtures" / "state_example.json"
OUT_DIR = REPO_ROOT / "docs" / "eval"


# --- recording the raw LLM answer (text, finish reason, tokens) -------------------------------------------------------


@dataclass
class RawCall:
    model: str = ""
    text: str = ""
    finish: Optional[str] = None  # None = the stream never ended (cancelled by the deadline)
    out_tokens: Optional[int] = None
    thought_tokens: Optional[int] = None


class RecordingProvider(LLMProvider):
    """Wraps the real provider and keeps every raw answer of the current run."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.calls: list[RawCall] = []
        self._patch_stream()

    @property
    def available(self) -> bool:  # type: ignore[override]
        return self.inner.available

    @property
    def retry_label(self) -> str:  # type: ignore[override]
        return getattr(self.inner, "retry_label", self.inner.name)

    def _patch_stream(self) -> None:
        """Gemini only: read finish_reason / usage from the last streamed chunk (not exposed by the provider)."""
        models = getattr(getattr(getattr(self.inner, "_client", None), "aio", None), "models", None)
        if models is None:
            return
        original = models.generate_content_stream
        calls = self.calls

        async def wrapped(**kwargs: Any) -> Any:
            record = RawCall(model=str(kwargs.get("model", "")))
            calls.append(record)
            stream = await original(**kwargs)

            async def chunks() -> Any:
                last = None
                async for chunk in stream:
                    last = chunk
                    record.text += chunk.text or ""
                    yield chunk
                if last is not None:
                    candidates = getattr(last, "candidates", None) or []
                    reason = getattr(candidates[0], "finish_reason", None) if candidates else None
                    record.finish = getattr(reason, "name", None) or (str(reason) if reason else None)
                    usage = getattr(last, "usage_metadata", None)
                    record.out_tokens = getattr(usage, "candidates_token_count", None)
                    record.thought_tokens = getattr(usage, "thoughts_token_count", None)

            return chunks()

        models.generate_content_stream = wrapped

    async def generate(self, system: str, user: str, on_text: Optional[TextCallback] = None) -> LLMResult:
        return await self.inner.generate(system, user, on_text)

    async def generate_retry(self, system: str, user: str, on_text: Optional[TextCallback] = None) -> LLMResult:
        return await self.inner.generate_retry(system, user, on_text)


# --- YouTube stub -------------------------------------------------------------------------------------------------------


async def _fake_search(query: str, kind: str = "music", kid_safe: bool = False) -> list[media_search.MediaResult]:
    """Three fixed results: the evaluation measures the LLM, not YouTube."""
    found = [media_search.MediaResult(video_id=f"evalvid{i:04d}", title=f"{query} {i}", channel="eval",
                                      duration_s=240, kid_safe=True) for i in range(1, 4)]
    media_search.remember(found)
    return found


# --- cases ------------------------------------------------------------------------------------------------------------


def _merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in patch.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def build_state(base: dict, presets: dict, overrides: dict | None) -> State:
    data = base
    for name in (overrides or {}).get("presets", []):
        data = _merge(data, presets[name])
    data = _merge(data, (overrides or {}).get("state", {}))
    return State.model_validate(data)


@dataclass
class Run:
    case: str
    group: str
    text: str
    attempt: int
    outcome: str
    source: str
    reason: str
    latency_ms: float
    llm_ttft_ms: Optional[float]
    llm_total_ms: Optional[float]
    llm_types: list[str]
    final_types: list[str]
    said: list[str]
    problems: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    raw_calls: list[dict] = field(default_factory=list)
    review: bool = False
    error: Optional[str] = None


def _llm_types(calls: list[RawCall]) -> list[str]:
    """Action types in the last raw LLM answer that parses (empty when none does)."""
    for call in reversed(calls):
        try:
            payload = json.loads(call.text)
        except ValueError:
            continue
        actions = payload.get("actions", []) if isinstance(payload, dict) else []
        return [str(a.get("type")) for a in actions if isinstance(a, dict)]
    return []


def evaluate(case: dict, info: Any, actions: list, calls: list[RawCall]) -> tuple[str, list[str]]:
    expect = case.get("expect", {})
    want_source = expect.get("source", "LLM")
    final = [a for a in actions if a.reason != "follow_up"]
    types = set(_llm_types(calls)) | {a.type for a in final}
    said = " ".join(normalize(a.text if a.type == "speak" else a.question or "") for a in final
                    if a.type in ("speak", "ask"))

    if info.source != want_source:
        if want_source == "LLM":
            reason = info.reason
            if reason == "invalid_json" and calls and calls[-1].finish == "MAX_TOKENS":
                reason = "truncated"
            return f"fallback:{reason}", [f"expected the LLM, got a fixed text ({info.reason})"]
        return "wrong", [f"expected source {want_source}, got {info.source} ({info.reason})"]

    problems = []
    if expect.get("any_types") and not types & set(expect["any_types"]):
        problems.append(f"none of {expect['any_types']} in {sorted(types)}")
    missing = [t for t in expect.get("all_types", []) if t not in types]
    if missing:
        problems.append(f"missing {missing} (got {sorted(types)})")
    banned = [t for t in expect.get("none_types", []) if t in types]
    if banned:
        problems.append(f"must not contain {banned}")
    mentions = [normalize(str(m)) for m in expect.get("mentions", [])]
    if mentions and not any(m in said for m in mentions):
        problems.append(f"says none of {expect['mentions']}")
    return ("wrong" if problems else "ok"), problems


async def run_case(case: dict, attempt: int, base: dict, presets: dict, provider: RecordingProvider) -> Run:
    state = build_state(base, presets, case.get("overrides"))
    now = time.time()
    event = Event(type="driver_speech", ts=now, data={"text": case["text"]})
    provider.calls.clear()
    client = AssistantClient(provider=provider)  # fresh memory and policies for every run
    actions = await client.handle_event(event, state, now=now)
    info = client.last_result
    calls = list(provider.calls)
    outcome, problems = evaluate(case, info, actions, calls)
    final = [a for a in actions if a.reason != "follow_up"]
    return Run(
        case=case["id"], group=case.get("group", ""), text=case["text"], attempt=attempt, outcome=outcome,
        source=info.source, reason=info.reason, latency_ms=round(info.latency_ms, 1),
        llm_ttft_ms=info.llm_ttft_ms and round(info.llm_ttft_ms, 1),
        llm_total_ms=info.llm_total_ms and round(info.llm_total_ms, 1),
        llm_types=_llm_types(calls), final_types=[a.type for a in final],
        said=[(a.text if a.type == "speak" else a.question) or "" for a in final if a.type in ("speak", "ask")],
        problems=problems, rejected=[f"{r}: {json.dumps(raw, ensure_ascii=False, default=str)[:160]}"
                                     for raw, r in info.rejected],
        raw_calls=[asdict(c) for c in calls], review=bool(case.get("expect", {}).get("review")), error=info.error,
    )


# --- report -----------------------------------------------------------------------------------------------------------


def _pct(n: int, total: int) -> str:
    return f"{100.0 * n / total:.0f}%" if total else "-"


def _quantile(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1], 0)


def summarize_runs(runs: list[Run]) -> dict[str, Any]:
    outcomes = Counter(r.outcome for r in runs)
    llm = [r.llm_total_ms for r in runs if r.llm_total_ms]
    ttft = [r.llm_ttft_ms for r in runs if r.llm_ttft_ms]
    total = [r.latency_ms for r in runs]
    finishes = Counter(c["finish"] or "cancelled" for r in runs for c in r.raw_calls)
    thoughts = [c["thought_tokens"] for r in runs for c in r.raw_calls if c["thought_tokens"]]
    by_group: dict[str, Counter] = defaultdict(Counter)
    for r in runs:
        by_group[r.group][r.outcome] += 1
    return {
        "runs": len(runs),
        "outcomes": dict(outcomes.most_common()),
        "ok_rate": round(outcomes["ok"] / len(runs), 3) if runs else None,
        "fixed_text_rate": round(sum(n for o, n in outcomes.items() if o.startswith("fallback:")) / len(runs), 3)
        if runs else None,
        "latency_ms": {"answer_p50": _quantile(total, 0.5), "answer_p95": _quantile(total, 0.95),
                       "llm_ttft_p50": _quantile(ttft, 0.5), "llm_total_p50": _quantile(llm, 0.5),
                       "llm_total_p95": _quantile(llm, 0.95)},
        "llm_finish_reasons": dict(finishes),
        "thought_tokens_p50": _quantile([float(t) for t in thoughts], 0.5),
        "by_group": {g: dict(c) for g, c in sorted(by_group.items())},
    }


def write_markdown(path: Path, meta: dict, summary: dict, runs: list[Run]) -> None:
    lines = [
        f"# Assistant LLM evaluation: {meta['label']} ({meta['date']})",
        "",
        f"Model `{meta['model']}` (retry `{meta['backup_model']}`), `max_output_tokens` {meta['max_output_tokens']}, "
        f"`thinking_level` {meta['thinking_level']}, deadline {meta['timeout_s']} s. "
        f"{meta['cases']} cases x {meta['repeat']} runs = {summary['runs']} runs. YouTube search "
        f"{'real' if meta['real_search'] else 'stubbed'}. Overrides: {meta['overrides'] or 'none'}. "
        f"Produced by `assistant/dev/eval_llm.py`.",
        "",
        "## Summary",
        "",
        "| Outcome | Runs | Share |",
        "|---|---|---|",
    ]
    for outcome, n in summary["outcomes"].items():
        lines.append(f"| `{outcome}` | {n} | {_pct(n, summary['runs'])} |")
    lat = summary["latency_ms"]
    lines += [
        "",
        f"- Driver got a correct answer: **{_pct(summary['outcomes'].get('ok', 0), summary['runs'])}**; "
        f"a fixed text instead of the LLM: **{summary['fixed_text_rate']:.0%}**.",
        f"- Answer latency p50 / p95: {lat['answer_p50']} / {lat['answer_p95']} ms; LLM first token p50 "
        f"{lat['llm_ttft_p50']} ms; LLM complete p50 / p95: {lat['llm_total_p50']} / {lat['llm_total_p95']} ms.",
        f"- LLM stream end reasons: {summary['llm_finish_reasons']} (`cancelled` = stopped by the deadline); "
        f"thinking tokens p50 when the model thought: {summary['thought_tokens_p50']}.",
        "",
        "## By group",
        "",
        "| Group | " + " | ".join(["ok", "wrong", "fixed text"]) + " |",
        "|---|---|---|---|",
    ]
    for group, counts in summary["by_group"].items():
        fixed = sum(n for o, n in counts.items() if o.startswith("fallback:"))
        lines.append(f"| {group} | {counts.get('ok', 0)} | {counts.get('wrong', 0)} | {fixed} |")
    lines += ["", "## Runs that failed", "", "| Case | Driver said | Outcome | Problem | Assistant said |",
              "|---|---|---|---|---|"]
    for r in runs:
        if r.outcome == "ok":
            continue
        said = " / ".join(r.said) or "-"
        lines.append(f"| `{r.case}` #{r.attempt} | {r.text} | `{r.outcome}` | {'; '.join(r.problems)} | {said} |")
    review = [r for r in runs if r.review]
    if review:
        lines += ["", "## To judge by hand (content cannot be checked automatically)", "",
                  "| Case | Driver said | Assistant said |", "|---|---|---|"]
        for r in review:
            lines.append(f"| `{r.case}` #{r.attempt} | {r.text} | {' / '.join(r.said) or '-'} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- main -------------------------------------------------------------------------------------------------------------


def apply_overrides(pairs: list[str]) -> None:
    """``llm.max_output_tokens=1024`` -> assistant.yaml value for this run only (the file is not changed)."""
    from assistant.settings import get_config

    for pair in pairs:
        dotted, _, raw = pair.partition("=")
        node = get_config()
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node.setdefault(key, {})
        node[leaf] = yaml.safe_load(raw)


async def main_async(args: argparse.Namespace) -> int:
    apply_overrides(args.set or [])
    spec = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    cases = spec["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only or c.get("group") in args.only]
    base = json.loads(BASE_STATE.read_text(encoding="utf-8"))
    settings = llm_settings()
    inner = make_provider()
    if not inner.available:
        print("No usable LLM (LLM_PROVIDER / LLM_API_KEY / LLM_MODEL in .env): nothing to evaluate.")
        return 2
    provider = RecordingProvider(inner)
    if not args.real_search:
        media_search.search = _fake_search  # type: ignore[assignment]

    print(f"Model {settings.model} | {len(cases)} cases x {args.repeat} runs")
    runs: list[Run] = []
    for case in cases:
        for attempt in range(1, args.repeat + 1):
            run = await run_case(case, attempt, base, spec.get("presets", {}), provider)
            runs.append(run)
            mark = "OK " if run.outcome == "ok" else "XX "
            print(f"{mark}{run.case:<20} #{attempt} {run.outcome:<28} {run.latency_ms:>6.0f} ms  "
                  f"{' / '.join(run.said)[:90]}")
            if run.problems and run.outcome == "wrong":
                print(f"    -> {'; '.join(run.problems)}")
            await asyncio.sleep(args.delay)

    summary = summarize_runs(runs)
    date = time.strftime("%Y-%m-%d")
    meta = {
        "label": args.label, "date": date, "model": settings.model, "backup_model": settings.backup_model,
        "max_output_tokens": cfg("llm", "max_output_tokens"), "thinking_level": cfg("llm", "thinking_level"),
        "thinking_budget": cfg("llm", "thinking_budget"), "timeout_s": cfg("llm", "timeout_s"),
        "temperature": cfg("llm", "temperature"), "cases": len(cases), "repeat": args.repeat,
        "real_search": args.real_search, "overrides": args.set or [],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.out_dir / f"llm-{args.label}-{date}"
    stem.with_suffix(".json").write_text(json.dumps({"meta": meta, "summary": summary,
                                                     "runs": [asdict(r) for r in runs]},
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(stem.with_suffix(".md"), meta, summary, runs)
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nReport: {stem.with_suffix('.md')}")
    return 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Evaluate the DriveMate assistant on free driver requests.")
    parser.add_argument("--only", nargs="*", help="case ids or groups (default: all)")
    parser.add_argument("--repeat", type=int, default=2, help="runs per case (the LLM is not deterministic)")
    parser.add_argument("--label", default="baseline", help="name in the report file")
    parser.add_argument("--delay", type=float, default=0.3, help="seconds between calls (rate limit)")
    parser.add_argument("--real-search", action="store_true", help="use the real YouTube search")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--set", nargs="*", metavar="KEY=VALUE",
                        help="assistant.yaml override for this run, e.g. llm.max_output_tokens=1024")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
