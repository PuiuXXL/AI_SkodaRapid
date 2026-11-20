"""Voice test server: a fake core for testing the browser voice end to end (roluri/P3 step 3).

Lets P3 test "speak -> LLM -> voice" without core (P2) or the dashboard (P4):

* serves ``dashboard/src/voice/dev.html`` and the voice JS modules;
* mounts the real :mod:`assistant.router` (``/tts``, ``/media``);
* serves the pre-generated clips (``/sounds/clips/...``);
* implements a minimal ``/ws/ui``: recognised speech is sent to the real
  :func:`assistant.client.AssistantClient.handle_event` with a scene fixture as the
  state, and the resulting ``speak`` / ``ask`` actions are spoken back.

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
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from assistant import music
from assistant.client import AssistantClient
from assistant.contract import Action, Event, State
from assistant.refusal import is_refusal
from assistant.router import router as assistant_router
from assistant.settings import REPO_ROOT, cfg
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
    app = FastAPI(title="DriveMate P3 voice test")
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

        async def send(message: dict[str, Any]) -> None:
            """Send one JSON message to the browser."""
            await ws.send_text(json.dumps(message, ensure_ascii=False))

        async def log_line(text: str) -> None:
            """Show a line in the dev page's log panel."""
            await send({"type": "dev_log", "text": text})

        async def open_dialog_window() -> None:
            """Plan E1: after a question, accept voice without the wake word for 6 s."""
            window = float(cfg("speech", "dialog_window_s", default=6))
            state.interaction.dialog_window_open = True
            await send({"type": "state", "state": {"interaction": {"dialog_window_open": True}}})
            await asyncio.sleep(window)
            state.interaction.dialog_window_open = False
            await send({"type": "state", "state": {"interaction": {"dialog_window_open": False}}})

        async def run_event(event: Event) -> None:
            """Send one event through the real assistant client and speak the result."""
            state.ts = time.time()
            early: list[asyncio.Future] = []

            def on_early(action: Action) -> None:
                """Speak a sentence while the LLM is still streaming."""
                early.append(asyncio.ensure_future(send(speak_message(action))))

            actions = await client.handle_event(event, state, on_early_speech=on_early)
            await asyncio.gather(*early)
            info = client.last_result
            await log_line(f"{event.type} -> source={info.source} reason={info.reason} "
                           f"latency={info.latency_ms:.0f}ms ttft={info.llm_ttft_ms} rejected={len(info.rejected)}")
            for action in actions:
                await log_line("  " + action.model_dump_json(exclude_none=True, exclude_defaults=True))
                if action.type in ("speak", "ask") and not action.streamed:
                    await send(speak_message(action))
                elif action.type == "play_media" and action.track_id:
                    await send({"type": "media", "action": "play", "url": music.track_url(action.track_id),
                                "volume": action.volume or music.volume_for(state)})
                elif action.type == "stop_media":
                    await send({"type": "media", "action": "stop"})

        await log_line(f"connected; LLM provider = {client.provider.name}; scene = {scene or 'state_example'}")
        try:
            while True:
                message = json.loads(await ws.receive_text())
                kind = message.get("type")
                if kind == "speech" and message.get("final"):
                    text = message.get("text", "")
                    await log_line(f"heard: {text!r} (addressed={message.get('addressed')})")
                    if not message.get("addressed"):
                        continue
                    if state.assessment.fatigue >= 0.6 and is_refusal(text):
                        await run_event(Event(type="driver_refused", ts=time.time(), data={"text": text}))
                    else:
                        await run_event(Event(type="driver_speech", ts=time.time(), data={"text": text}))
                elif kind == "speak_done" and message.get("is_question") and not message.get("interrupted"):
                    # Runs in the background so speech keeps being received during the window.
                    asyncio.create_task(open_dialog_window())
                elif kind in ("speech_onset", "alarm_played", "speak_done"):
                    await log_line(f"{kind}: {json.dumps(message)}")
                elif kind == "command":
                    await handle_command(message, send, run_event, log_line)
        except WebSocketDisconnect:
            return

    async def handle_command(message, send, run_event, log_line) -> None:
        """Buttons of dev.html: trigger an event, say a text, alarm, pause/resume."""
        name = message.get("name")
        if name == "trigger":
            await run_event(Event(type=message.get("event", "trip_start"), ts=time.time(), data=message.get("data", {})))
        elif name == "say":
            await send(speak_message(Action(type="speak", to="driver", text=message.get("text", ""), source="RULE")))
        elif name == "alarm":
            await send({"type": "alarm", "id": f"a{int(time.time())}", "clip_url": message.get("clip_url"), "ts": time.time()})
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
