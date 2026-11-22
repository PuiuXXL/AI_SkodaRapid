# P3 · Assistant, voice and phone

[Project setup](../README.md) · [Role brief](../roluri/P3-llm-voce-telefon.md) · [Configuration](config/assistant.yaml)

P3 turns core events and driver requests into short spoken responses and validated actions. Core retains authority over safety and execution. The assistant can operate with fixed offline responses when Gemini is disabled, unavailable or too slow.

## Tech stack

| Technology | Use |
| --- | --- |
| Python 3.11 | Assistant runtime |
| Google Gen AI SDK / Gemini | Structured conversational responses and action proposals |
| Pydantic v2 | Events, state, actions and response validation |
| edge-tts | Romanian neural speech streamed through HTTP |
| FastAPI + Uvicorn | TTS/media endpoints and standalone voice test server |
| aiohttp + yt-dlp | Media search, extraction and HTTP audio proxy |
| Browser Web Speech API | Driver speech recognition and wake-word interaction |
| Browser Web Audio / speechSynthesis | Audio playback, alarm priority and fallback speech |
| websockets | Phone bridge connection to core |
| dbus-next / KDE Connect | Linux/Android phone transport |
| pytest + pytest-asyncio | Offline policies, dialogue and action tests |

## Implementation

1. `client.py` receives an event and a state snapshot, applies policies and builds a compact context.
2. `summary.py`, `cabin.py` and `memory.py` supply relevant trip/cabin/conversation context.
3. `llm/` selects an offline provider or Gemini. `prompts/system.md` defines the structured-response contract.
4. `actions.py` validates action payloads. Core performs an additional validation before execution.
5. `dialog.py` tracks pending questions and confirmations. `answers.py` normalizes supported replies.
6. `policies.py`, `refusal.py` and `preferences.py` govern when to speak, refusals and driver preferences.
7. `tts.py` prepares/streams spoken sentences. `router.py` serves TTS and media to the browser.
8. `music.py` and `media_search.py` resolve appropriate media and expose playable resources.
9. `integrations/phone_bridge.py` connects phone notifications/actions to core.

### Deadlines and fallback

`assistant.yaml` configures the deadline for the first spoken LLM sentence and a separate total deadline. Early complete sentences can be played while generation continues. A transient-error retry uses the remaining budget and an optional backup model. Fixed prompts handle offline operation, invalid responses and timeouts.

The browser audio layer is under `dashboard/src/voice/`. Critical/urgent speech takes priority, stale normal utterances can be dropped, and playback feedback is sent to core. The dialogue window is kept open after a question or wake word according to its current implementation. Audio is half-duplex to avoid the assistant recognizing its own voice.

## Install and configure

From the repository root, inside the virtual environment:

```bash
python -m pip install -r requirements/p3-assistant.txt -r requirements/p2-core.txt
```

Use the root `.env`:

```dotenv
LLM_PROVIDER=gemini
LLM_API_KEY=your-local-key
LLM_MODEL=your-available-model-id
```

Choose a model available to your account. Provider/model retries and deadlines are configured in `assistant/config/assistant.yaml`. Set `LLM_PROVIDER=offline` for fixed replies without LLM requests. Model keys and phone numbers are never committed.

The configured spoken language is Romanian. Text templates are in `config/texts.ro.yaml`, and voice names are in `config/assistant.yaml`. Dashboard labels are independent of spoken language.

## Run

### Integrated platform

```bash
python -m core.main
```

Core mounts the assistant router and runs its background link. Start a perception source and the Vite dashboard in separate terminals, then enable voice in Chrome.

### Standalone voice development

```bash
python -m assistant.dev.voice_server --port 8010
```

Open `http://localhost:8010` in Chrome and press **Start** to grant microphone/audio access. This development server uses a fake core for voice interaction. It has its own `/ws/ui` and mounts the real TTS/media routes.

### Phone bridge

```bash
python -m integrations.phone_bridge --dry-run
```

For a real Android phone, pair KDE Connect on Linux, set `KDECONNECT_DEVICE_ID` and run without `--dry-run`. This uses D-Bus and requires the corresponding phone permissions. The frontend only marks an action complete when the backend/bridge reports its outcome.

## Preferences

`talkativeness` controls proactive suggestions, `answer_length` controls response length and `follow_up` controls follow-up questions. The dashboard sends the accepted values through the core command contract. Preferences apply to the current trip and initial values come from the driver profile. Critical safety rules have their own priority.

## Verification

```bash
python -m pip install pytest-cov ruff
python -m pytest tests/assistant -q --cov=assistant --cov-fail-under=70
python -m pytest tests/core/test_assistant_link.py tests/core/test_alert_conversation.py -q
node --test dashboard/tests/voice.test.mjs
```

Tests use offline providers, synthetic media and isolated profiles. They cover policies, refusals, pending confirmations, media selection, route context, preferences and HTTP endpoints. Live LLM evaluations are separate under `assistant/dev/`; reports in `docs/eval/` describe the configuration and measured conditions.
