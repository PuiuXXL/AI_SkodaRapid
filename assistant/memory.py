"""Short conversation memory sent to the LLM (plan D1: "memorie scurtă").

Only the last few utterances are kept (``memory.turns`` in assistant.yaml, default
3), so the LLM can resolve "da" / "spune-i că ajung în 20 de minute" without ever
receiving a long history. Nothing is written to disk.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from assistant.settings import cfg


@dataclass(frozen=True)
class Turn:
    """One utterance.

    Attributes:
        speaker: ``"driver"``, ``"passenger"`` or ``"assistant"``.
        text: What was said.
        ts: Unix time.
    """

    speaker: str
    text: str
    ts: float


class ShortMemory:
    """Ring buffer of the last ``memory.turns`` utterances."""

    def __init__(self, size: int | None = None) -> None:
        """Create an empty memory.

        Args:
            size: Number of utterances kept; defaults to ``memory.turns``.
        """
        self._turns: deque[Turn] = deque(maxlen=size or int(cfg("memory", "turns", default=3)))

    def add(self, speaker: str, text: str, ts: float) -> None:
        """Remember one utterance (empty text is ignored)."""
        if text and text.strip():
            self._turns.append(Turn(speaker, text.strip(), ts))

    def recent(self) -> list[Turn]:
        """Return the remembered utterances, oldest first."""
        return list(self._turns)

    def clear(self) -> None:
        """Forget everything (new trip, director reset)."""
        self._turns.clear()
