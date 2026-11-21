"""Safety (C): deterministic rules, no LLM on this path (plan principle 1, section 5).

:class:`Safety` wires the rules into the engine:

* the SOS machine (C3, C4, C5) runs on every PerceptionFrame (fast path) and on every tick (timers);
* the monitoring rule (C7) and the arbiter (C1, C8 veto) run on every tick;
* the browser's ``alarm_played`` gives the alarm latency, its ``speech`` the spoken answers.

SOS channels: the DriveMate Contact page when P4's ``integrations.contact_app`` exists; ``call`` (Twilio) and
``sms`` (the driver's phone, via the bridge) report ``not_connected`` until the phone part is wired.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

from core.dialog_window import DialogWindow
from core.safety.alarm import Alarms
from core.safety.arbiter import Arbiter
from core.safety.monitoring import MonitoringRule
from core.safety.sos import SosChannel, SosMachine
from shared.contracts import SosReport, State, UiAlarmPlayed, UiSpeech

if TYPE_CHECKING:
    from core.engine import Engine

log = logging.getLogger("drivemate.core.safety")

__all__ = ["Safety", "default_sos_channels"]


def _contact_page(report: SosReport) -> str:
    """The red SOS alert with the live map on DriveMate Contact (P4, F5)."""
    try:
        push_sos = importlib.import_module("integrations.contact_app").push_sos
    except (ImportError, AttributeError):
        return "not_connected"
    push_sos(report)
    return "ok"


def _not_connected(_: SosReport) -> str:
    return "not_connected"


def default_sos_channels() -> dict[str, SosChannel]:
    return {"contact_page": _contact_page, "call": _not_connected, "sms": _not_connected}


class Safety:
    def __init__(self, engine: Engine, sos_channels: dict[str, SosChannel] | None = None) -> None:
        self.engine = engine
        engine.safety = self
        self.dialog = DialogWindow(engine)
        self.arbiter = Arbiter(engine)
        self.alarms = Alarms(engine)
        channels = default_sos_channels() if sos_channels is None else sos_channels
        self.sos = SosMachine(engine, self.arbiter, self.alarms, self.dialog, channels)
        self.monitoring = MonitoringRule(engine, self.arbiter)
        engine.add_frame_listener(self.sos.on_frame)
        engine.add_browser_listener(self.on_browser)
        engine.add_tick_listener(self.on_tick)
        engine.add_reset_listener(self.reset)

    def on_browser(self, message: Any, now: float) -> None:
        if isinstance(message, UiAlarmPlayed):
            self.alarms.on_played(message.id, now)
        elif isinstance(message, UiSpeech):
            self.sos.on_speech(message, now)

    def on_tick(self, state: State, now: float) -> None:
        self.dialog.tick(state, now)
        self.sos.tick(state, now)
        self.monitoring.tick(state, now)
        self.arbiter.tick(state, now)

    def reset(self, now: float) -> None:
        for part in (self.dialog, self.arbiter, self.alarms, self.sos, self.monitoring):
            part.reset(now)
