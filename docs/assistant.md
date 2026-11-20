# DriveMate assistant (P3): LLM + voice + phone

This module makes DriveMate feel like a copilot instead of a sensor. It talks briefly, knows when to stay quiet, understands a "yes" given in any way (voice, nod, thumbs-up) and reads the driver's messages aloud so the phone is never touched.

> **P3 proposes and phrases. P2 decides when the assistant may speak and what is safe.**
> Alarms, SOS and the decision to notify the trusted contact are deterministic rules in `core/` (P2). The LLM is never on the safety path (DriveMate-PLAN-FINAL.md, sections 2 and 5).

Plan references: sections 4.D, 4.E, 4.F, 4.K, 5, 6, 7 and 13 of `DriveMate-PLAN-FINAL.md`, plus `roluri/P3-llm-voce-telefon.md`.

---

## 1. Quick start

```bash
# Python 3.11, from the repo root
py -3.11 -m venv .venv                         # Windows (Linux/macOS: python3.11 -m venv .venv)
.venv/Scripts/python -m pip install -r requirements/p3-assistant.txt

.venv/Scripts/python -m pytest tests/assistant -q             # all P3 tests (no network needed)
.venv/Scripts/python -m assistant.dev.try_llm                 # scenes through the assistant (LLM or fixed texts)
.venv/Scripts/python integrations/audio_clips.py              # (re)generate the audio clips (needs internet)
.venv/Scripts/python -m assistant.dev.voice_server            # voice test page: http://localhost:8010 (Google Chrome)
.venv/Scripts/python integrations/phone_bridge.py --dry-run   # phone bridge without a phone
```

On Linux/macOS use `.venv/bin/python` instead of `.venv/Scripts/python`.

### LLM key (Google Gemini)

The assistant uses a **Gemini Flash** model through Google AI Studio. The free tier needs no card.

1. Go to <https://aistudio.google.com>, sign in with a Google account, then **Get API key → Create API key**.
2. Copy `.env.example` to `.env` in the repo root (`.env` is gitignored) and fill in:
   ```
   LLM_PROVIDER=gemini
   LLM_API_KEY=<your key>
   LLM_MODEL=gemini-3.5-flash-lite
   ```
   Measured on 2026-11-21 (free tier, Romania): `gemini-3.5-flash-lite` answered in **1.0–1.5 s** with valid actions. `gemini-3.5-flash` took ~10 s, while `gemini-3.7-flash` and `gemini-3.8-flash` timed out (504). Only "lite"-class models fit the 2.5 s budget.
3. Check it with `.venv/Scripts/python -m assistant.dev.try_llm scene4_passenger_phone`. The output should say `source=LLM`.

**Without a key the project still runs.** The assistant then uses the fixed texts from `assistant/config/texts.ro.yaml` (`source=RULE`), and safety is unaffected. This is how the jury can run it with no account.

Privacy note for the slide (plan section 3): the LLM receives only the ~10-line text summary of the state and the conversation / message text, never images. On the free tier, Google may use prompts to improve its products.

---

## 2. File map

