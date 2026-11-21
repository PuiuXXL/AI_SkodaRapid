"""The unresponsive driver (C4, C5, F6): normal -> alarm -> asking -> countdown -> sos_sent.

* **alarm** (P1): eyes closed for ``safety.microsleep.closed_ms`` (P1 reports ``closed_ms`` and leaves the decision
  here) or a fatigue head drop. Fired on the frame itself, not at the next tick (target < 300 ms).
* **asking** (P1): after ``sos.ask_after_alarm_s``, "Ești bine?" and a dialog window: voice, nod or thumbs up.
* **countdown** (P0): no answer (or "nu"): the passenger instructions by name, then ``sos.countdown_s``; the alarm is
  replayed every ``sos.realarm_s`` after the instructions.
* **sos_sent** (P0): the report from ``templates.yaml`` goes to every SOS channel.

Any "yes" before the end cancels (``sos_cancelled`` in the log, with the channel). A new alarm needs the eyes to open
first (``armed``), so one long closure gives one alarm, not one per frame.

SOS channels are callables ``report -> status`` registered by name: the DriveMate Contact page (P4) now, the Twilio
call and the SMS from the driver's phone when the phone part is wired. A channel must return quickly; one that talks
to the network must run in a thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from core import clips
from core.ab_baseline import AbBaseline
from core.dialog_window import DialogWindow
from core.safety.alarm import Alarms
from core.safety.answers import Answer, parse_gesture, parse_voice
from core.safety.arbiter import Arbiter
from core.settings import render, template, th
from core.text import seconds
from shared.contracts import PerceptionFrame, Position, SosReport, SosStatus, State, UiSpeech, to_wire

if TYPE_CHECKING:
    from core.engine import Engine

log = logging.getLogger("drivemate.core.sos")

SosChannel = Callable[[SosReport], str]
ACTIVE = ("alarm", "asking", "countdown", "sos_sent")
RULE = "sos"


class SosMachine:
    def __init__(self, engine: Engine, arbiter: Arbiter, alarms: Alarms, dialog: DialogWindow,
                 channels: dict[str, SosChannel] | None = None) -> None:
        self.engine, self.arbiter, self.alarms, self.dialog = engine, arbiter, alarms, dialog
        self.channels: dict[str, SosChannel] = dict(channels or {})
        self.ab: AbBaseline | None = None  # the A/B counter (B8) counts every microsleep alarm as a DriveMate alert
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.state = "normal"
        self.since: float | None = None
        self.alarm_started: float | None = None
        self.ask_at = self.ask_deadline = self.countdown_deadline = self.next_realarm = 0.0
        self.alert = ""
        self.armed = True
        self.last_report: SosReport | None = None
        self.consumed_at: float | None = None  # when an input last answered the SOS (not for the assistant then)

    # --- detection (fast path: every frame) ----------------------------------------------------------------------

    def condition(self, frame: PerceptionFrame) -> tuple[str, str] | None:
        """(alert, explanation) when the driver's state calls for the P1 alarm, else None."""
        speed = self.engine.state.trip.speed_kmh
        if speed < float(th("safety", "microsleep", "min_speed_kmh")):
            return None
        eyes, head = frame.driver.eyes, frame.driver.head
        if eyes.reliable and eyes.closed_ms >= float(th("safety", "microsleep", "closed_ms")):
            return "microsleep", render("explanations", "microsleep", s=seconds(eyes.closed_ms / 1000.0),
                                        speed_kmh=round(speed))
        if th("safety", "microsleep", "nodding_alarm") and head.nodding:
            return "nodding", render("explanations", "nodding", speed_kmh=round(speed))
        return None

    def on_frame(self, frame: PerceptionFrame, now: float) -> None:
        found = self.condition(frame)
        if found is None:
            self.armed = True
        elif self.state == "normal" and self.armed:
            self.armed = False
            self._alarm(found[0], found[1], frame.ts, now)
        if self.state in ACTIVE:
            if frame.driver.head.answer:
                self.answer(frame.driver.head.answer, "nod" if frame.driver.head.answer == "yes" else "shake", now)
            gesture = parse_gesture(frame.driver.gesture)
            if gesture:
                self.answer(gesture, "gesture", now)

    def on_speech(self, speech: UiSpeech, now: float) -> None:
        if self.state not in ACTIVE or not speech.final:
            return
        if not (speech.addressed or self.dialog.is_open(now)):
            return
        answer = parse_voice(speech.text)
        if answer:
            self.answer(answer, "voice", now)

    # --- transitions ---------------------------------------------------------------------------------------------

    def _alarm(self, alert: str, explanation: str, capture_ts: float | None, now: float) -> None:
        self.state, self.since, self.alarm_started, self.alert = "alarm", now, now, alert
        self.arbiter.raise_alert(RULE, "P1", alert, now)  # stops speech and music first
        self.alarms.send(now, alert, "P1", capture_ts=capture_ts or None, explanation=explanation)
        if self.ab is not None:
            self.ab.our_alert(now, alert)
        self.ask_at = now + float(th("sos", "ask_after_alarm_s"))

    def _ask(self, now: float) -> None:
        self.state, self.since = "asking", now
        clip_id = str(template("clips", "are_you_ok"))
        self.engine.say(clip_id, clips.clip_text(clip_id, "Ești bine?"), is_question=True, expects="yes_no",
                        prefix="sos")
        window = float(th("sos", "ask_clip_s")) + float(th("sos", "answer_window_s"))
        self.dialog.open(now, window, "driver", reason="sos")
        self.ask_deadline = now + window
        self.engine.log_event("are_you_ok", now, text="Ești bine?")

    def _countdown(self, now: float, why: str) -> None:
        self.state, self.since = "countdown", now
        self.arbiter.raise_alert(RULE, "P0", "unresponsive", now)
        countdown = float(th("sos", "countdown_s"))
        self.countdown_deadline = now + countdown
        driver, passenger = clips.person_names(self.engine.state)
        if passenger and self.engine.state.passenger.present:
            text = render("sos", "passenger_instructions", passenger_name=clips.display(passenger),
                          driver_name=clips.display(driver))
            self.engine.say(clips.passenger_instructions_clip(passenger, driver), text, to="passenger",
                            prefix="sos")
            self.next_realarm = now + float(th("sos", "instructions_clip_s"))
        else:
            self.next_realarm = now + float(th("sos", "realarm_s"))
        self.dialog.open(now, countdown, "driver", reason="sos")  # the driver can still cancel
        unresponsive = now - (self.alarm_started or now)
        self.engine.log_event("sos_countdown", now, explanation=render("explanations", "unresponsive",
                                                                      s=seconds(unresponsive)),
                              countdown_s=countdown, why=why, passenger=passenger)

    def _send(self, now: float) -> None:
        self.state, self.since = "sos_sent", now
        self.arbiter.raise_alert(RULE, "P0", "sos_sent", now)
        self.dialog.close(now)
        report = self.build_report(now)
        self.last_report = report
        results: dict[str, str] = {}
        for name, channel in self.channels.items():
            try:
                results[name] = channel(report)
            except Exception as exc:  # one broken channel must not stop the others (C9)
                log.exception("SOS channel %s failed", name)
                results[name] = f"error: {exc.__class__.__name__}"
        self.engine.log_event("sos_sent", now, text=report.text, report=to_wire(report), channels=results)

    def answer(self, value: Answer, channel: str, now: float) -> None:
        """A yes / no from any channel while the machine is active."""
        if self.state not in ACTIVE:
            return
        self.consumed_at = now
        if value == "yes":
            stage = self.state
            self._normal(now)
            clip_id = str(template("clips", "confirm_ok"))
            self.engine.say(clip_id, clips.clip_text(clip_id, "Ok."), prefix="sos")
            text = "Șoferul a răspuns după SOS." if stage == "sos_sent" else "Șoferul a răspuns."
            self.engine.log_event("sos_cancelled", now, channel=channel, text=text, stage=stage,
                                  latency_ms=round((now - (self.alarm_started or now)) * 1000.0, 1))
        elif self.state in ("alarm", "asking"):
            self._countdown(now, why=f"answer_no:{channel}")

    def _normal(self, now: float) -> None:
        self.state, self.since, self.alert = "normal", None, ""
        self.arbiter.clear(RULE)
        self.dialog.close(now)

    # --- timers (every tick) -------------------------------------------------------------------------------------

    def tick(self, state: State, now: float) -> None:
        if self.state == "alarm" and now >= self.ask_at:
            self._ask(now)
        elif self.state == "asking" and now >= self.ask_deadline:
            self._countdown(now, why="no_answer")
        elif self.state == "countdown":
            if now >= self.countdown_deadline:
                self._send(now)
            elif now >= self.next_realarm:
                self.alarms.send(now, "unresponsive", "P0")
                self.next_realarm = now + float(th("sos", "realarm_s"))
        left = max(0.0, self.countdown_deadline - now) if self.state == "countdown" else None
        state.safety.sos = SosStatus.model_validate(
            {"state": self.state, "since_ts": self.since, "countdown_s": round(left, 1) if left is not None else None}
        )

    # --- report --------------------------------------------------------------------------------------------------

    def build_report(self, now: float) -> SosReport:
        """The fixed SOS report (plan C: template, no LLM)."""
        state = self.engine.state
        driver, _ = clips.person_names(state)
        passenger = state.passenger
        passenger_state = "absent" if not passenger.present else "awake" if passenger.awake else "asleep"
        occupants_n = 1 + int(passenger.present) + sum(1 for o in state.occupants if o.seat == "rear")
        pos: Position = state.trip.pos
        fields = {
            "driver_name": clips.display(driver),
            "unresponsive_s": round(now - (self.alarm_started or now)),
            "occupants_n": occupants_n,
            "passenger_state_text": template("sos", "passenger_state", passenger_state),
            "maps_url": render("links", "maps", lat=pos.lat, lon=pos.lon),
            "time_hhmm": datetime.fromtimestamp(now).strftime("%H:%M"),
        }
        return SosReport.model_validate({
            "driver_name": fields["driver_name"], "unresponsive_s": fields["unresponsive_s"],
            "occupants_n": occupants_n, "passenger_state": passenger_state, "pos": pos.model_dump(),
            "maps_url": fields["maps_url"], "time_hhmm": fields["time_hhmm"], "ts": now,
            "text": render("sos", "sms", **fields),
        })
