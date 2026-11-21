"""P4's trip source for core: the car follows the route drawn on the dashboard map.

Core loads it through ``core.simulation.load_simulator`` (``Simulator.tick() -> Trip`` at 10 Hz, ``command(cmd)`` with
the director's commands). Without a route it is core's own demo trip (:class:`core.simulation.FakeSimulator`), so the
scenes work as before. With a route (``set_route``, from ``PUT /simulator/route``):

* the car advances along the road at the director's speed and time scale (``speed``, ``time_scale``), from
  ``start`` / ``pause``; ``trip.pos`` is its position, ``trip.eta_min`` the time to the destination at that speed;
* ``trip.next_poi`` is the next stop ahead (waypoints excluded) with ``dist_km``; at the destination, or at the stop
  chosen with ``stop_at_next_poi`` (the car drives there and stops), ``trip.at_poi`` is that stop and the speed 0;
* ``start`` leaves a stop, ``reset`` returns to the origin (the route is kept), ``seek`` jumps along the road (paused);
* ``stop_at(poi_id)`` (core, after the driver accepted a proposed stop): the car drives to that stop or attraction
  and stops there (for an attraction, at the nearest point of the road).

Two fields that the contract keeps as extras of ``Trip`` (``ContractModel`` keeps unknown fields) say more:
``trip.place`` (where the car is, in names from the route: last place passed, next one, destination) and
``trip.attractions_ahead`` (tourist sights ahead, with distance, detour and description), for the LLM's context
and core's attraction rule (core/attractions.py).

Everything else (safety, scores, reminders at a stop, the LLM's context) reads ``State.trip`` as before: the contract
does not change.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import yaml

from core.simulation import SCENES, FakeSimulator
from shared.contracts import Position, Trip, UiCommand
from simulator.route import PlacedStop, Route, RouteInput

CONFIG_FILE = Path(__file__).with_name("simulator.yaml")
log = logging.getLogger("drivemate.simulator")


def load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return dict(yaml.safe_load(f))


class Simulator:
    def __init__(self, clock: Any = time.monotonic, config: dict[str, Any] | None = None) -> None:
        self.clock = clock
        self.cfg = config or load_config()
        self.demo = FakeSimulator(clock)
        self.route: Route | None = None
        self.revision = 0
        self.speed_kmh = float(self.cfg["default_speed_kmh"])
        self.time_scale = 1.0
        self._restart()

    def _restart(self) -> None:
        """Back to the origin, paused: a new route or a director reset."""
        self.km = 0.0
        self.elapsed_min = 0.0
        self.running = False
        self.at_stop: PlacedStop | None = None
        self.target: PlacedStop | None = None
        self.scene: int | None = None
        self.road = "city"
        self._last = self.clock()

    # --- the route file (core/route_api.py) ------------------------------------------------------------------------

    def set_route(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and follow a route file; ValueError (or pydantic's ValidationError) with the reason if invalid."""
        route_input = RouteInput.model_validate(data)
        route = Route(route_input, stop_offset_max_m=float(self.cfg["stop_offset_max_m"]),
                      geometry_max_points=int(self.cfg["geometry_max_points"]), stops_max=int(self.cfg["stops_max"]),
                      attraction_offset_max_m=float(self.cfg["attraction_offset_max_m"]),
                      attractions_max=int(self.cfg["attractions_max"]))
        self.route = route
        self.revision += 1
        if route_input.speed_kmh is not None:
            self.speed_kmh = route_input.speed_kmh
        self._restart()
        return self.route_status()

    def clear_route(self) -> dict[str, Any]:
        """Back to core's demo trip."""
        self.route = None
        self.revision += 1
        self.demo.reset()
        self.demo.speed_kmh, self.demo.time_scale = self.speed_kmh, self.time_scale
        return self.route_status()

    def seek(self, fraction: float) -> dict[str, Any]:
        """Jump to ``fraction`` (0-1) of the road, paused and not at a stop."""
        if self.route is None:
            raise ValueError("niciun traseu încărcat")
        self.km = self.route.length_km * min(1.0, max(0.0, fraction))
        self.at_stop = self.target = None
        self.running = False
        self._last = self.clock()
        return self.route_status()

    def stop_at(self, poi_id: str) -> bool:
        """Drive to stop / attraction ``poi_id`` ahead and stop there; False if there is no such place ahead."""
        route = self.route
        place = route.find(poi_id) if route else None
        if route is None or place is None or place.km < self.km - float(self.cfg["passed_poi_km"]):
            return False
        if place.km <= self.km + float(self.cfg["arrive_km"]):  # already there
            self.km, self.at_stop, self.target = max(self.km, place.km), place, None
        else:
            self.target = place
        return True

    def route_status(self) -> dict[str, Any]:
        route = self.route
        return {"revision": self.revision, "active": route is not None,
                "route": route.input.model_dump(mode="json", exclude_none=True) if route else None,
                "summary": route.summary() if route else None,
                "km": round(self.km, 3) if route else None, "running": self.running if route else None,
                "speed_kmh": self.speed_kmh, "time_scale": self.time_scale,
                "arrived": bool(route and self.at_stop is route.destination)}

    # --- TripSource ------------------------------------------------------------------------------------------------

    def tick(self) -> Trip:
        if self.route is None:
            return self.demo.tick()
        route, arrive = self.route, float(self.cfg["arrive_km"])
        now = self.clock()
        dt_h = (now - self._last) / 3600.0 * self.time_scale
        self._last = now
        if self.at_stop is None and self.km >= route.length_km - arrive:
            self.at_stop = route.destination
        moving = self.running and self.at_stop is None and self.speed_kmh > 0
        if moving and dt_h > 0:
            end = self.target.km if self.target is not None else route.length_km
            step = self.speed_kmh * dt_h
            if self.km + step >= end - arrive:  # arrives during this tick: stops there
                self.elapsed_min += max(0.0, end - self.km) / self.speed_kmh * 60.0
                self.km = end
                self.at_stop = self.target or route.destination
                self.target = None
                moving = False
            else:
                self.km += step
                self.elapsed_min += dt_h * 60.0
        speed = self.speed_kmh if moving else 0.0
        if speed >= float(self.cfg["highway_kmh"]):
            self.road = "highway"
        elif speed > 0:
            self.road = "city"
        lat, lon, _ = route.locate(self.km)
        remaining = route.length_km - self.km
        eta = 0.0 if remaining <= arrive else (remaining / self.speed_kmh * 60.0 if self.speed_kmh > 0 else None)
        nxt = route.next_poi(self.km, float(self.cfg["passed_poi_km"]), skip=self.at_stop)
        sights = route.attractions_ahead(self.km, float(self.cfg["passed_poi_km"]),
                                         float(self.cfg["attractions_ahead_km"]))
        return Trip(speed_kmh=round(speed, 1), road=self.road, elapsed_min=round(self.elapsed_min, 2),
                    pos=Position(lat=round(lat, 6), lon=round(lon, 6)),
                    eta_min=None if eta is None else round(eta, 1), scene=self.scene, stopped=speed == 0.0,
                    at_poi=self.at_stop.poi() if self.at_stop else None,
                    next_poi=nxt.poi(self.km) if nxt else None,
                    place=route.place(self.km),
                    attractions_ahead=[p.ahead(self.km) for p in sights if p is not self.at_stop]
                    [: int(self.cfg["attractions_listed"])])

    def command(self, cmd: UiCommand) -> None:
        self.demo.command(cmd)  # kept in step, for when the route is cleared
        value = cmd.value
        if cmd.cmd == "speed" and isinstance(value, (int, float)):
            self.speed_kmh = max(0.0, float(value))
        elif cmd.cmd == "time_scale" and isinstance(value, (int, float)) and value > 0:
            self.time_scale = float(value)
        elif cmd.cmd == "scene" and isinstance(value, int) and value in SCENES:
            self.scene = value
            self.road, self.speed_kmh = SCENES[value]
        route = self.route
        if route is None:
            return
        log.info("route command %s %s (km %.2f, at %s)", cmd.cmd, value if value is not None else cmd.on, self.km,
                 self.at_stop.stop.id if self.at_stop else None)
        if cmd.cmd in ("speed", "scene", "start") and self.at_stop is not route.destination:
            self.at_stop = None  # leaves the stop, as the demo trip does
        if cmd.cmd in ("start", "pause"):
            self.running = cmd.cmd == "start"
            self._last = self.clock()
        elif cmd.cmd == "stop_at_next_poi":
            self.target = route.next_poi(self.km, 0.0, skip=self.at_stop)
        elif cmd.cmd == "reset":
            self._restart()
