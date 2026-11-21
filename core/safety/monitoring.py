"""C7: "Nu te mai văd, monitorizarea e întreruptă" (plan principle 7: the system says when it can no longer protect).

``safety.monitoring_ok`` is false when there is no fresh frame or P1 says the driver camera does not see the face.
After ``safety.monitoring.lost_after_ms`` the rule raises a P2 alert (the LLM goes silent), says the clip, logs the
reason, and repeats it every ``repeat_s`` while it lasts. It only speaks once the camera has seen the driver in this
trip (no announcement while core starts before P1), and it does not talk over a more critical alert (the SOS). While a
closure is in progress (``core/safety/drowsiness.py`` holds it over a lost face) it waits: that is the alarm's job.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core import clips
from core.safety.arbiter import Arbiter
from core.settings import render, template, th
from shared.contracts import State

if TYPE_CHECKING:
    from core.engine import Engine

RULE = "monitoring"


class MonitoringRule:
    def __init__(self, engine: Engine, arbiter: Arbiter) -> None:
        self.engine, self.arbiter = engine, arbiter
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.seen_ok = False
        self.lost_since: float | None = None
        self.announced_at: float | None = None
        self.announcements = 0

    def tick(self, state: State, now: float) -> None:
        if state.safety.monitoring_ok:
            self.seen_ok = True
            if self.announced_at is not None:
                self.arbiter.clear(RULE)
                self.engine.log_event("monitoring_restored", now, text="Te văd din nou.",
                                      lost_s=round(now - (self.lost_since or now), 1))
            self.lost_since = self.announced_at = None
            return
        if not self.seen_ok:
            return
        if self.lost_since is None:
            self.lost_since = now
        if (now - self.lost_since) * 1000.0 < float(th("safety", "monitoring", "lost_after_ms")):
            return
        drowsiness = getattr(self.engine.safety, "drowsiness", None)
        if drowsiness is not None and drowsiness.closure is not None:
            return  # the face got lost inside a closure (the head fell): the drowsiness rule and the SOS own it
        if self.announced_at is not None and now - self.announced_at < float(th("safety", "monitoring", "repeat_s")):
            return
        reason = state.driver.monitoring_reason or "unknown"
        reasons = template("monitoring_reasons")
        reason_text = reasons.get(reason, reasons["unknown"])
        first = self.announced_at is None
        self.arbiter.raise_alert(RULE, "P2", "monitoring_lost", now)
        self.announced_at = now
        self.announcements += 1
        if not self.arbiter.outranks("P2", RULE):
            clip_id = str(template("clips", "monitoring_lost"))
            self.engine.say(clip_id, clips.clip_text(clip_id, "Nu te mai văd. Monitorizarea e întreruptă."),
                            prefix="mon")
        if first:
            self.engine.log_event("monitoring_lost", now, reason=reason,
                                  explanation=render("explanations", "monitoring_lost", reason_text=reason_text))
