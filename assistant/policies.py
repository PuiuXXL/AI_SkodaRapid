"""When the assistant is allowed to take the floor (plan C8, D1, G2, section 5).

These checks run BEFORE any LLM call, so a blocked event costs nothing and the
answer is an explicit ``stay_silent`` (visible in the event log, plan G2).

Rules, in order:

1. **Safety veto** - at P0-P2, or when core says ``safety.llm_allowed = False``, the
   assistant stays silent (plan C8: "LLM-ul tace la P0–P2"). Alarms are P2's job.
2. **Muted after a refusal** - while ``assistant.muted_until`` is in the future, no
   initiative (plan D10, C10). Messages from contacts and anything the driver asks
   for are still handled (plan section 5, rule 8).
3. **In-car conversation** - while people talk (``conversation = True``) proactive
   comfort is skipped; safety and cause resolution still go through (plan G2).
4. **Rate limit** - at most one PROACTIVE intervention every
   ``policies.proactive_min_interval_s`` seconds (plan: "cel mult o intervenție
   proactivă la 30 s").

Note: whether the LLM itself is switched off (director button, plan C6) is not a
policy - in that case the fixed fallback texts are used (see client.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from assistant.contract import Event, State
from assistant.settings import cfg


@dataclass(frozen=True)
class PolicyDecision:
    """Result of :meth:`Policies.check`.

    Attributes:
        allowed: True if the assistant may answer the event.
        reason: Why it must stay silent (``"safety_veto"``, ``"muted"``,
            ``"conversation"``, ``"rate_limited"``), or ``"ok"``.
    """

    allowed: bool
    reason: str = "ok"


class Policies:
    """Stateful policy checker (remembers the time of the last proactive intervention).

    One instance lives inside :class:`assistant.client.AssistantClient`.
    """

    def __init__(self) -> None:
        """Start with no previous proactive intervention."""
        self._last_proactive_ts: Optional[float] = None

    @staticmethod
    def is_proactive(event: Event) -> bool:
        """True for events the driver did not ask for (rate-limited, mutable)."""
        return event.type in cfg("policies", "proactive_events", default=[])

    def check(self, event: Event, state: State, now: float) -> PolicyDecision:
        """Decide whether the assistant may answer ``event`` right now.

        Args:
            event: The event from core.
            state: Current state.
            now: Current Unix time (passed in so tests are deterministic).

        Returns:
            A :class:`PolicyDecision`.
        """
        level = state.safety.level
        if level in cfg("policies", "llm_vetoed_levels", default=["P0", "P1", "P2"]) or not state.safety.llm_allowed:
            return PolicyDecision(False, "safety_veto")

        muted_until = state.assistant.muted_until
        if muted_until is not None and muted_until > now:
            if event.type not in cfg("policies", "allowed_while_muted", default=[]):
                return PolicyDecision(False, "muted")

        if not self.is_proactive(event):
            return PolicyDecision(True)

        if state.conversation and event.type not in cfg("policies", "allowed_during_conversation", default=[]):
            return PolicyDecision(False, "conversation")

        interval = float(cfg("policies", "proactive_min_interval_s", default=30))
        if self._last_proactive_ts is not None and now - self._last_proactive_ts < interval:
            return PolicyDecision(False, "rate_limited")
        return PolicyDecision(True)

    def record(self, event: Event, now: float) -> None:
        """Remember that the assistant intervened (call after a non-silent answer)."""
        if self.is_proactive(event):
            self._last_proactive_ts = now

    def reset(self) -> None:
        """Forget the last intervention (director "reset" button, tests)."""
        self._last_proactive_ts = None
