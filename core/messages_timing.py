"""F2: when a message may be delivered (REGULĂ). Defer, ask, or read.

* **defer** (``deferred_reason``): a safety alert is active (``messages.defer_levels``), the risk is high
  (``defer_min_risk``), the speed is high (``defer_min_speed_kmh``) or a distraction cause from the cabin is being
  handled (``defer_causes``: the passenger, the child; a message is never deferred because of itself). The voice
  says "Ți-l citesc imediat ce e liniște." once; the message is checked again every ``retry_s``.
* **ask**: someone else could hear it (passenger present or a rear occupant): "Mesaj personal de la Mihai. Îl citesc
  tare?" (the assistant phrases it; reading waits for a yes).
* **read**: the driver is alone.

The messages of the trusted contact (C10, F8) follow the same rule: they are never blocked by the assistant's
silence, but they are not read in the middle of an alert either.
"""

from __future__ import annotations

from typing import Literal

from core.settings import th
from shared.contracts import State

Delivery = Literal["defer", "ask", "read"]


def others_present(state: State) -> bool:
    """Same definition as P3's ``assistant.cabin.others_present``: the passenger seat or the back seat."""
    return state.passenger.present or any(o.seat == "rear" for o in state.occupants)


def decide(state: State) -> tuple[Delivery, str | None]:
    """(delivery, deferred_reason) for a message arriving now."""
    if (state.safety.level or "P4") in th("messages", "defer_levels"):
        return "defer", "safety_alert"
    if state.assessment.risk >= int(th("messages", "defer_min_risk")):
        return "defer", "high_risk"
    if state.trip.speed_kmh >= float(th("messages", "defer_min_speed_kmh")):
        return "defer", "high_speed"
    if state.cause.label in th("messages", "defer_causes"):
        return "defer", "distraction"
    return ("ask" if others_present(state) else "read"), None
