"""WebSocket connections of core: browsers on ``/ws/ui``, P1 on ``/ws/perception``, the phone bridge on ``/ws/phone``.

Sending never blocks the caller (the safety path must not wait for a slow browser): every peer has its own queue and
its own sender task. When a queue is full, the oldest ``state`` message is dropped first (a newer one is coming in
100 ms); an alarm, a ``speak`` or a command is never dropped for a state.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import Any

from fastapi import WebSocket

try:
    import orjson

    def dumps(message: dict[str, Any]) -> str:
        return orjson.dumps(message).decode("utf-8")

except ImportError:  # orjson is in requirements/p2-core.txt; json keeps tests running without it

    def dumps(message: dict[str, Any]) -> str:
        return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


log = logging.getLogger("drivemate.core.hub")


class Peer:
    """One WebSocket peer with a bounded outgoing queue."""

    def __init__(self, ws: WebSocket, name: str, maxsize: int = 64) -> None:
        self.ws = ws
        self.name = name
        self.maxsize = maxsize
        self._queue: deque[tuple[str, str]] = deque()  # (kind, text)
        self._ready = asyncio.Event()
        self.sent = 0
        self.dropped = 0

    def send_text(self, text: str, kind: str = "") -> None:
        """Queue one message; never blocks. ``kind="state"`` messages are the first to go when the queue is full."""
        if len(self._queue) >= self.maxsize:
            for i, (queued_kind, _) in enumerate(self._queue):
                if queued_kind == "state":
                    del self._queue[i]
                    break
            else:
                self._queue.popleft()
            self.dropped += 1
        self._queue.append((kind, text))
        self._ready.set()

    def send(self, message: dict[str, Any]) -> None:
        self.send_text(dumps(message), str(message.get("type", "")))

    async def run_sender(self) -> None:
        """Send queued messages until the connection closes (run as a task per peer)."""
        while True:
            await self._ready.wait()
            while self._queue:
                _, text = self._queue.popleft()
                await self.ws.send_text(text)
                self.sent += 1
            self._ready.clear()


class Hub:
    """All connected peers. Methods return whether someone was there to receive the message."""

    def __init__(self) -> None:
        self.ui: set[Peer] = set()
        self.perception: Peer | None = None
        self.phone: Peer | None = None

    def broadcast_ui(self, message: dict[str, Any]) -> bool:
        if not self.ui:
            return False
        text, kind = dumps(message), str(message.get("type", ""))
        for peer in list(self.ui):
            peer.send_text(text, kind)
        return True

    def send_perception(self, message: dict[str, Any]) -> bool:
        if self.perception is None:
            return False
        self.perception.send(message)
        return True

    def send_phone(self, message: dict[str, Any]) -> bool:
        if self.phone is None:
            return False
        self.phone.send(message)
        return True

    def stats(self) -> dict[str, Any]:
        def peer(p: Peer | None) -> dict[str, Any] | None:
            return None if p is None else {"sent": p.sent, "dropped": p.dropped}

        return {
            "ui_clients": len(self.ui),
            "ui_dropped": sum(p.dropped for p in self.ui),
            "perception": peer(self.perception),
            "phone": peer(self.phone),
        }
