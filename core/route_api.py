"""``/simulator``: the route file drawn on the dashboard map (P4, ``#/simulator``), for a trip source that follows one.

* ``GET /simulator/route``: the active route file, where the car is on it, the revision.
* ``PUT /simulator/route``: load a route file (``simulator/route.py``); 422 with the reason when it is invalid.
* ``DELETE /simulator/route``: back to the demo trip.
* ``POST /simulator/seek`` ``{"fraction": 0.4}``: jump along the road (paused).

The car's motion stays on ``/ws/ui`` (``start``, ``pause``, ``speed``, ``time_scale``, ``stop_at_next_poi``, ``reset``)
and its result reaches everyone through ``State.trip``: the contract does not change. Mounted only when the trip
source has these methods (P4's ``simulator.Simulator``); the stand-in :class:`core.simulation.FakeSimulator` has none.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

if TYPE_CHECKING:
    from core.engine import Engine

ROUTE_METHODS = ("set_route", "clear_route", "seek", "route_status")


def _reason(exc: Exception) -> str:
    """One readable sentence: the first validation error with where it is, or the message."""
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ()))
        message = str(first.get("msg", "invalid")).removeprefix("Value error, ")
        return f"{where}: {message}" if where else message
    return str(exc)


def route_router(engine: Engine) -> APIRouter | None:
    sim: Any = engine.simulator
    if not all(callable(getattr(sim, name, None)) for name in ROUTE_METHODS):
        return None
    router = APIRouter(prefix="/simulator", tags=["simulator"])

    @router.get("/route")
    async def get_route() -> dict[str, Any]:
        return dict(sim.route_status())

    @router.put("/route")
    async def put_route(data: dict[str, Any] = Body(...)) -> dict[str, Any]:  # noqa: B008 (FastAPI's idiom)
        try:
            status = dict(sim.set_route(data))
        except (ValueError, TypeError) as exc:  # pydantic's ValidationError is a ValueError
            raise HTTPException(status_code=422, detail=_reason(exc)) from exc
        summary = status.get("summary") or {}
        stops = [s for s in summary.get("stops", []) if s.get("category") not in ("waypoint", "destination")]
        engine.log_event("route_loaded", time.time(), source=None,
                         text=f"Traseu nou: {summary.get('origin')} → {summary.get('destination')}, "
                              f"{float(summary.get('length_km') or 0):.1f} km, {len(stops)} opriri.",
                         route_id=summary.get("id"), length_km=summary.get("length_km"), stops=len(stops))
        return status

    @router.delete("/route")
    async def delete_route() -> dict[str, Any]:
        status = dict(sim.clear_route())
        engine.log_event("route_cleared", time.time(), source=None,
                         text="Traseul hărții a fost scos. Drum demonstrativ.")
        return status

    @router.post("/seek")
    async def seek(data: dict[str, Any] = Body(...)) -> dict[str, Any]:  # noqa: B008
        fraction = data.get("fraction")
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= fraction <= 1:
            raise HTTPException(status_code=422, detail="fraction: un număr între 0 și 1")
        try:
            return dict(sim.seek(float(fraction)))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
