"""Perception main process (asyncio): camera workers -> PerceptionFrame -> core, plus the MJPEG preview.

    python -m perception.main                      # both enabled cameras -> ws://localhost:8000/ws/perception
    python -m perception.main --print --no-ws      # PerceptionFrame JSON lines on stdout, no core needed
    python -m perception.main --synthetic --print  # synthetic camera (no webcam), e.g. CI / laptops without camera
    python -m perception.main --no-models ...      # no model files: frames are valid but have no face

* One :class:`~perception.worker.CameraWorker` process per enabled camera (docs/perception.md §2).
* Every ``1 / output.publish_hz`` s the newest result of each camera is merged into one ``PerceptionFrame``
  (perception/contract.py; P2's ``shared/contracts.py`` takes over as soon as it exists).
* WebSocket client to ``output.ws_url`` with exponential backoff: runs fine without core and logs the outage once.
  Commands from core: ``dialog_window``, ``debug`` (forwarded to the workers), ``calibrate`` (gaze zones, run by the
  driver worker: ``ack`` "started", then ``calibration_prompt`` messages, then ``ack`` "done" / "error"), ``enroll``
  (``not_implemented`` until P1 step 4).
* MJPEG on ``:output.mjpeg_port``: ``/video/driver``, ``/video/passenger``; workers encode JPEGs only while a
  client is connected. ``/`` shows both, ``/health`` is JSON.
* Degradation rule (perception/degrade.py): passenger rate first, then YOLO; the driver face never.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import orjson

from perception.config import PerceptionConfig, load_config
from perception.contract import CONTRACT_SOURCE, parse_command, validate_frame
from perception.degrade import DegradeController
from perception.log import configure_logging, get_logger
from perception.perf import LatencyWindow, SystemMonitor, round_or_none
from perception.worker import CameraWorker, WorkerOptions

__all__ = ["Perception", "build_frame", "main"]

log = get_logger("perception.main")

POLL_S = 0.005
DIALOG_DEFAULT_S = 6.0  # plan E1: 6 s dialog window when core gives no end time


# --- PerceptionFrame from the worker messages ------------------------------------------------------------


def _p50(msg: dict[str, Any] | None, model: str) -> float | None:
    if not msg or msg.get("kind") != "frame":
        return None
    value = msg["perf"]["models"].get(model, {}).get("p50")
    return float(value) if value is not None else None


def _phone(cfg: PerceptionConfig, phone: dict[str, Any], gaze: dict[str, Any]) -> dict[str, Any]:
    """AS7: the detector (YOLO vote) first; the lap pattern (gaze) only when the detector sees no phone."""
    if phone["in_use"]:
        return {"in_use": True, "conf": phone["conf"], "source": "detector"}
    if gaze.get("lap_pattern"):
        return {"in_use": True, "conf": cfg.phone.lap_pattern.conf, "source": "lap_pattern"}
    return {"in_use": False, "conf": phone["conf"], "source": None}


def build_frame(
    cfg: PerceptionConfig,
    *,
    seq: int,
    ts: float,
    driver: dict[str, Any] | None,
    passenger: dict[str, Any] | None,
    cameras: dict[str, bool],
    e2e_ms_p95: float | None,
    system: dict[str, float | None],
    degrade_level: int = 0,
) -> dict[str, Any]:
    """Merge the newest worker results into a PerceptionFrame dict (plan §7 shape, P1 fields).

    ``driver`` / ``passenger``: the newest ``kind="frame"`` message of that camera, or None when the camera is down;
    ``cameras``: enabled camera -> available.
    """
    proposed = cfg.output.proposed_fields
    frame: dict[str, Any] = {"ts": round(ts, 3), "seq": seq, "occupants": [], "driver": {}, "passenger": {}, "perf": {}}

    # driver -------------------------------------------------------------------------------------------------
    d = driver if driver and driver.get("kind") == "frame" else None
    if d is not None:
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
            frame["occupants"].append({"id": 1, "seat": "driver", "source": "cam_driver", "profile": None})
        if proposed:
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
    elif proposed:
        frame["driver"] = {
            "eyes": {"state": "UNKNOWN"},
            "monitoring_ok": False,
            "monitoring_reason": "camera_unavailable",
        }

    # passenger ----------------------------------------------------------------------------------------------
    p = passenger if passenger and passenger.get("kind") == "frame" else None
    if p is not None:
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
            frame["occupants"].append({"id": 2, "seat": "front_right", "source": "cam_passenger", "profile": None})
        if proposed:
            frame["passenger"]["monitoring_reason"] = mon["reason"]
    elif proposed and "passenger" in cameras:
        frame["passenger"] = {"present": False, "monitoring_reason": "camera_unavailable"}

    # perf ---------------------------------------------------------------------------------------------------
    perf: dict[str, Any] = {"cameras": {}}
    for name, msg in (("driver", d), ("passenger", p)):
        if name not in cameras:
            continue
        cam = {"capture_fps": 0.0, "process_fps": 0.0, "dropped_frames": 0}
        if msg is not None:
            cam = {
                "capture_fps": msg["perf"]["capture_fps"],
                "process_fps": msg["perf"]["process_fps"],
                "dropped_frames": msg["perf"]["dropped_frames"],
            }
        if proposed:
            cam["available"] = cameras[name]
        perf["cameras"][name] = cam
    perf.update(
        face_driver_ms_p50=_p50(d, "face"),
        face_passenger_ms_p50=_p50(p, "face"),
        pose_ms_p50=None,  # YOLO26-pose: only for rear_seat (S feature), not run
        phone_ms_p50=_p50(d, "phone"),
        gesture_ms_p50=_p50(d, "gesture"),
        sface_ms_p50=None,  # identity (step 4) not run yet
        e2e_ms_p95=e2e_ms_p95,
        cpu=system.get("cpu"),
        ram_mb=system.get("ram_mb"),
        gpu=system.get("gpu"),
    )
    if proposed:
        perf["degrade_level"] = degrade_level
        perf["stages_ms"] = {
            name: msg["perf"]["models"] for name, msg in (("driver", d), ("passenger", p)) if msg is not None
        }
    frame["perf"] = perf
    return frame


# --- WebSocket client ---------------------------------------------------------------------------------------


class WsClient:
    """Keeps a connection to core; sends the newest frame; hands received JSON to ``on_message``."""

    def __init__(
        self, url: str, first_retry_s: float, max_retry_s: float, on_message: Callable[[dict[str, Any]], None]
    ):
        self.url = url
        self.first_retry_s = first_retry_s
        self.max_retry_s = max_retry_s
        self.on_message = on_message
        self.connected = False
        self.sent = 0
        self._outbox: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)  # frames: newest only
        self._control: asyncio.Queue[bytes] = asyncio.Queue(maxsize=256)  # acks: all of them, before frames
        self._wake = asyncio.Event()
        self._outage_logged = False

    def offer(self, data: bytes) -> None:
        """Queue the newest frame; an unsent older one is dropped (core only needs the latest state)."""
        if self._outbox.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._outbox.get_nowait()
        self._outbox.put_nowait(data)
        self._wake.set()

    def send_json(self, obj: dict[str, Any]) -> None:
        """Control messages (acks) are never dropped in favour of frames."""
        with contextlib.suppress(asyncio.QueueFull):
            self._control.put_nowait(orjson.dumps(obj))
        self._wake.set()

    async def run(self) -> None:
        import websockets

        retry = self.first_retry_s
        while True:
            try:
                async with websockets.connect(self.url, open_timeout=3, ping_interval=10, max_queue=16) as ws:
                    self.connected = True
                    retry = self.first_retry_s
                    log.info("connected to core", extra={"fields": {"url": self.url}})
                    self._outage_logged = False
                    sender = asyncio.create_task(self._send(ws))
                    try:
                        async for raw in ws:
                            try:
                                data = orjson.loads(raw)
                            except orjson.JSONDecodeError:
                                log.warning("ignored non-JSON message from core")
                                continue
                            if isinstance(data, dict):
                                self.on_message(data)
                    finally:
                        sender.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await sender
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # refused, reset, timeout: all the same, retry later
                if not self._outage_logged:
                    log.warning(
                        "core not reachable; retrying in the background (logged once until it connects)",
                        extra={"fields": {"url": self.url, "error": type(exc).__name__}},
                    )
                    self._outage_logged = True
            self.connected = False
            await asyncio.sleep(retry * random.uniform(0.8, 1.2))
            retry = min(retry * 2, self.max_retry_s)

    async def _send(self, ws: Any) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while not self._control.empty():
                await ws.send(self._control.get_nowait().decode("utf-8"))
            if not self._outbox.empty():
                await ws.send(self._outbox.get_nowait().decode("utf-8"))
                self.sent += 1


# --- the main process -----------------------------------------------------------------------------------------


_INDEX = b"""<!doctype html><meta charset="utf-8"><title>DriveMate perception</title>
<body style="background:#111;color:#ddd;font-family:sans-serif">
<h3>DriveMate perception (P1) - MJPEG preview</h3>
<div style="display:flex;gap:12px;flex-wrap:wrap">
<figure><img src="/video/driver" width="640"><figcaption>/video/driver</figcaption></figure>
<figure><img src="/video/passenger" width="640"><figcaption>/video/passenger</figcaption></figure>
</div><p><a style="color:#8cf" href="/health">/health</a></p></body>"""


class Perception:
    def __init__(
        self,
        cfg: PerceptionConfig,
        *,
        cameras: list[str],
        options: WorkerOptions,
        ws: bool = True,
        mjpeg: bool = True,
        mjpeg_port: int | None = None,
        print_frames: bool = False,
        out: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.workers = {name: CameraWorker(name, cfg, options) for name in cameras}
        self.print_frames = print_frames
        self._out = out or (lambda line: print(line, flush=True))
        self.ws: WsClient | None = (
            WsClient(cfg.output.ws_url, cfg.output.ws_reconnect_s, cfg.output.ws_reconnect_max_s, self.handle_message)
            if ws
            else None
        )
        self.mjpeg = mjpeg
        self.mjpeg_port = cfg.output.mjpeg_port if mjpeg_port is None else mjpeg_port
        self.bound_port: int | None = None
        self.degrade = DegradeController(cfg.rates)
        self.e2e = LatencyWindow(cfg.rates.perf_window)
        self.system = SystemMonitor()
        self.seq = 0
        self.frames_published = 0
        self._last_driver_seq = -1
        self._pending_capture: float | None = None  # t_capture of a driver frame not yet published
        self._clients: dict[str, int] = dict.fromkeys(self.workers, 0)
        self.acks: list[dict[str, Any]] = []
        self._calib_seen: tuple[int, str, int | None] = (0, "idle", None)  # (id, state, prompt step)

    # commands from core ------------------------------------------------------------------------------------

    def _send_event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "ack":
            self.acks.append(event)
        log.info(event.get("type", "event"), extra={"fields": event})
        if self.ws is not None:
            self.ws.send_json(event)

    def _calibration_events(self, msg: dict[str, Any]) -> None:
        """Turn the driver worker's persistent calibration state into prompt / ack messages for core."""
        cal = msg.get("calibration")
        if not cal:
            return
        prompt = cal.get("prompt") if cal["state"] == "running" else None
        key = (int(cal["id"]), str(cal["state"]), prompt["step"] if prompt else None)
        if key == self._calib_seen:
            return
        self._calib_seen = key
        if prompt is not None:
            self._send_event({"type": "calibration_prompt", "profile": cal.get("profile"), **prompt})
        elif cal["state"] in ("done", "error"):
            detail = {k: v for k, v in cal.items() if k not in ("id", "state", "prompt")}
            self._send_event({"type": "ack", "cmd": "calibrate", "status": cal["state"], "detail": detail})

    def handle_message(self, data: dict[str, Any]) -> None:
        try:
            cmd = parse_command(data)
        except Exception as exc:
            log.warning("ignored invalid command", extra={"fields": {"data": data, "error": str(exc)[:200]}})
            return
        status, detail = "ok", None
        if cmd.cmd == "debug":
            for w in self.workers.values():
                w.send({"cmd": "debug", "on": cmd.on}, persist=True)
        elif cmd.cmd == "dialog_window":
            target = "passenger" if cmd.to in ("passenger", 2) else "driver"
            seconds = (cmd.until - time.time()) if cmd.until else DIALOG_DEFAULT_S
            worker = self.workers.get(target)
            if worker is None:
                status, detail = "error", f"camera {target} not running"
            else:
                worker.send({"cmd": "dialog_window", "open": cmd.open, "until_perf": time.perf_counter() + seconds})
        elif cmd.cmd == "calibrate":
            worker = self.workers.get("driver")
            profile = cmd.profile or cmd.name
            if worker is None:
                status, detail = "error", "camera driver not running"
            elif not profile:
                status, detail = "error", "calibrate needs a profile name"
            else:
                worker.send({"cmd": "calibrate", "profile": profile, "quick": cmd.quick})
                status, detail = "started", f"profile {profile}{' (quick)' if cmd.quick else ''}"
        elif cmd.cmd == "enroll":
            status, detail = "not_implemented", "face enrolment is P1 step 4 (scripts/enroll_face.py)"
        ack = {"type": "ack", "cmd": cmd.cmd, "status": status, "detail": detail}
        self.acks.append(ack)
        log.info("command", extra={"fields": ack})
        if self.ws is not None:
            self.ws.send_json(ack)

    # loops -----------------------------------------------------------------------------------------------

    async def _pump(self) -> None:
        while True:
            for w in self.workers.values():
                msg = w.poll()
                if (
                    msg is not None
                    and w.name == "driver"
                    and msg["kind"] == "frame"
                    and msg["seq"] != self._last_driver_seq
                ):
                    self._last_driver_seq = msg["seq"]
                    self._pending_capture = msg["t_capture"]
                    self._calibration_events(msg)
            await asyncio.sleep(POLL_S)

    async def _publish(self) -> None:
        period = 1.0 / self.cfg.output.publish_hz
        next_t = time.perf_counter()
        while True:
            next_t += period
            now = time.perf_counter()
            if self._pending_capture is not None:  # e2e: capture of the newest driver frame -> this publication
                self.e2e.add((now - self._pending_capture) * 1000.0)
                self._pending_capture = None
            p95 = round_or_none(self.e2e.p95(), 1)
            change = self.degrade.update(time.monotonic(), p95)
            if change is not None:
                log.warning("degradation step", extra={"fields": {"level": change.level, "e2e_p95_ms": p95}})
                if "passenger" in self.workers:
                    self.workers["passenger"].send({"cmd": "rates", "face_hz": change.passenger_face_hz}, persist=True)
                for w in self.workers.values():
                    w.send({"cmd": "rates", "phone_hz": change.phone_hz}, persist=True)
            self.seq += 1
            data = build_frame(
                self.cfg,
                seq=self.seq,
                ts=time.time(),
                driver=self.workers["driver"].latest if "driver" in self.workers else None,
                passenger=self.workers["passenger"].latest if "passenger" in self.workers else None,
                cameras={name: w.available for name, w in self.workers.items()},
                e2e_ms_p95=p95,
                system=self.system.sample(),
                degrade_level=self.degrade.level,
            )
            frame = validate_frame(data)
            payload = orjson.dumps(frame)
            self.frames_published += 1
            if self.print_frames:
                self._out(payload.decode("utf-8"))
            if self.ws is not None:
                self.ws.offer(payload)
            await asyncio.sleep(max(0.0, next_t - time.perf_counter()))

    # MJPEG -----------------------------------------------------------------------------------------------

    async def _start_mjpeg(self) -> Any:
        from aiohttp import web

        async def index(_: web.Request) -> web.Response:
            return web.Response(body=_INDEX, content_type="text/html")

        async def health(_: web.Request) -> web.Response:
            return web.json_response(
                {
                    "contract": CONTRACT_SOURCE,
                    "cameras": {n: {"available": w.available, "restarts": w.restarts} for n, w in self.workers.items()},
                    "ws_connected": bool(self.ws and self.ws.connected),
                    "frames_published": self.frames_published,
                    "degrade_level": self.degrade.level,
                    "mjpeg_clients": self._clients,
                }
            )

        async def video(request: web.Request) -> web.StreamResponse:
            name = request.match_info["camera"]
            worker = self.workers.get(name)
            if worker is None:
                raise web.HTTPNotFound(text=f"camera {name} is not running")
            resp = web.StreamResponse(
                headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame", "Cache-Control": "no-cache"}
            )
            await resp.prepare(request)
            self._clients[name] += 1
            worker.want_jpeg(True)
            last = -1
            try:
                while True:
                    if worker.jpeg_seq != last and worker.latest_jpeg:
                        last = worker.jpeg_seq
                        jpg = worker.latest_jpeg
                        head = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpg)
                        await resp.write(head + jpg + b"\r\n")
                    await asyncio.sleep(0.5 / self.cfg.output.video_fps)
            except (ConnectionResetError, ConnectionError):
                pass
            finally:
                self._clients[name] -= 1
                if self._clients[name] <= 0:
                    worker.want_jpeg(False)  # nobody watches: the worker stops encoding
            return resp

        app = web.Application()
        app.router.add_get("/", index)
        app.router.add_get("/health", health)
        app.router.add_get("/video/{camera}", video)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.mjpeg_port)
        try:
            await site.start()
        except OSError as exc:
            log.error(
                "MJPEG port unavailable: preview disabled",
                extra={"fields": {"port": self.mjpeg_port, "error": str(exc)}},
            )
            await runner.cleanup()
            return None
        server = getattr(site, "_server", None)
        sockets = getattr(server, "sockets", None) or []
        self.bound_port = sockets[0].getsockname()[1] if sockets else self.mjpeg_port
        log.info("MJPEG preview", extra={"fields": {"url": f"http://localhost:{self.bound_port}/"}})
        return runner

    # run -------------------------------------------------------------------------------------------------

    async def run(self, seconds: float = 0.0) -> None:
        for w in self.workers.values():
            w.start()
        log.info("perception started", extra={"fields": {"cameras": list(self.workers), "contract": CONTRACT_SOURCE}})
        runner = await self._start_mjpeg() if self.mjpeg else None
        tasks = [asyncio.create_task(self._pump()), asyncio.create_task(self._publish())]
        if self.ws is not None:
            tasks.append(asyncio.create_task(self.ws.run()))
        try:
            if seconds > 0:
                await asyncio.sleep(seconds)
            else:
                await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            if runner is not None:
                await runner.cleanup()
            await asyncio.to_thread(self.stop_workers)
            self.system.close()

    def stop_workers(self) -> None:
        for w in self.workers.values():
            w.stop()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--print", dest="print_frames", action="store_true", help="PerceptionFrame JSON lines on stdout")
    p.add_argument("--no-ws", action="store_true", help="do not connect to core")
    p.add_argument("--no-mjpeg", action="store_true", help="no MJPEG preview server")
    p.add_argument("--mjpeg-port", type=int, default=None)
    p.add_argument("--synthetic", action="store_true", help="synthetic camera source (no webcam)")
    p.add_argument("--no-models", action="store_true", help="do not load models (frames without a face)")
    p.add_argument(
        "--passenger", choices=["auto", "on", "off"], default="auto", help="auto = cameras.passenger.enabled"
    )
    p.add_argument("--seconds", type=float, default=0.0, help="stop after this long (0 = until Ctrl+C)")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)

    # with --print, stdout carries only frames; logs go to stderr
    configure_logging(args.log_level, json=False, stream=sys.stderr)
    cfg = load_config(args.config)
    cameras = ["driver"]
    if args.passenger == "on" or (args.passenger == "auto" and cfg.cameras.passenger.enabled):
        cameras.append("passenger")
    options = WorkerOptions(synthetic=args.synthetic, models=not args.no_models, log_level="WARNING")
    app = Perception(
        cfg,
        cameras=cameras,
        options=options,
        ws=not args.no_ws,
        mjpeg=not args.no_mjpeg,
        mjpeg_port=args.mjpeg_port,
        print_frames=args.print_frames,
    )
    try:
        asyncio.run(app.run(args.seconds))
    except KeyboardInterrupt:
        app.stop_workers()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
