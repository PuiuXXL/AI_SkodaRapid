"""Alarms with the driver's name (C3) and their latency (J1: "latența alarmei", target < 300 ms).

``alarm_ms`` = from the moment core detected the threshold crossing to the moment the browser's ``alarm_played``
arrived, both on core's clock (the browser may run on another machine with another clock). The time from the
camera capture is logged too (``capture_ms``), for the slide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core import clips
from core.settings import th
from shared.contracts import UiAlarm, to_wire

if TYPE_CHECKING:
    from core.engine import Engine


@dataclass
class PendingAlarm:
    alert: str
    detected_at: float  # core clock, when the rule fired
    capture_ts: float | None  # PerceptionFrame.ts of the frame that crossed the threshold


class Alarms:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.pending: dict[str, PendingAlarm] = {}
        self.sent = 0

    def send(self, now: float, alert: str, level: str, *, capture_ts: float | None = None,
             explanation: str | None = None) -> str:
        """Play ``alarm_<driver>`` now (it interrupts speech and music in the browser). Returns the alarm id."""
        self.sent += 1
        alarm_id = f"a{self.sent}"
        driver, _ = clips.person_names(self.engine.state)
        clip_id = clips.alarm_clip(driver)
        message = UiAlarm.model_validate({"id": alarm_id, "clip_url": clips.clip_url(clip_id), "level": level,
                                          "alert": alert})
        self.engine.hub.broadcast_ui(to_wire(message))
        self.pending[alarm_id] = PendingAlarm(alert, now, capture_ts)
        self.engine.log_event("alarm", now, text=clips.clip_text(clip_id, f"{clips.display(driver).upper()}!"),
                              explanation=explanation, alarm_id=alarm_id, alert=alert, level=level, clip=clip_id)
        return alarm_id

    def on_played(self, alarm_id: str, now: float) -> float | None:
        """The browser played alarm ``alarm_id``: record the latency. Returns alarm_ms (None for an unknown id)."""
        pending = self.pending.pop(alarm_id, None)
        if pending is None:
            return None
        alarm_ms = round((now - pending.detected_at) * 1000.0, 1)
        capture_ms = round((now - pending.capture_ts) * 1000.0, 1) if pending.capture_ts else None
        self.engine.core_perf["alarm_ms_last"] = alarm_ms
        self.engine.state.safety.alarm_ms_last = alarm_ms
        on_target = alarm_ms <= float(th("safety", "alarm_target_ms"))
        self.engine.log_event("alarm_played", now, latency_ms=alarm_ms, alarm_id=alarm_id, alert=pending.alert,
                              capture_ms=capture_ms, on_target=on_target,
                              text=f"Alarmă redată în {alarm_ms:.0f} ms.")
        return alarm_ms

    def reset(self, now: float) -> None:
        self.pending.clear()
