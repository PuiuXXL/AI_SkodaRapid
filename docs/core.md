# DriveMate core (P2): context + safety + SOS

> Work in progress. This page starts with the contract; the core loop, the safety rules and the scores are added as
> they land.

## 1. The contract: `shared/contracts.py` (v2.1)

One file, Pydantic v2, imported by every module. It follows `DriveMate-PLAN-FINAL.md` section 7 (state), section 6
(actions) and section 13 (interfaces). Changes: `CONTRACT: <field>, <type>, <who writes it>, <why>` on the group, new
fields optional with a default, bump `CONTRACT_VERSION`, update `tests/core/fixtures/state_example.json`.

**Changes since 2.0:**
- **2.1:** `driver.face_conf` may be `null` (P1 sends null before the first monitoring result; with a number-only
  field those frames failed validation); `passenger.monitoring_ok / monitoring_warnings / camera_mode / face_conf`
  declared (P1 already sends them); `alarm_played` and other log types added to `CORE_EVENT_TYPES` (list only).

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

Adopted from P3's YouTube media (D11, plan v2.2, `docs/assistant.md` section 6.1), all optional: `search_media` in
`ActionType` (internal to the assistant, listed in `ASSISTANT_INTERNAL_ACTIONS`: core's validator rejects it if it
ever arrives), `Action.query / kind / options / title`, `ask.expects = "choice"` (a choice question must carry
`options`), `play_media.title` with `track_id = "yt:<id>"`, `media.source` (`catalog` / `youtube`), `loop` on the
`media` message, and `NO_CONFIRMATION_PREFERENCES = {"volume"}` (volume runs without "Bine?").

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
| `6` | yawns, slow blinks, passenger asleep | yawn every 20 s, blinks of 420 ms every 2 s (PERCLOS ~0.21), `passenger.awake=false` |
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

## 2. The core process (`core/main.py`)

```bash
pip install -r requirements/p2-core.txt -r requirements/p3-assistant.txt   # P3's for /tts and /media
python -m core.main                         # http://127.0.0.1:8000
python -m core.main --host 0.0.0.0          # the phone bridge runs on another laptop (plan decision 9)
python scripts/fake_perception.py           # second terminal: P1's stand-in
curl http://127.0.0.1:8000/health           # connections, data age, simulator in use
```

| File | What it does |
|---|---|
| `core/main.py` | FastAPI: `/ws/perception`, `/ws/ui`, `/ws/phone`, `GET /health`; the 10 Hz loop; mounts `assistant.router` (P3) and `integrations.contact_app.router` (P4) when they import. An error in one tick or one message handler is logged once; the loop and the connections go on. |
| `core/engine.py` | The state. Takes P1's frames, the browser's messages and the bridge's messages; builds `State` every tick; the event log (`log_event`). Plug-in points for the next steps: `add_frame_listener` (fast safety path, runs on every frame, not at the next tick), `add_browser_listener`, `add_tick_listener`. |
| `core/hub.py` | One queue and one sender task per WebSocket peer: sending never blocks; old `state` messages go first when a browser is slow. |
| `core/simulation.py` | P4's `simulator.Simulator` when it exists; otherwise `FakeSimulator`: a straight route with OMV (fuel, km 42) and a cafe, scene presets (scenes 5-9 on the highway at 118 km/h, scene 7 stopped at OMV). |

**How the state is built.** P1's blocks (`driver` without `reaction`, `passenger`, `occupants`, `perf`) come from the
newest frame if it is younger than `loop.perception_stale_ms`; otherwise the driver block is reset with
`monitoring_ok=false` and `monitoring_reason` `no_frames` (connected, no data) or `camera_unavailable` (not
connected). `safety.monitoring_ok` = fresh frame and P1's `driver.monitoring_ok`. Declared rear occupants (ids 3+) are
added after the camera ones. Message texts stay in core: the `/ws/ui` state has no `messages[].text`.

**Director commands handled now** (`{"type": "command", "cmd": ...}` on `/ws/ui`): `debug`, `calibrate`, `enroll`
(forwarded to P1), `llm` (`on`: C6 switch), `declare_occupant` (`value: {profile, role}` or `{remove: id}`),
`fake_message` (`value: {from, app, text}`), `scene`, `speed`, `time_scale`, `start`, `pause`, `stop_at_next_poi`,
`reset`.

Checked end to end (core + `fake_perception.py` + a `/ws/ui` client): 10.3 states/s, 15 frames/s, scene 8 on the
highway, eyes closed up to 1.9 s, covered camera -> `monitoring_ok=false` (`occluded`), no invalid or dropped message.

## 3. Safety (`core/safety/`, plan C): deterministic, no LLM

