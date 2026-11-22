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


def duration_s(clip_id: str) -> float | None:
    """The clip's length from P3's index (``duration_s``, written by integrations/audio_clips.py), or None."""
    value = available().get(clip_id, {}).get("duration_s")
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


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


def alarm_variants(driver: str, alert: str) -> list[str]:
    """The existing ``alarm_<alert>_<n>_<driver>`` clips, in order (empty when P3 has none for this alert)."""
    pattern = str(template("clips", "alarm_alert"))
    found = []
    for number in range(1, 10):
        clip_id = pattern.format(alert=alert, n=number, driver=driver)
        if not exists(clip_id):
            break
        found.append(clip_id)
    return found


def alarm_clip(driver: str, alert: str | None = None, *, variant: int = 0, repeat: bool = False) -> str:
    """The alarm clip for ``alert`` (2026-11-22: it says what to do, "ANDREI! Trezește-te!").

    In order: the firmer ``alarm_repeat_<alert>_<driver>`` when ``repeat``; variant ``variant`` (used in turn) of
    ``alarm_<alert>_<n>_<driver>``; ``alarm_<driver>`` ("ANDREI!"); the default driver's alarm (a name is better
    than none). Without P3's index the plain ``alarm_<driver>`` is returned (the browser then has no clip anyway).
    """
    plain = str(template("clips", "alarm")).format(driver=driver)
    if not available():
        return plain
    key = (template("clips", "alarm_aliases") or {}).get(alert, alert) if alert else None
    if key:
        repeat_id = str(template("clips", "alarm_repeat")).format(alert=key, driver=driver)
        if repeat and exists(repeat_id):
            return repeat_id
        variants = alarm_variants(driver, key)
        if variants:
            return variants[variant % len(variants)]
    if exists(plain):
        return plain
    fallback = str(template("clips", "alarm")).format(driver=template("clips", "default_driver"))
    log.warning("no clip %s, using %s", plain, fallback)
    return fallback


def passenger_wake_clip(passenger: str, driver: str) -> str | None:
    """ "Maria, te rog, vorbește puțin cu Andrei, să rămână treaz." or None (TTS of the same text then)."""
    clip_id = str(template("clips", "passenger_wake")).format(passenger=passenger, driver=driver)
    return clip_id if exists(clip_id) else None


def passenger_instructions_clip(passenger: str, driver: str) -> str | None:
    """The clip that tells the passenger what to do, or None when it does not exist (TTS of the template then)."""
    clip_id = str(template("clips", "passenger_instructions")).format(passenger=passenger, driver=driver)
    return clip_id if exists(clip_id) else None
