# P2 · Context, safety and SOS

[Project setup](../README.md) · [Shared contract](../shared/contracts.py) · [Role brief](../roluri/P2-context-siguranta.md)

Core combines P1 observations with trip context, computes driver-state assessments and decides which intervention is appropriate. A 10 Hz state loop serves the dashboard. Time-critical safety rules run independently of slow assistant work.

## Tech stack

| Technology | Use |
| --- | --- |
| Python 3.11 | Engine, scoring and deterministic safety |
| FastAPI + Uvicorn | HTTP API and WebSocket endpoints |
| asyncio | State loop, independent peer senders and assistant work |
| Pydantic v2 | Incoming frames, UI messages, phone messages and actions |
| PyYAML | Safety thresholds, prompts and demo overrides |
| python-dotenv | Local integration settings |
| websockets / httpx | Supporting clients and API tests |
| pytest + pytest-asyncio + pytest-cov | Deterministic fake-time tests, async tests and coverage |

The full core/assistant test boundary also needs the P3 runtime dependencies. In particular, `AssistantLink` loads TTS metadata support from `assistant.tts`, which imports `edge_tts`.

## Implementation

- `main.py` creates the FastAPI application, starts the state loop and attaches the installed modules.
- `hub.py` maintains separate queues/senders for browser, perception and phone peers. Slow clients do not block safety processing.
- `engine.py` validates/merges perception input, drives trip state and dispatches controls.
- `scoring/` computes reaction measures, fatigue, disengagement, attention, conversation and blind metres.
- `cause.py` associates driver distraction with available cabin context.
- `safety/` contains monitoring-loss, distraction, drowsiness, alarm, SOS and arbitration rules.
- `assistant_link.py` queues assistant requests, validates returned actions, coordinates questions and gives safety speech priority.
- `safe_contact.py`, `reminders.py`, `attractions.py` and `scorecard.py` implement consent-aware notifications, stop reminders, route suggestions and reporting.
- `route_api.py` and `simulator/` accept the dashboard's route and simulate travel along its geometry.

### Safety flow

`PerceptionFrame → safety rules → assessment/context → permitted assistant work → State/events`

SOS progresses through `alarm → asking → countdown → sos_sent`. Voice/head/gesture responses are interpreted according to the active safety state. Recovery remains possible after the report is sent. The browser reports playback completion, while fallback timers prevent a missing browser callback from blocking the sequence.

LLM output is checked against the shared action contract and core's current permissions. It cannot directly overwrite safety scores or silence critical alarms.

## HTTP and WebSocket contracts

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Connections, perception age and simulator state |
| `/ws/perception` | P1 frames, command acknowledgements and commands |
| `/ws/ui` | UI controls, speech, playback feedback, state and events |
| `/ws/phone` | Phone status, messages and outgoing bridge actions |
| `GET/PUT/DELETE /simulator/route` | Inspect, replace and clear a map route |
| `POST /simulator/seek` | Change simulated route progress |
| `/tts/*`, `/media/*` | P3 routes, mounted when its runtime is available |

`shared/contracts.py` is the interface reference. Golden fixtures under `tests/contract/fixtures/` are consumed on both sides of the boundary.

## Install and run

From the repository root:

```bash
python -m pip install -r requirements/p2-core.txt -r requirements/p3-assistant.txt
python -m core.main
```

Optional server arguments:

```bash
python -m core.main --host 0.0.0.0 --port 8000 --log-level info
```

Bind to the default localhost for a local demo. A reachable host is needed for clients on another machine. Configure their endpoints accordingly.

For a camera-free demo, start this in a second terminal:

```bash
python -m scripts.fake_perception
```

Start the dashboard in a third terminal, following the root README. Inspect `http://localhost:8000/health` before debugging the frontend.

## Configuration

- `core/config/thresholds.yaml` contains timing, scoring, safety, consent/cooldown and assistant thresholds.
- `demo_mode` merges the validated `demo` overrides into normal thresholds.
- `core/config/templates.yaml` supplies fixed prompts.
- `.env` supplies provider credentials and integration configuration.
- `profiles/<driver>/profile.json` supplies trusted-contact consent and driver preferences.

Core attempts to import optional contact and Twilio integrations. The current checkout includes `phone_bridge.py` and audio tooling; dedicated contact/Twilio modules are extension points. Verify integration health before claiming that a notification reached a real recipient.

## Testing

```bash
python -m pip install pytest-cov ruff
python -m pytest tests/core tests/simulator tests/contract/test_core_reads_p1.py tests/contract/test_dashboard_route.py -q --cov=core --cov=shared --cov=simulator --cov-fail-under=93
python -m pytest tests/contract -q
python -m pytest tests/integration -m slow -q --durations=5
```

Core tests set the assistant to offline mode and isolate profiles. The fake-time rig in `tests/core/p2_helpers.py` can advance long safety sequences without waiting in real time. Integration tests start actual core/perception processes over loopback WebSockets. They require the P1 dependencies too.

The CI runtime-import preflight checks both core and assistant dependencies before pytest, so a missing optional runtime cannot silently turn a large portion of the tests into disabled-assistant failures.