| File | Rule |
|---|---|
| `sos.py` | **C3, C4, C5.** `normal -> alarm (P1) -> asking (P1) -> countdown (P0) -> sos_sent (P0)`. Alarm when `driver.eyes.closed_ms >= safety.microsleep.closed_ms` (eyes reliable) or `driver.head.nodding`, **on the frame itself** (fast path, not at the next tick). After `sos.ask_after_alarm_s`: the "Ești bine?" clip + a dialog window. No answer (or "nu"): the passenger instructions clip by name, the countdown, the alarm again every `realarm_s` after the instructions, then the report to every SOS channel. Any yes (voice, nod, thumbs up) cancels before the end. One alarm per closure: the eyes must open before the next one. |
| `alarm.py` | `alarm` message with `alarm_<driver>.mp3`; `alarm_ms` = core detection -> `alarm_played` from the browser, both on core's clock -> `safety.alarm_ms_last`, `perf.alarm_ms_last`, event `alarm_played` (`on_target` vs `safety.alarm_target_ms`). |
| `monitoring.py` | **C7.** `safety.monitoring_ok` false for `lost_after_ms` -> P2 + "Nu te mai văd" clip + the reason in the log, repeated every `repeat_s`; "Te văd din nou" when it is back. Silent until the camera has seen the driver once in this trip, and never over a more critical alert. |
| `arbiter.py` | **C1, C8 veto.** Every rule raises / clears its alert; `safety.level` = the most critical, `safety.alert`, `llm_allowed` = level not in P0-P2. A rise to a more critical level sends `speak_control: stop` and `media: stop` before the rule's own sound. |
| `answers.py` | Yes / no from the voice (phrases in `templates.yaml`, the first one in the sentence wins), the nod (`head.answer`), the gesture (`Thumb_Up` / `Thumb_Down`). |
| `../dialog_window.py` | Opens the window on both sides: `dialog_window` to P1 (nods and gestures) and `interaction.dialog_window_open` for the voice (no wake word needed). |
| `../clips.py` | Picks P3's clips (`clips.json`) by name: `alarm_<driver>`, `passenger_instructions_<passenger>_<driver>`; default names while P1 does not recognise the person. |

