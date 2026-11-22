# Assistant LLM evaluation: baseline (2026-11-22)

Model `gemini-3.5-flash-lite` (retry `gemini-3.1-flash-lite`), `max_output_tokens` 400, `thinking_level` low, deadline 2.5 s. 41 cases x 3 runs = 123 runs. YouTube search stubbed. Produced by `assistant/dev/eval_llm.py`.

## Summary

| Outcome | Runs | Share |
|---|---|---|
| `ok` | 92 | 75% |
| `fallback:truncated` | 15 | 12% |
| `fallback:silent_on_request` | 13 | 11% |
| `wrong` | 3 | 2% |

- Driver got a correct answer: **75%**; a fixed text instead of the LLM: **23%**.
- Answer latency p50 / p95: 885.0 / 1782.0 ms; LLM first token p50 857.0 ms; LLM complete p50 / p95: 910.0 / 1818.0 ms.
- LLM stream end reasons: {'STOP': 99, 'MAX_TOKENS': 15} (`cancelled` = stopped by the deadline); thinking tokens p50 when the model thought: 312.0.

## By group

| Group | ok | wrong | fixed text |
|---|---|---|---|
| alerts | 8 | 0 | 4 |
| media | 20 | 0 | 1 |
| messages | 4 | 0 | 11 |
| reminders | 13 | 2 | 0 |
| stops | 7 | 1 | 7 |
| talk | 14 | 0 | 4 |
| trip | 26 | 0 | 1 |

## Runs that failed

| Case | Driver said | Outcome | Problem | Assistant said |
|---|---|---|---|---|
| `next_town_no_map` #3 | Ce oraș urmează? | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `read_msgs_passenger` #1 | Citește-mi mesajele. | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `read_msgs_passenger` #2 | Citește-mi mesajele. | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `read_msgs_passenger` #3 | Citește-mi mesajele. | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `read_msgs_alone` #1 | Citește-mi mesajele. | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `read_msgs_alone` #2 | Citește-mi mesajele. | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `any_msgs` #1 | Am mesaje noi? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `any_msgs` #2 | Am mesaje noi? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `any_msgs` #3 | Am mesaje noi? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `who_wrote` #1 | Cine mi-a scris? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `who_wrote` #2 | Cine mi-a scris? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `who_wrote` #3 | Cine mi-a scris? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `reminder_exists` #2 | Amintește-mi să iau lichid de parbriz la benzinărie. | `wrong` | must not contain ['create_reminder'] | Notat: lichid de parbriz, la prima benzinărie. Bine? |
| `reminder_exists` #3 | Amintește-mi să iau lichid de parbriz la benzinărie. | `wrong` | none of ['speak', 'ask'] in ['stay_silent'] | - |
| `music_plain` #1 | Pune muzică. | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Pun ceva din ce-ți place? |
| `hungry` #1 | Mi-e foame, unde pot opri? | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `hungry` #2 | Mi-e foame, unde pot opri? | `wrong` | says none of ['omv'] | Notat: mâncare, la prima cafenea. Bine? |
| `hungry` #3 | Mi-e foame, unde pot opri? | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `need_fuel` #3 | Am nevoie de benzină. | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `want_break` #2 | Vreau să fac o pauză. | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `pharmacy` #1 | Unde e cea mai apropiată farmacie? | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `stop_omv` #2 | Hai să oprim la OMV. | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `stop_omv` #3 | Hai să oprim la OMV. | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `why_alert` #1 | De ce m-ai alertat adineauri? | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `why_alert` #2 | De ce m-ai alertat adineauri? | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `why_alert` #3 | De ce m-ai alertat adineauri? | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `tired` #1 | Sunt cam obosit. | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |
| `thanks` #1 | Mulțumesc mult. | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `thanks` #2 | Mulțumesc mult. | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `thanks` #3 | Mulțumesc mult. | `fallback:silent_on_request` | expected the LLM, got a fixed text (silent_on_request) | Scuze, n-am înțeles. Poți repeta? |
| `who_are_you` #1 | Cine ești tu? | `fallback:truncated` | expected the LLM, got a fixed text (invalid_json) | Scuze, n-am înțeles. Poți repeta? |

## To judge by hand (content cannot be checked automatically)

| Case | Driver said | Assistant said |
|---|---|---|
| `next_town_no_map` #1 | Ce oraș urmează? | Următorul oraș mare e Ploiești, peste aproximativ 25 de kilometri. |
| `next_town_no_map` #2 | Ce oraș urmează? | Urmează Cluj-Napoca, la aproximativ 20 de minute. |
| `next_town_no_map` #3 | Ce oraș urmează? | Scuze, n-am înțeles. Poți repeta? |
| `pharmacy` #1 | Unde e cea mai apropiată farmacie? | Scuze, n-am înțeles. Poți repeta? |
| `pharmacy` #2 | Unde e cea mai apropiată farmacie? | Notat: farmacie, la prima farmacie. Bine? |
| `pharmacy` #3 | Unde e cea mai apropiată farmacie? | Notat: farmacie, la prima farmacie. Bine? |
| `why_alert` #1 | De ce m-ai alertat adineauri? | Scuze, n-am înțeles. Poți repeta? |
| `why_alert` #2 | De ce m-ai alertat adineauri? | Scuze, n-am înțeles. Poți repeta? |
| `why_alert` #3 | De ce m-ai alertat adineauri? | Scuze, n-am înțeles. Poți repeta? |
| `what_time` #1 | Cât e ceasul? | Este ora 23:00, Andrei. |
| `what_time` #2 | Cât e ceasul? | Este ora 23:00. |
| `what_time` #3 | Cât e ceasul? | Este ora 23:00. |
