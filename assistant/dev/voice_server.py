"""Voice test server: a fake core for testing the browser voice end to end (roluri/P3 step 3).

Lets P3 test "speak -> LLM -> voice" without core (P2) or the dashboard (P4):

* serves ``dashboard/src/voice/dev.html`` and the voice JS modules;
* mounts the real :mod:`assistant.router` (``/tts``, ``/media``);
* serves the pre-generated clips (``/sounds/clips/...``);
* implements a minimal ``/ws/ui``: recognised speech is sent to the real
  :func:`assistant.client.AssistantClient.handle_event` with a scene fixture as the
  state, and the resulting actions are executed the way core would (speech, music,
  reminders, message reading; phone replies are only logged);
* uses the real :class:`assistant.dialog.DialogManager` for confirmations ("da" /
  nod / thumbs-up), the KSS answer and the quiz. Buttons on the page simulate the
  nod and gestures that P1's camera will provide.

Run (from the repo root)::

    .venv/Scripts/python -m assistant.dev.voice_server            # Windows
    .venv/bin/python -m assistant.dev.voice_server                # Linux / macOS

then open http://localhost:8010 in **Google Chrome** and press "Start".
Optional: ``--scene scene3_message`` picks the fixture used as state
(``tests/assistant/fixtures/scenes/*.json``), ``--port`` changes the port.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
import time
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from assistant import media_search, music, preferences
from assistant.answers import InputEvent
from assistant.client import AssistantClient
from assistant.contract import Action, Event, Reminder, State
from assistant.dialog import DialogManager
from assistant.refusal import is_refusal
from assistant.router import router as assistant_router
from assistant.settings import REPO_ROOT, cfg
from assistant.textutil import normalize
from assistant.tts import speak_message

log = logging.getLogger("drivemate.assistant.dev")

VOICE_DIR = REPO_ROOT / "dashboard" / "src" / "voice"
SOUNDS_DIR = REPO_ROOT / "dashboard" / "public" / "sounds"
FIXTURES = REPO_ROOT / "tests" / "assistant" / "fixtures"


def load_state(scene: str | None) -> State:
    """Example state of plan section 7, with a scene's overrides applied if given."""
    base = json.loads((FIXTURES / "state_example.json").read_text(encoding="utf-8"))
    if scene:
        overrides = json.loads((FIXTURES / "scenes" / f"{scene}.json").read_text(encoding="utf-8"))["state_overrides"]
        base = _merge(base, overrides)
    return State.model_validate(base)


