"""The route file the dashboard map produces (``drivemate_route`` v1) and positions along it.

The dashboard (``#/simulator``) draws a road route with OSRM through the points the user placed; the first point is
the origin, the others are stops in order, the last one is the destination. It sends the file to core
(``PUT /simulator/route``) and lets the user download it as ``drivemate-route.json``::

    {"type": "drivemate_route", "version": 1, "id": "...", "name": "Cluj-Napoca → Turda",
     "origin": {"id": "p1", "name": "Cluj-Napoca", "category": "origin", "lat": 46.769, "lon": 23.589},
     "stops": [{"id": "p2", "name": "Benzinărie Gilău", "category": "fuel", "lat": ..., "lon": ...},
               {"id": "p3", "name": "Turda", "category": "destination", "lat": ..., "lon": ...}],
     "geometry": [{"lat": ..., "lon": ...}, ...], "distance_km": 61.2, "speed_kmh": 72,
     "attractions": [{"id": "wiki-ro-123", "name": "Salina Turda", "kind": "attraction", "lat": ..., "lon": ...,
                      "description": "...", "wikipedia": "ro:Salina Turda", "source": "wikipedia"}]}

Stop categories are the POI categories of the reminders (``fuel``, ``cafe``, ``pharmacy``, ``supermarket``,
``auto_parts``), ``waypoint`` (shapes the road, never a stop) and ``destination`` (the last stop, only there).
Attractions are tourist sights near the road (Wikipedia or added by hand): the road does not go through them;
the car can stop at the nearest point of the road (``category: "attraction"``).
"""

from __future__ import annotations

import bisect
import itertools
import math
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.contracts import Poi

EARTH_KM = 6371.0088
DESTINATION = "destination"
WAYPOINT = "waypoint"
ATTRACTION = "attraction"

Lat = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Lon = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: Lat
    lon: Lon


class Stop(Point):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    category: str = Field(pattern=r"^[a-z_]{1,32}$")


class Attraction(Point):
    """A tourist sight near the road. ``description`` comes from Wikipedia or the user, never from the LLM."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default=ATTRACTION, pattern=r"^[a-z_]{1,32}$")
    description: str | None = Field(default=None, max_length=300)
    wikipedia: str | None = Field(default=None, max_length=200)
    source: str = Field(default="wikipedia", max_length=20)


class RouteInput(BaseModel):
    """The route file. Unknown fields are refused: a typo must not silently drop a stop."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["drivemate_route"] = "drivemate_route"
    version: Literal[1] = 1
    id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=120)
    source: str = Field(default="dashboard_map", max_length=40)
    created_ts: float | None = Field(default=None, allow_inf_nan=False)
    origin: Stop
    stops: list[Stop] = Field(min_length=1)
    geometry: list[Point] = Field(min_length=2)
    distance_km: float | None = Field(default=None, ge=0, allow_inf_nan=False)  # as reported by the router
    speed_kmh: float | None = Field(default=None, ge=0, le=200, allow_inf_nan=False)
    attractions: list[Attraction] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self) -> RouteInput:
        if self.stops[-1].category != DESTINATION:
            raise ValueError("ultima oprire este destinația (category 'destination')")
        if any(stop.category == DESTINATION for stop in self.stops[:-1]):
            raise ValueError("numai ultima oprire poate fi destinația")
        ids = [stop.id for stop in (self.origin, *self.stops, *self.attractions)]
        if len(set(ids)) != len(ids):
            raise ValueError("id-urile punctelor trebuie să fie unice")
        return self


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(h)))


