"""C2: escalation for a critical distraction (P2): discrete signal -> voice -> alarm.

A distraction is critical when, above ``safety.distraction.min_speed_kmh``:

* **off_road**: ``driver.gaze.off_road_ms`` reaches ``off_road_ms`` (``off_road_ms_high_speed`` from
  ``high_speed_kmh``). P1 already keeps short mirror glances out of ``off_road_ms`` and freezes it on ``unknown``;
  an ``unknown`` zone or a low gaze confidence never alerts;
* **phone**: ``driver.phone.in_use`` for ``phone_min_ms`` (the detector; the lap pattern only from
  ``lap_pattern_min_conf``).

One episode, while the condition holds: at once the ``visual_cue`` event (the dashboard lights up) and a P2 alert
(the LLM is silent); after ``escalation.voice_after_ms`` a fixed sentence with the driver's name ("Andrei, fii atent
la drum, te rog." / "Andrei, lasă telefonul, ți-l citesc eu." when a message is waiting); after ``alarm_after_ms`` the
alarm. A distraction never starts the SOS: the driver is awake.

**Cue vs. voice stage** (``escalation.cue_pauses_voice``): during the discrete cue the assistant's voice only
**pauses** (like a mirror check, D4) and resumes ("...cum ziceam") when the gaze is back before the spoken warning; the
voice and the music are stopped at the spoken stage. Before 2026-11-22 the cue itself stopped everything, so a 1.8 s
glance cut the assistant mid-sentence and dropped its question (docs/eval/alerts-conversation-baseline-2026-11-22.md).
The same sentence is not repeated within ``cooldown_s``. Nothing is said over a more critical alert (the SOS).
When the episode ends, ``distraction_end`` logs how long the driver needed to come back (the visual reaction, B1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core import clips
from core.ab_baseline import AbBaseline
from core.safety.alarm import Alarms
from core.safety.arbiter import Arbiter
from core.settings import render, template, th
from core.text import seconds
from shared.contracts import State

if TYPE_CHECKING:
    from core.engine import Engine

RULE = "distraction"
#: Alert -> (template text key, clip key) of the voice stage.
VOICE: dict[str, tuple[str, str]] = {
    "off_road": ("off_road", "eyes_on_road"),
    "phone": ("phone", "phone_down"),
    "phone_message": ("phone_message", "phone_read_for_you"),
}


@dataclass
class Episode:
    alert: str
    started: float
    stage: int = 1  # 1 visual cue, 2 voice, 3 alarm
    explanation: str = ""  # the latest one ("Telefon în mână 4,2 s la 100 km/h."), for alert_explain


class DistractionRule:
    def __init__(self, engine: Engine, arbiter: Arbiter, alarms: Alarms, ab: AbBaseline) -> None:
        self.engine, self.arbiter, self.alarms, self.ab = engine, arbiter, alarms, ab
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.episode: Episode | None = None
        self.phone_since: float | None = None
        self.last_voice: dict[str, float] = {}
        self.voices: dict[str, int] = {}  # warnings said per key (the variants are used in turn)
        self.episodes = 0

    def condition(self, state: State, now: float) -> tuple[str, str] | None:
        """(alert, explanation) when there is a critical distraction now, else None."""
        speed = state.trip.speed_kmh
        driver = state.driver
        phone = driver.phone
        phone_seen = phone.in_use and (
            phone.source == "detector"
            or (phone.source == "lap_pattern" and phone.conf >= float(th("safety", "distraction",
                                                                         "lap_pattern_min_conf"))))
        self.phone_since = (self.phone_since or now) if phone_seen else None
        if speed < float(th("safety", "distraction", "min_speed_kmh")) or not state.safety.monitoring_ok:
            return None
        if self.phone_since is not None:
            held = now - self.phone_since
            if held * 1000.0 >= float(th("safety", "distraction", "phone_min_ms")):
                return "phone", render("explanations", "phone", s=seconds(held), speed_kmh=round(speed))
        gaze = driver.gaze
        if gaze.zone == "unknown" or gaze.conf < float(th("safety", "min_gaze_conf")):
            return None
        high = speed >= float(th("safety", "distraction", "high_speed_kmh"))
        limit = float(th("safety", "distraction", "off_road_ms_high_speed" if high else "off_road_ms"))
        if gaze.off_road_ms >= limit:
            zones = template("zones")
            zone_text = zones.get(gaze.zone, zones["away"])
            return "off_road", render("explanations", "off_road", zone_text=zone_text,
                                      s=seconds(gaze.off_road_ms / 1000.0), speed_kmh=round(speed))
        return None

    def tick(self, state: State, now: float) -> None:
        found = self.condition(state, now)
        episode = self.episode
        if found is None:
            if episode is not None:
                self._end(episode, now)
            return
        alert, explanation = found
        if episode is None or episode.alert != alert:
            if episode is not None:
                self._end(episode, now)
            episode = self._start(alert, explanation, now)
        episode.explanation = explanation
        elapsed_ms = (now - episode.started) * 1000.0
        if episode.stage == 1 and elapsed_ms >= float(th("safety", "escalation", "voice_after_ms")):
            episode.stage = 2
            if self._pauses() and not self.arbiter.outranks("P2", RULE):
                self.arbiter.interrupt(RULE)  # the spoken stage: the paused assistant and the music stop now
            self._voice(state, alert, explanation, now)
        if episode.stage == 2 and elapsed_ms >= float(th("safety", "escalation", "alarm_after_ms")):
            episode.stage = 3
            if not self.arbiter.outranks("P2", RULE):
                self.alarms.send(now, alert, "P2", explanation=explanation)

    @staticmethod
    def _pauses() -> bool:
        return bool(th("safety", "escalation", "cue_pauses_voice"))

    def _start(self, alert: str, explanation: str, now: float) -> Episode:
        self.episode = Episode(alert, now)
        self.episodes += 1
        pauses = self._pauses()
        self.arbiter.raise_alert(RULE, "P2", alert, now, interrupt=not pauses)
        assistant = self.engine.assistant
        if pauses and assistant is not None and not self.arbiter.outranks("P2", RULE):
            assistant.hold_voice(now, alert)
        self.ab.our_alert(now, alert)
        self.engine.log_event("visual_cue", now, explanation=explanation, alert=alert, level="P2")
        return self.episode

    def _voice(self, state: State, alert: str, explanation: str, now: float) -> None:
        if self.arbiter.outranks("P2", RULE):
            return
        waiting = any(m.state in ("pending", "deferred") for m in state.messages)
        key = "phone_message" if alert == "phone" and waiting else alert
        last = self.last_voice.get(key, float("-inf"))
        if now - last < float(th("safety", "escalation", "cooldown_s")):
            return
        self.last_voice[key] = now
        text_key, clip_key = VOICE[key]
        driver, _ = clips.person_names(state)
        name = clips.display(driver)
        repeat = now - last <= float(th("safety", "escalation", "repeat_window_min")) * 60.0
        if repeat:
            # the same warning again soon: firmer, with the next step (no pre-generated clip: TTS)
            text, clip_id = render("escalation_repeat", text_key, driver_name=name), None
        else:
            # the first one as before (it has a clip), then the other ways of saying it, in turn
            count = self.voices.get(key, 0)
            options = [str(template("escalation", text_key))] + list(template("escalation_variants", text_key) or [])
            chosen = options[count % len(options)]
            text = chosen.format(driver_name=name)
            clip_id = str(template("clips", clip_key)) if count % len(options) == 0 else None
        self.voices[key] = self.voices.get(key, 0) + 1
        self.engine.say(clip_id, text, prefix="dis")
        self.engine.log_event("alert", now, text=text, explanation=explanation, alert=alert, level="P2")

    def _end(self, episode: Episode, now: float) -> None:
        self.episode = None
        self.arbiter.clear(RULE)
        assistant = self.engine.assistant
        if assistant is not None:
            assistant.release_voice(now)  # back on the road before the spoken stage: "...cum ziceam"
            if episode.stage >= 3:  # it came to the alarm: the assistant says what happened, calmly (D5)
                assistant.explain_alert(now, alert=episode.alert, explanation=episode.explanation)
        text = "Privirea a revenit pe drum." if episode.alert == "off_road" else "Telefonul a fost lăsat."
        self.engine.log_event("distraction_end", now, alert=episode.alert, stage=episode.stage,
                              latency_ms=round((now - episode.started) * 1000.0, 1), text=text)
