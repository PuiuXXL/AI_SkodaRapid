"""Music recommendation against disengagement (plan D8).

When disengagement (D) is high and the context is monotonous, the assistant asks
"Pare monoton. Pun ceva mai energic, din ce-ți place?" and, after a "yes", plays a
track. This module decides WHICH tracks are acceptable:

* only tracks from ``assistant/data/media_catalog.json`` (no streaming service:
  the plan cut the Spotify API, we use local royalty-free mp3 files);
* matching the driver's taste (genres from the profile, or defaults);
* with the right energy (high energy for D);
* respecting the cabin: a child on board -> ``kid_safe`` only; passenger asleep ->
  low volume (plan G3, G4).

The LLM then picks one of :func:`candidates` (shown in the state summary) and
``assistant/actions.py`` rejects any ``track_id`` outside that list. Without the
LLM, :func:`pick_track` chooses deterministically.

The effect of the music on D is measured by P2 (plan D6), not here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from assistant import cabin
from assistant.preferences import driver_profile
from assistant.contract import State
from assistant.settings import cfg, resolve_path

log = logging.getLogger("drivemate.assistant.music")


@dataclass(frozen=True)
class Track:
    """One entry of the media catalog.

    Attributes:
        id: Stable id used in actions and in the file name (``t01`` -> ``t01.mp3``).
        title: Title shown on the dashboard and said by the assistant.
        artist: Artist name.
        genre: One genre label (pop, rock, electronic, jazz, lofi, kids, ...).
        energy: 1 (calm) to 5 (very energetic).
        kid_safe: True if suitable with a child on board.
        file: mp3 file name inside ``music.media_dir``.
        source: Where the track was downloaded from (URL).
        license: Licence name (e.g. "Pixabay Content License").
    """

    id: str
    title: str
    artist: str
    genre: str
    energy: int
    kid_safe: bool
    file: str
    source: str = ""
    license: str = ""


@lru_cache(maxsize=1)
def load_catalog() -> tuple[Track, ...]:
    """Load and cache the media catalog (``music.catalog`` in assistant.yaml).

    Returns:
        All tracks; an empty tuple if the file is missing or invalid (logged).
    """
    path = resolve_path(cfg("music", "catalog", default="assistant/data/media_catalog.json"))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Media catalog not loaded (%s): music suggestions disabled.", exc)
        return ()
    tracks = []
    for item in raw.get("tracks", []):
        try:
            tracks.append(Track(
                id=item["id"], title=item.get("title", item["id"]), artist=item.get("artist", ""),
                genre=item.get("genre", "").lower(), energy=int(item.get("energy", 3)),
                kid_safe=bool(item.get("kid_safe", False)), file=item.get("file", f"{item['id']}.mp3"),
                source=item.get("source", ""), license=item.get("license", ""),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed catalog entry %r: %s", item, exc)
    return tuple(tracks)


def get_track(track_id: Optional[str]) -> Optional[Track]:
    """Return the catalog track with this id, or None."""
    return next((t for t in load_catalog() if t.id == track_id), None)


def track_file(track: Track) -> Path:
    """Absolute path of the track's mp3 (may not exist if not downloaded yet)."""
    return resolve_path(cfg("music", "media_dir", default="assistant/data/media")) / track.file


def track_url(track_id: str) -> str:
    """URL served by ``assistant/router.py``: ``/media/<id>.mp3`` (catalog) or ``/media/yt/<id>.m4a`` (YouTube)."""
    if track_id.startswith("yt:"):
        return f"/media/yt/{track_id[3:]}.m4a"
    return f"/media/{track_id}.mp3"


def loops(track_id: str) -> bool:
    """Whether the browser should loop the track: catalog music yes, YouTube (songs, podcasts) no."""
    return not track_id.startswith("yt:")


def profile_genres(state: State) -> list[str]:
    """Favourite genres of the driver.

    Reads ``profiles/<profile>/profile.json`` (owned by P4) and looks for a list in
    ``music_genres`` or ``preferences.music_genres``. Falls back to
    ``music.default_genres`` from assistant.yaml.

    Args:
        state: Current state (the driver occupant gives the profile id).

    Returns:
        Lower-case genre names, most preferred first.
    """
    data = driver_profile(state)
    prefs = data.get("preferences")
    genres = data.get("music_genres") or (prefs.get("music_genres") if isinstance(prefs, dict) else None)
    if isinstance(genres, list) and genres:
        return [str(g).lower() for g in genres]
    return [g.lower() for g in cfg("music", "default_genres", default=[])]


def candidates(state: State, reason: str = "disengagement") -> list[Track]:
    """Tracks acceptable right now, best first.

    Filters: ``kid_safe`` when a child is on board; energy >=
    ``music.min_energy_for_disengagement`` when ``reason == "disengagement"``; not
    the track already playing. Sorted by: liked genre first, then higher energy.

    Args:
        state: Current state.
        reason: Why music is proposed (``"disengagement"`` or anything else).

    Returns:
        At most ``music.candidates_for_llm`` tracks (may be empty).
    """
    liked = profile_genres(state)
    min_energy = cfg("music", "min_energy_for_disengagement", default=4) if reason == "disengagement" else 1
    child = cabin.has_child(state)
    playing = state.media.track_id if state.media.playing else None

    podcast_genre = cfg("music", "podcast_genre", default="podcast")
    pool = [
        t for t in load_catalog()
        if t.energy >= min_energy and (t.kid_safe or not child) and t.id != playing
        and t.genre != podcast_genre
    ]

    def rank(track: Track) -> tuple[int, int]:
        genre_rank = liked.index(track.genre) if track.genre in liked else len(liked)
        return genre_rank, -track.energy

    pool.sort(key=rank)
    return pool[: cfg("music", "candidates_for_llm", default=5)]


def podcasts(state: State) -> list[Track]:
    """Podcast tracks (genre ``music.podcast_genre``) playable in the current cabin.

    Offered together with the quiz when the driver refuses music (plan D8). Never
    proposed as music by :func:`candidates`.
    """
    podcast_genre = cfg("music", "podcast_genre", default="podcast")
    child = cabin.has_child(state)
    return [t for t in load_catalog() if t.genre == podcast_genre and (t.kid_safe or not child)]


def pick_track(state: State, reason: str = "disengagement") -> Optional[Track]:
    """Deterministic choice used without the LLM: the best candidate, or None."""
    found = candidates(state, reason)
    return found[0] if found else None


def volume_for(state: State) -> float:
    """Playback volume for the current cabin (plan G3: passenger asleep -> low)."""
    if cabin.passenger_asleep(state):
        return float(cfg("music", "volume_passenger_asleep", default=0.25))
    return float(cfg("music", "volume_normal", default=0.6))
