# Assistant LLM evaluation: cause-before (2026-11-22)

Model `gemini-3.5-flash-lite` (retry `gemini-3.1-flash-lite`), `max_output_tokens` 1024, `thinking_level` minimal, deadline 2.5 s. 5 cases x 5 runs = 25 runs. YouTube search stubbed. Overrides: none. Produced by `assistant/dev/eval_llm.py`.

## Summary

| Outcome | Runs | Share |
|---|---|---|
| `ok` | 20 | 80% |
| `wrong` | 5 | 20% |

- Driver got a correct answer: **80%**; a fixed text instead of the LLM: **0%**.
- Answer latency p50 / p95: 851.0 / 1148.0 ms; LLM first token p50 825.0 ms; LLM complete p50 / p95: 850.0 / 1147.0 ms.
- LLM stream end reasons: {'STOP': 25} (`cancelled` = stopped by the deadline); thinking tokens p50 when the model thought: None.

## By group

| Group | ok | wrong | fixed text |
|---|---|---|---|
| cause | 20 | 5 | 0 |

## Runs that failed

| Case | Driver said | Outcome | Problem | Assistant said |
|---|---|---|---|---|
| `cause_passenger_phone` #1 | [cause_detected passenger_showing_phone] | `wrong` | says ['ochii pe drum'] | Maria, poți să-i povestești tu? / Andrei, ochii pe drum. |
| `cause_passenger_phone` #2 | [cause_detected passenger_showing_phone] | `wrong` | says ['ochii pe drum'] | Maria, poți să-i povestești tu? / Andrei, ochii pe drum. |
| `cause_passenger_phone` #3 | [cause_detected passenger_showing_phone] | `wrong` | says ['ochii pe drum'] | Maria, poți să-i povestești tu? / Andrei, ochii pe drum. |
| `cause_passenger_phone` #4 | [cause_detected passenger_showing_phone] | `wrong` | says ['ochii pe drum'] | Maria, poți să-i povestești tu? / Andrei, ochii pe drum. |
| `cause_passenger_phone` #5 | [cause_detected passenger_showing_phone] | `wrong` | says ['ochii pe drum'] | Maria, poți să-i povestești tu? / Andrei, ochii pe drum. |
