"""Multimodal answer fusion (plan E3): one "yes" / "no" from voice, head or hand.

The driver can answer a question in any of these ways (plan E3):

* **Yes** = "da" / nod (``head.answer = "yes"``) / thumbs-up 👍
* **No** = "nu" / head shake (``head.answer = "no"``) / thumbs-down 👎
* **Silence** = open palm ✋
* **Refusal** (only in the fatigue dialog) = "lasă-mă în pace" / "taci" / ✋ / 👎

Inputs arrive on different channels at slightly different times; :func:`fuse`
takes all candidate inputs seen while the dialog window was open and returns the
earliest valid one, with the channel it came from (shown in the event log).

The head and gesture values are produced by P1 and copied into the state by core;
this module only interprets them. Gesture names follow MediaPipe Gesture
Recognizer: ``Thumb_Up``, ``Thumb_Down``, ``Open_Palm``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from assistant.refusal import is_refusal
from assistant.textutil import normalize

AnswerValue = Literal["yes", "no", "silence", "refusal"]
Channel = Literal["voice", "nod", "gesture"]

#: Normalised words / phrases meaning "yes" (whole utterance or its first word).
YES_WORDS: frozenset[str] = frozenset({
    "da", "sigur", "ok", "okay", "bine", "hai", "desigur", "evident", "normal", "te rog",
    "da te rog", "yes", "yeah", "corect", "exact", "pune", "trimite", "citeste",
})

#: Normalised words / phrases meaning "no".
NO_WORDS: frozenset[str] = frozenset({
    "nu", "nu multumesc", "nu e nevoie", "nu te rog", "deloc", "no", "nope", "anuleaza",
})

#: Gesture name -> meaning (MediaPipe Gesture Recognizer categories).
GESTURES: dict[str, AnswerValue] = {"Thumb_Up": "yes", "Thumb_Down": "no", "Open_Palm": "silence"}


@dataclass(frozen=True)
class InputEvent:
    """One raw input seen while waiting for an answer.

    Attributes:
        channel: ``"voice"``, ``"nod"`` (head answer) or ``"gesture"``.
        value: Voice text, ``"yes"``/``"no"`` for nod, or a gesture name.
        ts: Unix time it was observed.
    """

    channel: Channel
    value: str
    ts: float


@dataclass(frozen=True)
class Answer:
    """The fused answer.

    Attributes:
        value: ``yes`` / ``no`` / ``silence`` / ``refusal``.
        channel: The channel that produced it (for the event log, plan E3).
        ts: When it was given (P2 uses it for the gesture / verbal reaction time).
    """

    value: AnswerValue
    channel: Channel
    ts: float


def interpret_voice(text: str, fatigue_dialog: bool = False) -> AnswerValue | None:
    """Interpret a spoken answer.

    Args:
        text: Recognised text.
        fatigue_dialog: True inside the fatigue conversation, where refusals count.

    Returns:
        The meaning, or None if the text is not a yes / no / refusal.
    """
    if fatigue_dialog and is_refusal(text):
        return "refusal"
    norm = normalize(text)
    if not norm:
        return None
    if norm in NO_WORDS or norm.split()[0] == "nu":
        return "no"
    if norm in YES_WORDS or norm.split()[0] in YES_WORDS:
        return "yes"
    return None


#: Spoken Romanian numbers 1-9 (normalised, no diacritics) for the KSS answer (plan D3).
KSS_WORDS: dict[str, int] = {
    "unu": 1, "una": 1, "unul": 1, "doi": 2, "doua": 2, "trei": 3, "patru": 4, "cinci": 5,
    "sase": 6, "sapte": 7, "opt": 8, "noua": 9,
}


def parse_kss(text: str) -> int | None:
    """Read a Karolinska Sleepiness Scale answer (1 = very alert ... 9 = very sleepy).

    Accepts digits ("7", "cam 7") and Romanian words ("șapte", "vreo opt"). The first
    number found wins, so "7, poate 8" gives 7.

    Examples:
        >>> parse_kss("Cam șapte")
        7
        >>> parse_kss("8")
        8
        >>> parse_kss("nu știu") is None
        True

    Args:
        text: Recognised answer.

    Returns:
        An integer 1-9, or None when no KSS value is present.
    """
    for word in normalize(text).split():
        if word.isdigit() and 1 <= int(word) <= 9:
            return int(word)
        if word in KSS_WORDS:
            return KSS_WORDS[word]
    return None


#: Leading answer words removed before looking for a new request ("nu, mersi, dar ..." -> "...").
_ANSWER_LEAD = re.compile(
    r"^[\s…,.;:!?-]*(?:(?:da|nu|ok|okay|bine|sigur|nu\s+mul[tț]umesc|mul[tț]umesc|mersi|merci|dar|ci|[sș]i"
    r"|mai\s+bine|deloc|nu\s+acum)(?:[\s…,.;:!?-]+|$))+",
    re.IGNORECASE,
)
#: Words that alone do not make a request ("nu, nu acum", "da, te rog", "da, dar mai târziu").
_NOT_A_REQUEST = frozenset({"nu", "da", "acum", "te", "rog", "multumesc", "mersi", "merci", "bine", "ok", "deloc",
                            "nimic", "gata", "asa", "chiar", "frumos", "sigur", "poate", "lasa", "mai", "tarziu",
                            "incolo", "apoi", "dupa", "putin", "stiu"})


def request_after_answer(text: str) -> str | None:
    """The new request that follows a yes / no: "nu, vreau să pui muzică" -> "vreau să pui muzică".

    Returns:
        The rest of the utterance when it is a request of its own (at least two words, one of them
        meaningful), else None ("nu", "nu, mersi", "da, te rog", "nu, nu acum").
    """
    rest = _ANSWER_LEAD.sub("", text or "", count=1).strip(" ,.;:!?-")
    words = normalize(rest).split()
    if rest == (text or "").strip() or len(words) < 2:
        return None
    if not any(len(w) >= 3 and w not in _NOT_A_REQUEST for w in words):
        return None
    return rest


def is_plain_answer(text: str) -> bool:
    """True when ``text`` is only a yes / no with polite words ("da", "da, te rog", "nu, mersi").

    False when it carries a request of its own, even one that starts like a yes:
    "pune muzică" ("pune" counts as yes for a music offer), "ok, cât mai e?".
    """
    rest = _ANSWER_LEAD.sub("", text or "", count=1).strip(" ,.;:!?-")
    return not any(len(w) >= 3 and w not in _NOT_A_REQUEST for w in normalize(rest).split())


def interpret(event: InputEvent, fatigue_dialog: bool = False) -> AnswerValue | None:
    """Interpret one input on any channel (see module docstring for the mapping)."""
    if event.channel == "voice":
        return interpret_voice(event.value, fatigue_dialog)
    if event.channel == "nod":
        return event.value if event.value in ("yes", "no") else None  # type: ignore[return-value]
    meaning = GESTURES.get(event.value)
    if fatigue_dialog and meaning in ("no", "silence"):
        return "refusal"  # ✋ / 👎 in the fatigue dialog = refusal (plan D10, E3)
    return meaning


def fuse(inputs: Iterable[InputEvent], fatigue_dialog: bool = False) -> Answer | None:
    """Return the earliest meaningful answer among the inputs, or None.

    Args:
        inputs: Everything seen during the dialog window (any order).
        fatigue_dialog: True inside the fatigue conversation.

    Returns:
        The :class:`Answer`, or None if nothing was a recognisable answer.
    """
    for event in sorted(inputs, key=lambda e: e.ts):
        meaning = interpret(event, fatigue_dialog)
        if meaning is not None:
            return Answer(meaning, event.channel, event.ts)
    return None
