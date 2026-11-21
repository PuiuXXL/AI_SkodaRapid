"""simulator/: the route file from the dashboard map and the car that follows it (core's TripSource)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from shared import contracts as c
from simulator.route import Route, RouteInput, haversine_km
from simulator.sim import Simulator

LON = 23.0


def route_file(**changes: Any) -> dict[str, Any]:
    """A straight road north along 23°E, 46.00° -> 46.10° (about 11.1 km): fuel at 46.03, a waypoint, the end."""
    data: dict[str, Any] = {
        "type": "drivemate_route", "version": 1, "id": "r1", "name": "Sud → Nord",
        "origin": {"id": "a", "name": "Sud", "category": "origin", "lat": 46.0, "lon": LON},
        "stops": [
            {"id": "b", "name": "Benzinărie", "category": "fuel", "lat": 46.03, "lon": LON + 0.001},
            {"id": "w", "name": "Nod", "category": "waypoint", "lat": 46.05, "lon": LON},
            {"id": "d", "name": "Nord", "category": "destination", "lat": 46.1, "lon": LON},
        ],
        "geometry": [{"lat": 46.0 + i * 0.01, "lon": LON} for i in range(11)],
    }
    data.update(changes)
    return data


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def sim() -> tuple[Simulator, Clock]:
    clock = Clock()
    simulator = Simulator(clock=clock)
    simulator.set_route(route_file())
    return simulator, clock


def run(sim: Simulator, clock: Clock, seconds: float, step: float = 0.1) -> c.Trip:
    trip = sim.tick()
    for _ in range(round(seconds / step)):
        clock.t += step
        trip = sim.tick()
    return trip


def cmd(name: str, value: Any = None) -> c.UiCommand:
    return c.UiCommand(cmd=name, value=value)


LENGTH_KM = haversine_km((46.0, LON), (46.1, LON))


# --- the route file ----------------------------------------------------------------------------------------------


def test_route_places_stops_along_the_road_and_keeps_waypoints_out_of_the_pois() -> None:
    route = Route(RouteInput.model_validate(route_file()), stop_offset_max_m=500, geometry_max_points=100,
                  stops_max=10)
    assert route.length_km == pytest.approx(LENGTH_KM, rel=1e-6)
    assert [round(p.km, 2) for p in route.stops] == [3.34, 5.56, round(LENGTH_KM, 2)]
    assert [p.stop.id for p in route.pois] == ["b", "d"]
    lat, lon, heading = route.locate(LENGTH_KM / 2)
    assert (lat, lon) == pytest.approx((46.05, LON), abs=1e-6) and heading == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("change", [
    {"stops": [{"id": "d", "name": "Nord", "category": "fuel", "lat": 46.1, "lon": LON}]},  # no destination
    {"stops": [{"id": "d", "name": "X", "category": "destination", "lat": 46.05, "lon": LON},
               {"id": "e", "name": "Y", "category": "destination", "lat": 46.1, "lon": LON}]},  # two destinations
    {"geometry": [{"lat": 46.0, "lon": LON}]},  # one point
    {"geometry": [{"lat": 91.0, "lon": LON}, {"lat": 46.1, "lon": LON}]},  # latitude out of range
    {"geometry": [{"lat": float("nan"), "lon": LON}, {"lat": 46.1, "lon": LON}]},  # not a number
    {"origin": {"id": "d", "name": "Sud", "category": "origin", "lat": 46.0, "lon": LON}},  # duplicate id
    {"stopz": []},  # unknown field
    {"version": 2},
])
def test_invalid_route_files_are_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RouteInput.model_validate(route_file(**change))


def test_a_stop_far_from_the_road_or_a_route_without_length_is_refused() -> None:
    sim = Simulator(clock=Clock())
    far = route_file(stops=[{"id": "b", "name": "Departe", "category": "fuel", "lat": 46.03, "lon": LON + 0.05},
                            {"id": "d", "name": "Nord", "category": "destination", "lat": 46.1, "lon": LON}])
    with pytest.raises(ValueError, match="Departe"):
        sim.set_route(far)
    with pytest.raises(ValueError, match="distincte"):
        sim.set_route(route_file(geometry=[{"lat": 46.0, "lon": LON}, {"lat": 46.0, "lon": LON}]))
    assert sim.route is None  # a refused file changes nothing


# --- the car ---------------------------------------------------------------------------------------------------------


def test_without_a_route_it_is_cores_demo_trip() -> None:
    clock = Clock()
    trip = Simulator(clock=clock).tick()
    assert trip.speed_kmh == 50.0 and trip.next_poi is not None and trip.next_poi.id == "omv_km42"


def test_a_new_route_waits_at_the_origin_then_drives_at_the_directors_speed(sim: tuple[Simulator, Clock]) -> None:
    simulator, clock = sim
    trip = run(simulator, clock, 5)
    assert trip.speed_kmh == 0 and trip.stopped and trip.pos.lat == pytest.approx(46.0)
    assert trip.next_poi is not None and trip.next_poi.id == "b" and trip.next_poi.category == "fuel"
    simulator.command(cmd("speed", 90))
    simulator.command(cmd("time_scale", 20))
    simulator.command(cmd("start"))
    trip = run(simulator, clock, 3)  # 3 s x20 at 90 km/h = 1.5 km
    assert trip.speed_kmh == 90 and trip.road == "highway" and not trip.stopped
    assert trip.pos.lat == pytest.approx(46.0 + 1.5 / LENGTH_KM * 0.1, abs=2e-4)
    assert trip.next_poi.dist_km == pytest.approx(3.34 - 1.5, abs=0.02)
    assert trip.eta_min == pytest.approx((LENGTH_KM - 1.5) / 90 * 60, abs=0.2)
    simulator.command(cmd("pause"))
    paused = run(simulator, clock, 2)
    assert paused.speed_kmh == 0 and paused.pos == trip.pos and paused.road == "highway"


def test_stop_at_next_poi_drives_there_and_start_leaves_it(sim: tuple[Simulator, Clock]) -> None:
    simulator, clock = sim
    simulator.command(cmd("time_scale", 20))
    simulator.command(cmd("start"))
    simulator.command(cmd("stop_at_next_poi"))
    trip = run(simulator, clock, 30)
    assert trip.at_poi is not None and trip.at_poi.id == "b" and trip.stopped and trip.speed_kmh == 0
    assert trip.next_poi is not None and trip.next_poi.id == "d"  # the waypoint is never a stop
    assert simulator.route is not None
    assert simulator.km == pytest.approx(simulator.route.stops[0].km)
    simulator.command(cmd("start"))
    trip = run(simulator, clock, 1)
    assert trip.at_poi is None and trip.speed_kmh == 50


def test_the_car_stops_at_the_destination_and_stays_there(sim: tuple[Simulator, Clock]) -> None:
    simulator, clock = sim
    simulator.command(cmd("speed", 120))
    simulator.command(cmd("time_scale", 20))
    simulator.command(cmd("start"))
    trip = run(simulator, clock, 30)
    assert trip.at_poi is not None and trip.at_poi.category == "destination" and trip.eta_min == 0
    assert trip.next_poi is None and trip.pos.lat == pytest.approx(46.1)
    assert simulator.route_status()["arrived"] is True
    simulator.command(cmd("start"))
    assert run(simulator, clock, 1).speed_kmh == 0
    simulator.command(cmd("reset"))  # director reset: a new trip on the same route
    trip = run(simulator, clock, 0.1)
    assert trip.pos.lat == pytest.approx(46.0) and trip.at_poi is None and trip.elapsed_min == 0


def test_seek_jumps_along_the_road_paused_and_clear_returns_to_the_demo_trip(sim: tuple[Simulator, Clock]) -> None:
    simulator, clock = sim
    simulator.command(cmd("start"))
    status = simulator.seek(0.5)
    assert status["km"] == pytest.approx(LENGTH_KM / 2, abs=1e-3) and status["running"] is False
    trip = run(simulator, clock, 1)
    assert trip.pos.lat == pytest.approx(46.05) and trip.speed_kmh == 0
    assert trip.next_poi is not None and trip.next_poi.id == "d"  # the fuel station is behind
    revision = simulator.route_status()["revision"]
    status = simulator.clear_route()
    assert status["active"] is False and status["revision"] == revision + 1
    with pytest.raises(ValueError):
        simulator.seek(0.1)
    assert run(simulator, clock, 0.1).next_poi.id == "omv_km42"


def test_route_status_returns_the_file_as_sent() -> None:
    simulator = Simulator(clock=Clock())
    status = simulator.set_route(route_file(speed_kmh=72))
    assert status["route"]["stops"][0]["name"] == "Benzinărie" and status["speed_kmh"] == 72
    assert status["summary"]["destination"] == "Nord" and status["active"] is True


def test_every_trip_is_valid_for_the_contract(sim: tuple[Simulator, Clock]) -> None:
    simulator, clock = sim
    simulator.command(cmd("start"))
    simulator.command(cmd("scene", 5))
    for _ in range(20):
        clock.t += 0.5
        c.Trip.model_validate(simulator.tick().model_dump())


# --- where the car is, tourist sights ------------------------------------------------------------------------------

SIGHT = {"id": "s1", "name": "Cetate", "kind": "fort", "lat": 46.07, "lon": LON + 0.02, "description": "O cetate."}


def test_trip_says_where_the_car_is_in_names_from_the_route(sim: tuple[Simulator, Clock]) -> None:
    simulator, clock = sim
    simulator.seek(0.4)  # about 4.4 km: after the fuel station (3.3), before the waypoint (5.6)
    place = run(simulator, clock, 0.1).model_extra["place"]
    assert (place["after"], place["before"], place["destination"]) == ("Benzinărie", "Nod", "Nord")
    assert place["after_km"] == pytest.approx(1.1, abs=0.1) and place["before_km"] == pytest.approx(1.1, abs=0.1)
    simulator.seek(1.0)
    place = run(simulator, clock, 0.1).model_extra["place"]
    assert place["after"] == "Nord" and "before" not in place and place["destination_km"] == 0


def test_sights_ahead_are_listed_with_detour_and_the_car_can_stop_at_one() -> None:
    clock = Clock()
    simulator = Simulator(clock=clock)
    simulator.set_route(route_file(attractions=[SIGHT]))
    trip = run(simulator, clock, 0.1)
    (sight,) = trip.model_extra["attractions_ahead"]
    assert (sight["id"], sight["kind"], sight["description"]) == ("s1", "fort", "O cetate.")
    assert sight["dist_km"] == pytest.approx(7.8, abs=0.1) and sight["detour_km"] == pytest.approx(1.5, abs=0.1)
    assert trip.next_poi is not None and trip.next_poi.id == "b"  # a sight is not a stop on the road
    assert simulator.stop_at("nope") is False and simulator.stop_at("w") is False  # unknown id, waypoint
    assert simulator.stop_at("s1") is True
    simulator.command(cmd("time_scale", 20))
    simulator.command(cmd("start"))
    trip = run(simulator, clock, 40)
    assert trip.at_poi is not None and (trip.at_poi.id, trip.at_poi.category) == ("s1", "attraction")
    assert trip.at_poi.model_extra["kind"] == "fort" and trip.speed_kmh == 0
    assert trip.model_extra["attractions_ahead"] == []  # the one we stopped at is not "ahead"
    assert simulator.stop_at("s1") is True  # already there: stays
    simulator.seek(0.9)
    assert simulator.stop_at("s1") is False  # behind the car


def test_a_sight_far_from_the_road_or_a_duplicate_id_is_refused() -> None:
    simulator = Simulator(clock=Clock())
    with pytest.raises(ValueError, match="Departe"):
        simulator.set_route(route_file(attractions=[{**SIGHT, "name": "Departe", "lon": LON + 0.2}]))
    with pytest.raises(ValidationError):
        simulator.set_route(route_file(attractions=[{**SIGHT, "id": "b"}]))
