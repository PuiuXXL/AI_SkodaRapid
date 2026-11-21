"""K4: propose a tourist sight on the way as a stop (with P4's location simulator).

The route drawn on the dashboard map can carry tourist sights (``simulator/route.py``); P4's trip source lists the
ones ahead in ``trip.attractions_ahead``, an extra field of ``Trip`` (the contract keeps unknown fields), each with
``id``, ``name``, ``kind``, ``dist_km``, ``detour_km`` and maybe ``description``. Without it (core's demo trip) this
rule does nothing.

* :class:`AttractionRule`: once the driver has driven ``attractions.min_drive_min``, while the car moves and nothing
  more important is going on (no alert at or above the LLM veto, no dialog, the assistant silent and not muted), it
  proposes the nearest sight ``attractions.min_ahead_km`` .. ``attractions.suggest_within_km`` ahead, each one once,
  at most one every ``attractions.cooldown_min`` of trip time;
* :func:`attraction_stop`: the ``stop_suggested`` data, also used by the K3 break (``core/reminders.pick_stop``),
  which prefers a sight to a plain stop when no reminder needs that stop.

The proposal is the usual ``stop_suggested`` event: P3's assistant asks, and a "yes" makes the car stop there
(``core/assistant_link.py`` -> ``simulator.stop_at``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.settings import th
from shared.contracts import LLM_VETO_LEVELS, State

if TYPE_CHECKING:
    from core.engine import Engine


def attractions_ahead(state: State) -> list[dict[str, Any]]:
    """``trip.attractions_ahead`` as sent by the trip source, keeping only well-formed entries, nearest first."""
    items = (state.trip.model_extra or {}).get("attractions_ahead") or []
    valid = [item for item in items if isinstance(item, dict) and item.get("id") and item.get("name")
             and isinstance(item.get("dist_km"), (int, float)) and not isinstance(item.get("dist_km"), bool)]
    return sorted(valid, key=lambda item: float(item["dist_km"]))


def attraction_stop(sight: dict[str, Any]) -> dict[str, Any]:
    """The ``stop_suggested`` data for a sight (``kind: "attraction"`` tells the assistant what it is)."""
    data: dict[str, Any] = {"poi_id": str(sight["id"]), "poi_name": str(sight["name"]),
                            "dist_km": round(float(sight["dist_km"]), 1), "poi_options": [str(sight["id"])],
                            "kind": "attraction", "attraction_kind": sight.get("kind") or "attraction",
                            "detour_km": sight.get("detour_km")}
    if sight.get("description"):
        data["description"] = str(sight["description"])
    return data


class AttractionRule:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        engine.add_tick_listener(self.on_tick)
        engine.add_reset_listener(self.reset)
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.suggested: set[str] = set()
        self.last_trip_min: float | None = None

    def _assistant_free(self, state: State, now: float) -> bool:
        link = self.engine.assistant
        if link is None or not getattr(link, "available", False):
            return False
        dialog = getattr(link, "dialog", None)
        muted = state.assistant.muted_until is not None and now < state.assistant.muted_until
        # Core knows the voice ended from the browser's speak_done; with the sound off in the browser it never comes,
        # so an utterance older than attractions.speech_wait_s no longer counts as speaking.
        speaking = getattr(link, "speaking", None)
        started = (getattr(link, "utterances", {}).get(speaking) or {}).get("ts") if speaking is not None else None
        wait = float(th("attractions", "speech_wait_s"))
        talking = speaking is not None and (started is None or now - started < wait)
        return (not talking and not getattr(link, "queue", None) and not muted
                and not (dialog is not None and dialog.has_pending(now))
                and not state.interaction.dialog_window_open)

    def on_tick(self, state: State, now: float) -> None:
        if not th("attractions", "enabled"):
            return
        sights = attractions_ahead(state)
        if not sights:
            return
        trip, safety = state.trip, state.safety
        if trip.speed_kmh <= float(th("reminders", "stopped_max_kmh")):
            return
        if trip.elapsed_min < float(th("attractions", "min_drive_min")):
            return
        if self.last_trip_min is not None and trip.elapsed_min - self.last_trip_min < float(th("attractions",
                                                                                              "cooldown_min")):
            return
        if (safety.level or "P4") in LLM_VETO_LEVELS or safety.alert or not safety.monitoring_ok:
            return
        near, far = float(th("attractions", "min_ahead_km")), float(th("attractions", "suggest_within_km"))
        sight = next((s for s in sights if s["id"] not in self.suggested and near <= float(s["dist_km"]) <= far), None)
        if sight is None or not self._assistant_free(state, now):
            return
        self.suggested.add(str(sight["id"]))
        self.last_trip_min = trip.elapsed_min
        data = attraction_stop(sight)
        self.engine.log_event("attraction_suggested", now, text=f"Propun o oprire la {data['poi_name']} "
                                                                f"(peste {data['dist_km']:g} km).", **data)
        self.engine.assistant.submit("stop_suggested", now, **data)
