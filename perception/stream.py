"""MJPEG preview for the dashboard (plan §13): ``http://<host>:8001/video/driver`` and ``/video/passenger``.

* aiohttp, ``multipart/x-mixed-replace``; each part is the newest JPEG of that camera (640 px, quality 70,
  ``output.video_fps``), rendered and encoded **in the camera worker, only while at least one client watches**: the
  first client turns ``want_jpeg`` on, the last one leaving turns it off.
* ``/`` shows every running camera, ``/health`` returns the JSON given by the owner (main process).
* A busy port only disables the preview (logged); the PerceptionFrame stream keeps running.
* Frames live in memory only: the preview is streamed, never stored (docs/perception.md §5).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from perception.log import get_logger

__all__ = ["JpegSource", "MjpegServer"]

log = get_logger("perception.stream")


class JpegSource(Protocol):
    """A camera whose newest preview JPEG can be streamed (``perception.worker.CameraWorker``)."""

    latest_jpeg: bytes | None
    jpeg_seq: int  # increases with every new JPEG
    available: bool

    def want_jpeg(self, on: bool) -> None: ...


def _index(cameras: list[str]) -> bytes:
    figures = "".join(
        f'<figure><img src="/video/{c}" width="640"><figcaption>/video/{c}</figcaption></figure>' for c in cameras
    )
    return (
        '<!doctype html><meta charset="utf-8"><title>DriveMate perception</title>'
        '<body style="background:#111;color:#ddd;font-family:sans-serif">'
        "<h3>DriveMate perception (P1) - MJPEG preview</h3>"
        f'<div style="display:flex;gap:12px;flex-wrap:wrap">{figures}</div>'
        '<p><a style="color:#8cf" href="/health">/health</a></p></body>'
    ).encode()


class MjpegServer:
    def __init__(
        self,
        sources: Mapping[str, JpegSource],
        *,
        host: str,
        port: int,
        fps: float,
        health: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.sources = sources
        self.host = host
        self.port = port
        self.fps = fps
        self.health = health
        self.clients: dict[str, int] = dict.fromkeys(sources, 0)
        self.bound_port: int | None = None
        self._runner: Any = None

    def _watch(self, name: str, delta: int) -> None:
        self.clients[name] = max(0, self.clients.get(name, 0) + delta)
        self.sources[name].want_jpeg(self.clients[name] > 0)  # nobody watches: the worker stops encoding

    async def _video(self, request: Any) -> Any:
        from aiohttp import web

        name = request.match_info["camera"]
        source = self.sources.get(name)
        if source is None:
            raise web.HTTPNotFound(text=f"camera {name} is not running")
        resp = web.StreamResponse(
            headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame", "Cache-Control": "no-cache"}
        )
        await resp.prepare(request)
        self._watch(name, +1)
        last = -1
        try:
            while True:
                jpg = source.latest_jpeg
                if source.jpeg_seq != last and jpg:
                    last = source.jpeg_seq
                    head = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpg)
                    await resp.write(head + jpg + b"\r\n")
                await asyncio.sleep(0.5 / self.fps)
        except (ConnectionResetError, ConnectionError):
            pass
        finally:
            self._watch(name, -1)
        return resp

    async def start(self) -> int | None:
        """Start serving; returns the bound port (``port=0`` picks a free one), or None if the port is busy."""
        from aiohttp import web

        async def index(_: web.Request) -> web.Response:
            return web.Response(body=_index(list(self.sources)), content_type="text/html")

        async def health(_: web.Request) -> web.Response:
            data = self.health() if self.health is not None else {}
            return web.json_response({**data, "mjpeg_clients": dict(self.clients)})

        app = web.Application()
        app.router.add_get("/", index)
        app.router.add_get("/health", health)
        app.router.add_get("/video/{camera}", self._video)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        try:
            await site.start()
        except OSError as exc:
            log.error(
                "MJPEG port unavailable: preview disabled", extra={"fields": {"port": self.port, "error": str(exc)}}
            )
            await runner.cleanup()
            return None
        server = getattr(site, "_server", None)
        sockets = getattr(server, "sockets", None) or []
        self.bound_port = sockets[0].getsockname()[1] if sockets else self.port
        self._runner = runner
        log.info("MJPEG preview", extra={"fields": {"url": f"http://localhost:{self.bound_port}/"}})
        return self.bound_port

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        for name in self.sources:
            self.sources[name].want_jpeg(False)
            self.clients[name] = 0
