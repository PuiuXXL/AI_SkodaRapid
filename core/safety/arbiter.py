"""The arbiter (C1): P0 > P1 > P2 > P3 > P4. A higher level interrupts everything below it at once.

Each rule reports its own alert with :meth:`Arbiter.raise_alert` and withdraws it with :meth:`Arbiter.clear`. The
arbiter writes ``safety.level`` (the most critical active alert), ``safety.alert`` and the LLM veto
``safety.llm_allowed`` (C8: the LLM is silent at P0-P2). When the top level becomes more critical than before, it
sends ``speak_control: stop`` and ``media: stop`` before the rule plays its own sound (plan 5.2: every non-critical
sound stops at an alert).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from shared.contracts import LLM_VETO_LEVELS, SAFETY_LEVELS, State, UiMedia, UiSpeakControl, to_wire

if TYPE_CHECKING:
    from core.engine import Engine


def rank(level: str | None) -> int:
    """0 for P0 (most critical) ... 4 for P4; 5 for no level."""
    return SAFETY_LEVELS.index(level) if level in SAFETY_LEVELS else len(SAFETY_LEVELS)


@dataclass
class Alert:
    level: str
    alert: str
    since: float


class Arbiter:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.active: dict[str, Alert] = {}  # rule name -> its alert
        self.interruptions = 0
        # called with the rule that interrupted, e.g. the assistant drops (or keeps, for a distraction) its question
        self.on_interrupt: list[Callable[[str | None], None]] = []

    def top(self) -> tuple[str, Alert] | None:
        if not self.active:
            return None
        return min(self.active.items(), key=lambda item: (rank(item[1].level), -item[1].since))

    @property
    def level(self) -> str | None:
        top = self.top()
        return top[1].level if top else None

    def raise_alert(self, rule: str, level: str, alert: str, now: float, *, interrupt: bool = True) -> None:
        """Rule ``rule`` has an active alert. Interrupts lower sounds when this makes the top level more critical.

        ``interrupt=False``: the level (and the LLM veto) apply, but nothing is stopped; the rule decides itself
        when the sounds stop (the distraction's discrete cue only pauses the assistant, see ``distraction.py``).
        """
        before = rank(self.level)
        previous = self.active.get(rule)
        self.active[rule] = Alert(level, alert, previous.since if previous and previous.level == level else now)
        if interrupt and rank(level) < before and level in LLM_VETO_LEVELS:
            self.interrupt(rule)
        self._write(self.engine.state)

    def clear(self, rule: str) -> None:
        if self.active.pop(rule, None) is not None:
            self._write(self.engine.state)

    def interrupt(self, rule: str | None = None) -> None:
        """Stop the assistant's voice and the music (the alarm clip itself also stops them in the browser).

        ``rule``: who interrupts; the assistant resumes its sentence only after a distraction's warning.
        """
        self.interruptions += 1
        for listener in self.on_interrupt:
            listener(rule)
        self.engine.hub.broadcast_ui(to_wire(UiSpeakControl(action="stop")))
        self.engine.hub.broadcast_ui(to_wire(UiMedia(action="stop")))
        self.engine.state.media.playing = False

    def outranks(self, level: str, rule: str) -> bool:
        """True when another rule holds a more critical alert than ``level`` (that rule's sound must not be covered)."""
        return any(rank(a.level) < rank(level) for name, a in self.active.items() if name != rule)

    def _write(self, state: State) -> None:
        top = self.top()
        state.safety.level = top[1].level if top else None  # type: ignore[assignment]
        state.safety.alert = top[1].alert if top else None
        state.safety.llm_allowed = state.safety.level not in LLM_VETO_LEVELS

    def tick(self, state: State, now: float) -> None:
        self._write(state)

    def reset(self, now: float) -> None:
        self.active.clear()
