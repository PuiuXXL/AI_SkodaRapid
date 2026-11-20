"""Deterministic refusal detection (plan D10).

When fatigue is high the assistant starts a short keep-awake conversation. If the
driver answers "lasă-mă în pace", "taci", "nu acum"... core calls
:func:`is_refusal`; a True result becomes the ``driver_refused`` event, the clip
"Ok, te las în pace." is played and P2's rule C10 decides whether the trusted
contact is notified (P3 never decides that).

Design constraints from the plan (roluri/P3, interfaces table):

* keyword based and deterministic - no LLM, no network;
* well under 1 ms per call;
* works with and without diacritics (speech recognisers are inconsistent).

Core should call it only inside the fatigue dialog (plan E3: "Refuz (în dialogul de
oboseală)"), where phrases such as "mai târziu" clearly mean "leave me alone".

Subtler refusals that the keywords miss are caught by the LLM, which returns
``stay_silent`` with ``reason="driver_refused"``.
"""

from __future__ import annotations

import re

from assistant.textutil import normalize

#: Phrases that are a refusal wherever they appear in the utterance
#: (already normalised: lower-case, no diacritics, no punctuation).
REFUSAL_PHRASES: tuple[str, ...] = (
    "lasa ma in pace",
    "lasa ma",
    "lasati ma",
    "nu acum",
    "nu vreau",
    "nu am chef",
    "n am chef",
    "nu ma intereseaza",
    "nu ma deranja",
    "nu mai vorbi",
    "nu vorbi",
    "nu te baga",
    "mai tarziu",
    "gata cu",
    "inceteaza",
    "liniste te rog",
    "taci",
    "taca ti gura",
    "tacere",
    "shut up",
    "leave me alone",
    "not now",
    "stop talking",
)

#: Single words that are a refusal only when they are (almost) the whole utterance:
#: "lasă" alone is a refusal, but "lasă telefonul" is not.
REFUSAL_SHORT_WORDS: frozenset[str] = frozenset({"lasa", "stop", "destul", "gata", "ajunge", "liniste"})

#: Phrases that cancel a match ("nu acum, dar mai târziu da" is not a refusal of
#: the conversation; "nu vreau să dorm" is the driver asking to stay awake).
NEGATING_PHRASES: tuple[str, ...] = (
    "nu vreau sa dorm",
    "nu vreau sa adorm",
    "vreau sa vorbim",
    "hai sa vorbim",
)

_PHRASE_PATTERNS = tuple(re.compile(rf"(?:^| ){re.escape(p)}(?: |$)") for p in REFUSAL_PHRASES)


def is_refusal(text: str) -> bool:
    """Return True when the utterance refuses the assistant.

    Examples:
        >>> is_refusal("Lasă-mă în pace!")
        True
        >>> is_refusal("lasa ma in pace")
        True
        >>> is_refusal("lasă telefonul pe bord")
        False
        >>> is_refusal("Da, sunt cam obosit")
        False

    Args:
        text: The recognised utterance (any case, with or without diacritics).

    Returns:
        True if it is a refusal, False otherwise (including empty text).
    """
    norm = normalize(text)
    if not norm:
        return False
    if any(phrase in norm for phrase in NEGATING_PHRASES):
        return False
    words = norm.split()
    if len(words) <= 2 and words[0] in REFUSAL_SHORT_WORDS:
        return True
    return any(pattern.search(norm) for pattern in _PHRASE_PATTERNS)
