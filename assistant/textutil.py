"""Small text helpers shared by the assistant modules.

Kept dependency-free and fast: they run on every utterance.
"""

from __future__ import annotations

import re
import unicodedata

# Romanian letters with diacritics, including the legacy cedilla forms (ş ţ) that
# speech recognisers and phones still produce.
_RO_MAP = str.maketrans({
    "ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
    "Ă": "a", "Â": "a", "Î": "i", "Ș": "s", "Ş": "s", "Ț": "t", "Ţ": "t",
})

_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def normalize(text: str) -> str:
    """Lower-case, strip diacritics and punctuation, collapse spaces.

    ``"Lasă-mă în PACE!"`` becomes ``"lasa ma in pace"``. Used to compare spoken
    text with keyword lists regardless of how the recogniser spelled it.

    Args:
        text: Any user text (may be empty).

    Returns:
        The normalised text (ASCII letters, digits and single spaces).
    """
    text = (text or "").translate(_RO_MAP).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def word_count(text: str) -> int:
    """Count spoken words (punctuation ignored).

    Args:
        text: The sentence.

    Returns:
        Number of words, used for the ``speech.max_words_to_driver`` rule.
    """
    return len(normalize(text).split()) if text else 0


def split_sentences(text: str) -> list[str]:
    """Split text into sentences for sentence-by-sentence TTS (plan D4).

    Args:
        text: One or more sentences.

    Returns:
        Non-empty sentences, punctuation kept.
    """
    return [part.strip() for part in _SENTENCE_END.split(text or "") if part.strip()]


class SafeDict(dict):
    """``str.format_map`` helper: missing placeholders become a neutral word.

    ``"Salut {driver}".format_map(SafeDict(default="tu"))`` gives ``"Salut tu"``
    instead of raising ``KeyError``.
    """

    def __init__(self, *args, default: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._default = default

    def __missing__(self, key: str) -> str:
        return self._default


def fill(template: str, default: str = "", **values: object) -> str:
    """Fill ``{placeholders}`` in a fixed text, never raising on missing values.

    Args:
        template: Text with ``{name}`` placeholders (from texts.<lang>.yaml).
        default: Replacement for placeholders without a value.
        **values: Placeholder values; ``None`` counts as missing.

    Returns:
        The filled text, with doubled spaces removed.
    """
    clean = {key: str(val) for key, val in values.items() if val not in (None, "")}
    text = template.format_map(SafeDict(clean, default=default))
    return _SPACES.sub(" ", text).strip()
