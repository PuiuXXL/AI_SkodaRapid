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
* ``GET /assistant/health`` - which LLM provider is active, for ``integrations.llm``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from assistant import music
from assistant.tts import speech_cache

log = logging.getLogger("drivemate.assistant.router")

router = APIRouter(tags=["assistant"])


@router.get("/tts/{speech_id}.mp3")
async def get_tts(speech_id: str) -> Response:
    """Return the mp3 of a registered sentence.

    Raises:
        HTTPException: 404 for an unknown id, 502 if synthesis failed (e.g. no
            internet; the browser player then falls back to ``speechSynthesis``).
    """
    try:
        audio = await speech_cache.get(speech_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown speech id") from None
    except Exception as exc:  # noqa: BLE001 - any synthesis failure = 502
        log.warning("TTS failed for %s: %s", speech_id, exc)
        raise HTTPException(status_code=502, detail="tts failed") from exc
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "max-age=3600"})


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


@router.get("/assistant/health")
async def health() -> dict:
    """Report the active LLM provider (``gemini`` / ``offline``) and the language."""
    from assistant.client import get_client
    from assistant.settings import cfg

    provider = get_client().provider
    return {"llm": provider.name, "llm_available": provider.available, "language": cfg("language", default="ro")}
