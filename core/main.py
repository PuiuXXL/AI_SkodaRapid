"""DriveMate core (P2): FastAPI on :8000 with ``/ws/perception``, ``/ws/ui``, ``/ws/phone`` and the 10 Hz state loop.

Run from the repo root::

    python -m core.main                      # http://127.0.0.1:8000, demo_mode from thresholds.yaml
    python -m core.main --host 0.0.0.0       # reachable from the phone bridge on another laptop (plan decision 9)
    python scripts/fake_perception.py        # in a second terminal: P1's stand-in, one key per scene

Mounted when importable: ``assistant.router`` (P3: ``/tts``, ``/media``) and ``integrations.contact_app.router``
(P4: DriveMate Contact). ``GET /health`` shows the connections, the data age and the simulator in use.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from core.assistant_link import AssistantLink
from core.engine import Engine
from core.hub import Hub, Peer
from core.safety import Safety
from core.settings import th
from core.simulation import load_simulator

REPO_ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("drivemate.core")


def _optional_router(module_name: str) -> Any | None:
    """``module.router`` if the module imports cleanly, else None (logged): a missing piece never stops core."""
    try:
        return importlib.import_module(module_name).router
    except Exception as exc:  # P3 / P4 code or its dependencies may be missing on this laptop
        log.warning("%s not mounted (%s: %s)", module_name, exc.__class__.__name__, exc)
        return None


async def state_loop(engine: Engine) -> None:
    """Build and publish the state at ``loop.state_hz``. An error in one tick is logged and the loop goes on."""
    period = 1.0 / float(th("loop", "state_hz"))
    next_t = time.monotonic()
    failures: set[str] = set()
    while True:
        try:
            engine.publish(engine.tick(time.time()))
        except Exception as exc:  # the safety loop must never die
            key = f"{exc.__class__.__name__}: {exc}"
            if key not in failures:
                failures.add(key)
                log.exception("state tick failed")
        next_t += period
        delay = next_t - time.monotonic()
        if delay < 0:  # fell behind (e.g. laptop asleep): restart the schedule instead of bursting
            next_t, delay = time.monotonic(), 0.0
        await asyncio.sleep(delay)


async def _serve(ws: WebSocket, peer: Peer, on_message: Any) -> None:
    """Receive JSON messages for one peer until it disconnects; its sender runs alongside."""
    sender = asyncio.create_task(peer.run_sender())
    failures: set[str] = set()
    try:
        while True:
            text = await ws.receive_text()
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            try:
                on_message(data, time.time())
            except Exception as exc:  # a bug in one handler must not drop P1's connection
                key = f"{exc.__class__.__name__}: {exc}"
                if key not in failures:
                    failures.add(key)
                    log.exception("%s message handler failed", peer.name)
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender


def create_app(engine: Engine | None = None) -> FastAPI:
    """The core app. Tests pass their own ``engine``; the real one loads P4's simulator when it exists."""
    if engine is None:
        contact_router = _optional_router("integrations.contact_app")
        simulator, simulator_name = load_simulator()
        engine = Engine(Hub(), simulator, simulator_name, contact_app=contact_router is not None)
    else:
        contact_router = None
    if engine.safety is None:
        Safety(engine)  # C: alarm, SOS, "Nu te mai văd", distractions, arbiter, A/B
    if engine.assistant is None:
        AssistantLink(engine)  # the slow path: P3's assistant, after the safety rules
    assistant_router = _optional_router("assistant.router")
    hub = engine.hub

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(state_loop(engine)), asyncio.create_task(engine.assistant.run()),
                 asyncio.create_task(engine.assistant.warm_up())]
        log.info("core started: simulator=%s, demo_mode=%s, assistant=%s", engine.simulator_name, th("demo_mode"),
                 "on" if engine.assistant.available else "off")
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="DriveMate core", lifespan=lifespan)
    app.state.engine = engine
    if assistant_router is not None:
        app.include_router(assistant_router)
    if contact_router is not None:
        app.include_router(contact_router)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return engine.health(time.time())

    @app.websocket("/ws/ui")
    async def ws_ui(ws: WebSocket) -> None:
        await ws.accept()
        peer = Peer(ws, "ui")
        hub.ui.add(peer)
        for event in engine.recent_events:  # the log so far, then the current state
            peer.send(event)
        peer.send(engine.ui_payload(engine.state))
        try:
            await _serve(ws, peer, engine.on_browser_message)
        finally:
            hub.ui.discard(peer)

    @app.websocket("/ws/perception")
    async def ws_perception(ws: WebSocket) -> None:
        await ws.accept()
        peer = Peer(ws, "perception")
        if hub.perception is not None:
            log.warning("a second perception connected: it replaces the first one")
        hub.perception = peer
        engine.on_perception_connected(True, time.time())
        try:
            await _serve(ws, peer, engine.on_perception_message)
        finally:
            if hub.perception is peer:
                hub.perception = None
                engine.on_perception_connected(False, time.time())

    @app.websocket("/ws/phone")
    async def ws_phone(ws: WebSocket) -> None:
        await ws.accept()
        peer = Peer(ws, "phone")
        hub.phone = peer
        engine.log_event("phone_bridge_connected", time.time(), text="Puntea cu telefonul s-a conectat.")
        try:
            await _serve(ws, peer, engine.on_phone_message)
        finally:
            if hub.phone is peer:
                hub.phone = None
                engine.state.phone.connected = False
                engine.log_event("phone_bridge_disconnected", time.time(), text="Puntea cu telefonul s-a deconectat.")

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="DriveMate core (P2).")
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 = reachable from other laptops (phone bridge)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
    except ImportError:
        pass

    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level=args.log_level, ws_ping_interval=10)


if __name__ == "__main__":
    main()
