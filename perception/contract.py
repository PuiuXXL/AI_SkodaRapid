"""The perception side of the JSON contract: ``PerceptionFrame`` (P1 -> core) and the commands core sends back.

``shared/contracts.py`` is owned by P2 and does not exist yet. Until it does, this module defines **provisional**
Pydantic models that follow ``DriveMate-PLAN-FINAL.md`` §7 field by field, for the parts P1 writes
(``roluri/P1-computer-vision.md``, "Interfețele tale"):

* ``driver.eyes / head / gaze / yawn / speaking / phone / gesture``;
* the camera-seen ``occupants`` (driver, front_right);
* the whole ``passenger`` block;
* ``perf.cameras`` and ``perf.*_ms_*``, ``cpu``, ``ram_mb``, ``gpu``.

As soon as ``shared/contracts.py`` defines ``PerceptionFrame`` (and optionally ``PerceptionCommand``),
:func:`validate_frame` and :func:`parse_command` use those instead; nothing here has to change. This file is never a
second source of truth: the provisional models are deleted when P2's contract lands (``CONTRACT_SOURCE`` tells which
one is in use).

Fields P1 produces that are **not** in the plan's contract (``closed_ms``, ``squint``, ``monitoring_reason``, ...) are
listed in docs/perception.md §9 with the exact ``CONTRACT:`` text for the group. They are sent only when
``output.proposed_fields`` is true; every model here allows extra fields, so they never break validation.
"""

from __future__ import annotations

import importlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CONTRACT_SOURCE",
    "GAZE_ZONES",
    "Command",
    "PerceptionFrame",
    "contract_source",
    "parse_command",
    "validate_frame",
]

GAZE_ZONES = (
    "road",
    "mirror_left",
    "mirror_right",
    "mirror_rear",
    "cluster",
    "infotainment",
    "lap",
    "passenger",
    "rear_seat",
    "away",
    "unknown",
)
GazeZone = Literal[
    "road",
    "mirror_left",
    "mirror_right",
    "mirror_rear",
    "cluster",
    "infotainment",
    "lap",
    "passenger",
    "rear_seat",
    "away",
    "unknown",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


# --- PerceptionFrame (plan §7, P1 fields) ----------------------------------------------------------------


class Occupant(_Model):
    id: int
    seat: Literal["driver", "front_right", "rear"]
    source: Literal["cam_driver", "cam_passenger", "declared"]
    profile: str | None = None
    role: Literal["adult", "child"] = "adult"


class Eyes(_Model):
    ear: float | None = None
    eye_used: Literal["left", "right"] | None = None
    perclos_60s: float = 0.0
    blink_ms: float | None = None
    microsleep: bool = False  # always False from P1: P2 decides from closed_ms (docs/perception.md §8)
    reliable: bool = False


class Head(_Model):
    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None
    nodding: bool = False
    answer: Literal["yes", "no"] | None = None


class Gaze(_Model):
    zone: GazeZone = "unknown"
    conf: float = 0.0
    source: Literal["face", "body"] | None = None
    off_road_ms: float = 0.0
    vats_60s: int = 0
    entropy_60s: float | None = None


class Phone(_Model):
    in_use: bool = False
    conf: float = 0.0
    source: Literal["detector", "lap_pattern"] | None = None


class Driver(_Model):
    eyes: Eyes = Field(default_factory=Eyes)
    head: Head = Field(default_factory=Head)
    gaze: Gaze = Field(default_factory=Gaze)
    yawn: bool = False
    speaking: bool = False
    phone: Phone = Field(default_factory=Phone)
    gesture: str | None = None


class Passenger(_Model):
    present: bool = False
    awake: bool = True
    eyes_closed_s: float = 0.0
    speaking: bool = False
    holding_phone: bool = False
    gesture: str | None = None
    answer: Literal["yes", "no"] | None = None


class CameraPerf(_Model):
    capture_fps: float = 0.0
    process_fps: float = 0.0
    dropped_frames: int = 0


class Perf(_Model):
    cameras: dict[str, CameraPerf] = Field(default_factory=dict)
    face_driver_ms_p50: float | None = None
    face_passenger_ms_p50: float | None = None
    pose_ms_p50: float | None = None
    phone_ms_p50: float | None = None
    gesture_ms_p50: float | None = None
    sface_ms_p50: float | None = None
    e2e_ms_p95: float | None = None
    cpu: float | None = None
    ram_mb: float | None = None
    gpu: float | None = None


class PerceptionFrame(_Model):
    """One message on ``/ws/perception`` (15 Hz)."""

    ts: float  # time.time() at the capture of the newest driver frame (publication time without driver data)
    seq: int
    occupants: list[Occupant] = Field(default_factory=list)
    driver: Driver = Field(default_factory=Driver)
    passenger: Passenger = Field(default_factory=Passenger)
    perf: Perf = Field(default_factory=Perf)


# --- commands core -> perception (plan §13: dialog_window, calibrate, debug, enroll) ---------------------


class Command(_Model):
    cmd: Literal["dialog_window", "calibrate", "debug", "enroll"]
    # dialog_window
    open: bool = False
    to: Literal["driver", "passenger"] | int | None = None  # person id (occupants[].id) or seat
    until: float | None = None  # time.time() when the window closes
    # debug
    on: bool = False
    # calibrate / enroll
    profile: str | None = None
    name: str | None = None
    quick: bool = False  # calibrate: ~15 s road + mirrors only, merged into the existing profile (proposed, §9)
    camera: Literal["driver", "passenger"] | None = None  # enroll: the camera that takes the face (proposed, §9)


# --- switch to P2's contract when it exists --------------------------------------------------------------


def _shared() -> Any | None:
    try:
        return importlib.import_module("shared.contracts")
    except ImportError:
        return None


def contract_source() -> str:
    mod = _shared()
    return "shared/contracts.py" if mod is not None and hasattr(mod, "PerceptionFrame") else "provisional (perception)"


CONTRACT_SOURCE = contract_source()


def validate_frame(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a frame dict against the contract in use; returns the JSON-ready dict (extras kept if allowed)."""
    mod = _shared()
    model: type[BaseModel] = getattr(mod, "PerceptionFrame", PerceptionFrame) if mod is not None else PerceptionFrame
    return model.model_validate(data).model_dump(mode="json")


def parse_command(data: dict[str, Any]) -> Command:
    """Accept ``{"cmd": ...}`` or ``{"type": "command", "cmd": ...}`` / ``{"type": "<cmd>", ...}`` from core."""
    payload = dict(data)
    if "cmd" not in payload and payload.get("type") in ("dialog_window", "calibrate", "debug", "enroll"):
        payload["cmd"] = payload["type"]
    payload.pop("type", None)
    mod = _shared()
    shared_cmd = getattr(mod, "PerceptionCommand", None) if mod is not None else None
    if shared_cmd is not None:
        shared_cmd.model_validate(data)  # P2's model is the authority on what is valid
    return Command.model_validate(payload)