| Path | What it is |
|---|---|
| `assistant/client.py` | **Entry point for core.** `handle_event(event, state) -> list[Action]`: policies → LLM (streamed, 2.5 s deadline) → validation → fixed fallback. |
| `assistant/refusal.py` | **Entry point for core.** `is_refusal(text) -> bool`: deterministic, < 1 ms (plan D10). |
| `assistant/router.py` | **Mounted by core.** `GET /tts/{id}.mp3`, `GET /media/{track_id}.mp3`, `GET /assistant/health`. |
| `assistant/tts.py` | edge-tts synthesis, sentence cache, and `speak_message(action)`, which builds the `speak` message for the browser. |
| `assistant/actions.py` | Validation of actions against plan section 6: types, levels, parameters, 15 words, max 3, confirmation. |
| `assistant/policies.py` | When the assistant may answer: P0–P2 veto, muted after refusal, conversation, 1 proactive answer / 30 s. |
| `assistant/fallback.py` | Fixed answers per event type (no LLM, timeout, error, director switch). |
| `assistant/summary.py` | State → ~10 lines of text for the LLM. |
| `assistant/memory.py` | Last 3 utterances (short memory). |
| `assistant/music.py` | Music candidates by taste / energy / cabin (plan D8), volume. |
| `assistant/answers.py` | Multimodal yes / no / silence / refusal fusion (plan E3). |
| `assistant/cabin.py` | Who is in the car (names, child, passenger asleep). |
| `assistant/textutil.py` | Normalisation (diacritics), word count, sentence split, safe templates. |
| `assistant/settings.py` | Loads `assistant/config/*.yaml` and `.env`. |
| `assistant/contract.py` | Single import point for contract types; uses `shared/contracts.py` automatically when it exists. |
| `assistant/_TEMP_contract_DELETE_LATER.py` | **Temporary** copy of the contract (sections 6 and 7). Delete it once P2 publishes `shared/contracts.py`. |
| `assistant/llm/` | `base.py` (interface), `gemini.py` (Gemini, streaming + JSON schema), `offline.py` (no key). |
| `assistant/prompts/system.md` | System prompt: rules, action table, per-event guidance, examples. Tune it during rehearsals. |
| `assistant/config/assistant.yaml` | Every threshold and list of P3 (no secrets). |
| `assistant/config/texts.ro.yaml` | Fixed Romanian texts: fallbacks and clips. Copy to `texts.en.yaml` to switch to English. |
| `assistant/data/media_catalog.json` | Music catalog (6 tracks; titles and sources still TODO). The mp3 files go in `assistant/data/media/` (gitignored). |
| `assistant/dev/try_llm.py` | Manual LLM test on the scene fixtures. |
| `assistant/dev/voice_server.py` | Fake core and voice test page (port 8010). |
| `integrations/audio_clips.py` | Pre-generates the critical clips into `dashboard/public/sounds/clips/` and writes `clips.json`. |
| `integrations/phone_bridge.py` | KDE Connect ↔ core bridge (separate process, Linux), with `--dry-run` for any OS. |
| `dashboard/src/voice/` | Browser voice: `index.js` (API for P4), `stt.js`, `player.js`, `onset.js`, `dev.html`. |
| `dashboard/public/sounds/clips/` | Generated clips (27 mp3 + `clips.json`). Committed, so the demo works offline. |
| `tests/assistant/` | Tests (`p3_helpers.py` holds the helpers) and fixtures (`fixtures/state_example.json` + `fixtures/scenes/*.json`). |

---

## 3. Interfaces for core (P2)

### 3.1 `handle_event`

```python
from assistant.client import handle_event, get_client
from assistant.tts import speak_message

actions = await handle_event(event, state, on_early_speech=None)
info = get_client().last_result          # source LLM/RULE, reason, latency, llm_ttft_ms, rejected
```

- `event` and `state` may be Pydantic models or plain dicts.
- It never raises. It always returns at most 3 validated actions.
- `on_early_speech(action)` is optional. It is called for each valid `speak` / `ask` that is complete while the LLM is still streaming. Send it to the browser right away; the same action comes back in the final list with `streamed=True`, so do not speak it twice.
- Actions with `needs_confirmation=True` must be executed only after a "yes" (see `assistant/answers.py`).
- `last_result.llm_ttft_ms` / `llm_total_ms` feed `perf.llm_ttft_ms` / `perf.llm_total_ms` (plan J1). `source` and `reason` feed the event log (plan H3).
- `get_client().reset()` clears memory and the rate limit (new trip / director reset).

### 3.2 Event types (P3 proposal; the plan leaves them open)

