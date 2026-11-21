"""Stand-in for core's ``/ws/perception`` endpoint (P1 dev tool, until P2's core exists).

    python scripts/ws_sink.py                       # listen on ws://localhost:8000/ws/perception
    python scripts/ws_sink.py --show                # also print one frame per second (driver eyes / head / perf)
    python scripts/ws_sink.py --send debug          # after connect: send {"cmd": "debug", "on": true}
    python scripts/ws_sink.py --send dialog_window --send calibrate

Validates every received message against the contract in use (perception/contract.py -> shared/contracts.py once
P2 publishes it) and prints the rate once a second. Nothing is stored.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orjson

from perception.contract import CONTRACT_SOURCE, validate_frame

COMMANDS: dict[str, dict[str, Any]] = {
    "debug": {"cmd": "debug", "on": True},
    "debug_off": {"cmd": "debug", "on": False},
    "dialog_window": {"cmd": "dialog_window", "open": True, "to": "driver"},
    "calibrate": {"cmd": "calibrate", "profile": "andrei"},
    "enroll": {"cmd": "enroll", "name": "andrei"},
}


async def serve(host: str, port: int, path: str, show: bool, send: list[str], seconds: float) -> dict[str, int]:
    import websockets

    stats = {"frames": 0, "invalid": 0, "acks": 0}

    async def handler(ws: Any) -> None:
        if ws.request.path != path:
            await ws.close(code=4404, reason="unknown path")
            return
        print(f"perception connected ({CONTRACT_SOURCE})", flush=True)
        for name in send:
            await ws.send(orjson.dumps(COMMANDS[name]).decode())
        count, last = 0, time.monotonic()
        try:
            async for raw in ws:
                count, last = handle(raw, count, last)
        except websockets.ConnectionClosed:
            print("perception disconnected", flush=True)

    def handle(raw: Any, count: int, last: float) -> tuple[int, float]:
        data = orjson.loads(raw)
        if data.get("type") == "ack":
            stats["acks"] += 1
            print("ack:", data, flush=True)
            return count, last
        try:
            frame = validate_frame(data)
        except Exception as exc:
            stats["invalid"] += 1
            print("INVALID frame:", str(exc)[:300], flush=True)
            return count, last
        stats["frames"] += 1
        count += 1
        now = time.monotonic()
        if now - last >= 1.0:
            d = frame["driver"]
            line = f"{count / (now - last):5.1f} Hz  seq {frame['seq']}"
            if show:
                eyes, head = d.get("eyes", {}), d.get("head", {})
                line += (
                    f"  eyes {eyes.get('state', '-')} ear {eyes.get('ear')}  yaw {head.get('yaw')}"
                    f"  e2e p95 {frame['perf'].get('e2e_ms_p95')} ms  monitoring {d.get('monitoring_reason') or 'ok'}"
                )
            print(line, flush=True)
            count, last = 0, now
        return count, last

    async with websockets.serve(handler, host, port):
        print(f"listening on ws://{host}:{port}{path}", flush=True)
        if seconds > 0:
            await asyncio.sleep(seconds)
        else:
            await asyncio.Future()
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--path", default="/ws/perception")
    p.add_argument("--show", action="store_true")
    p.add_argument("--send", action="append", default=[], choices=sorted(COMMANDS))
    p.add_argument("--seconds", type=float, default=0.0)
    args = p.parse_args(argv)
    try:
        stats = asyncio.run(serve(args.host, args.port, args.path, args.show, args.send, args.seconds))
    except KeyboardInterrupt:
        return 0
    print("summary:", stats, flush=True)
    return 0 if stats["invalid"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
