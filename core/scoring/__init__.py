"""Scores (B): reaction, fatigue F, disengagement D, attention, risk, conversation, blind meters, the cause of the
distraction (B4, ``core/cause.py``) and the effect of the interventions (D6, ``core/intervention.py``).

:class:`Scores` updates ``state.assessment``, ``state.driver.reaction``, ``state.conversation`` and ``state.blind_m``
on every tick, after the safety rules. Inputs besides the state: the questions and voice onsets from the browser
(verbal reaction), nods and gestures from P1 (gesture reaction), the off-road episodes of the distraction rule
(visual reaction).

When F reaches ``fatigue.high`` (or D ``disengagement.high``) the assistant gets ``fatigue_high``
(``disengagement_high``): the KSS conversation, or the music. Once per crossing, again only after the score fell
under ``low`` (hysteresis), never while the assistant is silenced after a refusal (C10: these are its initiatives).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.cause import CauseDetector
from core.intervention import InterventionTracker
from core.scoring.attention import AttentionScore, BlindMeters, ConversationDetector, risk_level
from core.scoring.disengagement import DisengagementScore
from core.scoring.fatigue import FatigueScore
from core.scoring.reaction import ReactionTracker
from core.settings import render, th
from shared.contracts import PerceptionFrame, State, UiSpeakDone, UiSpeech, UiSpeechOnset

if TYPE_CHECKING:
    from core.engine import Engine

__all__ = ["Scores"]


def _two_decimals(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


class Scores:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        engine.scores = self
        self.reaction = ReactionTracker()
        self.fatigue = FatigueScore()
        self.disengagement = DisengagementScore()
        self.attention = AttentionScore()
        self.blind = BlindMeters()
        self.conversation = ConversationDetector()
        self.cause = CauseDetector()
        self.intervention = InterventionTracker(engine, self.cause)
        self.armed = {"fatigue": True, "disengagement": True}
        self.last_inputs: tuple[Any, Any] = (None, None)
        engine.add_browser_listener(self.on_browser)
        engine.add_frame_listener(self.on_frame)
        engine.add_tick_listener(self.on_tick)
        engine.add_reset_listener(self.reset)

    def reset(self, now: float) -> None:
        for part in (self.reaction, self.fatigue, self.disengagement, self.attention, self.blind, self.conversation,
                     self.cause, self.intervention):
            part.reset()
        self.armed = {"fatigue": True, "disengagement": True}

    # --- inputs --------------------------------------------------------------------------------------------------

    def on_browser(self, message: Any, now: float) -> None:
        if isinstance(message, UiSpeakDone) and message.is_question and not message.interrupted:
            self.reaction.question(now)
        elif isinstance(message, UiSpeechOnset):
            self.reaction.answer("verbal", now)
            self.conversation.mic(now)
        elif isinstance(message, UiSpeech) and message.final:
            self.reaction.heard(message.text)
            self.conversation.mic(now)

    def on_frame(self, frame: PerceptionFrame, now: float) -> None:
        current = (frame.driver.head.answer, frame.driver.gesture)
        if any(value and value != before for value, before in zip(current, self.last_inputs, strict=True)):
            self.reaction.answer("gesture", now)
        self.last_inputs = current

    # --- every tick ----------------------------------------------------------------------------------------------

    def on_tick(self, state: State, now: float) -> None:
        episode = getattr(getattr(self.engine.safety, "distraction", None), "episode", None)
        if episode is not None and episode.alert == "off_road":
            self.reaction.visual_cue(episode.started)
        self.reaction.tick(state.driver.gaze.zone, now)
        slow = self.reaction.slow_ratio()

        attention = self.attention.update(state, now)
        fatigue = self.fatigue.update(state, now, slow)
        disengagement = self.disengagement.update(state, now, slow, self.reaction.response_rate(),
                                                  self.reaction.mean_words(), fatigue)
        self.blind.update(state, now)

        assessment = state.assessment
        assessment.attention = round(attention, 3)
        assessment.fatigue = round(fatigue, 3)
        assessment.disengagement = round(disengagement, 3)
        assessment.risk = risk_level(attention, fatigue, state.trip.speed_kmh)
        state.conversation = self.conversation.update(state, now)
        state.blind_m.last = round(self.blind.last, 1)
        state.blind_m.trip = round(self.blind.trip, 1)

        reaction = state.driver.reaction
        reaction.visual_ms = self.reaction.last["visual"]
        reaction.verbal_ms = self.reaction.last["verbal"]
        reaction.gesture_ms = self.reaction.last["gesture"]
        reaction.baseline_ms = {channel: round(self.reaction.baseline(channel), 1)
                                for channel in ("visual", "verbal", "gesture")}
        reaction.missed = self.reaction.missed
        rate = self.reaction.response_rate()
        reaction.response_rate_10min = None if rate is None else round(rate, 2)

        self._crossing("fatigue", fatigue, self.fatigue.terms, state, now)
        self._crossing("disengagement", disengagement, self.disengagement.terms, state, now)
        self._cause(state, now)
        self.intervention.tick(state, now)

    def _cause(self, state: State, now: float) -> None:
        """B4: a new cause goes to the event log and, for the labels the assistant resolves, to the assistant."""
        label = self.cause.update(state, now)
        if label is None:
            return
        cause = state.cause
        muted = state.assistant.muted_until is not None and now < state.assistant.muted_until
        self.engine.log_event("cause", now, text=render("causes", label, glances=cause.glances_30s), label=label,
                              target=cause.target, person_id=cause.person_id, conf=cause.conf,
                              sources=list(cause.sources), muted=muted)
        assistant = self.engine.assistant
        if assistant is not None and not muted and label in th("cause", "notify_labels"):
            assistant.submit("cause_detected", now, label=label)

    def _crossing(self, name: str, value: float, terms: dict[str, float], state: State, now: float) -> None:
        if value < float(th(name, "low")):
            self.armed[name] = True
        if value < float(th(name, "high")) or not self.armed[name]:
            return
        self.armed[name] = False
        label = "Oboseală F" if name == "fatigue" else "Dezinteres D"
        event = f"{name}_high"
        muted = state.assistant.muted_until is not None and now < state.assistant.muted_until
        self.engine.log_event(event, now, text=f"{label} = {_two_decimals(value)}",
                              terms={k: round(v, 2) for k, v in terms.items()}, muted=muted)
        assistant = self.engine.assistant
        if assistant is not None and not muted:
            assistant.submit(event, now)
            if name == "fatigue" and self.engine.safe_contact is not None:
                self.engine.safe_contact.fatigue_dialog_started(now, value)  # C10: a refusal now counts
