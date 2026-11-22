"""The unresponsive driver (C4, C5, F6): normal -> alarm -> asking -> countdown -> sos_sent.

* **alarm** (P1): started by the drowsiness rule (``core/safety/drowsiness.py``) when the eyes have been shut
  ``safety.drowsiness.alarm_ms``, on the frame itself (target < 300 ms from the threshold to ``alarm_played``). The
  dialog window opens at once: a spoken "sunt bine" counts from the alarm on.
* **asking** (P1): "Ești bine?" once the alarm clip is over (``alarm_played`` + ``sos.alarm_clip_s`` +
  ``ask_after_alarm_s``). The answer window (``answer_window_s``) starts when the question ended (``speak_done``).
  No answer, but the eyes have been open ``reask_open_s``: asked once more ("Andrei, mă auzi?") instead of the
  countdown. A bare "nu" is unclear and asks again too.
* **countdown** (P0): no answer, or a clear no ("nu sunt bine", "ajutor", 👎): the passenger instructions by name,
  then ``sos.countdown_s``; the alarm is replayed every ``sos.realarm_s`` once the instructions are over.
* **sos_sent** (P0): the report from ``templates.yaml`` goes to every SOS channel. The dialog window STAYS open
  (``sent_window_s``, refreshed) and every ``sent_reask_s`` the driver is asked again how to cancel ("Andrei, dacă ești
  bine, spune «sunt bine» sau arată degetul mare."). Before 2026-11-22 the window was closed here: a spoken "sunt bine"
  without the wake word was ignored and P1 stopped looking for nods / thumbs up, so nothing could end the SOS and the
  car stayed at P0 (assistant silent) for good.

Any yes (voice, nod, 👍) cancels, even after the report ("Șoferul a răspuns după SOS."); the drowsiness rule then
proposes a break. A head shake is ignored here: a driver who just woke up shakes the head, and that is no "no".

Every timer has a fallback (the ``*_clip_s`` values) for a browser that does not report ``alarm_played`` or
``speak_done``: the browser can make a step later, never block it.

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
from core.safety.answers import SosAnswer, parse_gesture, parse_sos_voice
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


def _s(key: str) -> float:
    return float(th("sos", key))


class SosMachine:
    def __init__(self, engine: Engine, arbiter: Arbiter, alarms: Alarms, dialog: DialogWindow,
                 channels: dict[str, SosChannel] | None = None) -> None:
        self.engine, self.arbiter, self.alarms, self.dialog = engine, arbiter, alarms, dialog
        self.channels: dict[str, SosChannel] = dict(channels or {})
        self.ab: AbBaseline | None = None  # the A/B counter (B8) counts every alarm as a DriveMate alert
        self.eyes_open_s: Callable[[float], float] = lambda now: 0.0  # set by the drowsiness rule
        self.on_cancelled: list[Callable[[float], None]] = []  # e.g. the drowsiness rule proposes a break
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.state = "normal"
        self.since: float | None = None
        self.alarm_started: float | None = None
        self.ask_at = self.ask_deadline = self.countdown_deadline = self.next_realarm = 0.0
        self.alert = ""
        self.trigger: str | None = None
        self.reasked = False
        self.alarm_id: str | None = None
        self.question_id: str | None = None
        self.instructions_id: str | None = None
        self.next_sent_ask = 0.0  # sos_sent: when the driver is next asked to cancel
        self.last_report: SosReport | None = None
        self.consumed_at: float | None = None  # when an input last answered the SOS (not for the assistant then)

    # --- the start (called by the drowsiness rule on the frame that crossed the threshold) -----------------------

    def start(self, alert: str, explanation: str, capture_ts: float | None, now: float) -> bool:
        """Alarm now. Returns False when the machine is already running (one SOS at a time)."""
        if self.state != "normal":
            return False
        self.state, self.since, self.alarm_started, self.alert, self.trigger = "alarm", now, now, alert, alert
        self.reasked = False
        self.arbiter.raise_alert(RULE, "P1", alert, now)  # stops speech and music first
        self.alarm_id = self.alarms.send(now, alert, "P1", capture_ts=capture_ts or None, explanation=explanation)
        if self.ab is not None:
            self.ab.our_alert(now, alert)
        self.ask_at = now + self.alarms.last_clip_s + _s("ask_after_alarm_s")  # moved later by alarm_played
        self.dialog.open(now, self._window_s(), "driver", reason="sos")  # one window for the whole SOS
        return True

    def _window_s(self) -> float:
        """The dialog window covers every step (P1 restarts its nod counting when a window is opened again)."""
        return (self.alarms.last_clip_s + _s("ask_after_alarm_s") + _s("ask_clip_s") + _s("answer_window_s")
                + _s("reask_clip_s") + _s("answer_window_s") + _s("countdown_s") + 2.0)

    def _cover(self, until: float, now: float) -> None:
        """Keep the dialog window open until ``until`` (a late browser moved a step)."""
        if self.dialog.until is None or self.dialog.until < until + 1.0:
            self.dialog.open(now, until + 1.0 - now, "driver", reason="sos")

    # --- answers -------------------------------------------------------------------------------------------------

    def on_frame(self, frame: PerceptionFrame, now: float) -> None:
        if self.state not in ACTIVE:
            return
        if frame.driver.head.answer == "yes":
            self.answer("yes", "nod", now)  # a shake is ignored (see the module docstring)
        gesture = parse_gesture(frame.driver.gesture)
        if gesture:
            self.answer(gesture, "gesture", now)

    def on_speech(self, speech: UiSpeech, now: float) -> None:
        if self.state not in ACTIVE or not speech.final:
            return
        if not (speech.addressed or self.dialog.is_open(now)):
            return
        answer = parse_sos_voice(speech.text)
        if answer:
            self.answer(answer, "voice", now)

    def answer(self, value: SosAnswer, channel: str, now: float) -> None:
        """A yes / no / unclear from any channel while the machine is active."""
        if self.state not in ACTIVE:
            return
        self.consumed_at = now
        if value == "yes":
            stage, trigger = self.state, self.trigger
            self._normal(now)
            clip_id = str(template("clips", "confirm_ok"))
            self.engine.say(clip_id, clips.clip_text(clip_id, "Ok."), prefix="sos")
            self._passenger_wake(trigger, now)
            text = "Șoferul a răspuns după SOS." if stage == "sos_sent" else "Șoferul a răspuns."
            self.engine.log_event("sos_cancelled", now, channel=channel, text=text, stage=stage,
                                  latency_ms=round((now - (self.alarm_started or now)) * 1000.0, 1))
            for listener in self.on_cancelled:
                listener(now)
        elif value == "no":
            if self.state in ("alarm", "asking"):
                self._countdown(now, why=f"answer_no:{channel}")
        elif self.state in ("alarm", "asking") and not self.reasked:  # unclear: ask once more
            self._reask(now, why=f"unclear:{channel}")

    def _passenger_wake(self, trigger: str | None, now: float) -> None:
        """After a microsleep / a falling head: the awake front passenger is asked to talk with the driver."""
        state = self.engine.state
        if trigger not in ("microsleep", "nodding") or not bool(th("sos", "passenger_wake")):
            return
        if not (state.passenger.present and state.passenger.awake):
            return
        driver, passenger = clips.person_names(state)
        if not passenger:
            return
        text = render("sos", "passenger_wake", passenger_name=clips.display(passenger),
                      driver_name=clips.display(driver))
        # important, not critical: it waits for "Ok." and goes before the break question (same priority, in order)
        self.engine.say(clips.passenger_wake_clip(passenger, driver), text, to="passenger", prefix="sos",
                        priority="important")
        self.engine.log_event("passenger_wake", now, text=text, passenger=passenger)

    # --- browser feedback ----------------------------------------------------------------------------------------

    def on_alarm_played(self, alarm_id: str, now: float) -> None:
        """The alarm clip started now: "Ești bine?" comes after it, not over it."""
        if self.state == "alarm" and alarm_id == self.alarm_id:
            self.ask_at = max(self.ask_at, now + self.alarms.last_clip_s + _s("ask_after_alarm_s"))
            self._cover(self.ask_at + _s("ask_clip_s") + _s("answer_window_s"), now)

    def on_speak_done(self, utterance_id: str, now: float) -> None:
        if self.state == "asking" and utterance_id == self.question_id:
            self.ask_deadline = now + _s("answer_window_s")  # the answer window starts when the question ended
            self._cover(self.ask_deadline, now)
        elif self.state == "countdown" and utterance_id == self.instructions_id:
            self.next_realarm = min(self.next_realarm, now + _s("instructions_pause_s"))

    # --- transitions ---------------------------------------------------------------------------------------------

    def _ask(self, now: float) -> None:
        self.state, self.since = "asking", now
        clip_id = str(template("clips", "are_you_ok"))
        self.question_id = self.engine.say(clip_id, clips.clip_text(clip_id, "Ești bine?"), is_question=True,
                                           expects="yes_no", prefix="sos")
        self.ask_deadline = now + _s("ask_clip_s") + _s("answer_window_s")  # until speak_done says otherwise
        self._cover(self.ask_deadline, now)
        self.engine.log_event("are_you_ok", now, text="Ești bine?")

    def _reask(self, now: float, why: str) -> None:
        self.state, self.since, self.reasked = "asking", now, True
        driver, _ = clips.person_names(self.engine.state)
        text = render("sos", "reask", driver_name=clips.display(driver))
        self.question_id = self.engine.say(None, text, is_question=True, expects="yes_no", prefix="sos")
        self.ask_deadline = now + _s("reask_clip_s") + _s("answer_window_s")
        self._cover(self.ask_deadline, now)
        self.engine.log_event("sos_reask", now, text=text, why=why, open_s=round(self.eyes_open_s(now), 1))

    def _countdown(self, now: float, why: str) -> None:
        self.state, self.since = "countdown", now
        self.arbiter.raise_alert(RULE, "P0", "unresponsive", now)
        countdown = _s("countdown_s")
        self.countdown_deadline = now + countdown
        driver, passenger = clips.person_names(self.engine.state)
        self.instructions_id = None
        if passenger and self.engine.state.passenger.present:
            text = render("sos", "passenger_instructions", passenger_name=clips.display(passenger),
                          driver_name=clips.display(driver))
            self.instructions_id = self.engine.say(clips.passenger_instructions_clip(passenger, driver), text,
                                                   to="passenger", prefix="sos")
            self.next_realarm = now + _s("instructions_clip_s")  # earlier when their speak_done comes
        else:
            self.next_realarm = now + _s("realarm_s")
        self._cover(self.countdown_deadline, now)  # the driver can still cancel
        unresponsive = now - (self.alarm_started or now)
        self.engine.log_event("sos_countdown", now, explanation=render("explanations", "unresponsive",
                                                                      s=seconds(unresponsive)),
                              countdown_s=countdown, why=why, passenger=passenger)

    def _send(self, now: float) -> None:
        self.state, self.since = "sos_sent", now
        self.arbiter.raise_alert(RULE, "P0", "sos_sent", now)
        # the driver can still answer: voice without the wake word, a nod or a thumbs up (P1 looks for them only in
        # an open window)
        self.dialog.open(now, _s("sent_window_s"), "driver", reason="sos")
        self.next_sent_ask = now + _s("sent_reask_s")
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

    def _normal(self, now: float) -> None:
        self.state, self.since, self.alert, self.trigger = "normal", None, "", None
        self.arbiter.clear(RULE)
        self.dialog.close(now)

    # --- timers (every tick) -------------------------------------------------------------------------------------

    def tick(self, state: State, now: float) -> None:
        if self.state == "alarm" and now >= self.ask_at:
            self._ask(now)
        elif self.state == "asking" and now >= self.ask_deadline:
            if not self.reasked and self.eyes_open_s(now) >= _s("reask_open_s"):
                self._reask(now, why="eyes_open_no_answer")
            else:
                self._countdown(now, why="no_answer")
        elif self.state == "countdown":
            if now >= self.countdown_deadline:
                self._send(now)
            elif now >= self.next_realarm:
                self.alarms.send(now, "unresponsive", "P0")
                self.next_realarm = now + _s("realarm_s")
        elif self.state == "sos_sent":
            if now >= self.next_sent_ask:
                self._sent_ask(now)
            if not self.dialog.is_open(now) or (self.dialog.until or 0.0) - now < 2.0:
                self.dialog.open(now, _s("sent_window_s"), "driver", reason="sos")  # never let it close
        left = max(0.0, self.countdown_deadline - now) if self.state == "countdown" else None
        state.safety.sos = SosStatus.model_validate({
            "state": self.state, "since_ts": self.since, "countdown_s": round(left, 1) if left is not None else None,
            "trigger": self.trigger, "reasked": self.reasked,
        })

    def _sent_ask(self, now: float) -> None:
        """SOS sent and no answer yet: tell the driver how to cancel it, by name."""
        driver, _ = clips.person_names(self.engine.state)
        text = render("sos", "sent_ask", driver_name=clips.display(driver))
        self.question_id = self.engine.say(None, text, is_question=True, expects="yes_no", prefix="sos")
        self.next_sent_ask = now + _s("sent_reask_s")
        self.engine.log_event("sos_sent_ask", now, text=text)

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