@dataclass(frozen=True)
class PlacedStop:
    """A stop (or an attraction) with its distance along the road from the origin.

    For an attraction, ``km`` is the nearest point of the road and ``detour_km`` its distance from the road.
    """

    stop: Stop
    km: float
    detour_km: float = 0.0
    attraction: Attraction | None = None

    def poi(self, from_km: float | None = None) -> Poi:
        dist = None if from_km is None else round(max(0.0, self.km - from_km), 2)
        extra: dict[str, Any] = {}
        if self.attraction is not None:  # Poi keeps unknown fields (ContractModel): the kind and the detour
            extra = {"kind": self.attraction.kind, "detour_km": round(self.detour_km, 1)}
        return Poi(id=self.stop.id, category=self.stop.category, name=self.stop.name, km=round(self.km, 3),
                   lat=self.stop.lat, lon=self.stop.lon, dist_km=dist, **extra)

    def ahead(self, from_km: float) -> dict[str, Any]:
        """An attraction ahead, as ``trip.attractions_ahead`` lists it."""
        a = self.attraction
        item: dict[str, Any] = {"id": self.stop.id, "name": self.stop.name, "kind": a.kind if a else self.stop.category,
                                "dist_km": round(max(0.0, self.km - from_km), 1), "detour_km": round(self.detour_km, 1)}
        if a is not None and a.description:
            item["description"] = a.description
        return item


