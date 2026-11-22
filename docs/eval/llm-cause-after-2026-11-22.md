# Assistant LLM evaluation: cause-after (2026-11-22)

Model `gemini-3.5-flash-lite` (retry `gemini-3.1-flash-lite`), `max_output_tokens` 1024, `thinking_level` minimal, deadline 2.5 s. 5 cases x 5 runs = 25 runs. YouTube search stubbed. Overrides: none. Produced by `assistant/dev/eval_llm.py`.

## Summary

| Outcome | Runs | Share |
|---|---|---|
| `ok` | 25 | 100% |

- Driver got a correct answer: **100%**; a fixed text instead of the LLM: **0%**.
- Answer latency p50 / p95: 848.0 / 1199.0 ms; LLM first token p50 808.0 ms; LLM complete p50 / p95: 846.0 / 1185.0 ms.
- LLM stream end reasons: {'STOP': 25} (`cancelled` = stopped by the deadline); thinking tokens p50 when the model thought: None.

## By group

| Group | ok | wrong | fixed text |
|---|---|---|---|
| cause | 25 | 0 | 0 |

## Runs that failed

| Case | Driver said | Outcome | Problem | Assistant said |
|---|---|---|---|---|
