# DriveMate core (P2): context + safety + SOS

> Work in progress. This page starts with the contract; the core loop, the safety rules and the scores are added as
> they land.

## 1. The contract: `shared/contracts.py` (v2.0)

One file, Pydantic v2, imported by every module. It follows `DriveMate-PLAN-FINAL.md` section 7 (state), section 6
(actions) and section 13 (interfaces). Changes: `CONTRACT: <field>, <type>, <who writes it>, <why>` on the group, new
fields optional with a default, bump `CONTRACT_VERSION`, update `tests/core/fixtures/state_example.json`.

### 1.1 What is in it

| Interface | Models | Helper |
|---|---|---|
| `/ws/perception`, P1 -> core | `PerceptionFrame` (no `type` key), `PerceptionAck`, `CalibrationPrompt` | `parse_perception_message` |
| `/ws/perception`, core -> P1 | `PerceptionCommand` (`dialog_window`, `calibrate`, `debug`, `enroll`) | |
| State, core -> everyone (10 Hz) | `State`, as in section 7 | `to_wire` |
| `assistant.handle_event(event, state)` | `Event`, `Action` (flat) | |
| C8 validator | one typed model per action (`SpeakAction` ... `StaySilentAction`), `TypedAction`, `ACTION_ALLOWED_LEVELS`, `ACTION_NEEDS_CONFIRMATION` | `parse_action`, `Action.typed()` |
| `/ws/ui`, core -> browser | `UiState`, `UiEvent`, `UiSpeak`, `UiSpeakControl`, `UiAlarm`, `UiMedia` | `parse_ui_message` |
| `/ws/ui`, browser -> core | `UiCommand`, `UiSpeech`, `UiSpeechOnset`, `UiSpeakDone`, `UiAlarmPlayed` | `parse_browser_message` |
| `/ws/phone`, bridge -> core | `PhoneMessage`, `PhoneCall`, `PhoneStatusMessage`, `PhoneResult` (`PhoneEvent`) | `parse_phone_event` |
| `/ws/phone`, core -> bridge | `SendReply`, `SendSms` (`PhoneCommand`) | `parse_phone_command` |
| `place_sos_call(report)`, `push_sos(report)` | `SosReport` | |
| `push_safe_contact(info)` | `SafeContactNotice` | |

### 1.2 Rules

1. Every state and frame field has a default, so each module sends only what it has. The only required fields are
   list-item ids (occupant, message, reminder, POI) and the parameters of the typed actions.
2. Unknown fields are kept (`extra="allow"`): a newer module never breaks an older one.
3. `from` is `from_` in Python. Serialize with `to_wire(model)` so the JSON says `"from"`.
4. Vocabularies that are still moving (`monitoring_reason`, `cause.label`, event types, director commands) are plain
   strings; the known values are in `MONITORING_REASONS`, `CAUSE_LABELS`, `EVENT_TYPES` / `CORE_EVENT_TYPES`,
   `UI_COMMANDS`.

### 1.3 Decisions taken while merging the provisional contracts

P1 (`perception/contract.py`) and P3 (`assistant/_TEMP_contract_DELETE_LATER.py`) wrote provisional copies before
this file existed. Both switch to it automatically. Where they disagreed:

| Topic | P1 | P3 | Contract v2.0 | Why |
|---|---|---|---|---|
| `driver.head.yaw/pitch/roll` | `null` default | `0.0` default | **`null`** | 0 means "straight ahead"; no face must not look like a valid angle |
| `driver.eyes.reliable` | `false` default | `true` default | **`false`** | no data = not reliable (AS14: only head metrics then) |
| `occupants[].source` | required | `"declared"` default | **`"declared"` default** | rule 1; P1 always sends it anyway |
| `Action` | — | one flat model | **flat model kept** + one typed model per type | the LLM schema and P3's code use the flat model; core's validator uses the typed ones |
| `intervention`, `ab`, `blind_m`, `scorecard`, `integrations`, `perf` | — | plain dicts | **typed models** | section 7 defines their fields; P3 does not read them |

Adopted from P1's proposals (`docs/perception.md` section 9, `docs/notes/modules.md`, `docs/notes/output.md`), all
optional: `driver.eyes.closed_ms / state / squint / long_closure / blink_rate / open_baseline`,
`driver.phone.near_face / side / usage / foreign_seen`, `driver.gaze.calibrated / off_road_60s_ms / lap_pattern`,
`driver.monitoring_ok / monitoring_reason / monitoring_warnings / face_too_small / face_conf / camera_mode /
gesture_score`, `passenger.monitoring_reason`, `occupants[].profile_score`, `perf.cameras.<cam>.available /
capture_ts / age_ms / dropped_results`, `perf.degrade_level / stages_ms / publish_ts`, the `calibrate.quick` and
`enroll.camera` command fields, the `ack` and `calibration_prompt` messages.

**Microsleep:** P1 reports `driver.eyes.closed_ms` and always sends `microsleep: false`; core decides microsleep from
`closed_ms` with the threshold in `core/config/thresholds.yaml`.

