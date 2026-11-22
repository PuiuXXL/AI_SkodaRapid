# Assistant LLM evaluation: after-greeting (2026-11-22)

Model `gemini-3.5-flash-lite` (retry `gemini-3.1-flash-lite`), `max_output_tokens` 1024, `thinking_level` minimal, deadline 2.5 s. 46 cases x 2 runs = 92 runs. YouTube search stubbed. Overrides: none. Produced by `assistant/dev/eval_llm.py`.

## Summary

| Outcome | Runs | Share |
|---|---|---|
| `ok` | 92 | 100% |

- Driver got a correct answer: **100%**; a fixed text instead of the LLM: **0%**.
- Answer latency p50 / p95: 786.0 / 1053.0 ms; LLM first token p50 757.0 ms; LLM complete p50 / p95: 790.0 / 1052.0 ms.
- LLM stream end reasons: {'STOP': 84} (`cancelled` = stopped by the deadline); thinking tokens p50 when the model thought: None.

## By group

| Group | ok | wrong | fixed text |
|---|---|---|---|
| alerts | 8 | 0 | 0 |
| cause | 10 | 0 | 0 |
| media | 14 | 0 | 0 |
| messages | 10 | 0 | 0 |
| reminders | 10 | 0 | 0 |
| stops | 10 | 0 | 0 |
| talk | 12 | 0 | 0 |
| trip | 18 | 0 | 0 |

## Runs that failed

| Case | Driver said | Outcome | Problem | Assistant said |
|---|---|---|---|---|

## To judge by hand (content cannot be checked automatically)

| Case | Driver said | Assistant said |
|---|---|---|
| `next_town_no_map` #1 | Ce oraș urmează? | Nu știu orașele de pe traseu. Următoarea oprire e OMV, în 12 km. |
| `next_town_no_map` #2 | Ce oraș urmează? | Nu știu orașele de pe traseu. Următoarea oprire e OMV, în 12 km. |
| `pharmacy` #1 | Unde e cea mai apropiată farmacie? | Nu văd o farmacie pe traseu. Îți amintesc la prima farmacie? |
| `pharmacy` #2 | Unde e cea mai apropiată farmacie? | Nu văd o farmacie pe traseu. Îți amintesc la prima farmacie? Bine? |
| `why_alert` #1 | De ce m-ai alertat adineauri? | Nu am înregistrat nicio alertă pe traseul de până acum. Alertele vin de la sistemul de monitorizare a atenției. |
| `why_alert` #2 | De ce m-ai alertat adineauri? | Nu am înregistrat nicio alertă pe traseul de până acum. Alertele vin de la sistemul de monitorizare a atenției. |
| `what_time` #1 | Cât e ceasul? | Este ora 23:00, Andrei. |
| `what_time` #2 | Cât e ceasul? | Este ora 23:00. |
