"""Dashboard (P4) map -> core: the route file the location simulator sends to ``PUT /simulator/route``.

``fixtures/dashboard_route_file.json`` is shared: the dashboard's test asserts that ``routeFile(...)`` produces exactly
this file from the map's points and road (dashboard/tests/dashboard.test.tsx); here P4's trip source in core must
accept it and turn it into a trip the engine and the LLM read (``State.trip``).
"""

from __future__ import annotations

import pytest

from shared import contracts as c
from tests.contract.conftest import load_fixture

simulator = pytest.importorskip("simulator")


def test_core_follows_the_route_file_the_map_produces() -> None:
    sim = simulator.Simulator()
    status = sim.set_route(load_fixture("dashboard_route_file"))
    assert status["active"] and status["speed_kmh"] == 72
    assert status["summary"]["length_km"] == pytest.approx(11.119, abs=0.01)
    trip = c.Trip.model_validate(sim.tick().model_dump())
    assert trip.pos.lat == pytest.approx(46.0) and trip.next_poi is not None
    assert (trip.next_poi.id, trip.next_poi.category) == ("b", "fuel")  # the waypoint is never a stop
    sight = trip.model_extra["attractions_ahead"][0]
    assert (sight["id"], sight["kind"], sight["description"]) == ("wiki-ro-1", "fort", "O cetate medievală.")
    assert sight["detour_km"] == pytest.approx(1.5, abs=0.1)
    assert trip.model_extra["place"]["after"] == "Sud"
