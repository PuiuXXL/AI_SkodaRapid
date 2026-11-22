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
| `assistant/router.py` | **Mounted by core.** `GET /tts/{id}.mp3`, `GET /media/{track_id}.mp3`, `GET /media/yt/{video_id}.m4a` (YouTube audio proxy), `GET /assistant/health`. |
| `assistant/media_search.py` | YouTube music / podcasts on request (section 6.1): search (Data API or yt-dlp), spoken titles, choice question, answer parsing, audio stream resolution. |
| `assistant/tts.py` | edge-tts synthesis, sentence cache, and `speak_message(action)`, which builds the `speak` message for the browser. |
| `assistant/actions.py` | Validation of actions against plan section 6: types, levels, parameters, word limit (`speech.max_words_to_driver`, 30, whole text), max 3, confirmation. |
| `assistant/policies.py` | When the assistant may answer: P0–P2 veto, muted after refusal, conversation, 1 proactive answer / 30 s. |
| `assistant/fallback.py` | Fixed answers per event type (no LLM, timeout, error, director switch). |
| `assistant/summary.py` | State → ~10 lines of text for the LLM. |
| `assistant/memory.py` | Last 3 utterances (short memory). |
| `assistant/preferences.py` | How the driver wants the assistant to interact: `talkativeness`, `follow_up`, `answer_length` (section 3.6). Reads `profiles/<driver>/profile.json`; voice changes last one trip. |
| `assistant/music.py` | Music candidates by taste / energy / cabin (plan D8), volume. |
| `assistant/answers.py` | Multimodal yes / no / silence / refusal fusion (plan E3), and `parse_kss` for the KSS value 1–9 (plan D3). |
| `assistant/dialog.py` | **Used by core.** `DialogManager`: holds actions waiting for "yes", resolves the answer (voice, nod or gesture), and drives the KSS answer and the quiz. |
| `assistant/quiz.py` + `assistant/data/quiz.json` | Short spoken quiz (20 questions, all ≤ 15 words, kid-safe), offered when the driver refuses music (plan D8). |
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
| `assistant/dev/voice_server.py` | Fake core and voice test page (port 8010). It also **simulates two P2 rules** (logged as `[simulat P2]`): KSS ≥ 7 → `stop_suggested` for the next POI (D3/K3), and a refusal with high fatigue → assistant muted 15 min plus a simulated SMS to the trusted contact (C10). |
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
| `media_declined` | driver said no to the music (`DialogManager` emits it) | – (handled without the LLM: quiz offer with `reason="quiz_offer"`) |
| `kss_answer` | driver answered the KSS question (`DialogManager` emits it) | `value` (1–9). The assistant only acknowledges it ("Ok, 7 e mult. Hai să găsim o pauză."). **P2 must then pick the stop** (plan D3/K3) and send `stop_suggested`, because the concrete question "Oprim la OMV peste 12 km?" opens the next dialog window. |
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
| `title` | for `play_media` of a YouTube result: the short spoken title (show it on the dashboard) |
| `options` | for `ask` with `expects: "choice"`: the YouTube results (section 6.1) |
| `query`, `kind` | for `search_media` (internal to the assistant, never returned to core) |

`search_media` is an action the LLM may produce, but `handle_event` resolves it before returning: core receives an `ask` with `expects: "choice"` instead (section 6.1).

### 3.4 Answers, confirmations, KSS and quiz: `DialogManager`

Actions with `needs_confirmation` must not run until the driver says yes. Core keeps one `DialogManager` per trip:

```python
from assistant.dialog import DialogManager
from assistant.answers import InputEvent

dialog = DialogManager()

actions = await handle_event(event, state)
for action in dialog.register(actions, now):    # held actions are NOT returned
    execute(action)                              # speak the question, etc.

# For every input while something is pending (voice text from /ws/ui, head.answer and
# gesture from the state, all with timestamps):
result = dialog.handle([InputEvent("voice", text, ts), InputEvent("nod", "yes", ts2)],
                       now, state=state, fatigue_dialog=fatigue_dialog_open)
if result.handled:
    for action in result.execute: execute(action)   # confirmed; suggest_media -> play_media
    for action in result.speak:   say(action)       # "Notat." / "Trimis." / quiz feedback (clips or TTS)
    for ev in result.events:      await handle_event(ev, state)   # media_declined, kss_answer, driver_refused
    log(result.answer, result.channel)               # plan E3: which channel answered
else:
    ...  # not an answer: treat the text as a normal driver_speech
```

