"""Yes / no on every channel for the safety questions (C4, E3): voice, nod / shake, thumbs up / down.

Deterministic and local: the safety path never waits for the LLM. The phrases are in ``templates.yaml``; the one that
starts first in the sentence wins (the longer one at the same position), so "da, nu-i nimic" is yes and "nu sunt
bine" is no.

* :func:`parse_voice` (``answers``): the general yes / no (the reminder at a stop, the check-in question).
* :func:`parse_sos_voice` (``sos_answers``): the answer to "Ești bine?". A reassuring negation ("nu-i nimic", "nu mi-e
  rău") is a yes, only a clear "no" starts the countdown, and a bare "nu" is ``unclear`` (asked once more).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Literal

from core.settings import template

Answer = Literal["yes", "no"]
SosAnswer = Literal["yes", "no", "unclear"]

#: MediaPipe gesture -> answer (P1 reports the gesture name).
GESTURE_ANSWERS: dict[str, Answer] = {"Thumb_Up": "yes", "Thumb_Down": "no"}
#: A first clause that is only this ("Nu, sunt bine.") does not decide the answer: the rest of the sentence does.
_BARE_NO = frozenset({"nu", "nu nu"})


def normalize(text: str) -> str:
    """Lower case, no diacritics, only letters and digits separated by single spaces."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def _first_phrase(text: str, groups: Mapping[str, Sequence[object]]) -> str | None:
    """The group of the phrase that starts first in ``text`` (the longest one at the same position)."""
    words = f" {normalize(text)} "
    best: tuple[int, int, str] | None = None  # (position, -length, group)
    for group, phrases in groups.items():
        for phrase in phrases:
            needle = normalize(str(phrase))
            if not needle:
                continue
            position = words.find(f" {needle} ")
            if position >= 0:
                candidate = (position, -len(needle), group)
                if best is None or candidate < best:
                    best = candidate
    return best[2] if best else None


def parse_voice(text: str) -> Answer | None:
    """The answer in an utterance, or None when it is neither."""
    answer = _first_phrase(text, {"yes": template("answers", "yes"), "no": template("answers", "no")})
    return answer  # type: ignore[return-value]


def parse_sos_voice(text: str) -> SosAnswer | None:
    """The answer to "Ești bine?": yes, a clear no, ``unclear`` (a bare "nu"), or None when it is none of them."""
    groups = {name: template("sos_answers", name) for name in ("yes", "no", "unclear")}
    clauses = [clause for clause in re.split(r"[,.;!?]+", text) if normalize(clause)]
    if len(clauses) > 1 and normalize(clauses[0]) in _BARE_NO:  # "Nu, sunt bine." = yes; "Nu, nu sunt bine." = no
        rest = _first_phrase(" ".join(clauses[1:]), groups)
        if rest in ("yes", "no"):
            return rest  # type: ignore[return-value]
    return _first_phrase(text, groups)  # type: ignore[return-value]


def parse_gesture(gesture: str | None) -> Answer | None:
    return GESTURE_ANSWERS.get(gesture or "")
