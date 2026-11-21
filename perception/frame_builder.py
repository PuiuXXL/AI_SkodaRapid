"""Newest camera results -> one ``PerceptionFrame`` (plan §7, the fields P1 writes), validated with Pydantic.

* Input: the newest worker message of each camera (``kind="frame"``, perception/worker.py). A camera whose newest
  result is older than ``max_age_ms`` (pending ``output.result_max_age_ms``) counts as having **no data**: its block
  keeps the contract defaults and it is reported unavailable.
* **Time.** ``ts`` = ``time.time()`` at the **capture** of the newest driver frame (the worker stamps ``t_wall``), so
  P2 can line it up with core and browser events. Without fresh driver data, ``ts`` falls back to the publication
  time. Internal durations (age, e2e, model timings) stay on ``time.perf_counter()``.
* **New modules without changing this file.** A worker module may return a ``frame_patch``: a dict in the shape of
  the PerceptionFrame (e.g. ``{"driver": {"head": {"answer": "yes"}}}``), deep-merged after the base frame. Mappings
  that are not a dict merge (lists such as ``occupants[].profile``) register a function with :func:`register_mapper`.
* :func:`build_valid_frame` validates against the contract in use (``perception.contract.validate_frame``: P2's
  ``shared/contracts.py`` as soon as it exists, the provisional models before). If a module's patch breaks
  validation, the frame is rebuilt without patches and the problem is logged once: a new module cannot stop the
  stream.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from perception.config import PerceptionConfig
from perception.contract import validate_frame
from perception.log import get_logger
from perception.perf import build_perf_block

__all__ = ["Mapper", "build_frame", "build_valid_frame", "deep_merge", "fresh_result", "register_mapper"]

log = get_logger("perception.frame_builder")

# (frame dict being built, the camera's worker message, camera name, config) -> None, mutates the frame
Mapper = Callable[[dict[str, Any], Mapping[str, Any], str, PerceptionConfig], None]
_MAPPERS: dict[str, Mapper] = {}
_patch_errors_logged: set[str] = set()

DRIVER_ID = 1
PASSENGER_ID = 2


def register_mapper(module: str) -> Callable[[Mapper], Mapper]:
    """Decorator: run ``fn(frame, msg, camera, cfg)`` for every fresh message whose ``modules`` list has ``module``."""

    def deco(fn: Mapper) -> Mapper:
        _MAPPERS[module] = fn
        return fn

    return deco


def deep_merge(base: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into ``base`` in place: dicts recursively, any other value replaces."""
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = dict(value) if isinstance(value, Mapping) else value
    return base


def result_age_ms(msg: Mapping[str, Any] | None, now_perf: float | None) -> float | None:
    if msg is None or now_perf is None or "t_capture" not in msg:
        return None
    return round(max(0.0, (now_perf - float(msg["t_capture"])) * 1000.0), 1)


def fresh_result(
    msg: Mapping[str, Any] | None, now_perf: float | None, max_age_ms: float | None
) -> Mapping[str, Any] | None:
    """The message if it is a frame result young enough to use, else None (no data from that camera)."""
    if msg is None or msg.get("kind") != "frame":
        return None
    if max_age_ms is not None:
        age = result_age_ms(msg, now_perf)
        if age is not None and age > max_age_ms:
            return None
    return msg


def _phone(cfg: PerceptionConfig, phone: Mapping[str, Any], gaze: Mapping[str, Any]) -> dict[str, Any]:
    """AS7: the detector (YOLO vote) first; the lap pattern (gaze) only when the detector sees no phone."""
    if phone["in_use"]:
        return {"in_use": True, "conf": phone["conf"], "source": "detector"}
    if gaze.get("lap_pattern"):
        return {"in_use": True, "conf": cfg.phone.lap_pattern.conf, "source": "lap_pattern"}
    return {"in_use": False, "conf": phone["conf"], "source": None}


def _driver_block(cfg: PerceptionConfig, d: Mapping[str, Any], frame: dict[str, Any]) -> None:
    st = d["state"]
    e, h, g = st["eyes"], st["head"], st["gaze"]
    mon = d["monitoring"]
    frame["driver"] = {
        "eyes": {
            "ear": e["ear"],
            "eye_used": e["eye_used"],
            "perclos_60s": e["perclos_60s"],
            "blink_ms": e["blink_ms"],
            "microsleep": False,  # P2 decides from closed_ms (docs/perception.md §8)
            "reliable": e["reliable"],
        },
        "head": {"yaw": h["yaw"], "pitch": h["pitch"], "roll": h["roll"], "nodding": h["nodding"], "answer": None},
        "gaze": {
            "zone": g["zone"],
            "conf": g["conf"],
            "source": g["source"],
            "off_road_ms": g["off_road_ms"],
            "vats_60s": g["vats_60s"],
            "entropy_60s": g["entropy_60s"],
        },
        "yawn": st["yawn"],
        "speaking": st["speaking"],
        "phone": _phone(cfg, d["phone"], g),
        "gesture": d["gesture"],
    }
    if mon["face_missing_s"] < cfg.monitoring.face_lost_s:
        frame["occupants"].append({"id": DRIVER_ID, "seat": "driver", "source": "cam_driver", "profile": None})
    if cfg.output.proposed_fields:
        ref = e["ref_left"] if e["eye_used"] == "left" else e["ref_right"]
        frame["driver"]["eyes"].update(
            closed_ms=e["closed_ms"],
            state=e["state"],
            squint=e["squint"],
            long_closure=e["long_closure"],
            blink_rate=e["blink_rate"],
            open_baseline=ref,
        )
        frame["driver"]["phone"].update(near_face=d["phone"]["near_face"], side=d["phone"]["side"])
        frame["driver"]["gaze"].update(
            calibrated=g["calibrated"], off_road_60s_ms=g["off_road_60s_ms"], lap_pattern=g["lap_pattern"]
        )
        frame["driver"].update(
            face_too_small=st["face"]["too_small"], monitoring_ok=mon["ok"], monitoring_reason=mon["reason"]
        )


