"""YouTube music and podcasts on request (S feature, docs/assistant.md section 6.1).

Flow ("dă-mi ceva metal energic"):

1. The LLM (or, without it, :func:`media_request` in the fallback) returns
   ``search_media {query, kind}``. That action is internal to the assistant.
2. ``assistant/client.py`` calls :func:`search` and replaces it with an ``ask`` with
   ``expects="choice"`` and ``options`` (the results), built by :func:`build_choice`:
   "Am găsit: Metallica, Hardwired, Slipknot, Duality sau Nu Metal Mix. Care?". When
   driving fast only one option is offered ("Pun Metallica, Hardwired?"), see
   :func:`offer_size`.
3. ``assistant/dialog.py`` reads the answer with :func:`parse_choice` ("a doua",
   "cel cu Metallica", "altceva", 👍) and returns ``play_media`` with
   ``track_id = "yt:<video id>"``.
4. Core plays ``music.track_url(track_id)`` = ``/media/yt/<id>.m4a``: ``assistant/router.py``
   resolves the audio stream with :func:`resolve_stream` and proxies it, so the same
   browser player as the mp3 catalog is used (no ads, ducking and alarm stop unchanged).

Search backends: the YouTube Data API v3 when ``YOUTUBE_API_KEY`` is set in ``.env``
(fast, SafeSearch), otherwise yt-dlp (no key, ~2-5 s). Only video ids returned by a
search in this process can be played (:func:`known`), the same rule as "never invent
ids" for the catalog.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from assistant.answers import interpret_voice
from assistant.contract import State
from assistant.settings import cfg, get_texts
from assistant.textutil import fill, normalize, word_count

log = logging.getLogger("drivemate.assistant.media_search")

Kind = Literal["music", "podcast"]

#: Prefix of YouTube track ids in actions and in the state (``yt:dQw4w9WgXcQ``).
TRACK_PREFIX = "yt:"
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_API = "https://www.googleapis.com/youtube/v3/{endpoint}?{query}"
_KNOWN_MAX = 200

# --- title cleaning ---------------------------------------------------------------------------------------------
_BRACKETS = re.compile(r"[(\[{【「].*?[)\]}】」]")
_HASHTAG = re.compile(r"#\w+")
_SEGMENTS = re.compile(r"\s*(?:\||//|•|·|¦)\s*")
_ARTIST_SEP = re.compile(r"\s+[-–—:]\s+|:\s+")  # noqa: RUF001
_NOT_SPOKEN = re.compile(r"[^\w\s,'&.-]", re.UNICODE)
#: Words never left at the end of a shortened title ("Rock pentru" -> "Rock").
_TRAILING_STOP = frozenset({
    "de", "si", "și", "pentru", "para", "e", "the", "and", "of", "a", "la", "cu", "in", "în", "for", "to",
    "din", "pe", "o", "un", "with", "feat", "ft", "vs", "-",
})
#: Words ignored when matching "cel cu Metallica" against titles.
_MATCH_STOP = frozenset({"cel", "cea", "aia", "ala", "aceea", "acela", "care", "zice", "melodia", "piesa", "cu"})

# --- choice answers -------------------------------------------------------------------------------------------
_ORDINALS: tuple[frozenset[str], ...] = (
    frozenset({"primul", "prima", "primu", "unu", "una", "1", "intai", "first"}),
    frozenset({"doilea", "doua", "doi", "2", "second"}),
    frozenset({"treilea", "treia", "trei", "3", "third"}),
)
_LAST = frozenset({"ultimul", "ultima", "last"})
_NEXT = ("altceva", "alta", "altele", "altul", "niciuna", "niciunul", "nici una", "nici unul", "urmatoarea",
         "urmatorul", "mai departe", "next", "altceva te rog")
_CANCEL = ("lasa", "stop", "anuleaza", "gata", "nimic", "renunta", "las o", "nu mai vreau")

# --- fallback request detection (no LLM) ------------------------------------------------------------------------
_REQUEST_VERBS = frozenset({"pune", "puneti", "pui", "cauta", "cautati", "dami", "vreau", "porneste", "play",
                            "asculta", "ascultam", "baga"})
_MUSIC_NOUNS = frozenset({"muzica", "melodie", "melodia", "piesa", "cantec", "ceva"})
_MEDIA_NOUNS = frozenset({"muzica", "melodie", "melodia", "piesa", "piese", "cantec", "cantece", "podcast",
                          "podcastul", "playlist", "mix", "album", "ceva"})
_QUERY_DROP = frozenset({"pune", "puneti", "pui", "sa", "cauta", "cautati", "da", "mi", "dami", "vreau", "as", "vrea", "porneste",  # noqa: E501
                         "play", "asculta", "ascultam", "baga", "te", "rog", "imi", "niste", "ceva", "un", "o", "pe",
                         "youtube", "copilot", "drivemate", "drive", "mate", "si", "mie", "noua"})


class MediaSearchError(Exception):
    """The search or the stream extraction failed (``str(exc)`` is a short machine-readable reason)."""


@dataclass(frozen=True)
class MediaResult:
    """One YouTube search result.

    Attributes:
        video_id: 11-character YouTube id.
        title: Title as published.
        channel: Channel name.
        duration_s: Length in seconds (``None`` = unknown / live).
        kid_safe: True when found with SafeSearch strict (a child is on board).
    """

    video_id: str
    title: str
    channel: str = ""
    duration_s: int | None = None
    kid_safe: bool = False

    @property
    def track_id(self) -> str:
        """Id used in ``play_media`` and in ``state.media.track_id``."""
        return TRACK_PREFIX + self.video_id

    def option(self, offered: bool) -> dict[str, Any]:
        """The option dict carried by the ``ask`` (``expects="choice"``)."""
        return {"track_id": self.track_id, "title": clean_title(self.title), "full_title": self.title,
                "channel": self.channel, "duration_s": self.duration_s, "offered": offered}


@dataclass
class StreamInfo:
    """A resolved audio stream (expires after a few hours).

    Attributes:
        url: Direct audio URL (googlevideo).
        headers: HTTP headers yt-dlp says the URL needs.
        content_type: ``audio/mp4`` or ``audio/webm``.
        expires: Unix time after which it must be resolved again.
    """

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = "audio/mp4"
    expires: float = 0.0


_known: OrderedDict[str, MediaResult] = OrderedDict()
_streams: dict[str, StreamInfo] = {}
_inflight: dict[str, asyncio.Future[StreamInfo]] = {}
_tasks: set[asyncio.Task[Any]] = set()


# =============================================================================================================
# ids
# =============================================================================================================


def valid_video_id(video_id: str) -> bool:
    """True for a syntactically valid YouTube id (nothing else ever reaches yt-dlp)."""
    return bool(_VIDEO_ID.match(video_id or ""))


def is_youtube_track(track_id: str | None) -> bool:
    """True for ``yt:<id>`` track ids."""
    return bool(track_id) and track_id.startswith(TRACK_PREFIX)


def video_id_of(track_id: str | None) -> str | None:
    """``yt:<id>`` -> ``<id>`` (``None`` for catalog ids or invalid ids)."""
    if not is_youtube_track(track_id):
        return None
    video_id = track_id[len(TRACK_PREFIX):]
    return video_id if valid_video_id(video_id) else None


def remember(results: Iterable[MediaResult]) -> None:
    """Keep results so ``play_media`` can be validated against what was really found."""
    for result in results:
        _known[result.video_id] = result
        _known.move_to_end(result.video_id)
    while len(_known) > _KNOWN_MAX:
        _known.popitem(last=False)


def known(track_or_video_id: str | None) -> MediaResult | None:
    """The search result for ``yt:<id>`` or ``<id>``, if this process found it."""
    video_id = video_id_of(track_or_video_id) if is_youtube_track(track_or_video_id) else track_or_video_id
    return _known.get(video_id or "")


def forget_all() -> None:
    """Clear found results and resolved streams (tests, new trip)."""
    _known.clear()
    _streams.clear()
    _inflight.clear()


async def warm_up() -> None:
    """Import yt-dlp in a thread at startup (plan section 8 rule 5: warm-up), ~1 s saved on the first search."""
    import importlib

    try:
        await asyncio.to_thread(importlib.import_module, "yt_dlp")
    except ImportError:
        log.warning("yt-dlp is not installed: YouTube search works only with YOUTUBE_API_KEY, playback not at all")


# =============================================================================================================
# spoken text
# =============================================================================================================


def _texts() -> dict[str, Any]:
    """The ``fallback`` group of texts.<language>.yaml."""
    return get_texts().get("fallback", {})


def clean_title(title: str, max_words: int | None = None) -> str:
    """A YouTube title as a short spoken phrase.

    ``"Metallica - Enter Sandman (Official Music Video) [4K]"`` -> ``"Metallica, Enter Sandman"``.
    Brackets, hashtags, emoji, ``| extra segments`` and noise words (``youtube.title_noise``)
    are removed; ALL-CAPS words are capitalised; at most ``max_words`` words are kept.
    """
    max_words = max_words or int(cfg("youtube", "option_max_words", default=4))
    text = html.unescape(title or "")
    text = _HASHTAG.sub(" ", _BRACKETS.sub(" ", text))
    segments = [s for s in _SEGMENTS.split(text) if s.strip()]
    text = segments[0] if segments else text
    for phrase in sorted(cfg("youtube", "title_noise", default=[]), key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", text, flags=re.IGNORECASE)
    text = _ARTIST_SEP.sub(", ", text, count=1)
    text = _NOT_SPOKEN.sub(" ", text).replace("_", " ")
    words = [w.capitalize() if len(w) > 2 and w.isupper() else w for w in text.split()]
    words = [w for w in words if w.strip(",.-'&")][:max_words]
    while words and words[-1].strip(",.-").lower() in _TRAILING_STOP:
        words.pop()
    spoken = " ".join(words).strip(" ,.-:&")
    return spoken or (title or "").strip()[:40]


def offer_size(state: State) -> int:
    """How many options one question offers: 1 when driving fast or at risk, else ``results_offered``."""
    fast = state.trip.speed_kmh >= float(cfg("youtube", "single_option_speed_kmh", default=90))
    risky = state.assessment.risk >= int(cfg("youtube", "single_option_risk", default=1))
    return 1 if fast or risky else int(cfg("youtube", "results_offered", default=3))


def choice_question(options: list[dict[str, Any]], start: int, size: int) -> tuple[str, list[str]]:
    """Question for ``options[start:start+size]`` within the driver word limit.

    Titles are shortened from ``youtube.option_max_words`` down to ``option_min_words``
    until the question has at most ``speech.max_words_to_driver`` words.

    Returns:
        ``(question, spoken titles)``.
    """
    batch = options[start:start + size]
    limit = int(cfg("speech", "max_words_to_driver", default=30))
    most = int(cfg("youtube", "option_max_words", default=4))
    least = int(cfg("youtube", "option_min_words", default=2))
    question, titles = "", []
    for words in range(most, least - 1, -1):
        titles = [clean_title(o.get("full_title") or o.get("title", ""), words) for o in batch]
        values = {f"o{i + 1}": t for i, t in enumerate(titles)}
        question = fill(_texts().get(f"youtube_choice_{len(batch)}", "{o1}?"), **values)
        if word_count(question) <= limit:
            break
    return question, titles


def build_choice(results: list[MediaResult], size: int) -> tuple[str, list[dict[str, Any]]]:
    """The question and the option list (all results; the first ``size`` are offered now)."""
    size = max(1, min(size, len(results)))
    options = [r.option(offered=i < size) for i, r in enumerate(results)]
    question, titles = choice_question(options, 0, size)
    for option, title in zip(options, titles):  # noqa: B905
        option["title"] = title
    return question, options


def playing_text(option: dict[str, Any]) -> str:
    """ "Pornesc Metallica, Hardwired." """
    return fill(_texts().get("youtube_playing", "{title}"), title=option.get("title") or "")


def parse_choice(text: str, batch: list[dict[str, Any]]) -> int | Literal["next", "cancel"] | None:
    """Read the driver's answer to a choice question.

    Args:
        text: Recognised speech ("a doua", "cel cu Metallica", "altceva", "da").
        batch: The options offered in that question.

    Returns:
        The index in ``batch``, ``"next"`` (offer other results), ``"cancel"``, or
        ``None`` when the text is not an answer (core then treats it as a new request).
    """
    norm = normalize(text)
    padded = f" {norm} "
    tokens = norm.split()
    if not tokens:
        return None
    for index, words in enumerate(_ORDINALS[:len(batch)]):
        if words & set(tokens):
            return index
    if _LAST & set(tokens):
        return len(batch) - 1
    if any(f" {phrase} " in padded for phrase in _CANCEL):
        return "cancel"
    if any(f" {phrase} " in padded for phrase in _NEXT) or norm in ("nu", "nu multumesc", "nu asta"):
        return "next"
    if len(batch) == 1 and interpret_voice(text) == "yes":
        return 0
    fillers = {normalize(str(w)) for w in cfg("youtube", "yes_fillers", default=[])}
    wanted = {t for t in tokens if len(t) >= 3 and t not in fillers and t not in _MATCH_STOP}
    best, best_score = None, 0
    for index, option in enumerate(batch):
        haystack = set(normalize(f"{option.get('full_title', '')} {option.get('channel', '')}").split())
        score = len(wanted & haystack)
        if score > best_score:
            best, best_score = index, score
    return best


def is_specific_wish(text: str) -> bool:
    """ "da, ceva metal" (a yes with a concrete wish) vs. a plain "da, te rog"."""
    if interpret_voice(text) != "yes":
        return False
    fillers = {normalize(str(w)) for w in cfg("youtube", "yes_fillers", default=[])}
    return any(len(t) >= 3 and t not in fillers for t in normalize(text).split())


def media_request(text: str) -> tuple[str, Kind] | None:
    """Deterministic detection of a music / podcast request (used when the LLM is off).

    ``"pune-mi ceva muzică metal"`` -> ``("muzica metal", "music")``;
    ``"caută un podcast despre istoria Romei"`` -> ``("podcast despre istoria romei", "podcast")``.
    """
    tokens = normalize(text).replace("da mi", "dami").replace("pune mi", "pune").split()
    if not (_REQUEST_VERBS & set(tokens)) or not (_MEDIA_NOUNS & set(tokens)):
        return None
    kind: Kind = "podcast" if any(t.startswith("podcast") for t in tokens) else "music"
    query = " ".join(t for t in tokens if t not in _QUERY_DROP)
    if not query or query in ("muzica", "melodie", "piesa"):
        return None
    return query, kind


def wants_music(text: str) -> bool:
    """A plain "pune muzică" / "vreau să pui muzică" with no wish (the catalog answers it, no search)."""
    tokens = set(normalize(text).replace("da mi", "dami").replace("pune mi", "pune").split())
    return bool(_REQUEST_VERBS & tokens) and bool(_MUSIC_NOUNS & tokens)


# =============================================================================================================
# search
# =============================================================================================================


def _api_key() -> str:
    """``YOUTUBE_API_KEY`` from ``.env`` (empty = use yt-dlp)."""
    return os.environ.get("YOUTUBE_API_KEY", "").strip()


def _ydl_options(**extra: Any) -> dict[str, Any]:
    """Common yt-dlp options (quiet, no download, optional JS runtime)."""
    options: dict[str, Any] = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    runtime = cfg("youtube", "js_runtime", default=None)
    if runtime:
        options["js_runtimes"] = {str(runtime): {}}
    options.update(extra)
    return options


def _iso_duration(value: str) -> int | None:
    """``PT1H2M3S`` -> 3723 (``None`` for live / unknown)."""
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def _get_json(endpoint: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    """One YouTube Data API call (the key is never logged)."""
    url = _API.format(endpoint=endpoint, query=urllib.parse.urlencode(params))
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def _search_api(query: str, count: int, kid_safe: bool, timeout: float) -> list[MediaResult]:
    """Search with the YouTube Data API v3 (search.list + videos.list for durations)."""
    key = _api_key()
    found = _get_json("search", {
        "part": "snippet", "type": "video", "q": query, "maxResults": min(25, count * 2), "key": key,
        "safeSearch": "strict" if kid_safe else "moderate",
        "regionCode": cfg("youtube", "region", default="RO"),
        "relevanceLanguage": cfg("youtube", "relevance_language", default="ro"),
    }, timeout)
    items = [i for i in found.get("items", []) if i.get("id", {}).get("videoId")]
    if not items:
        return []
    ids = [i["id"]["videoId"] for i in items]
    details = _get_json("videos", {"part": "contentDetails", "id": ",".join(ids), "key": key}, timeout)
    durations = {d["id"]: _iso_duration(d.get("contentDetails", {}).get("duration", "")) for d in details.get("items", [])}  # noqa: E501
    return [
        MediaResult(video_id=i["id"]["videoId"], title=html.unescape(i["snippet"].get("title", "")),
                    channel=html.unescape(i["snippet"].get("channelTitle", "")),
                    duration_s=durations.get(i["id"]["videoId"]), kid_safe=kid_safe)
        for i in items
        if i["snippet"].get("liveBroadcastContent", "none") == "none"
    ]


def _search_ytdlp(query: str, count: int) -> list[MediaResult]:
    """Search with yt-dlp (``ytsearchN:``), no key needed."""
    import yt_dlp

    with yt_dlp.YoutubeDL(_ydl_options(extract_flat="in_playlist")) as ydl:
        info = ydl.extract_info(f"ytsearch{count + 3}:{query}", download=False)  # a few spares for the filters
    results = []
    for entry in (info or {}).get("entries") or []:
        if not entry or entry.get("live_status") in ("is_live", "is_upcoming") or not valid_video_id(entry.get("id", "")):  # noqa: E501
            continue
        duration = entry.get("duration")
        results.append(MediaResult(video_id=entry["id"], title=entry.get("title") or "",
                                   channel=entry.get("channel") or entry.get("uploader") or "",
                                   duration_s=int(duration) if duration else None))
    return results


def _filter(results: list[MediaResult], kind: Kind, count: int) -> list[MediaResult]:
    """Keep results of a plausible length for ``kind``; if none fits, keep the non-live ones."""
    timed = [r for r in results if r.duration_s]
    if kind == "music":
        fits = [r for r in timed if r.duration_s <= float(cfg("youtube", "music_max_min", default=75)) * 60]
    else:
        fits = [r for r in timed if r.duration_s >= float(cfg("youtube", "podcast_min_min", default=5)) * 60]
    return (fits or timed or results)[:count]


async def search(query: str, kind: Kind = "music", kid_safe: bool = False) -> list[MediaResult]:
    """Search YouTube and remember the results.

    Args:
        query: Short search text from the LLM ("energetic metal").
        kind: ``music`` or ``podcast`` ("podcast" is added to the query when missing).
        kid_safe: A child is on board: SafeSearch strict (Data API only).

    Returns:
        Up to ``youtube.results_fetched`` results (may be empty).

    Raises:
        MediaSearchError: ``disabled``, ``kid_safe_needs_api``, ``timeout`` or ``failed: ...``.
    """
    if not cfg("youtube", "enabled", default=True):
        raise MediaSearchError("disabled")
    use_api = bool(_api_key())
    if kid_safe and not use_api and cfg("youtube", "require_api_with_child", default=True):
        raise MediaSearchError("kid_safe_needs_api")
    query = query.strip()
    if kind == "podcast" and "podcast" not in query.lower():
        query += " podcast"
    count = int(cfg("youtube", "results_fetched", default=6))
    timeout = float(cfg("youtube", "search_timeout_s", default=8))
    started = time.perf_counter()
    try:
        if use_api:
            raw = await asyncio.wait_for(asyncio.to_thread(_search_api, query, count, kid_safe, timeout), timeout)
        else:
            raw = await asyncio.wait_for(asyncio.to_thread(_search_ytdlp, query, count), timeout)
    except TimeoutError as exc:
        raise MediaSearchError("timeout") from exc
    except Exception as exc:
        raise MediaSearchError(f"failed: {type(exc).__name__}") from exc
    results = _filter(raw, kind, count)
    remember(results)
    log.info("search %r (%s, %s) -> %d results in %.0f ms", query, kind, "api" if use_api else "yt-dlp",
             len(results), (time.perf_counter() - started) * 1000)
    return results


# =============================================================================================================
# audio stream
# =============================================================================================================


def _extract_stream(video_id: str) -> StreamInfo:
    """Resolve the best audio-only stream with yt-dlp (m4a preferred: Chrome plays it natively)."""
    import yt_dlp

    with yt_dlp.YoutubeDL(_ydl_options(format="bestaudio[ext=m4a]/bestaudio")) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    url = (info or {}).get("url")
    if not url:
        raise MediaSearchError("no_audio_stream")
    expire = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("expire", [None])[0]
    limit = time.time() + float(cfg("youtube", "stream_cache_min", default=120)) * 60
    expires = min(limit, float(expire) - 300) if expire and expire.isdigit() else limit
    content_type = "audio/webm" if info.get("ext") == "webm" else "audio/mp4"
    return StreamInfo(url=url, headers=dict(info.get("http_headers") or {}), content_type=content_type,
                      expires=expires)


async def resolve_stream(video_id: str, refresh: bool = False) -> StreamInfo:
    """The audio stream of ``video_id`` (cached until it expires).

    Raises:
        MediaSearchError: invalid id or extraction failure.
    """
    if not valid_video_id(video_id):
        raise MediaSearchError("invalid_video_id")
    cached = _streams.get(video_id)
    if cached is not None and not refresh and cached.expires > time.time():
        return cached
    running = _inflight.get(video_id)
    if running is None or refresh:  # a prefetch already running is awaited, not repeated
        running = asyncio.ensure_future(_extract_and_cache(video_id))
        _inflight[video_id] = running
        running.add_done_callback(lambda _: _inflight.pop(video_id, None))
    return await asyncio.shield(running)


async def _extract_and_cache(video_id: str) -> StreamInfo:
    """Run the blocking extraction in a thread and cache the result."""
    try:
        stream = await asyncio.to_thread(_extract_stream, video_id)
    except MediaSearchError:
        raise
    except Exception as exc:
        raise MediaSearchError(f"extract_failed: {type(exc).__name__}") from exc
    _streams[video_id] = stream
    return stream


def prefetch(video_ids: Iterable[str]) -> None:
    """Resolve streams in the background so playback starts faster after the choice."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for video_id in video_ids:
        if not valid_video_id(video_id) or video_id in _streams or video_id in _inflight:
            continue
        task = loop.create_task(resolve_stream(video_id))
        _tasks.add(task)
        task.add_done_callback(_prefetch_done)


def _prefetch_done(task: asyncio.Task[Any]) -> None:
    """Drop the finished task; a failed prefetch is only logged (playback retries)."""
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.info("stream prefetch failed: %s", task.exception())
