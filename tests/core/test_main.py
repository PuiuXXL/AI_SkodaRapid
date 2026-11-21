"""Tests for core/main.py: the real WebSocket endpoints and the 10 Hz loop, through FastAPI's test client."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.engine import Engine
from core.hub import Hub
from core.main import create_app
from core.simulation import FakeSimulator
from scripts.fake_perception import FakePerception
from shared import contracts as c


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Engine(Hub(), FakeSimulator()))) as test_client:
        yield test_client


def wait_for(ws: Any, condition: Callable[[dict[str, Any]], bool], limit: int = 100) -> dict[str, Any]:
    """Read messages until one matches (the loop sends a state every 100 ms)."""
    for _ in range(limit):
        message = ws.receive_json()
        if condition(message):
            return message
    raise AssertionError("no matching message")


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["contract"] == c.CONTRACT_VERSION
    assert body["simulator"] == "FakeSimulator (core)" and body["perception"]["connected"] is False


def test_ui_gets_the_state_at_once_and_then_every_tick(client: TestClient) -> None:
    with client.websocket_connect("/ws/ui") as ui:
        first = wait_for(ui, lambda m: m["type"] == "state")
        assert isinstance(c.parse_ui_message(first), c.UiState)
        t0 = time.monotonic()
        seqs = [wait_for(ui, lambda m: m["type"] == "state")["state"]["seq"] for _ in range(5)]
        elapsed = time.monotonic() - t0
    assert seqs == sorted(seqs) and len(set(seqs)) == 5
    assert 0.25 < elapsed < 2.0  # ~10 Hz


def test_perception_frame_reaches_the_dashboard(client: TestClient) -> None:
    fake = FakePerception()
    with client.websocket_connect("/ws/ui") as ui, client.websocket_connect("/ws/perception") as perception:
        fake.press("7", time.time())
        perception.send_json(fake.frame(time.time()))
        state = wait_for(ui, lambda m: m["type"] == "state" and m["state"]["driver"]["eyes"]["state"] == "CLOSED")
        assert state["state"]["safety"]["monitoring_ok"] is True
        assert [o["seat"] for o in state["state"]["occupants"]] == ["driver", "front_right"]
        assert client.get("/health").json()["perception"]["frames"] == 1


def test_dashboard_command_reaches_perception(client: TestClient) -> None:
    with client.websocket_connect("/ws/perception") as perception, client.websocket_connect("/ws/ui") as ui:
        ui.send_text("not json")  # ignored, the connection stays open
        ui.send_json({"type": "command", "cmd": "debug", "on": True})
        command = perception.receive_json()
        assert c.PerceptionCommand.model_validate(command).cmd == "debug" and command["on"] is True
        ui.send_json({"type": "command", "cmd": "llm", "on": False})
        wait_for(ui, lambda m: m["type"] == "state" and m["state"]["safety"]["llm_enabled"] is False)


def test_phone_bridge(client: TestClient) -> None:
    with client.websocket_connect("/ws/ui") as ui, client.websocket_connect("/ws/phone") as phone:
        phone.send_json({"type": "phone_status", "connected": True, "battery": 64})
        state = wait_for(ui, lambda m: m["type"] == "state" and m["state"]["phone"]["connected"])
        assert state["state"]["phone"]["battery"] == 64 and state["state"]["integrations"]["phone_bridge"] == "ok"
    assert client.app.state.engine.hub.phone is None  # type: ignore[attr-defined]


def test_new_dashboard_sees_the_log_so_far(client: TestClient) -> None:
    with client.websocket_connect("/ws/perception"), client.websocket_connect("/ws/ui") as ui:
        event = wait_for(ui, lambda m: m["type"] == "event")
        assert event["event"]["type"] == "perception_connected" and event["event"]["source"] == "RULE"