| Pending question | Answer | Result |
|---|---|---|
| confirmation ("Bine?", "Trimit?", "Oprim?", "Îl citesc?") | yes (voice / nod / 👍) | `execute` the held actions, plus a clip: `confirm_noted` (reminder), `confirm_sent` (reply), `confirm_ok` (stop, preference), `confirm_done` (reminder done) |
| | no | `cancelled`, plus the `confirm_cancelled` clip. For refused music: event `media_declined` instead (→ quiz offer) |
| | music offer answered with a wish: "da, ceva metal energic" | offer `cancelled`, event `driver_speech {text}` (→ YouTube search, section 6.1) |
| | a yes / no **followed by a new request**: "nu, vreau să pui muzică", "da, și pune muzică" | the answer is applied (cancel without the clip / execute), and the rest of the sentence goes on as event `driver_speech {text}` (`answers.request_after_answer`). Also for the quiz offer |
| | ✋ silence | cancelled quietly |
| KSS ("Cât de obosit ești, 1–9?") | "șapte", "7", "cam opt" | event `kss_answer {value}` |
| | "lasă-mă în pace", ✋, 👎 | event `driver_refused` (→ P2's rule C10) |
| quiz offer | "da" / "quiz" | first question (`ask`, free answer) |
| | "podcast" (if the catalog has a track with genre `podcast`) | `play_media` of the podcast |
| quiz question | any answer | "Corect!" or "Nu chiar, era X." + the next question; after `quiz.length` questions: "Gata quizul: 2 din 3. Bravo!" |
| | "gata" / "stop" / ✋ | "Bine, oprim quizul." |
| YouTube choice ("Am găsit: A, B sau C. Care?" / "Pun A?") | "a doua", "prima", "ultima", "trei", "cel cu Metallica"; "da" / nod / 👍 when one option | `execute` = `play_media {track_id: "yt:<id>", title}` + "Pornesc A." |
| | "altceva", "nu", "niciuna", 👎, nod no | the next results as a new question; when none are left: "Altceva n-am găsit. Spune-mi ce să caut." |
| | "lasă", "stop", ✋ | cancelled quietly |
| | anything else ("pune ceva jazz") | not an answer (`handled=False`): treat it as a new `driver_speech` |

**"Te mai ajut cu ceva?" (`speech.follow_up`).** When the assistant answers the driver (`driver_speech`) with a statement and no question, `AssistantClient` adds `ask("Te mai ajut cu ceva?", expects="free", reason="follow_up")`. It never does so after proactive events (cause, fatigue, message), after a question, a held action or a refusal. A `speak` to the driver that ends with "?" is already turned into an `ask` by validation (`actions.question_as_ask`), so it opens the dialog window too. The answer is handled by `DialogManager`: "nu" / "nimic" / "gata" → nothing is said, and the browser closes its dialog window at once (`NO_MORE_ANSWERS` in `dashboard/src/voice/index.js`), so speech without the wake word is ignored again. "da" alone → "Spune." (a new question, a new window). "nu, pune muzică" → the request is passed on. Any other request → normal speech for the LLM. Note: the real core keeps its own window open until it expires (`core/dialog_window.py`); closing it on "nu" there is P2's choice.

An unanswered question expires after `speech.pending_timeout_s` (20 s). Its held actions are cancelled and never executed. A new utterance of the assistant (e.g. a cause or message interrupting a quiz) replaces the pending question.

To read a message after `read_message` is confirmed, core says the message text as is (no 15-word rule): `speak_message(Action(type="speak", to="driver", text=message.text, source="RULE"))`.

### 3.5 Policies applied before the LLM

1. Safety veto: `safety.level` in P0–P2 or `safety.llm_allowed = false` → `stay_silent("safety_veto")`.
2. Muted (`assistant.muted_until` in the future) → no initiative. Exceptions in `policies.allowed_while_muted` (messages, contact reply, driver requests).
3. `conversation = true` → comfort is skipped; `cause_detected` and `fatigue_high` still go through (plan G2).
4. At most one **proactive** answer per 30 s (`policies.proactive_events`). Comfort events (`driver_preferences.comfort_events`, now `disengagement_high`) use the interval of the driver's `talkativeness` instead (section 3.6).
5. `safety.llm_enabled = false` (director button, plan C6) → fixed texts, same behaviour otherwise.

### 3.6 Driver interaction preferences (`assistant/preferences.py`)

Three preferences change **how** the assistant talks, never what is safe:

| Key | Values | Effect |
|---|---|---|
| `talkativeness` | `low` / `normal` / `high` | Minimum time between two comfort suggestions (`driver_preferences.comfort_interval_s`: 120 / 30 / 15 s). Cause and fatigue keep the normal 30 s. Also in the LLM summary (less small talk at `low`). |
| `follow_up` | `always` / `never` | Whether "Te mai ajut cu ceva?" is added after a statement (3.4). |
| `answer_length` | `short` / `normal` | The LLM is asked to aim for `driver_preferences.answer_words.short` (12) words. The hard limit stays `speech.max_words_to_driver` (30), so a slightly longer answer is not replaced by a fixed text. |

Where the value comes from, last one wins: `driver_preferences.defaults` in `assistant.yaml` → `preferences` in `profiles/<driver>/profile.json` (written by hand or by a future profile page: P4 removed the old one on 2026-11-22; the file is read again when it changes) → a confirmed `set_preference` by voice ("răspunde mai scurt" → "Răspund mai scurt. Bine?" → "da"), kept in memory until `AssistantClient.reset()` (new trip / director reset). Values not listed under `preferences:` in `assistant.yaml` are ignored at every level.

**Voice, with or without the LLM.** Known phrases are recognised without the LLM, like the volume commands (`preferences.voice_command`, phrases in `driver_preferences.voice_commands`, utterances of at most `voice_max_words` = 12 words): "răspunde mai scurt", "răspunde normal", "nu mă mai întreba dacă mai vreau ceva", "întreabă-mă dacă mai vreau ceva", "vorbește mai rar", "nu-mi mai propune atâtea", "propune mai des". They get `set_preference` + the fixed question from `texts.ro.yaml` → `fallback.preference_confirm` ("Răspund mai scurt. Bine?"), or "E deja așa." when nothing would change. They work offline and never wait for Gemini. Any other wording goes to the LLM, which returns the same pair of actions (system prompt).

**Core's part (agreed with P2):**
- The voice change is recorded by **core**, in `AssistantLink._preference` (`preferences.store.apply(action, state)`), i.e. only after the C8 check: a change core rejects (e.g. the level went to P3 before the "da") never applies. `DialogManager` only releases the action. The dev voice server does the same in its `execute`.
- The dashboard's settings page (menu "Setări", `#/setari`, `dashboard/src/driver/SettingsPage.tsx`) sends `{type: "command", cmd: "assistant_preference", value: {key, value}}` (`UI_COMMANDS`). Core (`AssistantLink._panel_preference`) applies it at once, without "Bine?" (the driver chose it there), for this trip like a voice change; an unknown key or value is logged as `action_rejected`. A reset (`AssistantLink.reset`) forgets voice and panel changes.
- Core copies `preferences.effective(state)` into `state.assistant.preferences` (`shared/contracts.py`, `AssistantStatus`) every tick and right after a change, so the dashboard sees profile and voice changes.
- Decisions: a voice change lasts one trip (not written to `profile.json`); the three keys still need "Bine?" (only `volume` is in `NO_CONFIRMATION_PREFERENCES`); `talkativeness` slows down only `disengagement_high`.

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
{"type": "media", "action": "play" | "stop" | "volume", "url": "/media/t14.mp3", "volume": 0.6,
 "loop": true}                                                      // loop: music.loops(track_id), false for YouTube
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

- `addressed` is true when the text contains the wake word (`drivemate`, `drive mate`, `copilot`) or the dialog window is open. Core should act only on addressed final results. The wake word is removed from `text`; diacritics are kept. An utterance that **started** while the window was open stays addressed even if Chrome publishes its final text after the window closed (Chrome often needs 1.5–3 s).
- **Early finalisation (latency).** Chrome publishes a final result only after ~0.5–1 s of silence. So an addressed interim result that stays unchanged is sent as final before that:
  - after `quickAnswerMs` (300 ms) for a short answer while the dialog window is open (`da`, `nu`, `7`, `gata`...), with `early: "quick"`;
  - after `earlyFinalMs` (800 ms) for any other request of at least 2 words, with `early: "stable"`.

  Chrome's later final for the same result is ignored. If the driver kept talking after the early send, the full sentence is sent too. `wait_ms` is the time since the last change of the text. Both delays are options of `initVoice` (0 disables).
- **Streamed TTS.** `/tts/<id>.mp3` is streamed while edge-tts is still generating it: the browser starts playing at the first chunk (~0.9–1.5 s) instead of waiting for the whole file. The next sentences are already being synthesized in the background, so they usually start instantly.
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

### 6.1 YouTube music and podcasts on request (S feature)

The driver asks for something specific ("dă-mi ceva muzică metal energică", "caută un podcast despre istoria Romei"), or answers the music offer with a wish ("da, ceva metal"). The assistant searches YouTube, says the top results and plays the one the driver picks. The local catalog stays: it is used for the proactive offer against disengagement (D8) and whenever YouTube is not reachable.

```
Șofer:    „Dă-mi ceva metal energic.”
LLM:      search_media {query: "energetic metal", kind: "music"}      (fallback without LLM: media_search.media_request)
Asistent: „Caut.”                                                      (early speech while searching)
          search (Data API ~0.5 s / yt-dlp ~1.3-2.5 s) -> ask expects="choice", options = the results
Asistent: „Am găsit: Metallica, Hardwired, Slipknot, Duality sau Nu Metal Mix. Care?”     (<= speech.max_words_to_driver)
Șofer:    „A doua.” / „Cel cu Slipknot.” / „Altceva.” / 👍 (one option)
          DialogManager -> play_media {track_id: "yt:6fVE8kSM43I", title: "Slipknot, Duality"} + „Pornesc Slipknot, Duality.”
Core:     media play, url = music.track_url(track_id) = /media/yt/6fVE8kSM43I.m4a, loop = false
```

- **One option at speed.** At `speed_kmh >= youtube.single_option_speed_kmh` (90) or `risk >= youtube.single_option_risk` (1) only one option is offered ("Pun Metallica, Hardwired?"); "altceva" gives the next one. Three titles are too much to keep in mind at highway speed.
- **Spoken titles** are cleaned deterministically (`clean_title`): brackets, hashtags, emoji, `| extra parts` and noise words (`youtube.title_noise`) are removed, "Artist - Title" becomes "Artist, Title", and words are cut (4 down to 2) until the question fits `speech.max_words_to_driver`. No second LLM call.
- **Search:** YouTube Data API v3 when `YOUTUBE_API_KEY` is set in `.env` (free quota: 10,000 units/day, one search costs ~101, so ~100 searches/day; SafeSearch). Otherwise yt-dlp, no key. Measured on this laptop with yt-dlp: 2.2–2.4 s for the first search, 1.25 s after that.
- **Playback (variant B):** yt-dlp resolves the audio-only stream (m4a), prefetched while the question is spoken. `GET /media/yt/<id>.m4a` proxies it: same origin, `Range` supported (seeking), fetched upstream in 4 MB chunks, URL refreshed once on 403. Measured: audio starts **0.16 s** after the choice when the prefetch is done. Same `<audio>` element as the catalog, so alarms stop it, speech ducks it, and there are no ads.
- **Safety:** `search_media` and `play_media` are P4 (comfort), so they are rejected at P0–P3. Only video ids found by a search in this process can be played or proxied (`media_search.known`). A child on board means SafeSearch strict, which needs the Data API key. Without it, the assistant offers a kid_safe catalog track instead.
- **Stopping:** "oprește muzica", "oprește ce dă play acum", "pune pauză", or just "stop" while something plays, is recognised by keywords (`fallback.stop_media_request`) and answered at once without the LLM: `stop_media` + the "Ok." clip. "Oprește aici / la OMV" is about the car and is not matched. If the LLM returns an action with no sentence (e.g. only `stop_media`), "Ok." is added instead of falling back to "n-am înțeles".
- **Volume:** "mai încet", "dă-l mai tare", "e prea tare" (= quieter), "foarte încet" (double step), "la jumătate", "la maxim", "volumul la 30" -> `set_preference {key: "volume", value}` + "Ok.", also without the LLM (`fallback.volume_request`). Steps and limits: `music.volume_step` (0.2), `music.volume_min` (0.05). It only applies while something plays or when the volume / music is named, and never to "vorbește mai încet" (speech), "mergi mai încet" (speed) or "pune ceva mai tare" (another track). A volume change needs **no confirmation** (`music.volume_without_confirmation`); every other `set_preference` still asks. Core executes it as `{"type": "media", "action": "volume", "volume": value}` and sets `state.media.volume`.
- **Failures:** search impossible -> "Nu pot căuta acum. Pun ceva din ce am?" + a catalog `suggest_media`; no results -> "N-am găsit nimic potrivit. Spune-mi altfel ce să caut."
- **Privacy (slide):** the search text goes to YouTube (or Google, with the API). No audio or image does.
- **Terms of use:** yt-dlp extraction is against YouTube's terms. It is fine for the hackathon demo, but say "in a product: YouTube Music / Spotify API" if the jury asks.

---

## 7. Configuration (`assistant/config/assistant.yaml`)

Main keys: `language`, `llm.*` (timeout 2.5 s, max 3 actions, temperature, thinking), `speech.*` (30 words per text, raised from the plan's 15 on 2026-11-21; 6 s window), `policies.*`, `memory.turns`, `tts.*` (voices, rates), `clips.*`, `music.*`, `youtube.*` (section 6.1), `reminders.poi_categories` (**temporary**: replaced by the categories in `simulator/stops.json` once P4 creates it), `preferences.*`, `phone.*`.

Secrets are only in `.env`: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BACKUP_MODEL` (optional, overrides `llm.backup_model`), `YOUTUBE_API_KEY` (optional, section 6.1), `SAFE_CONTACT_NUMBER`, `EMERGENCY_NUMBER`, `KDECONNECT_DEVICE_ID`, `CORE_URL`.

`llm.thinking_level` is `low` and `llm.thinking_budget` is `null`: Gemini 3.x models reject `thinking_budget` (HTTP 400), and some also reject level `minimal`. A rejected value makes every call fail with `llm_error`. Tested on 2026-11-21 with the real prompt: `gemini-3.5-flash-lite` with the default thinking (`null`) timed out or took ~8 s; with `low` it answered in 0.7–1.6 s.

**Retry on a temporary Gemini error.** A `503 UNAVAILABLE` (Google overloaded), `429` (rate limit) or `500/502/504` gets **one** retry on `llm.backup_model` (default `gemini-3.1-flash-lite` with its default thinking, 0.8–1.2 s in tests; `gemini-2.5-flash` answered 404 although it is still listed, `gemini-3.5-flash` / `gemini-3.6-flash` took 2–3.5 s). The retry happens inside the **same** `llm.timeout_s` deadline (2.5 s), only if nothing was spoken yet and at least `llm.retry.min_remaining_s` (1 s) is left. Otherwise, or if the retry also fails, the fixed texts are used as before. A retried answer has `AnswerInfo.retry` set (e.g. `"503 UNAVAILABLE -> gemini-3.1-flash-lite"`) and a warning in the log. Safety never depends on it: alarms and the P0–P2 rules do not use the LLM.

The Gemini answer schema has one branch per action type, with all of its fields required (`assistant/llm/gemini.py` → `ACTION_FIELDS`). Without it, small models sometimes put a value in the wrong field (e.g. `value` instead of `text`).

---

## 8. Notes for the other roles

- **P2:** read the header of `assistant/_TEMP_contract_DELETE_LATER.py`. Once `shared/contracts.py` exists, `assistant/contract.py` switches automatically. Run `pytest tests/assistant` and delete the temporary file. The event types (3.2) and the `/ws/ui` and `/ws/phone` messages (4.2, 4.3, 5) are P3 proposals: change them in the contract if needed and tell P3.
- **P4:** see 4.1 for the voice. `profiles/<name>/profile.json` may contain `name`, `music_genres`, `safe_contact: {name}`, `emergency_contact: {name}` and `preferences: {talkativeness, follow_up, answer_length}`; P3 reads these fields (section 3.6). There is no profile page any more (removed by P4 on 2026-11-22): until a new one exists, the file is edited by hand; during a trip the preferences are changed by voice or on the dashboard's settings page (menu "Setări", `#/setari`). Core copies the current values into `state.assistant.preferences`, if the dashboard wants to show them. `simulator/stops.json` categories are used for reminders.
- **P1:** the voice uses `driver.head.answer` and `driver.gesture` (MediaPipe names `Thumb_Up`, `Thumb_Down`, `Open_Palm`) through `assistant/answers.py`.
- **YouTube (section 6.1), what the others need to do:** listed in `DriveMate-PLAN-FINAL.md` (section 4.D, D11) and in `roluri/P2…` / `roluri/P4…` ("Adăugat de P3: YouTube").

## 9. Status

| Area | Status |
|---|---|
| Refusal, policies, validation, fallback, summary, memory, music logic, answer fusion | done, tested |
| Confirmations (yes/no on any channel), KSS answer, quiz after refused music | done, tested; simulated on the voice test page (buttons for 👍 👎 ✋ and nods until P1 is connected) |
| Gemini client (streaming, JSON schema, 2.5 s deadline, early speech) | done; real call to test once the key is in `.env` |
| TTS router, clips (27 generated), browser voice modules, voice test page | done; Chrome microphone test pending (a manual step) |
| Phone bridge | written and dry-run tested; real KDE Connect test pending (needs the Linux laptop + Android) |
| Music catalog | 6 real tracks served from `assistant/data/media/`; titles, sources and a kid_safe track still missing |
| YouTube music / podcasts (6.1) | done on branch `p3-youtube-media`, tested (40 tests, no network) and end to end with real YouTube (search -> choice -> proxied audio); Chrome playback through the voice page and the Data API key path not tried yet |
| Integration with core `/ws/ui`, `/ws/phone` | waits for P2 |
