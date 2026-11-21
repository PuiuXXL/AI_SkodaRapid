"""D6 (and D2): the measured effect of each intervention, before vs. after ("efectul măsurat în această sesiune").

An intervention starts when the assistant gives a remedy:

* **delegate**: a cause from the cabin was answered ("Maria, poți să-i povestești tu?"). Metric: the glances at the
  passenger in ``intervention.before_s`` before vs. ``after_s`` after (fewer is better). No fewer glances = the
  remedy did not help, it is dropped (D2);
* **music**: music started against disengagement (``media.reason = disengagement``). Metric: mean D before vs.
  after (lower is better).

``effect_pct`` = improvement in percent (+X% on the card); the attention before / after is logged too.
``intervention.stats`` keeps the mean effect per type as a fraction (0.18 = +18 %), for the trip report (J3).
Fewer than ``min_samples`` state samples before the start: not measured (the trip has just started).
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.settings import render, th
from shared.contracts import State

if TYPE_CHECKING:
    from core.cause import CauseDetector
    from core.engine import Engine

LABELS = {"music": "music_energetic", "delegate": "delegate"}


@dataclass
class Running:
    kind: str
    started: float
    before: float
    attention_before: float
    deadline: float


@dataclass
class InterventionTracker:
    engine: Engine
    cause: CauseDetector
    samples: deque[tuple[float, float, float]] = field(default_factory=deque)  # (t, attention, D)
    running: Running | None = None
    effects: dict[str, list[float]] = field(default_factory=dict)
    history: list[dict[str, object]] = field(default_factory=list)  # every measured intervention, trip report (J3)

    def reset(self) -> None:
        self.samples.clear()
        self.running = None
        self.effects = {}
        self.history = []

    def _window(self, since: float, until: float) -> list[tuple[float, float, float]]:
        return [s for s in self.samples if since <= s[0] <= until]

    def start(self, kind: str, now: float) -> bool:
        """An intervention of ``kind`` begins now. Returns False when there is not enough data to measure it."""
        if self.running is not None and self.running.kind == kind:
            return False  # the same remedy repeated: keep measuring the first one
        before = self._window(now - float(th("intervention", "before_s")), now)
        if len(before) < int(th("intervention", "min_samples")):
            self.engine.log_event("intervention_skipped", now, text="Efectul nu se poate măsura încă.", kind=kind)
            return False
        if kind == "delegate":
            value = float(self.cause.count("passenger", now - float(th("intervention", "before_s")), now))
        else:
            value = statistics.fmean(d for _, _, d in before)
        self.running = Running(kind, now, value, statistics.fmean(a for _, a, _ in before),
                               now + float(th("intervention", "after_s")))
        return True

    def tick(self, state: State, now: float) -> None:
        self.samples.append((now, state.assessment.attention, state.assessment.disengagement))
        keep = float(th("intervention", "before_s")) + float(th("intervention", "after_s")) + 5.0
        while self.samples and self.samples[0][0] < now - keep:
            self.samples.popleft()
        running = self.running
        if running is None or now < running.deadline:
            return
        self.running = None
        after_samples = self._window(running.started, now)
        if running.kind == "delegate":
            after = float(self.cause.count("passenger", running.started, now))
        else:
            after = statistics.fmean(d for _, _, d in after_samples) if after_samples else running.before
        effect = 0.0 if running.before <= 0 else (running.before - after) / running.before * 100.0
        attention_after = statistics.fmean(a for _, a, _ in after_samples) if after_samples else 0.0
        pct = round(effect)
        helped = pct > 0
        self.effects.setdefault(running.kind, []).append(effect / 100.0)
        intervention = state.intervention
        intervention.last = LABELS.get(running.kind, running.kind)
        intervention.effect_pct = pct
        intervention.stats = {LABELS.get(kind, kind).split("_")[0]: round(statistics.fmean(values), 2)
                              for kind, values in self.effects.items()}
        text = render("interventions", f"{running.kind}_{'ok' if helped else 'no'}", pct=pct)
        self.history.append({"action": LABELS.get(running.kind, running.kind),
                             "reason": "distraction" if running.kind == "delegate" else "disengagement",
                             "effect_pct": pct, "helped": helped, "at": now})
        self.engine.log_event("intervention_effect", now, text=text, kind=running.kind, effect_pct=pct,
                              before=round(running.before, 2), after=round(after, 2),
                              attention_before=round(running.attention_before, 2),
                              attention_after=round(attention_after, 2), helped=helped)
