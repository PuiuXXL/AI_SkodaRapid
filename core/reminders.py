"""K: route reminders. K3 for now: which stop to propose for a break (the rule picks it, the LLM only phrases it).

K3 (plan D3): after a high KSS answer, the stop is the next POI ahead within ``reminders.stop_search_km``; an open
reminder of the same category is solved there too ("Oprim la OMV peste 12 km? Iei și lichidul de parbriz."). The
stop-triggered reminder (K2, "Ai zis să iei ...") comes with step F.
"""

from __future__ import annotations

from typing import Any

from core.settings import th
from shared.contracts import State


def pick_stop(state: State) -> dict[str, Any] | None:
    """The ``stop_suggested`` event data for a break, or None when there is no stop ahead in range."""
    poi = state.trip.next_poi
    if poi is None or (poi.dist_km is not None and poi.dist_km > float(th("reminders", "stop_search_km"))):
        return None
    task = next((r.task for r in state.reminders
                 if r.state == "active" and r.trigger.category == poi.category), None)
    data: dict[str, Any] = {"poi_id": poi.id, "poi_name": poi.name or poi.id, "dist_km": poi.dist_km,
                            "poi_options": [poi.id]}
    if task:
        data["task"] = task
    return data