class Route:
    """A validated route file: the road as a polyline with cumulative distances, and its stops placed on it."""

    def __init__(self, data: RouteInput, *, stop_offset_max_m: float, geometry_max_points: int,
                 stops_max: int, attraction_offset_max_m: float = 5000.0, attractions_max: int = 30) -> None:
        if len(data.geometry) > geometry_max_points:
            raise ValueError(f"traseul are {len(data.geometry)} puncte; maximum {geometry_max_points}")
        if len(data.stops) > stops_max:
            raise ValueError(f"traseul are {len(data.stops)} opriri; maximum {stops_max}")
        if len(data.attractions) > attractions_max:
            raise ValueError(f"traseul are {len(data.attractions)} obiective; maximum {attractions_max}")
        points: list[tuple[float, float]] = []
        for p in data.geometry:
            if not points or (p.lat, p.lon) != points[-1]:
                points.append((p.lat, p.lon))
        if len(points) < 2:
            raise ValueError("traseul trebuie să aibă cel puțin două puncte distincte")
        self.input = data
        self.points = points
        self.cumulative = [0.0]
        for a, b in itertools.pairwise(points):
            self.cumulative.append(self.cumulative[-1] + haversine_km(a, b))
        self.length_km = self.cumulative[-1]
        if self.length_km <= 0:
            raise ValueError("traseul nu are lungime")
        placed: list[PlacedStop] = []
        segment = 0
        for stop in data.stops:  # in order: each one at or after the previous one (a road may pass a place twice)
            km, segment, offset_m = self.project(stop.lat, stop.lon, first_segment=segment)
            if offset_m > stop_offset_max_m:
                raise ValueError(f"oprirea „{stop.name}” este la {offset_m:.0f} m de traseu "
                                 f"(maximum {stop_offset_max_m:.0f} m)")
            placed.append(PlacedStop(stop, km))
        placed[-1] = PlacedStop(data.stops[-1], self.length_km)  # the road ends at the destination
        self.stops = placed
        self.pois = [p for p in placed if p.stop.category != WAYPOINT]
        sights: list[PlacedStop] = []
        for sight in data.attractions:
            km, _, offset_m = self.project(sight.lat, sight.lon)
            if offset_m > attraction_offset_max_m:
                raise ValueError(f"obiectivul „{sight.name}” este la {offset_m / 1000:.1f} km de traseu "
                                 f"(maximum {attraction_offset_max_m / 1000:.1f} km)")
            stop = Stop(id=sight.id, name=sight.name, category=ATTRACTION, lat=sight.lat, lon=sight.lon)
            sights.append(PlacedStop(stop, km, offset_m / 1000.0, sight))
        self.attractions = sorted(sights, key=lambda p: p.km)
        # The named places along the road, for "where are we": the origin, every stop (waypoints too), the destination.
        self.places = [PlacedStop(data.origin, 0.0), *placed]

    @property
    def destination(self) -> PlacedStop:
        return self.stops[-1]

    def project(self, lat: float, lon: float, first_segment: int = 0) -> tuple[float, int, float]:
        """Nearest point of the road from ``first_segment`` on: (km along the road, segment, distance in m)."""
        k = math.cos(math.radians(lat))
        best = (math.inf, first_segment, 0.0)
        for i in range(first_segment, len(self.points) - 1):
            (alat, alon), (blat, blon) = self.points[i], self.points[i + 1]
            ax, ay = (alon - lon) * k, alat - lat
            dx, dy = (blon - alon) * k, blat - alat
            length2 = dx * dx + dy * dy
            t = 0.0 if length2 == 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / length2))
            px, py = ax + t * dx, ay + t * dy
            d2 = px * px + py * py
            if d2 < best[0]:
                best = (d2, i, t)
        d2, i, t = best
        km = self.cumulative[i] + t * (self.cumulative[i + 1] - self.cumulative[i])
        return km, i, math.radians(math.sqrt(d2)) * EARTH_KM * 1000.0

    def locate(self, km: float) -> tuple[float, float, float]:
        """(lat, lon, heading in degrees from north) at ``km`` along the road, clamped to its ends."""
        km = min(self.length_km, max(0.0, km))
        i = min(len(self.points) - 1, max(1, bisect.bisect_left(self.cumulative, km)))
        (alat, alon), (blat, blon) = self.points[i - 1], self.points[i]
        span = self.cumulative[i] - self.cumulative[i - 1]
        t = 0.0 if span <= 0 else (km - self.cumulative[i - 1]) / span
        r1, r2, dl = math.radians(alat), math.radians(blat), math.radians(blon - alon)
        heading = math.degrees(math.atan2(math.sin(dl) * math.cos(r2),
                                          math.cos(r1) * math.sin(r2) - math.sin(r1) * math.cos(r2) * math.cos(dl)))
        return alat + (blat - alat) * t, alon + (blon - alon) * t, heading % 360.0

    def next_poi(self, km: float, passed_km: float, skip: PlacedStop | None = None) -> PlacedStop | None:
        """The first stop ahead (one passed by less than ``passed_km`` still counts), other than ``skip``."""
        return next((p for p in self.pois if p.km >= km - passed_km and p is not skip), None)

    def find(self, poi_id: str) -> PlacedStop | None:
        """A stop (not a waypoint) or an attraction by id."""
        return next((p for p in (*self.pois, *self.attractions) if p.stop.id == poi_id), None)

    def attractions_ahead(self, km: float, passed_km: float, within_km: float) -> list[PlacedStop]:
        return [p for p in self.attractions if km - passed_km <= p.km <= km + within_km]

    def place(self, km: float) -> dict[str, Any]:
        """Where the car is, in names from the route file: the last place passed and the next one."""
        eps = 0.01
        after = next((p for p in reversed(self.places) if p.km <= km + eps), self.places[0])
        before = next((p for p in self.places if p.km > km + eps), None)
        place: dict[str, Any] = {"after": after.stop.name, "after_km": round(max(0.0, km - after.km), 1),
                                 "destination": self.destination.stop.name,
                                 "destination_km": round(max(0.0, self.length_km - km), 1)}
        if before is not None:
            place.update(before=before.stop.name, before_km=round(max(0.0, before.km - km), 1))
        return place

    def summary(self) -> dict[str, Any]:
        return {"id": self.input.id, "name": self.input.name, "origin": self.input.origin.name,
                "destination": self.destination.stop.name, "length_km": round(self.length_km, 3),
                "stops": [{"id": p.stop.id, "name": p.stop.name, "category": p.stop.category, "km": round(p.km, 3)}
                          for p in self.stops],
                "attractions": [{"id": p.stop.id, "name": p.stop.name,
                                 "kind": p.attraction.kind if p.attraction else ATTRACTION,
                                 "km": round(p.km, 3), "detour_km": round(p.detour_km, 2)} for p in self.attractions]}
