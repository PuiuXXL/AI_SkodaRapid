"""Send director commands to core and watch what it does, from a terminal (until P4's director panel has them).

Usage (from the repo root, core running)::

    python scripts/core_command.py scene 8               # trip preset: 8 = highway, 118 km/h (scenes 1-10)
    python scripts/core_command.py speed 90
    python scripts/core_command.py llm off               # C6: the director's LLM switch (on / off)
    python scripts/core_command.py message Mihai "Unde ești?"     # a simulated WhatsApp message
    python scripts/core_command.py stop                  # stop at the next POI
    python scripts/core_command.py rear ioana child      # declare a rear occupant
    python scripts/core_command.py debug on              # P1's debug overlay
    python scripts/core_command.py end                   # end of the trip: the trip report (scene 10)
    python scripts/core_command.py reset
    python scripts/core_command.py watch                 # live: alarms, voice, events, level, A/B counter
    python scripts/core_command.py watch --ack-alarms    # also answer alarm_played (no browser open)

``--url`` (default: CORE_URL from .env + /ws/ui) points at another core.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

#: name on the command line -> (core cmd, how the arguments become the message)
SIMPLE = {"start": "start", "pause": "pause", "stop": "stop_at_next_poi", "reset": "reset", "end": "end_trip"}


def default_url() -> str:
    with contextlib.suppress(ImportError):
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
    base = os.environ.get("CORE_URL", "http://localhost:8000").rstrip("/")
    return base.replace("https://", "wss://").replace("http://", "ws://") + "/ws/ui"


def on_off(word: str) -> bool:
    if word.lower() in ("on", "da", "1", "true", "pornit"):
        return True
    if word.lower() in ("off", "nu", "0", "false", "oprit"):
        return False
    raise SystemExit(f"expected on / off, got {word!r}")


def build_command(words: list[str]) -> dict[str, Any]:
    """The ``command`` message for ``/ws/ui`` from the command line words."""
    if not words:
        raise SystemExit(__doc__)
    name, args = words[0], words[1:]
    message: dict[str, Any] = {"type": "command"}
    if name in SIMPLE:
        message["cmd"] = SIMPLE[name]
    elif name in ("scene", "speed", "time") and len(args) == 1:
        message["cmd"] = {"scene": "scene", "speed": "speed", "time": "time_scale"}[name]
        message["value"] = int(args[0]) if name == "scene" else float(args[0])
    elif name in ("llm", "debug") and len(args) == 1:
        message.update(cmd=name, on=on_off(args[0]))
    elif name == "message" and len(args) >= 2:
        message.update(cmd="fake_message", value={"from": args[0], "app": "whatsapp", "text": " ".join(args[1:])})
    elif name == "rear" and len(args) >= 1:
        role = args[1] if len(args) > 1 else "adult"
        message.update(cmd="declare_occupant", value={"profile": args[0], "role": role})
    else:
        raise SystemExit(f"unknown command or arguments: {' '.join(words)}\n\n{__doc__}")
    return message


def describe(message: dict[str, Any], last: dict[str, Any]) -> str | None:
    """One line for ``watch``; states only when something worth seeing changed."""
    kind = message.get("type")
    if kind == "alarm":
        return f"ALARMĂ   {message.get('clip_url')}  ({message.get('level')}, {message.get('alert')})"
    if kind == "speak":
        source = message.get("clip_url") or "TTS"
        return f"VOCE     → {message.get('to')}: {message.get('text')!r}  [{source}]"
    if kind in ("speak_control", "media"):
        return f"{kind.upper():<8} {message.get('action')}"
    if kind == "event":
        event = message["event"]
        text = event.get("explanation") or event.get("text") or ""
        extra = f"  {event['latency_ms']:.0f} ms" if event.get("latency_ms") is not None else ""
        channel = f"  [{event['channel']}]" if event.get("channel") else ""
        return f"EVENT    {event['type']}: {text}{extra}{channel}"
    if kind == "state":
        s = message["state"]
        safety, trip, ab = s["safety"], s["trip"], s["ab"]
        summary = (safety["level"], safety["alert"], safety["sos"]["state"], safety["monitoring_ok"],
                   trip["road"], trip["speed_kmh"], ab["naive_alerts"], ab["our_alerts"], safety["llm_enabled"])
        if summary == last.get("summary"):
            return None
        last["summary"] = summary
        countdown = f" {safety['sos']['countdown_s']} s" if safety["sos"]["countdown_s"] is not None else ""
        return (f"STARE    nivel={safety['level'] or '-'} alertă={safety['alert'] or '-'} sos={safety['sos']['state']}"
                f"{countdown} cameră={'ok' if safety['monitoring_ok'] else 'NU'} {trip['road']} {trip['speed_kmh']:.0f}"
                f" km/h · A/B prag simplu {ab['naive_alerts']} / DriveMate {ab['our_alerts']}"
                f" · LLM {'pornit' if safety['llm_enabled'] else 'oprit'}")
    return None


async def send(url: str, message: dict[str, Any]) -> None:
    import websockets

    async with websockets.connect(url, open_timeout=3) as ws:
        await ws.send(json.dumps(message, ensure_ascii=False))
    print(f"trimis: {json.dumps(message, ensure_ascii=False)}")


async def watch(url: str, ack_alarms: bool) -> None:
    import websockets

    async with websockets.connect(url, open_timeout=3) as ws:
        print(f"conectat la {url} (Ctrl+C pentru ieșire)")
        start, last = time.time(), {}
        async for raw in ws:
            message = json.loads(raw)
            line = describe(message, last)
            if line:
                print(f"{time.time() - start:7.1f}s  {line}", flush=True)
            if ack_alarms and message.get("type") == "alarm":
                await ws.send(json.dumps({"type": "alarm_played", "id": message["id"], "ts": time.time()}))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("words", nargs="*", help="the command, e.g. scene 8")
    parser.add_argument("--url", default=None)
    parser.add_argument("--ack-alarms", action="store_true", help="watch: answer alarm_played like a browser")
    args = parser.parse_args(argv)
    url = args.url or default_url()
    try:
        if args.words[:1] == ["watch"]:
            asyncio.run(watch(url, args.ack_alarms))
        else:
            asyncio.run(send(url, build_command(args.words)))
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        sys.exit(f"core nu răspunde la {url}: {exc}")


if __name__ == "__main__":
    main()