| `event.type` | When core sends it | `event.data` |
|---|---|---|
| `trip_start` | occupants recognised at start (scene 1) | – |
| `driver_speech` | addressed driver utterance (`speech` with `addressed=true`) | `text` |
| `passenger_speech` | addressed passenger utterance | `text`, `person_id` |
| `cause_detected` | `state.cause.label` set (plan B4) | – (reads `state.cause`) |
| `fatigue_high` | F above threshold (D3/D10) | – |
| `disengagement_high` | D above threshold, monotonous context (D8) | – |
| `media_declined` | driver said no to the music | – |
| `message_received` | F2 timing rule allows delivery | `msg_id`, `delivery`: `"ask"` or `"read"` |
| `safe_contact_reply` | reply of the trusted contact (F8) | `msg_id`, `delivery` |
| `message_reply_dictated` | driver dictated a reply (F3) | `msg_id`, `text` |
| `stop_suggested` | P2 picked a stop (D3/K3) | `poi_id`, `poi_name`, `dist_km`, `task` (open reminder, optional), `poi_options` (optional) |
| `alert_explain` | after an alert (D5) | `explanation` (P2's sentence, e.g. "ai privit în jos 2,1 s la 110 km/h") |
| `driver_refused` | `is_refusal(text)` was true in the fatigue dialog | `text` |

`driver_refused` never goes to the LLM. It returns the clip "Ok, te las în pace." (`clip_id="refusal_ack"`) plus `stay_silent(reason="driver_refused")`. **Notifying the trusted contact is P2's rule C10**; P2 plays `notify_contact_<name>.mp3` itself.

### 3.3 Action format

A single flat model (`Action` in the contract). The `type` values and their parameters are exactly those of plan section 6. P3 adds a few optional fields:

| Field | Meaning |
|---|---|
| `source` | `"LLM"` or `"RULE"` (plan principle 5) |
| `clip_id` | a pre-generated clip that says `text`; play `/sounds/clips/<clip_id>.mp3` instead of TTS |
| `needs_confirmation` | from the "Cere confirmare" column (and F2 for `read_message`) |
| `streamed` | already spoken during streaming |
| `volume` | for `play_media` (cabin-aware, see `music.volume_for`) |

### 3.4 Policies applied before the LLM

1. Safety veto: `safety.level` in P0–P2 or `safety.llm_allowed = false` → `stay_silent("safety_veto")`.
2. Muted (`assistant.muted_until` in the future) → no initiative. Exceptions in `policies.allowed_while_muted` (messages, contact reply, driver requests).
3. `conversation = true` → comfort is skipped; `cause_detected` and `fatigue_high` still go through (plan G2).
4. At most one **proactive** answer per 30 s (`policies.proactive_events`).
5. `safety.llm_enabled = false` (director button, plan C6) → fixed texts, same behaviour otherwise.

---

## 4. Browser voice (`dashboard/src/voice/`) and `/ws/ui` messages

### 4.1 For P4 (React)

```js
import { initVoice, onTranscript, isSpeaking, stopVoice } from "./voice/index.js";

// Must run inside a click handler: the browser needs a gesture for the microphone and audio.
async function onStartClick() {
  await initVoice(ws);                       // ws = WebSocket to ws://localhost:8000/ws/ui
  onTranscript((r) => setSubtitle(r.text));  // interim + final results
}
// useEffect(() => () => stopVoice(), []);
```

- Works only in **Google Chrome** (not Chromium): the Web Speech API needs Google's service.
- The dashboard must serve `dashboard/public/sounds/` at `/sounds/` (Vite does this by default for `public/`), and core must mount `assistant.router` so `/tts/...` and `/media/...` are reachable from the page origin. In dev, proxy them to core.
- `initVoice` reads `/sounds/clips/clips.json` and preloads every clip, so alarms play instantly.

### 4.2 Messages core → browser

```jsonc
{"type": "speak", "id": "u12", "to": "driver", "is_question": true, "expects": "yes_no",
 "text": "Pare monoton. Pun ceva mai energic?", "clip_url": null,
 "sentences": [{"id": "3f2a…", "text": "Pare monoton.", "url": "/tts/3f2a….mp3"}, …]}
{"type": "speak_control", "action": "pause" | "resume" | "stop"}    // D4: yield the floor, "...cum ziceam"
{"type": "alarm", "id": "a7", "clip_url": "/sounds/clips/alarm_andrei.mp3"}   // stops speech AND music
{"type": "media", "action": "play" | "stop" | "volume", "url": "/media/t14.mp3", "volume": 0.6}
{"type": "state", "state": {…}}                                     // voice reads interaction.dialog_window_open
```

Build `speak` with `assistant.tts.speak_message(action)`. It also starts synthesizing every sentence in the background.

### 4.3 Messages browser → core

```jsonc
{"type": "speech", "text": "pune ceva muzică", "raw": "copilot pune ceva muzică", "final": true,
 "addressed": true, "confidence": 0.92, "ts": 1763672400.12}
{"type": "speech_onset", "ts": 1763672399.87}        // start of voice (WebAudio) -> P2 verbal reaction time
{"type": "speak_done", "id": "u12", "is_question": true, "interrupted": false, "ts": 1763672398.40}
{"type": "alarm_played", "id": "a7", "ts": 1763672401.05}   // alarm latency (plan J1)
```

- `addressed` is true when the text contains the wake word (`drivemate`, `drive mate`, `copilot`) or the dialog window is open. Core should act only on addressed final results.
- After `speak_done` for a question, core opens the 6 s dialog window (plan E1). The voice also keeps a local copy, so it works with a fake core.
- Half-duplex (plan E6): recognition and onset detection are off while the assistant speaks.

### 4.4 Pre-generated clips (`integrations/audio_clips.py`)

| Clip id | Text (ro) | Plan |
|---|---|---|
| `alarm_<name>` | "ANDREI!" | C3 |
| `are_you_ok` | "Ești bine?" | C4 |
| `passenger_instructions_<passenger>_<driver>` | "Maria, Andrei nu răspunde. Pornește avariile. Rămâi pe linie, chem ajutor." | C5 |
| `monitoring_lost` | "Nu te mai văd. Monitorizarea e întreruptă." | C7 |
| `refusal_ack` | "Ok, te las în pace." | D10 |
| `notify_contact_<contact>` | "Îi dau de veste lui Mihai." | C10 |
| `resume` | "...cum ziceam," | D4 |
| `message_deferred` | "Ți-l citesc imediat ce e liniște." | F2 |
| `confirm_ok/noted/sent/done/cancelled` | "Ok." / "Notat." / "Trimis." / "Gata." / "Bine, am anulat." | E7 |

Names come from `profiles/*/profile.json` (P4) when present (`name`, `safe_contact.name`, `emergency_contact.name`), otherwise from `clips.names` / `clips.contact_names` in `assistant.yaml`. Re-run the script after changing names or texts (`--force` regenerates everything).

---

## 5. Phone bridge (`integrations/phone_bridge.py`) and `/ws/phone`

A separate process. It can run on a Linux laptop other than the demo laptop: set `CORE_URL` in that laptop's `.env`.

```jsonc
// bridge -> core
{"type": "phone_message", "notification_id": "…", "app": "whatsapp", "from": "Mihai", "text": "…", "replyable": true, "ts": 1763672390.0}
{"type": "phone_status", "connected": true, "battery": 64}
{"type": "phone_result", "request_id": "r1", "ok": true, "error": null}
// core -> bridge
{"type": "send_reply", "request_id": "r1", "notification_id": "…", "text": "Ajung pe la 18:40."}
{"type": "send_sms", "request_id": "r2", "to": "safe_contact" | "emergency", "text": "DriveMate: …"}
```

- `send_reply` uses the notification's reply action (`sendReply`). This works for WhatsApp and for SMS apps with direct reply.
- `send_sms` takes a **role**, never a number. The numbers come from `.env` (`SAFE_CONTACT_NUMBER`, `EMERGENCY_NUMBER`) and are never logged. The message text comes from P2's fixed templates (SOS report, trusted contact).
- Whitelists are in `assistant.yaml` → `phone.app_whitelist` (Android app name → `sms` / `whatsapp`) and `phone.contact_whitelist`. Message texts are never logged.
- Setup (plan F): KDE Connect on Linux (`sudo dnf install kde-connect`, `sudo firewall-cmd --add-service=kdeconnect`), paired with an **Android** phone with notification access, both on the same network (phone hotspot / USB tethering). Then `kdeconnect-cli -l` shows the device id; put it in `KDECONNECT_DEVICE_ID`.
- `--dry-run` runs on any OS: no D-Bus and nothing sent. Type `Mihai|Salut!` to inject a fake WhatsApp message into core.
- Not implemented (S priority): incoming calls (F4).

---

## 6. Music (plan D8)

- Catalog: `assistant/data/media_catalog.json`. Fields: `id`, `title`, `artist`, `genre`, `energy` 1–5, `kid_safe`, `file`, `source`, `license`. Current content: 6 tracks (`lofi1`, `lofi2`, `pop1`, `pop2`, `rock1`, `rock2`); titles, artists and sources are still TODO, and there is no `kid_safe` track yet. Tests use their own catalog (`tests/assistant/fixtures/media_catalog_test.json`), so changing the real one never breaks them.
- Files: `assistant/data/media/<id>.mp3` (gitignored; share them between you, not through git). Served at `/media/<id>.mp3`.
- Candidates: energy ≥ 4 against disengagement, liked genres first (from `profiles/<driver>/profile.json` → `music_genres` or `preferences.music_genres`, otherwise `music.default_genres`), `kid_safe` only with a child on board, lower volume when the passenger sleeps.
- The LLM chooses one of the candidates listed in the summary. Any other `track_id` is rejected.

---

## 7. Configuration (`assistant/config/assistant.yaml`)

Main keys: `language`, `llm.*` (timeout 2.5 s, max 3 actions, temperature, thinking), `speech.*` (15 words, 6 s window), `policies.*`, `memory.turns`, `tts.*` (voices, rates), `clips.*`, `music.*`, `reminders.poi_categories` (**temporary**: replaced by the categories in `simulator/stops.json` once P4 creates it), `preferences.*`, `phone.*`.

Secrets are only in `.env`: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `SAFE_CONTACT_NUMBER`, `EMERGENCY_NUMBER`, `KDECONNECT_DEVICE_ID`, `CORE_URL`.

`llm.thinking_budget` and `llm.thinking_level` are both `null` by default: Gemini 3.x models reject `thinking_budget` (HTTP 400), and some also reject level `minimal`. A rejected value makes every call fail with `llm_error`.

The Gemini answer schema has one branch per action type, with all of its fields required (`assistant/llm/gemini.py` → `ACTION_FIELDS`). Without it, small models sometimes put a value in the wrong field (e.g. `value` instead of `text`).

---

## 8. Notes for the other roles

- **P2:** read the header of `assistant/_TEMP_contract_DELETE_LATER.py`. Once `shared/contracts.py` exists, `assistant/contract.py` switches automatically. Run `pytest tests/assistant` and delete the temporary file. The event types (3.2) and the `/ws/ui` and `/ws/phone` messages (4.2, 4.3, 5) are P3 proposals: change them in the contract if needed and tell P3.
- **P4:** see 4.1 for the voice. `profiles/<name>/profile.json` may contain `name`, `music_genres`, `safe_contact: {name}` and `emergency_contact: {name}`; P3 reads these fields. `simulator/stops.json` categories are used for reminders.
- **P1:** the voice uses `driver.head.answer` and `driver.gesture` (MediaPipe names `Thumb_Up`, `Thumb_Down`, `Open_Palm`) through `assistant/answers.py`.

## 9. Status

| Area | Status |
|---|---|
| Refusal, policies, validation, fallback, summary, memory, music logic, answer fusion | done, tested |
| Gemini client (streaming, JSON schema, 2.5 s deadline, early speech) | done; real call to test once the key is in `.env` |
| TTS router, clips (27 generated), browser voice modules, voice test page | done; Chrome microphone test pending (a manual step) |
| Phone bridge | written and dry-run tested; real KDE Connect test pending (needs the Linux laptop + Android) |
| Music catalog | 6 real tracks served from `assistant/data/media/`; titles, sources and a kid_safe track still missing |
| Integration with core `/ws/ui`, `/ws/phone` | waits for P2 |
