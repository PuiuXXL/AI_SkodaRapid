"""P3's pre-generated clips (``dashboard/public/sounds/clips/clips.json``) and the names used to pick them.

Alarms and the SOS questions are local clips, never TTS from the cloud (plan C3, section 8 rule 6): they play in
under 300 ms and work without internet. The clip ids come from ``core/config/templates.yaml`` (``clips:``); the names
from ``occupants[].profile``, with the defaults from the same file while P1 does not recognise the person yet.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.settings import template
from shared.contracts import State

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIPS_INDEX = REPO_ROOT / "dashboard" / "public" / "sounds" / "clips" / "clips.json"

log = logging.getLogger("drivemate.core.clips")


@lru_cache(maxsize=1)
def available() -> dict[str, Any]:
    """clip id -> {file, text}; empty when P3's index is missing (the voice then falls back to the browser's TTS)."""
    try:
        return json.loads(CLIPS_INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("clips index not readable (%s): fixed texts will use the browser's TTS", exc)
        return {}


def exists(clip_id: str) -> bool:
    return clip_id in available()


def clip_url(clip_id: str) -> str:
    return str(template("clips", "url")).format(clip_id=clip_id)


def clip_text(clip_id: str, default: str = "") -> str:
    return str(available().get(clip_id, {}).get("text", default))


def person_names(state: State) -> tuple[str, str | None]:
    """(driver, passenger) profile names, lower case. Passenger is None when the front-right seat is empty."""
    driver = passenger = None
    for occupant in state.occupants:
        if occupant.seat == "driver":
            driver = occupant.profile
        elif occupant.seat == "front_right":
            passenger = occupant.profile or str(template("clips", "default_passenger"))
    return (driver or str(template("clips", "default_driver"))).lower(), passenger.lower() if passenger else None


def display(name: str | None) -> str:
    return (name or "").capitalize()


def alarm_clip(driver: str) -> str:
    """``alarm_<driver>``; the default driver's alarm when that clip does not exist (a name is better than none)."""
    clip_id = str(template("clips", "alarm")).format(driver=driver)
    if exists(clip_id) or not available():
        return clip_id
    fallback = str(template("clips", "alarm")).format(driver=template("clips", "default_driver"))
    log.warning("no clip %s, using %s", clip_id, fallback)
    return fallback


def passenger_instructions_clip(passenger: str, driver: str) -> str | None:
    """The clip that tells the passenger what to do, or None when it does not exist (TTS of the template then)."""
    clip_id = str(template("clips", "passenger_instructions")).format(passenger=passenger, driver=driver)
    return clip_id if exists(clip_id) else None
