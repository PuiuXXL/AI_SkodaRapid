# Assistant LLM evaluation: after-deadline (2026-11-22)

Model `gemini-3.5-flash-lite` (retry `gemini-3.1-flash-lite`), `max_output_tokens` 1024, `thinking_level` minimal, deadline 2.5 s. 46 cases x 2 runs = 92 runs. YouTube search stubbed. Overrides: none. Produced by `assistant/dev/eval_llm.py`.

## Summary

| Outcome | Runs | Share |
|---|---|---|
| `ok` | 87 | 95% |
| `fallback:silent_on_request` | 4 | 4% |
| `wrong` | 1 | 1% |

- Driver got a correct answer: **95%**; a fixed text instead of the LLM: **4%**.
- Answer latency p50 / p95: 850.0 / 1037.0 ms; LLM first token p50 823.0 ms; LLM complete p50 / p95: 853.0 / 1040.0 ms.
- LLM stream end reasons: {'STOP': 84} (`cancelled` = stopped by the deadline); thinking tokens p50 when the model thought: None.

## By group

| Group | ok | wrong | fixed text |
|---|---|---|---|
| alerts | 8 | 0 | 0 |
| cause | 10 | 0 | 0 |
| media | 12 | 0 | 2 |
| messages | 10 | 0 | 0 |
| reminders | 9 | 1 | 0 |
| stops | 10 | 0 | 0 |
| talk | 10 | 0 | 2 |
| trip | 18 | 0 | 0 |

## Runs that failed

| Case | Driver said | Outcome | Problem | Assistant said |
|---|---|---|---|---|
| `reminder_exists` #2 | Amintește-mi să iau lichid de parbriz la benzinărie. | `wrong` | must not contain ['create_reminder'] | Am deja notat: lichid de parbriz, la benzinărie. |
| `what_song` #1 | Ce melodie e asta? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `what_song` #2 | Ce melodie e asta? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `hello` #1 | Salut DriveMate! | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `hello` #2 | Salut DriveMate! | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |

## To judge by hand (content cannot be checked automatically)

| Case | Driver said | Assistant said |
|---|---|---|
| `next_town_no_map` #1 | Ce oraș urmează? | Nu știu orașele de pe traseu. Următoarea oprire e OMV, în 12 km. |
| `next_town_no_map` #2 | Ce oraș urmează? | Nu știu orașele de pe traseu. Următoarea oprire e OMV, în 12 km. |
| `pharmacy` #1 | Unde e cea mai apropiată farmacie? | Nu văd o farmacie pe traseu. Îți amintesc la prima farmacie? Bine? |
| `pharmacy` #2 | Unde e cea mai apropiată farmacie? | Nu văd o farmacie pe traseu. / Îți amintesc la prima farmacie? Bine? |
| `why_alert` #1 | De ce m-ai alertat adineauri? | Nu am înregistrat nicio alertă pe traseul acesta. Alertele vin de la sistemul de monitorizare a atenției. |
| `why_alert` #2 | De ce m-ai alertat adineauri? | Nu am înregistrat nicio alertă pe traseul acesta. Alertele vin de la camera de monitorizare. |
| `what_time` #1 | Cât e ceasul? | Este ora 23:00. |
| `what_time` #2 | Cât e ceasul? | Este ora 23:00. |
