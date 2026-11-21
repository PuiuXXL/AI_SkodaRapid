"""Test helpers for core (P2): a hub that records instead of sending, and a rig that drives the engine in fake time."""

from __future__ import annotations

from typing import Any

from core.engine import Engine
from core.hub import Hub
from core.safety import Safety
from core.safety.sos import SosChannel
from core.simulation import FakeSimulator
from scripts.fake_perception import FakePerception

T0 = 1_000_000.0
FRAME_HZ = 15.0
TICK_HZ = 10.0


class RecordingHub(Hub):
    """A hub without sockets: remembers what core sent."""

    def __init__(self) -> None:
        super().__init__()
        self.ui_sent: list[dict[str, Any]] = []
        self.perception_sent: list[dict[str, Any]] = []
        self.phone_sent: list[dict[str, Any]] = []

    def broadcast_ui(self, message: dict[str, Any]) -> bool:
        self.ui_sent.append(message)
        return True

    def send_perception(self, message: dict[str, Any]) -> bool:
        self.perception_sent.append(message)
        return True

    def send_phone(self, message: dict[str, Any]) -> bool:
        self.phone_sent.append(message)
        return True

    def of_type(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.ui_sent if m.get("type") == type_]

    def events(self, type_: str) -> list[dict[str, Any]]:
        return [m["event"] for m in self.of_type("event") if m["event"]["type"] == type_]


class Rig:
    """Engine + Safety + FakePerception, run in fake time: frames at 15 Hz, ticks at 10 Hz."""

    def __init__(self, scene: int = 8, sos_channels: dict[str, SosChannel] | None = None) -> None:
        self.hub = RecordingHub()
        self.engine = Engine(self.hub, FakeSimulator())
        self.safety = Safety(self.engine, sos_channels)
        self.t = T0
        self.fake = FakePerception(now=T0)
        self._next_frame = self._next_tick = T0
        self.command("scene", scene)
        self.engine.tick(T0)  # the trip speed is known before the first frame

    @property
    def state(self) -> Any:
        return self.engine.state

    def command(self, cmd: str, value: Any = None, on: bool | None = None) -> None:
        self.engine.on_browser_message({"type": "command", "cmd": cmd, "value": value, "on": on}, self.t)

    def press(self, key: str) -> None:
        self.fake.press(key, self.t)

    def run(self, seconds: float) -> None:
        end = self.t + seconds
        while True:
            t = min(self._next_frame, self._next_tick)
            if t > end:
                break
            self.t = t
            if t == self._next_frame:
                self.engine.on_perception_message(self.fake.frame(t), t)
                self._next_frame += 1.0 / FRAME_HZ
            if t == self._next_tick:
                self.engine.tick(t)
                self._next_tick += 1.0 / TICK_HZ
        self.t = end

    def run_until(self, condition: Any, limit_s: float = 60.0, step_s: float = 0.02) -> float:
        """Run until ``condition()`` is true; returns the elapsed fake time."""
        start = self.t
        while not condition():
            if self.t - start > limit_s:
                raise AssertionError("condition not reached")
            self.run(step_s)
        return self.t - start

    def say(self, text: str, addressed: bool = True) -> None:
        self.engine.on_browser_message({"type": "speech", "text": text, "final": True, "addressed": addressed,
                                        "ts": self.t}, self.t)

    def browser(self, message: dict[str, Any]) -> None:
        self.engine.on_browser_message(message, self.t)

    def speaks(self) -> list[dict[str, Any]]:
        return self.hub.of_type("speak")
