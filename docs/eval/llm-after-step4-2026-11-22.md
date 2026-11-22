# Assistant LLM evaluation: after-step4 (2026-11-22)

Model `gemini-3.5-flash-lite` (retry `gemini-3.1-flash-lite`), `max_output_tokens` 1024, `thinking_level` minimal, deadline 2.5 s. 46 cases x 2 runs = 92 runs. YouTube search stubbed. Overrides: none. Produced by `assistant/dev/eval_llm.py`.

## Summary

| Outcome | Runs | Share |
|---|---|---|
| `ok` | 88 | 96% |
| `fallback:silent_on_request` | 3 | 3% |
| `wrong` | 1 | 1% |

- Driver got a correct answer: **96%**; a fixed text instead of the LLM: **3%**.
- Answer latency p50 / p95: 827.0 / 1123.0 ms; LLM first token p50 813.0 ms; LLM complete p50 / p95: 843.0 / 1131.0 ms.
- LLM stream end reasons: {'STOP': 84} (`cancelled` = stopped by the deadline); thinking tokens p50 when the model thought: None.

## By group

| Group | ok | wrong | fixed text |
|---|---|---|---|
| alerts | 8 | 0 | 0 |
| cause | 10 | 0 | 0 |
| media | 14 | 0 | 0 |
| messages | 10 | 0 | 0 |
| reminders | 9 | 0 | 1 |
| stops | 9 | 0 | 1 |
| talk | 11 | 0 | 1 |
| trip | 17 | 1 | 0 |

## Runs that failed

| Case | Driver said | Outcome | Problem | Assistant said |
|---|---|---|---|---|
| `time_driving` #1 | De cât timp conduc? | `wrong` | none of ['speak'] in ['ask'] | Conduci de 74 de minute, Andrei. Mai ai 20 de minute până la destinație. Te mai ajut cu ceva? |
| `reminder_exists` #2 | Amintește-mi să iau lichid de parbriz la benzinărie. | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `pharmacy` #2 | Unde e cea mai apropiată farmacie? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `hello` #1 | Salut DriveMate! | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |

## To judge by hand (content cannot be checked automatically)

| Case | Driver said | Assistant said |
|---|---|---|
| `next_town_no_map` #1 | Ce oraș urmează? | Nu știu orașele de pe traseu. Următoarea oprire e OMV, în 12 km. |
| `next_town_no_map` #2 | Ce oraș urmează? | Nu știu orașele de pe traseu. Următoarea oprire e OMV, în 12 km. |
| `pharmacy` #1 | Unde e cea mai apropiată farmacie? | Nu văd o farmacie pe traseu. Îți amintesc la prima farmacie? |
| `pharmacy` #2 | Unde e cea mai apropiată farmacie? | Scuze, n-am înțeles. Poți repeta? |
| `why_alert` #1 | De ce m-ai alertat adineauri? | Nu am înregistrat nicio alertă pe traseul acesta. Alertele vin de la camera de monitorizare a atenției. |
| `why_alert` #2 | De ce m-ai alertat adineauri? | Nu am înregistrat nicio alertă pe traseul acesta. Alertele vin de la camerele care monitorizează atenția. |
| `what_time` #1 | Cât e ceasul? | Este ora 23:00. |
| `what_time` #2 | Cât e ceasul? | Este ora 23:00. |
