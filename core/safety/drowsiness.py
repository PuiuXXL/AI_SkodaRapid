"""C3, C4: eyes closed longer than a blink. P2's own timer over P1's ``driver.eyes.closed_ms`` (v2.2).

P1 measures each closure (``closed_ms`` from the interpolated drop, blinks <= 400 ms filtered, a reopen needs two open
frames) and holds it over a face dropout of 200 ms only. P2 keeps its own timer, ``safety.drowsiness.eyes_shut_ms``,
and turns it into stages (``thresholds.yaml``, ``safety.drowsiness``):

* below ``checkin_min_ms``: a long blink, nothing happens (PERCLOS and the blink duration already feed F);
* ``checkin_min_ms`` reached and the eyes open again: after ``checkin.after_open_s`` with the eyes open, the check-in
  question "Andrei, ai închis ochii câteva clipe. Facem o pauză?" (at most once per ``checkin.cooldown_min``);
* still closed at ``warn_ms``: the discrete signal (``visual_cue``) and a P2 alert (voice and music stop, LLM silent);
* still closed at ``alarm_ms``: the alarm with the driver's name, and the SOS machine takes over (``sos.py``).

The timer goes on while the face is lost or the eyes are unreliable inside a real closure (at least ``hold_from_ms``,
or with ``driver.head.nodding``), for up to ``face_lost_hold_ms``: a falling head leaves the face tracker, and with
the head down the shut lids often read SQUINT. Eyes P1 reports ``OPEN`` always end the closure.

**A head that falls with no closed eyes seen** (``safety.drowsiness.head_fall``, 2026-11-22): the face is lost right
after the head pitch dropped fast (``drop_deg`` within ``window_s``) or while it was far below the driver's own upright
pitch (``down_deg``): a closure starts at the last face frame and goes on while the face stays lost, so the alarm and
the SOS come at ``alarm_ms`` as for a microsleep (alert ``head_down``). Live test: the head let down with the eyes open
gave "Nu te mai văd. Monitorizarea e întreruptă." instead, because no closure had started before the face was lost.

The check-in is a rule, not the LLM: fixed texts from ``templates.yaml`` (``drowsiness``), answered by voice, nod or
thumbs up / down. Yes = the nearest stop ahead (``core.reminders.pick_stop``). It is said even while the assistant is
silenced after a refusal (a safety rule; the cooldown keeps it rare), never over an alert or another question. After
an SOS cancelled by a yes it is asked once more ("Andrei, facem o pauză?"), whatever the cooldown.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core import clips
from core.safety.answers import Answer, parse_gesture, parse_voice
from core.settings import render, template, th
from core.text import seconds
from shared.contracts import LLM_VETO_LEVELS, Drowsiness, PerceptionFrame, State, UiSpeech

if TYPE_CHECKING:
    from core.dialog_window import DialogWindow
    from core.engine import Engine
    from core.safety.arbiter import Arbiter
    from core.safety.sos import SosMachine

RULE = "drowsiness"


def _cfg(key: str) -> float:
    return float(th("safety", "drowsiness", key))


def _fall(key: str) -> float:
    return float(th("safety", "drowsiness", "head_fall", key))


def _checkin(key: str) -> float:
    return float(th("safety", "checkin", key))


def km_text(value: float | None) -> str:
    """Distance as spoken: "12" from 10 km on, "4,5" below."""
    if value is None:
        return "?"
    return f"{round(value)}" if value >= 10 else seconds(value)


@dataclass
class Closure:
    since: float  # when the eyes closed, on core's clock (now - closed_ms at the first frame)
    last_closed: float  # last frame where P1 saw them closed
    nodding: bool = False  # the head fell during this closure
    head_fall: bool = False  # started by a falling head that lost the face (no closed eyes seen)
    warned: bool = False
    alarmed: bool = False


@dataclass
class DueCheckin:
    reason: str  # "closure" or "after_sos"
    created: float
    not_before: float


class DrowsinessRule:
    def __init__(self, engine: Engine, arbiter: Arbiter, sos: SosMachine, dialog: DialogWindow) -> None:
        self.engine, self.arbiter, self.sos, self.dialog = engine, arbiter, sos, dialog
        sos.eyes_open_s = self.eyes_open_s  # the second "Ești bine?" needs the eyes open
        sos.on_cancelled.append(self.after_sos)
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.closure: Closure | None = None
        self.open_since: float | None = None  # eyes seen open since (blinks do not reset it)
        self.unseen_since: float | None = None  # eyes not measurable since (no face, unreliable)
        self.last_frame: float | None = None
        self.episodes: deque[float] = deque()  # end times of the closures >= checkin_min_ms
        self.last_episode_ms: float | None = None
        self.alarm_alert: str | None = None  # microsleep / nodding: the last SOS this rule started
        self.alarm_speed_kmh: float | None = None  # the speed at that alarm (for the check-in text)
        self.last_episode_ts: float | None = None
        self.due: DueCheckin | None = None
        self.last_checkin: float | None = None
        self.pending_until: float | None = None  # the check-in question is waiting for its answer
        self.last_inputs: tuple[Any, Any] = (None, None)
        self.pitches: deque[tuple[float, float]] = deque()  # (t, head pitch) of the frames with a face
        self.fall_checked = False  # the current loss of the face was already checked for a falling head

    # --- the timer (fast path: every frame) ----------------------------------------------------------------------

    def shut_ms(self, now: float) -> float:
        return 0.0 if self.closure is None else max(0.0, (now - self.closure.since) * 1000.0)

    def eyes_open_s(self, now: float) -> float:
        """How long the eyes have been seen open. Blinks and dropouts up to ``blink_max_ms`` do not reset it; a longer
        closure, an unknown eye state or a lost face does (0 then)."""
        blink_ms = _cfg("blink_max_ms")
        if self.open_since is None or self.shut_ms(now) > blink_ms:
            return 0.0
        if self.unseen_since is not None and (now - self.unseen_since) * 1000.0 > blink_ms:
            return 0.0
        return now - self.open_since

    def on_frame(self, frame: PerceptionFrame, now: float) -> None:
        self.last_frame = now
        eyes, head = frame.driver.eyes, frame.driver.head
        closed = eyes.reliable and (eyes.closed_ms > 0 or eyes.state == "CLOSED")
        face = head.pitch is not None
        self._track_pitch(head.pitch, now)
        if not face and self.closure is None and not self.fall_checked:
            self.fall_checked = True  # once per loss of the face
            self._head_fall(now)
        closure = self.closure
        if closure is not None and closure.head_fall and not face:
            closure.last_closed = now  # the face is still gone: the "closure" goes on
        if closed:
            start = now - eyes.closed_ms / 1000.0
            if closure is None:
                self.closure = closure = Closure(since=start, last_closed=now)
            else:
                closure.since, closure.last_closed = min(closure.since, start), now
            closure.nodding = closure.nodding or head.nodding
            self.unseen_since = None
        elif closure is not None:
            closure.nodding = closure.nodding or head.nodding
            if not self._holds(closure, frame, now):
                self._end(closure, now, opened=eyes.reliable)
        if self.closure is None:
            if eyes.reliable:
                self.unseen_since = None
                self.open_since = self.open_since if self.open_since is not None else now
            else:  # no face / eyes not measurable: "open" ends after a blink's length of this
                self.unseen_since = self.unseen_since if self.unseen_since is not None else now
                if (now - self.unseen_since) * 1000.0 > _cfg("blink_max_ms"):
                    self.open_since = None
        self._escalate(frame, now)
        self._answer_from_frame(frame, now)

    def _track_pitch(self, pitch: float | None, now: float) -> None:
        if pitch is None:
            return
        self.fall_checked = False
        self.pitches.append((now, float(pitch)))
        keep = _fall("baseline_s") + _fall("window_s")
        while self.pitches and self.pitches[0][0] < now - keep:
            self.pitches.popleft()

    def _head_fall(self, now: float) -> None:
        """The face just got lost: did the head fall (fast drop, or far below the driver's upright pitch)?"""
        if not self.pitches or self.engine.state.trip.speed_kmh < _fall("min_speed_kmh"):
            return
        last_t, last_pitch = self.pitches[-1]
        if now - last_t > _fall("max_gap_s"):
            return  # the face has been gone for a while: not a fall seen now
        window = _fall("window_s")
        recent = [p for t, p in self.pitches if t >= last_t - window]
        older = [p for t, p in self.pitches if t < last_t - window]
        drop = max(recent) - last_pitch
        upright = statistics.median(older) if len(older) >= int(_fall("min_baseline_frames")) else None
        below = (upright - last_pitch) if upright is not None else 0.0
        if drop < _fall("drop_deg") and below < _fall("down_deg"):
            return
        self.closure = Closure(since=last_t, last_closed=now, nodding=True, head_fall=True)
        self.unseen_since = None
        self.engine.log_event("head_fall", now, text="Capul a coborât și fața nu se mai vede.",
                              drop_deg=round(drop, 1), below_upright_deg=round(below, 1),
                              last_pitch=round(last_pitch, 1))

    def _holds(self, closure: Closure, frame: PerceptionFrame, now: float) -> bool:
        """The closure goes on although P1 does not see closed eyes on this frame."""
        eyes = frame.driver.eyes
        if eyes.reliable and (eyes.state == "OPEN" or not closure.nodding):
            return False  # P1 sees the eyes open (after its own reopen hysteresis)
        shut_ms = (closure.last_closed - closure.since) * 1000.0
        if not closure.nodding and shut_ms < _cfg("hold_from_ms"):
            return False  # a blink followed by a head turn is not a closure
        return (now - closure.last_closed) * 1000.0 <= _cfg("face_lost_hold_ms")

    def _escalate(self, frame: PerceptionFrame, now: float) -> None:
        closure = self.closure
        if closure is None or closure.alarmed:
            return
        speed = self.engine.state.trip.speed_kmh
        if speed < _cfg("min_speed_kmh"):
            return
        shut_ms = self.shut_ms(now)
        if shut_ms >= _cfg("alarm_ms"):
            closure.alarmed = True
            self.arbiter.clear(RULE)  # the SOS takes over at P1
            self.pending_until, self.due = None, None
            if closure.head_fall:
                alert, explanation = "head_down", render("explanations", "head_down", speed_kmh=round(speed))
                self.alarm_alert = "head_down"
            elif closure.nodding:
                alert, explanation = "nodding", render("explanations", "nodding", speed_kmh=round(speed))
                self.alarm_alert = "nodding"
            else:
                alert = "microsleep"
                explanation = render("explanations", "microsleep", s=seconds(shut_ms / 1000.0),
                                     speed_kmh=round(speed))
                self.alarm_alert = "microsleep"
            self.alarm_speed_kmh = speed
            self.sos.start(alert, explanation, frame.ts, now)
        elif shut_ms >= _cfg("warn_ms") and not closure.warned and self.sos.state == "normal":
            closure.warned = True
            explanation = render("explanations", "microsleep", s=seconds(shut_ms / 1000.0), speed_kmh=round(speed))
            self.arbiter.raise_alert(RULE, "P2", "eyes_closing", now)
            self.engine.log_event("visual_cue", now, explanation=explanation, alert="eyes_closing", level="P2")
            self.engine.log_event("drowsy_warning", now, explanation=explanation, closed_ms=round(shut_ms))

    def _end(self, closure: Closure, now: float, *, opened: bool) -> None:
        """The closure is over: the eyes opened, or the face stayed lost longer than the hold."""
        self.closure = None
        self.arbiter.clear(RULE)
        duration_ms = ((now if opened else closure.last_closed) - closure.since) * 1000.0
        if not opened:
            self.open_since = None
        elif duration_ms > _cfg("blink_max_ms"):
            self.open_since = now  # a real closure: the eyes are open from now on (a blink keeps the old time)
        if not opened or duration_ms < _cfg("checkin_min_ms"):
            return  # a long blink, or no face to tell (C7 announces a lost face)
        self.episodes.append(now)
        self.last_episode_ms, self.last_episode_ts = round(duration_ms), now
        self.engine.log_event("eyes_reopened", now, text=f"Ochii redeschiși după {seconds(duration_ms / 1000.0)} s.",
                              closed_ms=round(duration_ms), episodes_10min=self._episodes(now),
                              alarmed=closure.alarmed)
        if not closure.alarmed:
            self.schedule("closure", now)

    def _episodes(self, now: float) -> int:
        window_s = _cfg("episodes_window_min") * 60.0
        while self.episodes and now - self.episodes[0] > window_s:
            self.episodes.popleft()
        return len(self.episodes)

    # --- the check-in question -----------------------------------------------------------------------------------

    def schedule(self, reason: str, now: float) -> None:
        """Ask "Facem o pauză?" once the eyes have been open ``checkin.after_open_s``."""
        cooldown_s = _checkin("cooldown_min") * 60.0
        if reason == "closure" and self.last_checkin is not None and now - self.last_checkin < cooldown_s:
            self.engine.log_event("drowsy_check_skipped", now, text="Fără întrebare: s-a întrebat de curând.",
                                  reason="cooldown", last_checkin_ts=self.last_checkin)
            return
        not_before = now + (_checkin("after_sos_s") if reason == "after_sos" else 0.0)
        self.due = DueCheckin(reason, now, not_before)

    def after_sos(self, now: float) -> None:
        """The driver answered "Ești bine?": propose the break as well (after the "Ok." clip)."""
        self.schedule("after_sos", now)

    def tick(self, state: State, now: float) -> None:
        closure = self.closure
        stale_s = _cfg("face_lost_hold_ms") / 1000.0
        if closure is not None and self.last_frame is not None and now - self.last_frame > stale_s:
            self._end(closure, now, opened=False)  # P1 stopped sending frames: C7 takes over
        if self.pending_until is not None and now > self.pending_until:
            self.pending_until = None
            self.engine.log_event("drowsy_check_unanswered", now, text="Fără răspuns la întrebarea despre pauză.")
        self._maybe_ask(state, now)
        closure = self.closure
        stage = "none"
        if closure is not None:
            if closure.alarmed:
                stage = "alarm"
            elif closure.warned:
                stage = "warning"
            elif self.shut_ms(now) >= _cfg("checkin_min_ms"):
                stage = "closed"
        state.safety.drowsiness = Drowsiness(
            stage=stage, eyes_shut_ms=round(self.shut_ms(now)), episodes_10min=self._episodes(now),
            last_episode_ms=self.last_episode_ms, last_episode_ts=self.last_episode_ts,
            last_checkin_ts=self.last_checkin,
        )

    def _maybe_ask(self, state: State, now: float) -> None:
        due = self.due
        if due is None:
            return
        if now - due.created > _checkin("max_wait_s"):
            self.due = None
            self.engine.log_event("drowsy_check_skipped", now, text="Întrebarea despre pauză a expirat.",
                                  reason="expired", for_reason=due.reason)
            return
        busy = (self.pending_until is not None or self.sos.state != "normal" or now < due.not_before
                or (state.safety.level or "P4") in LLM_VETO_LEVELS or self.dialog.is_open(now))
        if busy or self.eyes_open_s(now) < _checkin("after_open_s"):
            return
        self.due = None
        driver, _ = clips.person_names(state)
        text = self._checkin_text(due.reason, clips.display(driver), state)
        self.engine.say(None, text, is_question=True, expects="yes_no", prefix="drw")
        window_s = _checkin("window_s")
        self.dialog.open(now, window_s, "driver", reason="drowsy_check")
        self.pending_until = now + window_s
        self.last_checkin = now
        self.engine.log_event("drowsy_check", now, text=text, reason=due.reason,
                              episodes_10min=self._episodes(now), last_episode_ms=self.last_episode_ms)

    def _checkin_text(self, reason: str, name: str, state: State) -> str:
        """The check-in question. After an SOS: what happened (seconds, speed) and the stop ahead, by name."""
        if reason == "closure":
            return render("drowsiness", "checkin", driver_name=name)
        from core.reminders import pick_stop  # here: core.reminders imports core.safety.answers

        speed = self.alarm_speed_kmh or state.trip.speed_kmh
        if speed < _cfg("min_speed_kmh"):
            return render("drowsiness", "checkin_after_sos", driver_name=name)
        nodding = self.alarm_alert in ("nodding", "head_down")
        if not nodding and not self.last_episode_ms:
            return render("drowsiness", "checkin_after_sos", driver_name=name)
        fields: dict[str, Any] = {"driver_name": name, "speed_kmh": round(speed)}
        if not nodding:
            fields["s"] = seconds((self.last_episode_ms or 0) / 1000.0)
        stop = pick_stop(state)
        key = "checkin_after_sos_nodding" if nodding else "checkin_after_sos_context"
        if stop is not None:
            key = "checkin_after_sos_nodding_stop" if nodding else "checkin_after_sos_stop"
            fields.update(poi_name=stop["poi_name"], dist_km=km_text(stop.get("dist_km")))
        return render("drowsiness", key, **fields)

    # --- the answer ----------------------------------------------------------------------------------------------

    def on_browser(self, message: Any, now: float) -> None:
        if self.pending_until is None or not isinstance(message, UiSpeech) or not message.final:
            return
        if self.sos.state != "normal" or not (message.addressed or self.dialog.is_open(now)):
            return
        answer = parse_voice(message.text)
        if answer is not None:
            self._resolve(answer, "voice", now)

    def _answer_from_frame(self, frame: PerceptionFrame, now: float) -> None:
        current = (frame.driver.head.answer, frame.driver.gesture)
        new = [value for value, before in zip(current, self.last_inputs, strict=True) if value and value != before]
        self.last_inputs = current
        if self.pending_until is None or not new or self.sos.state != "normal":
            return
        if current[0] in new and current[0] in ("yes", "no"):
            self._resolve(current[0], "nod" if current[0] == "yes" else "shake", now)  # type: ignore[arg-type]
        elif (gesture := parse_gesture(current[1])) is not None:
            self._resolve(gesture, "gesture", now)

    def _resolve(self, answer: Answer, channel: str, now: float) -> None:
        from core.reminders import pick_stop  # here: core.reminders imports core.safety.answers

        self.engine.input_consumed_at = now  # the assistant must not take this answer as a new request
        self.pending_until = None
        self.dialog.close(now)
        state = self.engine.state
        if answer == "yes":
            stop = pick_stop(state)
            if stop is not None:
                text = render("drowsiness", "break_stop", poi_name=stop["poi_name"],
                              dist_km=km_text(stop.get("dist_km")))
            else:
                text = str(template("drowsiness", "break_no_stop"))
            self.engine.say(None, text, prefix="drw")
            state.scorecard.suggestions_accepted += 1
            self.engine.log_event("break_accepted", now, channel=channel, text=text,
                                  poi_id=stop["poi_id"] if stop else None, poi_name=stop["poi_name"] if stop else None)
        else:
            text = str(template("drowsiness", "declined"))
            self.engine.say(None, text, prefix="drw")
            state.scorecard.suggestions_rejected += 1
            self.engine.log_event("break_declined", now, channel=channel, text=text)
