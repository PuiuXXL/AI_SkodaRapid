"""assistant/router.py: TTS, catalog media, the YouTube audio proxy and health, without network or an HTTP client.

The routes are plain ``async`` functions: they are called directly (the assistant CI has no ``httpx`` for FastAPI's
TestClient). Upstream YouTube responses come from a fake ``aiohttp.ClientSession``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from assistant import router as r


def run(coro: Any) -> Any:
    return asyncio.run(coro)


async def collect(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


# --- parse_range -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [("bytes=100-199", (100, 199, True)), ("bytes=5-", (5, None, True)), (None, (0, None, False)),
     ("items=1-2", (0, None, False)), ("  bytes=0-0 ", (0, 0, True))],
)  # fmt: skip
def test_parse_range(header: str | None, expected: tuple[int, int | None, bool]) -> None:
    assert r.parse_range(header) == expected


# --- /tts ----------------------------------------------------------------------------------------------------------


class FakeSpeech:
    def __init__(self, chunks: list[bytes] | Exception | None) -> None:
        self.chunks = chunks

    def known(self, speech_id: str) -> bool:
        return self.chunks is not None

    def stream(self, speech_id: str) -> AsyncIterator[bytes]:
        async def gen() -> AsyncIterator[bytes]:
            if isinstance(self.chunks, Exception):
                raise self.chunks
            for chunk in self.chunks or []:
                yield chunk

        return gen()


def test_tts_streams_the_registered_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r, "speech_cache", FakeSpeech([b"ab", b"cd"]))

    async def fetch() -> tuple[str, bytes]:  # one event loop: the first chunk and the rest come from one generator
        response = await r.get_tts("s1")
        return response.media_type, await collect(response)

    assert run(fetch()) == ("audio/mpeg", b"abcd")


@pytest.mark.parametrize(("chunks", "status"), [(None, 404), ([], 502), (RuntimeError("no internet"), 502)])
def test_tts_errors(monkeypatch: pytest.MonkeyPatch, chunks: Any, status: int) -> None:
    monkeypatch.setattr(r, "speech_cache", FakeSpeech(chunks))
    with pytest.raises(HTTPException) as exc:
        run(r.get_tts("s1"))
    assert exc.value.status_code == status


# --- /media --------------------------------------------------------------------------------------------------------


def test_media_track(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    track = SimpleNamespace(file="song.mp3")
    monkeypatch.setattr(r.music, "get_track", lambda tid: track if tid == "t1" else None)
    monkeypatch.setattr(r.music, "track_file", lambda t: tmp_path / t.file)
    for tid in ("nope", "t1"):  # unknown track, then a catalog track whose file is missing
        with pytest.raises(HTTPException) as exc:
            run(r.get_media(tid))
        assert exc.value.status_code == 404
    (tmp_path / "song.mp3").write_bytes(b"ID3")
    assert run(r.get_media("t1")).media_type == "audio/mpeg"


# --- /media/yt -----------------------------------------------------------------------------------------------------


class FakeContent:
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def iter_chunked(self, n: int) -> AsyncIterator[bytes]:
        for i in range(0, len(self.data), n):
            yield self.data[i : i + n]


class FakeUpstream:
    def __init__(self, status: int, data: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.status, self.content, self.headers = status, FakeContent(data), headers or {}
        self.released = False

    def release(self) -> None:
        self.released = True


def fake_session(responses: list[FakeUpstream | Exception]) -> type:
    class Session:
        def __init__(self, timeout: Any = None) -> None:
            self.closed = False

        async def get(self, url: str, headers: dict[str, str] | None = None) -> FakeUpstream:
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        async def close(self) -> None:
            self.closed = True

    return Session


def request(range_header: str | None = None) -> Request:
    headers = [(b"range", range_header.encode())] if range_header else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.fixture
def youtube(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """A known video whose stream resolves; records the ``refresh`` flag of every resolve."""
    refreshes: list[bool] = []

    async def resolve(video_id: str, refresh: bool = False) -> Any:
        refreshes.append(refresh)
        return r.media_search.StreamInfo(url="https://example.invalid/a", headers={"User-Agent": "x"})

    monkeypatch.setattr(r.media_search, "known", lambda vid: object() if vid == "v1" else None)
    monkeypatch.setattr(r.media_search, "resolve_stream", resolve)
    return refreshes


def test_youtube_partial_content_after_an_expired_url(monkeypatch: pytest.MonkeyPatch, youtube: list[bool]) -> None:
    ok = FakeUpstream(206, b"0123456789", {"Content-Range": "bytes 0-9/10"})
    monkeypatch.setattr(r.aiohttp, "ClientSession", fake_session([FakeUpstream(403), ok]))
    response = run(r.get_youtube_audio("v1", request("bytes=0-")))
    assert response.status_code == 206 and response.headers["Content-Range"] == "bytes 0-9/10"
    assert run(collect(response)) == b"0123456789" and ok.released
    assert youtube == [False, True]  # the 403 made it resolve again once


def test_youtube_full_body_when_the_server_ignores_the_range(
    monkeypatch: pytest.MonkeyPatch, youtube: list[bool]
) -> None:
    full = FakeUpstream(200, b"abc", {"Content-Length": "3"})
    monkeypatch.setattr(r.aiohttp, "ClientSession", fake_session([full]))
    response = run(r.get_youtube_audio("v1", request()))
    assert response.status_code == 200 and response.headers["Content-Length"] == "3"
    assert run(collect(response)) == b"abc"


@pytest.mark.parametrize(
    ("upstream", "status"),
    [(FakeUpstream(416), 416), (FakeUpstream(500), 502), (FakeUpstream(206, b"", {"Content-Length": "0"}), 416),
     (aiohttp.ClientError("down"), 502), (FakeUpstream(403), 502)],
)  # fmt: skip
def test_youtube_upstream_errors(
    monkeypatch: pytest.MonkeyPatch, youtube: list[bool], upstream: Any, status: int
) -> None:
    expired_twice = isinstance(upstream, FakeUpstream) and upstream.status == 403
    responses = [upstream, FakeUpstream(403)] if expired_twice else [upstream]
    monkeypatch.setattr(r.aiohttp, "ClientSession", fake_session(responses))
    with pytest.raises(HTTPException) as exc:
        run(r.get_youtube_audio("v1", request("bytes=0-")))
    assert exc.value.status_code == status


def test_youtube_unknown_video_and_unresolvable_stream(monkeypatch: pytest.MonkeyPatch, youtube: list[bool]) -> None:
    with pytest.raises(HTTPException) as exc:
        run(r.get_youtube_audio("other", request()))
    assert exc.value.status_code == 404

    async def broken(video_id: str, refresh: bool = False) -> Any:
        raise r.media_search.MediaSearchError("extract_failed")

    monkeypatch.setattr(r.media_search, "resolve_stream", broken)
    with pytest.raises(HTTPException) as exc:
        run(r.get_youtube_audio("v1", request()))
    assert exc.value.status_code == 502


# --- /assistant/health ---------------------------------------------------------------------------------------------


def test_health_reports_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import assistant.client

    provider = SimpleNamespace(name="offline", available=False)
    monkeypatch.setattr(assistant.client, "get_client", lambda: SimpleNamespace(provider=provider))
    out = run(r.health())
    assert out["llm"] == "offline" and out["llm_available"] is False and out["language"]