def _merge(base: dict, overrides: dict) -> dict:
    """Recursive dict merge (lists replaced)."""
    out = dict(base)
    for key, value in overrides.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def create_app(scene: str | None = None) -> FastAPI:
    """Build the FastAPI app of the fake core.

    Args:
        scene: Fixture name used as the state for every event.
    """
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Warm up in the background: the LLM connection (first answer) and yt-dlp (first YouTube search)."""
        warm = [asyncio.create_task(media_search.warm_up())]
        if client.provider.available:
            warm.append(asyncio.create_task(client.provider.warm_up()))
        yield
        for task in warm:
            task.cancel()

    app = FastAPI(title="DriveMate P3 voice test", lifespan=lifespan)
    app.include_router(assistant_router)
    app.mount("/voice", StaticFiles(directory=VOICE_DIR), name="voice")
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/sounds", StaticFiles(directory=SOUNDS_DIR), name="sounds")
    client = AssistantClient()

    @app.get("/")
    async def index() -> FileResponse:
        """The voice test page."""
        return FileResponse(VOICE_DIR / "dev.html")

    @app.websocket("/ws/ui")
    async def ws_ui(ws: WebSocket) -> None:
        """Minimal /ws/ui: speech -> handle_event -> speak (see module docstring)."""
        await ws.accept()
        state = load_state(scene)
        dialog = DialogManager()  # pending confirmations, KSS, quiz (assistant/dialog.py)

        async def send(message: dict[str, Any]) -> None:
            """Send one JSON message to the browser."""
            await ws.send_text(json.dumps(message, ensure_ascii=False))

        async def log_line(text: str) -> None:
            """Show a line in the dev page's log panel."""
            await send({"type": "dev_log", "text": text})

        async def open_dialog_window() -> None:
            """Plan E1: after a question, accept voice without the wake word for speech.dialog_window_s."""
            window = float(cfg("speech", "dialog_window_s", default=6))
            state.interaction.dialog_window_open = True
            await send({"type": "state", "state": {"interaction": {"dialog_window_open": True}}})
            await asyncio.sleep(window)
            state.interaction.dialog_window_open = False
            await send({"type": "state", "state": {"interaction": {"dialog_window_open": False}}})

        async def execute(action: Action) -> None:
            """Simulate what core would do with one executable action (log + audio)."""
            if action.type in ("speak", "ask"):
                if not action.streamed:
                    await send(speak_message(action))
            elif action.type == "play_media" and action.track_id:
                await send({"type": "media", "action": "play", "url": music.track_url(action.track_id),
                            "volume": action.volume or music.volume_for(state), "loop": music.loops(action.track_id)})
                state.media.playing, state.media.track_id = True, action.track_id
                state.media.title = action.title
                state.media.source = "catalog" if music.loops(action.track_id) else "youtube"
                if not music.loops(action.track_id):
                    await log_line(f"  [YouTube] {action.title} -> {music.track_url(action.track_id)}")
            elif action.type == "stop_media":
                await send({"type": "media", "action": "stop"})
                state.media.playing = False
            elif action.type == "set_preference" and action.key == "volume":
                state.media.volume = float(action.value)
                await send({"type": "media", "action": "volume", "volume": state.media.volume})
                await log_line(f"  volum muzică: {state.media.volume:.2f}")
            elif action.type == "set_preference" and preferences.store.apply(action, state):
                # Like core's AssistantLink._preference: recorded only when the action is executed.
                await log_line(f"  preferință: {action.key} = {action.value} (până la finalul călătoriei)")
            elif action.type == "read_message":
                message = next((m for m in state.messages if m.id == action.msg_id), None)
                if message is not None and message.text:
                    # Reading a message is not an LLM sentence: no 15-word rule, said as is.
                    await send(speak_message(Action(type="speak", to="driver", text=message.text, source="RULE")))
                    message.state = "read"
            elif action.type == "reply_message":
                await log_line(f"  [simulat] trimis prin telefon către {action.msg_id}: {action.text!r}")
            elif action.type == "create_reminder" and action.trigger is not None:
                reminder_id = f"r{len(state.reminders) + 1}"
                state.reminders.append(Reminder(id=reminder_id, task=action.task or "", trigger=action.trigger,
                                                state="active", created_ts=time.time()))
                await log_line(f"  [simulat] memento ACTIV {reminder_id}: {action.task} @ {action.trigger.category}")
            elif action.type == "complete_reminder":
                for reminder in state.reminders:
                    if reminder.id == action.reminder_id:
                        reminder.state = "done"
            elif action.type == "suggest_stop":
                await log_line(f"  [simulat] oprire acceptată: {action.poi_id}")

        async def apply_dialog(result) -> None:
            """Execute a DialogResult: confirmed actions, short replies, follow-up events."""
            await log_line(f"answer={result.answer} channel={result.channel} "
                           f"execute={[a.type for a in result.execute]} cancelled={[a.type for a in result.cancelled]}")
            for action in result.execute:
                await log_line("  EXECUTAT " + action.model_dump_json(exclude_none=True, exclude_defaults=True))
                await execute(action)
            for action in result.speak:
                # Quiz questions are already tracked inside the DialogManager: do NOT
                # register them again (that would drop the running quiz).
                await send(speak_message(action))
            for follow_up in result.events:
                await run_event(Event(type=follow_up.type, ts=time.time(), data=follow_up.data))

        async def run_event(event: Event) -> None:
            """Send one event through the real assistant client and execute the result."""
            state.ts = time.time()
            early: list[asyncio.Future] = []

            def on_early(action: Action) -> None:
                """Speak a sentence while the LLM is still streaming."""
                early.append(asyncio.ensure_future(send(speak_message(action))))

            actions = await client.handle_event(event, state, on_early_speech=on_early)
            await asyncio.gather(*early)
            info = client.last_result
            await log_line(f"{event.type} -> source={info.source} reason={info.reason} "
                           f"latency={info.latency_ms:.0f}ms ttft={info.llm_ttft_ms and round(info.llm_ttft_ms)} "
                           f"rejected={len(info.rejected)}" + (f" error={info.error}" if info.error else ""))
            if info.error and info.error.startswith("429"):
                await log_line("  (429 = limita de cereri pe minut a cheii gratuite Gemini; așteaptă ~1 minut)")
            elif info.error and info.error.startswith(("500", "503", "504")):
                await log_line("  (eroare temporară pe serverul Google; reîncearcă)")
            immediate = dialog.register(actions, time.time())
            for action in actions:
                tag = "  ÎN AȘTEPTARE (cere „da”) " if action.needs_confirmation else "  "
                await log_line(tag + action.model_dump_json(exclude_none=True, exclude_defaults=True))
            for action in immediate:
                await execute(action)
            await simulate_p2_rules(event)

        async def simulate_p2_rules(event: Event) -> None:
            """SIMULATION of P2's deterministic rules, so whole demo scenes can be tested here.

            In the real system these live in core/ (P2) - not in assistant/:
            * plan D3 / K3: after a high KSS answer, the rule picks the stop (the next POI,
              solving an open reminder of the same category) and sends ``stop_suggested``;
            * plan C10: a refusal while fatigue is high mutes the assistant (P3-P4 only) and
              sends the trusted contact an SMS from the driver's phone.
            """
            if event.type == "kss_answer" and int(event.data.get("value", 0)) >= int(cfg("kss", "high", default=7)):
                poi = state.trip.next_poi
                if poi is None:
                    return
                task = next((r.task for r in state.reminders
                             if r.state == "active" and r.trigger.category == poi.category), None)
                await log_line(f"[simulat P2 · regula D3/K3] KSS mare -> oprire propusă: {poi.name or poi.id}"
                               + (f" (rezolvă și mementoul: {task})" if task else ""))
                await run_event(Event(type="stop_suggested", ts=time.time(), data={
                    "poi_id": poi.id, "poi_name": poi.name or poi.id, "dist_km": poi.dist_km, "task": task}))
            elif event.type == "driver_refused" and state.assessment.fatigue >= 0.6:
                contact = state.safe_contact
                mute_s = 15 * 60
                state.assistant.muted_until = time.time() + mute_s
                state.assistant.mute_reason = "driver_refused"
                await log_line(f"[simulat P2 · regula C10] asistent pe liniște {mute_s // 60} min (alarmele rămân active)")  # noqa: E501
                if contact.configured and contact.consent and contact.name:
                    if contact.announce:
                        clip = f"notify_contact_{normalize(contact.name).replace(' ', '_')}"
                        await send(speak_message(Action(type="speak", to="driver", source="RULE",
                                                        text=f"Îi dau de veste lui {contact.name}.", clip_id=clip)))
                    await log_line(f"[simulat P2 · regula C10] SMS de pe telefonul șoferului către {contact.name} "
                                   "+ notificare galbenă pe DriveMate Contact")

        async def answer(inputs: list[InputEvent]) -> bool:
            """Give inputs to the dialog manager; True if they answered the pending question."""
            result = dialog.handle(inputs, time.time(), state=state, fatigue_dialog=state.assessment.fatigue >= 0.6)
            if result.handled:
                await apply_dialog(result)
            return result.handled

        await log_line(f"connected; LLM provider = {client.provider.name}; scene = {scene or 'state_example'}")
        try:
            while True:
                message = json.loads(await ws.receive_text())
                kind = message.get("type")
                if kind == "speech" and message.get("final"):
                    text = message.get("text", "")
                    how = {"quick": "răspuns scurt, trimis devreme", "stable": "text stabil, trimis devreme"}.get(
                        message.get("early"), "final Chrome")
                    await log_line(f"heard: {text!r} (addressed={message.get('addressed')}, {how}, "
                                   f"la {message.get('wait_ms')} ms după ultimul cuvânt)")
                    if not message.get("addressed"):
                        continue
                    if dialog.has_pending(time.time()) and await answer([InputEvent("voice", text, time.time())]):
                        continue
                    if state.assessment.fatigue >= 0.6 and is_refusal(text):
                        await run_event(Event(type="driver_refused", ts=time.time(), data={"text": text}))
                    else:
                        await run_event(Event(type="driver_speech", ts=time.time(), data={"text": text}))
                elif kind == "speak_done" and message.get("is_question") and not message.get("interrupted"):
                    # Runs in the background so speech keeps being received during the window.
                    asyncio.create_task(open_dialog_window())  # noqa: RUF006
                elif kind in ("speech_onset", "alarm_played", "speak_done"):
                    await log_line(f"{kind}: {json.dumps(message)}")
                elif kind == "command" and message.get("name") == "input":
                    # Buttons simulating P1's nod / gesture recognition (plan E3).
                    channel, value = message.get("channel"), message.get("value")
                    await log_line(f"input {channel}={value}")
                    if not await answer([InputEvent(channel, value, time.time())]):
                        await log_line("  (nicio întrebare în așteptare sau nu e un răspuns)")
                elif kind == "command":
                    await handle_command(message, send, run_event, log_line)
        except WebSocketDisconnect:
            return

    async def handle_command(message, send, run_event, log_line) -> None:
        """Buttons of dev.html: trigger an event, say a text, alarm, pause/resume."""
        name = message.get("name")
        if name == "trigger":
            await run_event(Event(type=message.get("event", "trip_start"), ts=time.time(), data=message.get("data", {})))  # noqa: E501
        elif name == "say":
            await send(speak_message(Action(type="speak", to="driver", text=message.get("text", ""), source="RULE")))
        elif name == "alarm":
            await send({"type": "alarm", "id": f"a{int(time.time())}", "clip_url": message.get("clip_url"), "ts": time.time()})  # noqa: E501
        elif name in ("pause", "resume", "stop"):
            await send({"type": "speak_control", "action": name})
        elif name == "music":
            track = music.pick_track(load_state(scene))
            if track is None:
                await log_line("no track available (catalog / mp3 files missing)")
            else:
                await send({"type": "media", "action": "play", "url": music.track_url(track.id), "volume": 0.6})
        elif name == "stop_music":
            await send({"type": "media", "action": "stop"})

    return app


def main() -> None:
    """Command-line entry point."""
    # Windows consoles default to cp1252, which cannot print Romanian diacritics.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="DriveMate P3 voice test server (fake core).")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--scene", default=None, help="fixture name in tests/assistant/fixtures/scenes/")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    print(f"Open http://localhost:{args.port} in Google Chrome")
    uvicorn.run(create_app(args.scene), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
