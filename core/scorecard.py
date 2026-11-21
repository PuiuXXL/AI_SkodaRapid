"""J2, J3: the trip scorecard (live in ``state.scorecard``) and the trip report at the end (scene 10).

Live, every tick:

* ``longest_focus_min``: the longest stretch of trip time while moving without an off-road glance longer than
  ``scorecard.focus_break_ms`` (and with the camera seeing the driver);
* ``phone_touches``: episodes with the driver's phone in hand (detector) for ``safety.distraction.phone_min_ms``
  while moving. The demo's "atingeri telefon: 0" is honest only if nobody holds the phone;
* ``hands_free_messages``, ``suggestions_accepted / rejected``, ``reminders_done`` are counted by the assistant link
  and the reminder rule.

The report (``build``) gathers the trip: distance, time, stops, the scorecard, blind meters (and the previous trip's,
"azi vs. ultima călătorie"), the A/B counter, the reaction per channel against the baseline, the effect of every
intervention, the evolution of attention / F / D (one point per ``scorecard.history_s``) and the event log. Its
fields follow P4's ``Report`` (dashboard/src/driver/contracts.ts) so the report page can show it. It is sent as the
event ``trip_report`` on the director's ``end_trip`` and before a ``reset`` (a trip is never lost).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from core.settings import th
from shared.contracts import State, UiCommand, to_wire

if TYPE_CHECKING:
    from core.engine import Engine


class TripReport:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        engine.trip_report = self
        engine.add_tick_listener(self.on_tick)
        engine.add_browser_listener(self.on_browser)
        engine.add_reset_listener(self.before_reset, before=True)
        engine.add_reset_listener(self.reset)
        self.last: dict[str, Any] | None = None
        self.previous: dict[str, Any] | None = None
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.focus_since: float | None = None  # trip minutes
        self.longest = 0.0
        self.phone_since: float | None = None
        self.phone_counted = False
        self.touches = 0
        self.distance_km = 0.0
        self.last_t: float | None = None
        self.stops: set[str] = set()
        self.history: list[dict[str, float]] = []
        self.next_point = float("-inf")

    # --- live ----------------------------------------------------------------------------------------------------

    def on_tick(self, state: State, now: float) -> None:
        dt = 0.0 if self.last_t is None else now - self.last_t
        self.last_t = now
        trip = state.trip
        moving = trip.speed_kmh > float(th("reminders", "stopped_max_kmh"))
        self.distance_km += max(0.0, trip.speed_kmh) * dt / 3600.0 * self._time_scale(state)
        if trip.at_poi is not None and not moving:
            self.stops.add(trip.at_poi.id)

        off_road_ms = state.driver.gaze.off_road_ms
        broken = not state.safety.monitoring_ok or off_road_ms >= float(th("scorecard", "focus_break_ms"))
        if broken:
            self.focus_since = None
        elif moving:
            if self.focus_since is None:
                self.focus_since = trip.elapsed_min
            if off_road_ms <= 0:  # a glance is only known to be long after 2 s: count the stretch on the road only
                self.longest = max(self.longest, trip.elapsed_min - self.focus_since)

        phone = state.driver.phone
        if moving and phone.in_use and phone.source == "detector":
            self.phone_since = now if self.phone_since is None else self.phone_since
            held_ms = (now - self.phone_since) * 1000.0
            if not self.phone_counted and held_ms >= float(th("safety", "distraction", "phone_min_ms")):
                self.phone_counted = True
                self.touches += 1
        else:
            self.phone_since, self.phone_counted = None, False

        card = state.scorecard
        card.longest_focus_min = round(self.longest, 1)
        card.phone_touches = self.touches

        if now >= self.next_point:
            self.next_point = now + float(th("scorecard", "history_s"))
            a = state.assessment
            self.history.append({"attention": a.attention, "fatigue": a.fatigue, "disengagement": a.disengagement,
                                 "risk": a.risk, "elapsed_min": round(trip.elapsed_min, 1)})

    def _time_scale(self, state: State) -> float:
        """Distance follows the trip time (the director's time scale): elapsed minutes per real minute."""
        simulator = self.engine.simulator
        return float(getattr(simulator, "time_scale", 1.0))

    # --- the report ----------------------------------------------------------------------------------------------

    def on_browser(self, message: Any, now: float) -> None:
        if isinstance(message, UiCommand) and message.cmd == "end_trip":
            self.publish(now)

    def before_reset(self, now: float) -> None:
        if self.engine.state.trip.elapsed_min > 0 or self.history:
            self.publish(now)

    def publish(self, now: float) -> dict[str, Any]:
        report = self.build(now)
        self.previous, self.last = self.last, report
        card = report["scorecard"]
        self.engine.log_event(
            "trip_report", now, report=report,
            text=(f"Fișa călătoriei: {report['distance_km']:.1f} km, concentrat cel mult "
                  f"{card['longest_focus_min']:.0f} min, {card['hands_free_messages']} mesaje fără mâini, "
                  f"{card['phone_touches']} atingeri ale telefonului, prag simplu {report['ab']['naive_alerts']} / "
                  f"DriveMate {report['ab']['our_alerts']}."))
        return report

    def build(self, now: float) -> dict[str, Any]:
        state = self.engine.state
        scores = self.engine.scores
        reaction = to_wire(state.driver.reaction)
        means = scores.reaction.means() if scores is not None else {}
        effects = list(scores.intervention.history) if scores is not None else []
        previous_blind = (self.last or {}).get("blind_m")
        return {
            "id": uuid.uuid4().hex[:12],
            "at": now,
            "distance_km": round(self.distance_km, 1),
            "elapsed_min": round(state.trip.elapsed_min, 1),
            "stops": len(self.stops),
            "scorecard": to_wire(state.scorecard),
            "blind_m": to_wire(state.blind_m),
            "blind_m_previous_trip": previous_blind,
            "ab": to_wire(state.ab),
            "history": list(self.history),
            "effects": effects,
            "intervention_stats": dict(state.intervention.stats),
            "reaction": reaction,
            "reaction_mean_ms": means,
            "log": [m["event"] for m in self.engine.recent_events],
        }
