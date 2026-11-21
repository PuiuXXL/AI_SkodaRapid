"""Yes / no on every channel for the safety questions (C4, E3): voice, nod / shake, thumbs up / down.

Deterministic and local: the safety path never waits for the LLM. The phrases are in ``templates.yaml`` (``answers``);
the one that starts first in the sentence wins, so "da, nu-i nimic" is yes and "nu sunt bine" is no.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from core.settings import template

Answer = Literal["yes", "no"]

#: MediaPipe gesture -> answer (P1 reports the gesture name).
GESTURE_ANSWERS: dict[str, Answer] = {"Thumb_Up": "yes", "Thumb_Down": "no"}


def normalize(text: str) -> str:
    """Lower case, no diacritics, only letters and digits separated by single spaces."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def parse_voice(text: str) -> Answer | None:
    """The answer in an utterance, or None when it is neither."""
    words = f" {normalize(text)} "
    best: tuple[int, int, Answer] | None = None  # (position, -length, answer)
    for answer in ("yes", "no"):
        for phrase in template("answers", answer):
            position = words.find(f" {normalize(str(phrase))} ")
            if position >= 0:
                candidate = (position, -len(phrase), answer)
                if best is None or candidate < best:
                    best = candidate
    return best[2] if best else None


def parse_gesture(gesture: str | None) -> Answer | None:
    return GESTURE_ANSWERS.get(gesture or "")