def _passenger_block(cfg: PerceptionConfig, p: Mapping[str, Any], frame: dict[str, Any]) -> None:
    st, mon = p["state"], p["monitoring"]
    present = mon["face_missing_s"] < cfg.monitoring.face_lost_s
    closed_s = st["eyes"]["closed_ms"] / 1000.0
    frame["passenger"] = {
        "present": present,
        "awake": closed_s < cfg.passenger.asleep_closed_s,
        "eyes_closed_s": round(closed_s, 2),
        "speaking": st["speaking"],
        "holding_phone": p["phone"]["in_use"],
        "gesture": p["gesture"],
        "answer": None,
    }
    if present:
        frame["occupants"].append(
            {"id": PASSENGER_ID, "seat": "front_right", "source": "cam_passenger", "profile": None}
        )
    if cfg.output.proposed_fields:
        frame["passenger"]["monitoring_reason"] = mon["reason"]


def _apply_modules(
    cfg: PerceptionConfig, frame: dict[str, Any], msgs: Mapping[str, Mapping[str, Any] | None]
) -> list[str]:
    """Module patches and registered mappers; returns the names of the modules that changed the frame."""
    applied: list[str] = []
    for camera, msg in msgs.items():
        if msg is None:
            continue
        for module, patch in (msg.get("frame_patch") or {}).items():
            if isinstance(patch, Mapping) and patch:
                deep_merge(frame, patch)
                applied.append(f"{camera}.{module}")
        for module in msg.get("modules") or ():
            mapper = _MAPPERS.get(module)
            if mapper is not None:
                mapper(frame, msg, camera, cfg)
                applied.append(f"{camera}.{module}")
    return applied


def build_frame(
    cfg: PerceptionConfig,
    *,
    seq: int,
    ts: float | None = None,
    driver: Mapping[str, Any] | None,
    passenger: Mapping[str, Any] | None,
    cameras: Mapping[str, bool],
    e2e_ms_p95: float | None,
    system: Mapping[str, float | None],
    degrade_level: int = 0,
    now_perf: float | None = None,
    max_age_ms: float | None = None,
    publish_ts: float | None = None,
    patches: bool = True,
) -> dict[str, Any]:
    """Merge the newest worker results into a PerceptionFrame dict (not validated: see :func:`build_valid_frame`).

    Args:
        driver, passenger: the newest worker message of that camera, or None when the camera is down / disabled.
        cameras: enabled camera -> worker available. A stale result (older than ``max_age_ms`` at ``now_perf``)
            makes the camera unavailable in the frame too.
        ts: explicit frame time; None = capture time of the fresh driver result, else ``publish_ts``.
        now_perf: ``time.perf_counter()`` at publication (data age); None = no age check.
        patches: apply module patches / mappers (False: the plain frame, used when a patch breaks validation).
    """
    d = fresh_result(driver, now_perf, max_age_ms)
    p = fresh_result(passenger, now_perf, max_age_ms)
    available = {name: bool(up) and (d if name == "driver" else p) is not None for name, up in cameras.items()}
    if ts is None:
        if d is not None and d.get("t_wall") is not None:
            ts = float(d["t_wall"])
        elif publish_ts is not None:
            ts = publish_ts
        else:
            ts = 0.0
    proposed = cfg.output.proposed_fields
    frame: dict[str, Any] = {"ts": round(ts, 3), "seq": seq, "occupants": [], "driver": {}, "passenger": {}, "perf": {}}

    if d is not None:
        _driver_block(cfg, d, frame)
    elif proposed:
        frame["driver"] = {
            "eyes": {"state": "UNKNOWN"},
            "monitoring_ok": False,
            "monitoring_reason": "camera_unavailable",
        }

    if p is not None:
        _passenger_block(cfg, p, frame)
    elif proposed and "passenger" in cameras:
        frame["passenger"] = {"present": False, "monitoring_reason": "camera_unavailable"}

    raw = {"driver": driver, "passenger": passenger}
    timing: dict[str, tuple[float | None, float | None]] = {}
    for name in cameras:
        msg = raw.get(name)
        wall = msg.get("t_wall") if msg is not None and msg.get("kind") == "frame" else None
        timing[name] = (round(float(wall), 3) if wall is not None else None, result_age_ms(msg, now_perf))
    frame["perf"] = build_perf_block(
        available,
        {"driver": d, "passenger": p},
        e2e_ms_p95=e2e_ms_p95,
        system=system,
        proposed=proposed,
        degrade_level=degrade_level,
        timing=timing,
        publish_ts=publish_ts,
    )
    if patches:
        _apply_modules(cfg, frame, {"driver": d, "passenger": p})
    return frame


def build_valid_frame(cfg: PerceptionConfig, **kwargs: Any) -> dict[str, Any]:
    """:func:`build_frame` + contract validation; a module patch that breaks validation is dropped (logged once)."""
    data = build_frame(cfg, **kwargs)
    try:
        return validate_frame(data)
    except ValidationError as exc:
        plain = build_frame(cfg, **{**kwargs, "patches": False})
        frame = validate_frame(plain)  # without patches it must validate: if not, that is a bug here, so raise
        key = str(sorted({str(err["loc"]) for err in exc.errors()}))
        if key not in _patch_errors_logged:
            _patch_errors_logged.add(key)
            log.error(
                "module patch breaks the contract: frame sent without module patches",
                extra={"fields": {"errors": exc.errors(include_url=False)[:5]}},
            )
        return frame
