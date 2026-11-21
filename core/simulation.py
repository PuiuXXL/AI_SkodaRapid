"""The trip context (B7): P4's ``simulator.Simulator`` when it exists, otherwise a small stand-in.

P4's interface (plan section 13): ``Simulator.tick() -> Trip`` (called at 10 Hz) and ``Simulator.command(cmd)`` with
the director's commands. Until it lands, :class:`FakeSimulator` gives core a plausible trip so the safety rules can
be tested at the right speed (scenes 8 and 9 happen on the highway, scene 7 stopped at a fuel station).
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Any, Protocol

from shared.contracts import Poi, Position, Trip, UiCommand

log = logging.getLogger("drivemate.core.simulation")


class TripSource(Protocol):
    def tick(self) -> Trip: ...

    def command(self, cmd: UiCommand) -> None: ...


#: Scene presets of the demo (plan section 9): road and speed.
SCENES: dict[int, tuple[str, float]] = {
    1: ("city", 0.0),
    2: ("city", 50.0),
    3: ("city", 50.0),
    4: ("city", 50.0),
    5: ("highway", 118.0),
    6: ("highway", 118.0),
    7: ("highway", 0.0),  # stopped at the fuel station
    8: ("highway", 118.0),
    9: ("highway", 118.0),
    10: ("highway", 0.0),
}

FUEL = Poi(id="omv_km42", category="fuel", name="OMV", km=42.0, lat=45.70, lon=21.05)
CAFE = Poi(id="cafe_km60", category="cafe", name="Cafenea", km=60.0, lat=45.66, lon=20.90)


class FakeSimulator:
    """A straight route with two POIs; speed, scene, pause, time scale and "stop at the next POI" from the panel."""

    def __init__(self, clock: Any = time.monotonic) -> None:
        self.clock = clock
        self.reset()

    def reset(self) -> None:
        self.road = "city"
        self.speed_kmh = 50.0
        self.scene: int | None = None
        self.km = 30.0
        self.elapsed_min = 0.0
        self.time_scale = 1.0
        self.running = True
        self.stopped_at: Poi | None = None
        self._last = self.clock()

    def _next_poi(self) -> Poi | None:
        for poi in (FUEL, CAFE):
            if poi.km is not None and poi.km >= self.km - 0.05:
                return poi.model_copy(update={"dist_km": round(max(0.0, poi.km - self.km), 1)})
        return None

    def tick(self) -> Trip:
        now = self.clock()
        dt_h = (now - self._last) / 3600.0 * self.time_scale
        self._last = now
        speed = self.speed_kmh if self.running and self.stopped_at is None else 0.0
        if speed > 0:
            self.km += speed * dt_h
            self.elapsed_min += dt_h * 60.0
        next_poi = self._next_poi()
        eta = round((100.0 - self.km) / 80.0 * 60.0, 0)  # 100 km route, ~80 km/h on average
        return Trip(
            speed_kmh=round(speed, 1),
            road=self.road,
            elapsed_min=round(self.elapsed_min, 2),
            pos=Position(lat=round(45.75 - self.km * 0.0012, 5), lon=round(21.23 - self.km * 0.0045, 5)),
            eta_min=max(0.0, eta),
            scene=self.scene,
            stopped=speed == 0.0,
            at_poi=self.stopped_at,
            next_poi=next_poi,
        )

    def command(self, cmd: UiCommand) -> None:
        value = cmd.value
        if cmd.cmd == "scene" and isinstance(value, int) and value in SCENES:
            self.scene = value
            self.road, self.speed_kmh = SCENES[value]
            self.stopped_at = FUEL if value == 7 else None
        elif cmd.cmd == "speed" and isinstance(value, (int, float)):
            self.speed_kmh = max(0.0, float(value))
            self.stopped_at = None
        elif cmd.cmd == "time_scale" and isinstance(value, (int, float)) and value > 0:
            self.time_scale = float(value)
        elif cmd.cmd in ("start", "pause"):
            self.running = cmd.cmd == "start"
        elif cmd.cmd == "stop_at_next_poi":
            self.stopped_at = self._next_poi()
        elif cmd.cmd == "reset":
            self.reset()


def load_simulator() -> tuple[TripSource, str]:
    """P4's ``simulator.Simulator`` if it can be imported, else :class:`FakeSimulator`; returns (source, name)."""
    try:
        module = importlib.import_module("simulator")
        simulator = module.Simulator()
        return simulator, "simulator.Simulator (P4)"
    except Exception as exc:  # any failure falls back to the stand-in, with the reason logged
        log.info("using the fake simulator (%s: %s)", exc.__class__.__name__, exc)
        return FakeSimulator(), "FakeSimulator (core)"
