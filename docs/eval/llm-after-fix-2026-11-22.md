# Assistant LLM evaluation: after-fix (2026-11-22)

Model `gemini-3.5-flash-lite` (retry `gemini-3.1-flash-lite`), `max_output_tokens` 1024, `thinking_level` minimal, deadline 2.5 s. 41 cases x 3 runs = 123 runs. YouTube search stubbed. Overrides: none. Produced by `assistant/dev/eval_llm.py`.

## Summary

| Outcome | Runs | Share |
|---|---|---|
| `ok` | 123 | 100% |

- Driver got a correct answer: **100%**; a fixed text instead of the LLM: **0%**.
- Answer latency p50 / p95: 790.0 / 1035.0 ms; LLM first token p50 750.0 ms; LLM complete p50 / p95: 797.0 / 1077.0 ms.
- LLM stream end reasons: {'STOP': 111} (`cancelled` = stopped by the deadline); thinking tokens p50 when the model thought: None.

## By group

| Group | ok | wrong | fixed text |
|---|---|---|---|
| alerts | 12 | 0 | 0 |
| media | 21 | 0 | 0 |
| messages | 15 | 0 | 0 |
| reminders | 15 | 0 | 0 |
| stops | 15 | 0 | 0 |
| talk | 18 | 0 | 0 |
| trip | 27 | 0 | 0 |

## Runs that failed

| Case | Driver said | Outcome | Problem | Assistant said |
|---|---|---|---|---|

## To judge by hand (content cannot be checked automatically)

| Case | Driver said | Assistant said |
|---|---|---|
| `next_town_no_map` #1 | Ce oraș urmează? | Nu știu orașele de pe traseu. Următoarea oprire e OMV, în 12 km. |
| `next_town_no_map` #2 | Ce oraș urmează? | Nu știu orașele de pe traseu. Următoarea oprire e OMV, în 12 km. |
| `next_town_no_map` #3 | Ce oraș urmează? | Nu știu orașele de pe traseu. Următoarea oprire e OMV, în 12 km. |
| `pharmacy` #1 | Unde e cea mai apropiată farmacie? | Nu văd o farmacie pe traseu. Îți amintesc la prima farmacie? Bine? |
| `pharmacy` #2 | Unde e cea mai apropiată farmacie? | Nu văd o farmacie pe traseu. Îți amintesc la prima farmacie? Bine? |
| `pharmacy` #3 | Unde e cea mai apropiată farmacie? | Nu văd o farmacie pe traseu. Îți amintesc la prima farmacie? |
| `why_alert` #1 | De ce m-ai alertat adineauri? | Nu am înregistrat nicio alertă în această călătorie. Alertele vin de la sistemul de monitorizare a atenției. |
| `why_alert` #2 | De ce m-ai alertat adineauri? | Nu am înregistrat nicio alertă pe parcursul acestui drum. Alertele vin de la sistemul de monitorizare a atenției. |
| `why_alert` #3 | De ce m-ai alertat adineauri? | Nu am înregistrat nicio alertă pe acest traseu. |
| `what_time` #1 | Cât e ceasul? | Este ora 23:00. |
| `what_time` #2 | Cât e ceasul? | Este ora 23:00. |
| `what_time` #3 | Cât e ceasul? | Este ora 23:00. |