**SOS channels** (`core.safety.default_sos_channels`): `contact_page` (P4's `integrations.contact_app.push_sos`
when it exists), `call` (Twilio) and `sms` (the driver's phone through the bridge) report `not_connected` until the
phone part is wired. A channel that fails is logged as `error: ...` and the others still run (C9).

Checked end to end (core + `fake_perception.py` + a client playing the browser): scene 8 (eyes closed -> stop +
alarm in 31-36 ms detection -> `alarm_played`, "Ești bine?" -> "Da" -> normal, LLM allowed again) and scene 9 (head
drop -> alarm -> no answer -> "Maria, Andrei nu răspunde..." -> 10 s countdown with re-alarms -> SOS report).

## 4. Distractions (C2) and the A/B counter (B8)

| File | Rule |
|---|---|
| `safety/distraction.py` | **C2.** Above `safety.distraction.min_speed_kmh`: `driver.gaze.off_road_ms` past `off_road_ms` (`off_road_ms_high_speed` from `high_speed_kmh`), or `driver.phone.in_use` for `phone_min_ms`. One episode: at once `visual_cue` + a P2 alert (voice and music stop, LLM silent); after `escalation.voice_after_ms` a fixed sentence ("Ochii pe drum." / "Lasă telefonul." / "Lasă telefonul, ți-l citesc eu." when a message is waiting); after `alarm_after_ms` the alarm. The same sentence is not repeated within `cooldown_s`; nothing is said over the SOS; `unknown` zones and low gaze confidence never alert. `distraction_end` logs the time to come back (visual reaction). |
| `ab_baseline.py` | **B8.** The simple threshold on the same perception, without zones, calibration, context or speed: head past `yaw_deg` / `pitch_deg` for `min_ms` (a mirror check counts), eyes closed `closed_ms`, any phone in the driver camera (the passenger's too). One per episode, one per `cooldown_s`, logged as `naive_alert`. DriveMate's side counts each distraction episode and each microsleep alarm. Both go to `state.ab`. |

Fixed texts without a clip go through P3's TTS (`/tts/...`); P3's player falls back to the browser's voice. Clip ids
for them are already in `templates.yaml` (`eyes_on_road`, `phone_down`, `phone_read_for_you`): once P3 generates
those clips they are used automatically.

Checked end to end: scene 2 (mirror glance -> "prag simplu 1 / DriveMate 0") and scene 3 (phone in hand with a
message waiting -> cue at 1.1 s -> "Lasă telefonul, ți-l citesc eu." -> alarm at 3 s -> phone down -> end; counter
"prag simplu 2 / DriveMate 1").

## 5. The assistant link (C): `core/assistant_link.py`

The slow path. Safety never waits for it: events go to `assistant.handle_event` one at a time in a background task
(an answer can take seconds), the actions that come back are checked again (C8) and executed.

| Events core sends | When |
|---|---|
| `trip_start` | the driver has been seen for `assistant.greet_after_s` (once per trip); new messages wait for it |
| `driver_speech` | an addressed final utterance that answers neither the SOS nor the assistant's pending question |
| `driver_refused` | a refusal while the fatigue dialog is on (`assessment.fatigue >= safe_contact.fatigue_min`); C10 in step H |
| `message_received` / `safe_contact_reply` | the F2 rule allows it, with `delivery` `ask` or `read` |
| `stop_suggested` | after a KSS answer of `assistant.kss_break_min` or more: the stop picked by `core/reminders.py` (K3) |
| follow-ups | what P3's `DialogManager` returns (`media_declined`, `kss_answer`, `driver_refused`, ...) |

| File | What it does |
|---|---|
| `validator.py` | **C8.** Rejects an unknown or internal type (`search_media`), a missing parameter, a level that does not allow it (the veto at P0-P2, `null` = P4), an action that needs a "yes" and did not get it (volume excepted). Logged as `action_rejected`. |
| `messages_timing.py` | **F2.** Defer (alert, risk, speed, distraction cause; "Ți-l citesc imediat ce e liniște." once, retried every `retry_s`), ask (someone else in the car), read (alone). |
| `reminders.py` | **K3** (first version): the next POI in range, solving an open reminder of the same category. |
| `assistant_link.py` | Events, early speech while the LLM streams (said once), execution (speech, music with `loop` / `source` / `reason`, volume, reading a message as is, the reply through the phone bridge with `send_reply`, reminders, stops, screen text, silence), answers on every channel through P3's `DialogManager`, the dialog window after a question (`speak_done`), **D4** (the voice pauses at a mirror glance, resumes "...cum ziceam"), ✋ to silence it, LLM latency and status (`perf.llm_*`, `integrations.llm`), the scorecard (accepted / rejected suggestions, hands-free messages, reminders done). |

The SOS has priority: an input that answered "Ești bine?" never reaches the assistant, and a safety alert drops the
pending question. Without P3's code installed, core and safety run, the assistant is off.

Checked end to end with P3's real client (no LLM key, its fixed texts): scene 1 greeting (paused at a mirror glance,
resumed), scene 3 message ("Mesaj de la Mihai. Îl citesc tare?" -> "da" -> the text read as is), "oprește muzica".

## 6. Scores (B): `core/scoring/`

Updated every tick after the safety rules: `state.assessment` (attention, F, D, risk), `state.driver.reaction`,
`state.conversation`, `state.blind_m`. A term without data yet (no reaction, no answer) is left out and the other
weights are rescaled (`common.weighted`), so a missing measurement neither raises nor hides a score.

| File | Score |
|---|---|
| `reaction.py` | **B1.** Visual: the off-road distraction's cue -> gaze back on the road. Verbal: `speak_done` of a question -> `speech_onset`. Gesture: the same question -> nod / gesture. Baseline = median of the first 3-5 per channel; `missed` and the response rate over 10 min; words per answer. |
| `fatigue.py` | **B2, F.** PERCLOS, blink duration, yawns, slow reaction, nodding, trip duration, plan weights, EMA. Held while the camera is lost. |
| `disengagement.py` | **B2, D.** Slow reaction, low gaze entropy, low response rate, short answers, monotony. Counts only in a monotonous context (highway, steady speed, `monotony.min_minutes` of trip time) with F under `max_fatigue`; otherwise it decays to 0. |
| `attention.py` | **B3** attention (on-road share over 10 s, VATS and phone penalties) and risk 0-3 (inattention and F, times the speed factor); **B6** blind meters; **B9** conversation (alternating lips + microphone). |
| `__init__.py` | Wiring, and the events for the assistant: `fatigue_high` (KSS conversation) and `disengagement_high` (the music offer) once per crossing of `high`, again after `low`, never while the assistant is silenced. |

Calibrated on `fake_perception.py` (fake time, time x20): normal driving keeps F ~0 and D under `low` (the
monotonous highway alone gives D ~0.3); key 5 on the highway crosses D 0.6 after ~20 s; key 6 crosses F 0.6 after
~60 s (P1's PERCLOS is a 60 s window). `disengagement.norm.low_entropy` is [1.0, 0.3] bits because a normal scan is
~1 bit; **both thresholds are to be tuned on P1's real data on Sunday.**

Checked end to end (real processes, P3's real client): scene 5, fixed gaze on the highway -> `disengagement_high` ->
"Pare monoton. Pun ceva mai energic, din ce-ți place?" -> "da" -> music with `reason=disengagement`.

## 7. The cause from two cameras (B4) and the effect of interventions (D2, D6)

| File | What it does |
|---|---|
| `cause.py` | **B4.** Glances = entries into a zone (driver camera), counted over `cause.window_s`, fused with what the passenger camera sees and the context. Priority: `passenger_showing_phone` (>= 3 glances at the passenger AND her phone seen), `passenger_talk` (the glances AND she spoke), `incoming_message` (a message in the last `message_window_s` AND the driver took the phone or looked at the lap), `phone`, `child_activity` (>= 3 glances at `rear_seat` with a child declared). Kept `hold_s` after the evidence ends. A new cause goes to the log (`cause`, text from `templates.yaml`) and, for `cause.notify_labels`, to the assistant as `cause_detected` (not while it is silenced). `phone` is not sent: the C2 escalation handles it. |
| `intervention.py` | **D6.** When the assistant answers a cabin cause (delegation, D2) or music starts against disengagement, the metric is taken over `intervention.before_s` and again `after_s` later: glances at the passenger for a delegation, mean D for the music. `intervention.last / effect_pct / stats` and the event `intervention_effect`: "Cauză rezolvată ✓ (+X%)" or "Remediul nu a ajutat ... Se renunță la el." Music asked by the driver is not measured. |

F2 now defers messages only for the cabin causes (`messages.defer_causes`): a message is never deferred because of
itself (`incoming_message`).

Note for the demo: the music's effect on D shows within 15 s mostly through the reaction terms (the driver answers
the offer promptly); the gaze entropy needs P1's 60 s window to recover.

Checked end to end (real processes, P3's real client): scene 4, Maria shows her phone, three glances -> cause from
both cameras -> "Maria, poți să-i povestești tu?" / "Andrei, ochii pe drum." -> A/B 2 / 0 -> 15 s later "Cauză
rezolvată ✓ (+100%)".

## 8. The trusted contact (C10, D10, F8): `core/safe_contact.py`, `core/profiles.py`

A rule, never the LLM. The fatigue dialog is on for `safe_contact.dialog_s` after `fatigue_high`; a refusal in it
(the keyword path of P3's `assistant.refusal`, ✋ / 👎 in the KSS question, or the LLM's
`stay_silent(reason="driver_refused")`) with F >= `safe_contact.fatigue_min`:

1. after P3's "Ok, te las în pace.", `assistant.muted_until = now + refusal_mute_min` (P3-P4 silent; alarms, SOS
   and the delivery of messages are not affected);
2. if the profile has a contact, consent, and `cooldown_min` has passed: "Îi dau de veste lui Mihai." (clip
   `notify_contact_<name>`, only when the contact really is told and `announce` is on), then the fixed text
   (`templates.yaml` `safe_contact.sms`) to the channels `sms` (driver's phone, via the bridge) and `contact_page`
   (P4's `push_safe_contact`): both `not_connected` until wired. Event `safe_contact_notified`, source RULE;
   otherwise `safe_contact_skipped` with the reason;
3. the contact's answer is a normal message (`safe_contact_reply`, F2); once it has been read, **one**
   `stop_suggested` goes to the assistant with the silence lifted for it (P3's policy would otherwise block it).

`profiles.py` reads `profiles/<driver>/profile.json` (P4's format: `safe_contact.name`, `consent.safe_contact_notify`,
`announce`) and re-reads it when it changes; no file = no contact. Phone numbers stay in `.env`.

Also new: an initiative the assistant skipped by policy (`rate_limited`, `safety_veto`, `conversation`) is sent again
after `assistant.retry_s` (at most `max_retries`) while its condition still holds; never while muted. Core passes its
clock to `handle_event` (`now`), so P3's one-initiative-per-30-s rule runs on the same time as core.

Checked end to end (real processes, P3's real client, a test profile outside the repo): scene 6, F 0.60 -> KSS
question -> "Lasă-mă în pace." -> "Ok, te las în pace." -> "Îi dau de veste lui Mihai." -> the text for Mihai ->
his answer read after "da" -> "Oprim la Cafenea peste 10.8 km?" -> "da".

## 9. Testing without the others

```bash
pytest tests/core                                   # the rules, scene by scene, in fake time
python -m core.main                                 # terminal 1
python scripts/fake_perception.py                   # terminal 2: keys 1-9 instead of the camera
python scripts/core_command.py watch                # terminal 3: alarms, voice, events, level, A/B counter
python scripts/core_command.py scene 8              # director commands until P4's panel has them
python scripts/core_command.py message Mihai "Unde ești?"
```

With the dashboard (`cd dashboard && npm run dev`, Google Chrome, Sursă -> "Live · local", "Activează vocea") the
alarms and the voice are heard; without a browser, `watch --ack-alarms` answers `alarm_played` in its place.
