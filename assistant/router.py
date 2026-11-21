"""HTTP routes of the assistant, mounted by core (plan section 13: ``assistant.router``).

Core does::

    from assistant.router import router as assistant_router
    app.include_router(assistant_router)

Routes:

* ``GET /tts/{speech_id}.mp3`` - one synthesized sentence (registered beforehand by
  :func:`assistant.tts.speak_message`), synthesized with edge-tts on first request
  and cached in memory.
* ``GET /media/{track_id}.mp3`` - a music track from the media catalog (plan D8),
  served from ``assistant/data/media/`` (mp3 files are shared outside git).
* ``GET /media/yt/{video_id}.m4a`` - the audio of a YouTube result (docs/assistant.md 6.1),
  resolved by yt-dlp and proxied (same origin, ``Range`` supported, fetched upstream in
  ``youtube.proxy_chunk_mb`` chunks). Only ids found by a search in this process are served.
* ``GET /assistant/health`` - which LLM provider is active, for ``integrations.llm``.
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Optional

import aiohttp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from assistant import media_search, music
from assistant.settings import cfg
from assistant.tts import speech_cache

log = logging.getLogger("drivemate.assistant.router")

router = APIRouter(tags=["assistant"])


@router.get("/tts/{speech_id}.mp3")
async def get_tts(speech_id: str) -> Response:
    """Stream the mp3 of a registered sentence while it is being synthesized.

    The first chunk is awaited before the response starts, so a failure that happens
    before any audio still becomes a proper HTTP error.

    Raises:
        HTTPException: 404 for an unknown id, 502 if synthesis failed (e.g. no
            internet; the browser player then falls back to ``speechSynthesis``).
    """
    if not speech_cache.known(speech_id):
        raise HTTPException(status_code=404, detail="unknown speech id")
    chunks = speech_cache.stream(speech_id)
    try:
        first = await chunks.__anext__()
    except StopAsyncIteration:
        raise HTTPException(status_code=502, detail="tts returned no audio") from None
    except Exception as exc:  # noqa: BLE001 - any synthesis failure = 502
        log.warning("TTS failed for %s: %s", speech_id, exc)
        raise HTTPException(status_code=502, detail="tts failed") from exc

    async def body() -> AsyncIterator[bytes]:
        """The first chunk, then the rest as it arrives."""
        yield first
        async for chunk in chunks:
            yield chunk

    return StreamingResponse(body(), media_type="audio/mpeg", headers={"Cache-Control": "max-age=3600"})


@router.get("/media/{track_id}.mp3")
async def get_media(track_id: str) -> FileResponse:
    """Return the mp3 of a catalog track.

    Raises:
        HTTPException: 404 if the track is not in the catalog or the file is missing.
    """
    track = music.get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="unknown track")
    path = music.track_file(track)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"missing file {track.file}")
    return FileResponse(path, media_type="audio/mpeg")


_RANGE = re.compile(r"^bytes=(\d+)-(\d*)$")
_CONTENT_RANGE = re.compile(r"/(\d+)$")
_PIECE = 64 * 1024


def parse_range(header: Optional[str]) -> tuple[int, Optional[int], bool]:
    """``"bytes=100-199"`` -> ``(100, 199, True)``; missing / unsupported -> ``(0, None, False)``."""
    match = _RANGE.match((header or "").strip())
    if not match:
        return 0, None, False
    return int(match.group(1)), int(match.group(2)) if match.group(2) else None, True


@router.get("/media/yt/{video_id}.m4a")
async def get_youtube_audio(video_id: str, request: Request) -> Response:
    """Proxy the audio stream of a YouTube result found by a search (see module docstring).

    Raises:
        HTTPException: 404 for an id no search returned, 416 for a range past the end,
            502 when the stream cannot be resolved or fetched.
    """
    if media_search.known(video_id) is None:
        raise HTTPException(status_code=404, detail="unknown video")
    start, end, partial = parse_range(request.headers.get("range"))
    chunk = int(float(cfg("youtube", "proxy_chunk_mb", default=4)) * 1024 * 1024)
    for attempt in (0, 1):  # a 403 means an expired URL: resolve again once
        try:
            stream = await media_search.resolve_stream(video_id, refresh=attempt == 1)
        except media_search.MediaSearchError as exc:
            log.warning("YouTube stream for %s not resolved: %s", video_id, exc)
            raise HTTPException(status_code=502, detail="stream not available") from exc
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=30))
        first_end = start + chunk - 1 if end is None else min(end, start + chunk - 1)
        try:
            upstream = await session.get(stream.url, headers={**stream.headers, "Range": f"bytes={start}-{first_end}"})
        except aiohttp.ClientError as exc:
            await session.close()
            raise HTTPException(status_code=502, detail="upstream unreachable") from exc
        if upstream.status in (403, 410) and attempt == 0:
            upstream.release()
            await session.close()
            continue
        if upstream.status == 416:
            upstream.release()
            await session.close()
            raise HTTPException(status_code=416, detail="range not satisfiable")
        if upstream.status not in (200, 206):
            upstream.release()
            await session.close()
            raise HTTPException(status_code=502, detail=f"upstream {upstream.status}")
        size_match = _CONTENT_RANGE.search(upstream.headers.get("Content-Range", ""))
        total = int(size_match.group(1)) if size_match else int(upstream.headers.get("Content-Length", 0))
        last = total - 1 if end is None else min(end, total - 1)
        if upstream.status == 200:  # the server ignored the range: it sends everything at once
            first_end = last
        if total == 0 or start > last:
            upstream.release()
            await session.close()
            raise HTTPException(status_code=416, detail="range not satisfiable")

        async def body(upstream: aiohttp.ClientResponse = upstream, session: aiohttp.ClientSession = session,
                       stream: media_search.StreamInfo = stream, first_end: int = first_end,
                       last: int = last) -> AsyncIterator[bytes]:
            """The first chunk, then the following ones, until ``last`` (closed when the browser stops)."""
            try:
                async for piece in upstream.content.iter_chunked(_PIECE):
                    yield piece
                position = first_end + 1
                while position <= last:
                    stop = min(position + chunk - 1, last)
                    async with session.get(stream.url, headers={**stream.headers, "Range": f"bytes={position}-{stop}"}) as part:
                        if part.status not in (200, 206):
                            log.warning("YouTube chunk %s-%s of %s: HTTP %s", position, stop, video_id, part.status)
                            return
                        async for piece in part.content.iter_chunked(_PIECE):
                            yield piece
                    position = stop + 1
            finally:
                upstream.release()
                await session.close()

        headers = {"Accept-Ranges": "bytes", "Content-Length": str(last - start + 1), "Cache-Control": "no-store"}
        if partial:
            headers["Content-Range"] = f"bytes {start}-{last}/{total}"
        return StreamingResponse(body(), status_code=206 if partial else 200, media_type=stream.content_type,
                                 headers=headers)
    raise HTTPException(status_code=502, detail="stream expired")


@router.get("/assistant/health")
async def health() -> dict:
    """Report the active LLM provider (``gemini`` / ``offline``) and the language."""
    from assistant.client import get_client
    from assistant.settings import cfg

    provider = get_client().provider
    return {"llm": provider.name, "llm_available": provider.available, "language": cfg("language", default="ro")}
