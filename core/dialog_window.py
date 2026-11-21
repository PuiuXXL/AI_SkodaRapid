"""The dialog window (plan E1): a few seconds in which an answer needs no wake word and P1 looks for nods and gestures.

Opening it tells both sides: P1 gets ``dialog_window {open, to, until}`` (head answers and gestures are only detected
inside it, AS8 / AS9) and the voice sees ``interaction.dialog_window_open`` in the state (speech without the wake
word counts as addressed). Used by the SOS question now and by the assistant's questions later (step C).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import PerceptionCommand, State

if TYPE_CHECKING:
    from core.engine import Engine

PERSON_IDS = {"driver": 1, "passenger": 2}  # occupants[].id of the two camera seats


class DialogWindow:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.until: float | None = None
        self.to = "driver"
        self.reason = ""

    def is_open(self, now: float) -> bool:
        return self.until is not None and now < self.until

    def open(self, now: float, seconds: float, to: str = "driver", reason: str = "") -> None:
        """Open (or extend) the window for ``seconds`` from now."""
        self.until, self.to, self.reason = now + seconds, to, reason
        interaction = self.engine.state.interaction
        interaction.dialog_window_open = True
        interaction.addressed_to = PERSON_IDS.get(to)
        self.engine.send_perception_command(
            PerceptionCommand.model_validate({"cmd": "dialog_window", "open": True, "to": to, "until": self.until})
        )

    def close(self, now: float) -> None:
        if self.until is None:
            return
        self.until = None
        self.reason = ""
        self.engine.state.interaction.dialog_window_open = False
        self.engine.send_perception_command(PerceptionCommand(cmd="dialog_window", open=False, until=now))

    def tick(self, state: State, now: float) -> None:
        if self.until is not None and now >= self.until:
            self.close(now)
        state.interaction.dialog_window_open = self.is_open(now)

    def reset(self, now: float) -> None:
        self.until = None
        self.reason = ""
