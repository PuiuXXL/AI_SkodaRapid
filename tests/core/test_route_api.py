"""core/route_api.py: the dashboard map's route file reaches the trip source, and the trip reaches the state."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.engine import Engine
from core.hub import Hub
from core.main import create_app
from core.route_api import route_router
from core.simulation import FakeSimulator

simulator = pytest.importorskip("simulator")  # P4's package; core runs without it


def route_file(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "r1", "name": "Sud → Nord",
        "origin": {"id": "a", "name": "Sud", "category": "origin", "lat": 46.0, "lon": 23.0},
        "stops": [{"id": "b", "name": "Benzinărie", "category": "fuel", "lat": 46.03, "lon": 23.0},
                  {"id": "d", "name": "Nord", "category": "destination", "lat": 46.1, "lon": 23.0}],
        "geometry": [{"lat": 46.0 + i * 0.01, "lon": 23.0} for i in range(11)],
    }
    data.update(changes)
    return data


@pytest.fixture
def setup() -> Iterator[tuple[TestClient, Engine]]:
    engine = Engine(Hub(), simulator.Simulator(), "simulator.Simulator (P4)")
    with TestClient(create_app(engine)) as client:
        yield client, engine


def test_the_stand_in_simulator_has_no_route_api() -> None:
    assert route_router(Engine(Hub(), FakeSimulator())) is None
    with TestClient(create_app(Engine(Hub(), FakeSimulator()))) as client:
        assert client.get("/simulator/route").status_code == 404


def test_a_route_file_drives_the_trip_in_the_state(setup: tuple[TestClient, Engine]) -> None:
    client, engine = setup
    assert client.get("/simulator/route").json()["active"] is False
    response = client.put("/simulator/route", json=route_file())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active"] is True and body["summary"]["destination"] == "Nord" and body["revision"] == 1
    assert engine.recent_events[-1]["event"]["type"] == "route_loaded"
    assert "Sud → Nord" in engine.recent_events[-1]["event"]["text"]
    state = engine.tick(1000.0)
    assert state.trip.pos.lat == pytest.approx(46.0) and state.trip.next_poi is not None
    assert state.trip.next_poi.name == "Benzinărie" and state.trip.next_poi.category == "fuel"
    assert client.post("/simulator/seek", json={"fraction": 0.5}).json()["km"] > 5
    assert engine.tick(1000.1).trip.next_poi.category == "destination"


@pytest.mark.parametrize(("body", "detail"), [
    (route_file(stops=[{"id": "d", "name": "Nord", "category": "fuel", "lat": 46.1, "lon": 23.0}]), "destinația"),
    (route_file(geometry=[{"lat": 46.0, "lon": 23.0}]), "geometry"),
    (route_file(stops=[{"id": "d", "name": "Departe", "category": "destination", "lat": 46.1, "lon": 23.5}]),
     "Departe"),
])
def test_an_invalid_route_file_is_refused_with_the_reason(setup: tuple[TestClient, Engine], body: dict[str, Any],
                                                          detail: str) -> None:
    client, _ = setup
    response = client.put("/simulator/route", json=body)
    assert response.status_code == 422 and detail in response.json()["detail"]
    assert client.get("/simulator/route").json()["active"] is False


def test_seek_needs_a_fraction_and_a_route_and_delete_returns_to_the_demo(setup: tuple[TestClient, Engine]) -> None:
    client, engine = setup
    assert client.post("/simulator/seek", json={"fraction": 0.5}).status_code == 409
    client.put("/simulator/route", json=route_file())
    for bad in ({"fraction": 2}, {"fraction": True}, {"fraction": "0.5"}, {}):
        assert client.post("/simulator/seek", json=bad).status_code == 422
    assert client.delete("/simulator/route").json()["active"] is False
    assert engine.recent_events[-1]["event"]["type"] == "route_cleared"
    assert engine.tick(1000.0).trip.next_poi.id == "omv_km42"