Adopted from P3's proposals (`docs/assistant.md` sections 3-5): the event types (`EVENT_TYPES`), the `/ws/ui` and
`/ws/phone` message formats, the `Action` extras (`source`, `clip_id`, `needs_confirmation`, `streamed`, `volume`).

Added by P2:
- `safety.sos {state, since_ts, countdown_s}`: where the unresponsive-driver state machine is (C4, C5), for the
  dashboard and the Contact page;
- `Event.source / text / explanation / channel / latency_ms` and `CORE_EVENT_TYPES`, for the event log (H3);
- `messages[].text` is only in the in-process state passed to the assistant; core leaves it out of the `/ws/ui`
  broadcast;
- `SosReport`, `SafeContactNotice` for P4's Contact page and the Twilio call.

### 1.4 Thresholds and templates (`core/config/`, read through `core/settings.py`)

- `thresholds.yaml`: every safety threshold, the F and D weights and ranges, the windows, `refusal_mute_min`,
  `safe_contact.*`, `sos.countdown_s`, `demo_mode`. Read with `th("sos", "countdown_s")`.
  - **Score ranges** (`norm: [a, b]`): term 0 at `a`, 1 at `b`, linear in between. `b < a` is an inverted range
    (e.g. low gaze entropy is the bad value).
  - **`demo_mode: true`** merges the `demo:` block over the normal values (shorter windows). A key in `demo:` that
    does not exist above is an error, so a typo cannot silently keep the long window.
  - **C8:** `tuning.limits` lists the only thresholds a thumbs down may move (P3-P4); `safety.*` and `sos.*` never.
- `templates.yaml`: the SOS report (`sos.call` for Twilio, without a link; `sos.sms` with the Google Maps link), the
  trusted-contact SMS, the stop reminder, the passenger instructions, one explanation sentence per alert (principle
  4). Filled with `render("reminders", "due", task="lichid de parbriz")`; a missing field is an error. No phone number
  is ever in this file.

### 1.5 `scripts/fake_perception.py` (stands in for P1)

```bash
python scripts/fake_perception.py                      # -> ws://localhost:8000/ws/perception (CORE_URL in .env)
python scripts/fake_perception.py --print --no-ws      # JSON lines on stdout, no core
python scripts/fake_perception.py --no-keys --script "0:1,3:2,8:7" --duration 15   # scripted, no keyboard
python scripts/fake_perception.py --auto-answer        # nod "yes" to every dialog window (slower with keys 5, 6)
```

| Key | Situation | What the frames show |
|---|---|---|
| `1` | normal | road + short scans (rear mirror, cluster, left mirror), blinks of 150 ms |
| `2` | mirror glance | 1.8 s `mirror_left`, yaw -45°: no DriveMate alert (P1 rule), naive A/B alert |
| `3` | phone | `phone.in_use`, `source=detector`, glances at `lap` |
| `4` | passenger x3 + their phone | 3 glances at `passenger` in 8 s, `passenger.holding_phone`, `foreign_seen` |
| `5` | fixed gaze | road only, no head motion: entropy falls to 0 over 60 s; with `--auto-answer` answers in 2.5 s |
| `6` | yawns, slow blinks, passenger asleep | yawn every 20 s, blinks of 450 ms, PERCLOS up, `passenger.awake=false` |
| `7` | eyes closed | `eyes.state=CLOSED`, `closed_ms` grows, `microsleep=false` (core decides) |
| `8` | head down, no answer | pitch -35°, `nodding` for 1.5 s, eyes closed, never answers |
| `9` | camera covered | `monitoring_ok=false`, `monitoring_reason=occluded`, the driver leaves `occupants` after 2 s |
| `y` / `n` | head yes / no | `head.answer` (or `passenger.answer` if the dialog window is addressed to them), 1 s |
| `h` / `g` / `b` | ✋ / 👍 / 👎 | `gesture`: `Open_Palm` / `Thumb_Up` / `Thumb_Down`, 1 s |
| `c` / `p` | conversation / passenger | alternating `speaking` every 2 s / passenger in or out |

Commands from core (`dialog_window`, `calibrate`, `debug`, `enroll`) get an `ack` in P1's format.

### 1.6 Checked

- `tests/core/test_contracts.py`: the section 7 example validates and serializes back without losing or changing a
  value; every action type, the `/ws/ui` and `/ws/phone` formats used by P3's code, the command short forms.
- P3: `pytest tests/assistant` passes on this contract (`assistant.contract.MISSING_FROM_SHARED` is empty).
- P1: 369 frames from `python -m perception.main --source synthetic --no-models --print --no-ws` validate, with no
  field outside the contract. `fake_perception.py` frames carry every field P1's frames carry.
- `tests/core/test_config.py`: the keys the role file asks for, the weights sum to 1 and match the plan's formulas,
  the demo overrides, the C8 limits, every template's fields, no phone number in the templates.
- `tests/core/test_fake_perception.py`: every key, the answers and gestures, the acks, and a round trip over a real
  WebSocket.
