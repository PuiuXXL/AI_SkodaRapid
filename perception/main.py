"""Perception main process (asyncio): camera workers -> PerceptionFrame -> core, plus the MJPEG preview.

    python -m perception.main                          # enabled cameras -> ws://localhost:8000/ws/perception
    python -m perception.main --print --no-ws          # PerceptionFrame JSON lines on stdout, no core needed
    python -m perception.main --source synthetic       # synthetic camera (no webcam): CI, laptops without camera
    python -m perception.main --device 0 --print       # another driver camera for this run (0 = laptop webcam)
    python -m perception.main --no-models ...          # no model files: frames are valid but have no face

* One :class:`~perception.worker.CameraWorker` process per enabled camera (docs/perception.md §2); the passenger
  camera only when enabled (``cameras.passenger.enabled`` or ``--passenger on``).
* Every ``1 / output.publish_hz`` s the newest result of each camera is merged into one ``PerceptionFrame``
  (perception/frame_builder.py) with its data age: a result older than ``output.result_max_age_ms``
  counts as no data. ``ts`` = capture time of the newest driver frame.
* WebSocket client to ``output.ws_url`` with exponential backoff and jitter: runs fine without core and logs the
  outage once until the next successful connection.
* Commands from core, each answered with ``{"type": "ack", "cmd", "status", "detail"}``: ``debug`` (all cameras),
  ``dialog_window`` (the addressed camera), ``calibrate`` (always the driver camera: ``started``, then
  ``calibration_prompt`` messages, then ``done`` / ``error``; the profile is then re-sent to the worker after any
  restart), ``enroll`` (the camera in ``camera``, else ``to``, else the driver: ``started``, ``progress`` with the
  frame count, then ``done`` / ``error``); any other command goes to the addressed camera **only if its pipeline
  declares it**, otherwise it is logged and answered ``not_implemented``.
* MJPEG on ``output.mjpeg_port`` (perception/stream.py): ``/video/driver``, ``/video/passenger``, ``/``, ``/health``.
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
from perception.contract import CONTRACT_SOURCE, parse_command
from perception.degrade import DegradeController
from perception.frame_builder import build_frame, build_valid_frame
from perception.log import configure_logging, get_logger
from perception.perf import LatencyWindow, SystemMonitor, round_or_none
from perception.stream import MjpegServer
from perception.worker import CameraWorker, PipelineFactory, WorkerOptions

__all__ = ["Perception", "WsClient", "build_frame", "main"]

log = get_logger("perception.main")

POLL_S = 0.005
DIALOG_DEFAULT_S = 6.0  # plan E1: 6 s dialog window when core gives no end time


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
        factory: PipelineFactory | str | None = None,
    ) -> None:
        self.cfg = cfg
        modules: dict[str, list[str]] = {str(k): v for k, v in cfg.workers.modules.items()}
        self.workers = {
            name: CameraWorker(name, cfg, options, factory=factory, modules=modules.get(name, [])) for name in cameras
        }
        self.print_frames = print_frames
        self._out = out or (lambda line: print(line, flush=True))
        self.ws: WsClient | None = (
            WsClient(cfg.output.ws_url, cfg.output.ws_reconnect_s, cfg.output.ws_reconnect_max_s, self.handle_message)
            if ws
            else None
        )
        self.stream: MjpegServer | None = (
            MjpegServer(
                self.workers,
                host=cfg.output.mjpeg_host,
                port=cfg.output.mjpeg_port if mjpeg_port is None else mjpeg_port,
                fps=cfg.output.video_fps,
                health=self._health,
            )
            if mjpeg
            else None
        )
        self.degrade = DegradeController(cfg.rates)
        self.e2e = LatencyWindow(cfg.rates.perf_window)
        self.system = SystemMonitor()
        self.seq = 0
        self.frames_published = 0
        self.last_frame: dict[str, Any] | None = None
        self._last_driver_seq = -1
        self._pending_capture: float | None = None  # t_capture of a driver frame not yet published
        self.acks: list[dict[str, Any]] = []
        self._calib_seen: tuple[int, str, int | None] = (0, "idle", None)  # (id, state, prompt step)
        self._enroll_seen: dict[str, tuple[int, str, int]] = {}  # camera -> (id, state, frame count)
        self._last_seq: dict[str, int] = {}

    @property
    def bound_port(self) -> int | None:
        return self.stream.bound_port if self.stream is not None else None

    def _health(self) -> dict[str, Any]:
        return {
            "contract": CONTRACT_SOURCE,
            "cameras": {
                n: {"available": w.available, "restarts": w.restarts, "commands": sorted(w.capabilities or ())}
                for n, w in self.workers.items()
            },
            "ws_connected": bool(self.ws and self.ws.connected),
            "frames_published": self.frames_published,
            "degrade_level": self.degrade.level,
        }

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
            driver = self.workers.get("driver")
            if cal["state"] == "done" and cal.get("profile") and driver is not None:
                # persisted: a restarted driver worker loads this calibration again instead of starting uncalibrated
                driver.send({"cmd": "load_profile", "profile": cal["profile"]}, persist=True)

    def _enroll_events(self, camera: str, msg: dict[str, Any]) -> None:
        """Persistent enrollment state of a camera (``identity.enroll``) -> ``progress`` / ``done`` / ``error`` acks."""
        enroll = (msg.get("identity") or {}).get("enroll")
        if not enroll or enroll.get("state") not in ("running", "done", "error"):
            return
        key = (int(enroll.get("id") or 0), str(enroll["state"]), int(enroll.get("count") or 0))
        if self._enroll_seen.get(camera) == key:
            return
        self._enroll_seen[camera] = key
        status = "progress" if enroll["state"] == "running" else enroll["state"]
        detail = {k: v for k, v in enroll.items() if k not in ("id", "state")}
        self._send_event({"type": "ack", "cmd": "enroll", "status": status, "detail": {"camera": camera, **detail}})

    def _route(self, cmd: Any) -> tuple[str, str | None]:
        """Send a command to the camera(s) it is for; returns the ack (status, detail)."""
        target = "passenger" if cmd.to in ("passenger", 2) else "driver"
        if cmd.cmd == "calibrate":
            target = "driver"  # gaze zones exist only on the driver camera
        elif cmd.cmd == "enroll" and getattr(cmd, "camera", None):
            target = cmd.camera
        if cmd.cmd == "debug":
            for w in self.workers.values():
                w.send({"cmd": "debug", "on": cmd.on}, persist=True)
            return "ok", None
        worker = self.workers.get(target)
        if worker is None:
            return "error", f"camera {target} not running"
        if cmd.cmd == "dialog_window":
            seconds = (cmd.until - time.time()) if cmd.until else DIALOG_DEFAULT_S
            worker.send({"cmd": "dialog_window", "open": cmd.open, "until_perf": time.perf_counter() + seconds})
            return "ok", None
        if cmd.cmd == "calibrate":
            profile = cmd.profile or cmd.name
            if not profile:
                return "error", "calibrate needs a profile name"
            worker.send({"cmd": "calibrate", "profile": profile, "quick": cmd.quick})
            return "started", f"profile {profile}{' (quick)' if cmd.quick else ''}"
        # enroll and any later command: only to a pipeline that declares it
        payload = {k: v for k, v in cmd.model_dump(mode="json").items() if v is not None}
        if cmd.cmd == "enroll":
            payload["camera"] = target
            if not (cmd.name or cmd.profile):
                return "error", "enroll needs a name"
        if worker.capabilities is None:  # the worker has not reported yet: send, it logs it if nothing handles it
            worker.send(payload)
            return "queued", f"camera {target} starting"
        if cmd.cmd in worker.capabilities:
            worker.send(payload)
            return ("started", f"camera {target}") if cmd.cmd == "enroll" else ("ok", None)
        log.info("command without a module yet: logged only", extra={"fields": {"cmd": cmd.cmd, "camera": target}})
        return "not_implemented", f"no module handles '{cmd.cmd}' on camera {target} yet"

    def handle_message(self, data: dict[str, Any]) -> None:
        try:
            cmd = parse_command(data)
        except Exception as exc:
            log.warning("ignored invalid command", extra={"fields": {"data": data, "error": str(exc)[:200]}})
            return
        status, detail = self._route(cmd)
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
                if msg is None or msg["kind"] != "frame" or msg["seq"] == self._last_seq.get(w.name):
                    continue
                self._last_seq[w.name] = msg["seq"]
                self._enroll_events(w.name, msg)
                if w.name == "driver":
                    self._last_driver_seq = msg["seq"]
                    self._pending_capture = msg["t_capture"]
                    self._calibration_events(msg)
            await asyncio.sleep(POLL_S)

    def _degrade(self, p95: float | None) -> None:
        change = self.degrade.update(time.monotonic(), p95)
        if change is None:
            return
        log.warning("degradation step", extra={"fields": {"level": change.level, "e2e_p95_ms": p95}})
        # one "rates" command per camera: the persisted copy (re-sent after a restart) must carry both rates
        for name, w in self.workers.items():
            cmd: dict[str, Any] = {"cmd": "rates", "phone_hz": change.phone_hz}
            if name == "passenger":  # the driver face is never degraded
                cmd["face_hz"] = change.passenger_face_hz
            w.send(cmd, persist=True)

    def publish_once(self) -> dict[str, Any]:
        """Build, validate and send one PerceptionFrame from the newest results (also used by tests)."""
        now = time.perf_counter()
        if self._pending_capture is not None:  # e2e: capture of the newest driver frame -> this publication
            self.e2e.add((now - self._pending_capture) * 1000.0)
            self._pending_capture = None
        p95 = round_or_none(self.e2e.p95(), 1)
        self._degrade(p95)
        self.seq += 1
        frame = build_valid_frame(
            self.cfg,
            seq=self.seq,
            driver=self.workers["driver"].latest if "driver" in self.workers else None,
            passenger=self.workers["passenger"].latest if "passenger" in self.workers else None,
            cameras={name: w.available for name, w in self.workers.items()},
            e2e_ms_p95=p95,
            system=self.system.sample(),
            degrade_level=self.degrade.level,
            now_perf=now,
            max_age_ms=self.cfg.output.result_max_age_ms,
            publish_ts=time.time(),
        )
        payload = orjson.dumps(frame)
        self.frames_published += 1
        self.last_frame = frame
        if self.print_frames:
            self._out(payload.decode("utf-8"))
        if self.ws is not None:
            self.ws.offer(payload)
        return frame

    async def _publish(self) -> None:
        """``publish_hz`` on average, each frame sent as soon as a fresh driver result is in.

        A free-running tick would make a driver result wait up to one period (66 ms at 15 Hz) before it is sent, and
        that wait counts in the e2e budget (capture -> publication < 150 ms p95). Here a frame is due every period; it
        goes out on the first fresh driver result within ``slack`` before the due time, or at ``due + slack`` without
        one (driver camera down: the frame still goes out, with the camera reported unavailable).
        """
        period = 1.0 / self.cfg.output.publish_hz
        slack = min(0.35 * period, 0.025)
        due = time.perf_counter()
        while True:
            now = time.perf_counter()
            if (self._pending_capture is not None and now >= due - slack) or now >= due + slack:
                self.publish_once()
                due = max(due + period, now + 0.5 * period)  # average rate kept, no catch-up bursts
            await asyncio.sleep(POLL_S)

    # run -------------------------------------------------------------------------------------------------

    async def run(self, seconds: float = 0.0) -> None:
        for w in self.workers.values():
            w.start()
        log.info("perception started", extra={"fields": {"cameras": list(self.workers), "contract": CONTRACT_SOURCE}})
        if self.stream is not None:
            await self.stream.start()
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
            if self.stream is not None:
                await self.stream.stop()
            await asyncio.to_thread(self.stop_workers)
            self.system.close()

    def stop_workers(self) -> None:
        for w in self.workers.values():
            w.stop()


def _with_driver_device(cfg: PerceptionConfig, device: str) -> PerceptionConfig:
    """``--device``: another driver camera for this run only (the yaml stays as it is)."""
    value: int | str = int(device) if device.isdigit() else device
    data = cfg.model_dump(mode="json")
    data["cameras"]["driver"]["device"] = value
    return PerceptionConfig.model_validate(data)  # re-validated: e.g. the same device as the passenger is refused


def log_camera_table(cfg: PerceptionConfig, cameras: list[str]) -> str:
    """Start-up log: every capture device (index, name, VID:PID) and which camera gets it, with the same selection
    the workers use (perception/capture.py ``select_device``). Returns the table text."""
    from perception.capture import assignment_rows, list_devices

    rows, assigned = assignment_rows(cfg.cameras, list_devices(), cameras)
    lines = ["capture devices:", f"  {'idx':>3}  {'name':<44} {'vid:pid':<10} assigned"]
    lines += [f"  {r['index']:>3}  {r['name'][:44]:<44} {r['vid_pid']:<10} {r['assigned']}" for r in rows]
    if not rows:
        lines.append("  (none found)")
    lines += [f"  {cam}: {how}" for cam, how in assigned.items()]
    text = "\n".join(lines)
    log.info(text)
    for cam, how in assigned.items():
        if how.startswith("NOT FOUND"):
            log.warning("camera_unavailable at start", extra={"fields": {"camera": cam}})
        elif how.startswith("fallback"):
            log.warning("camera on the development fallback", extra={"fields": {"camera": cam, "device": how}})
    return text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--print", dest="print_frames", action="store_true", help="PerceptionFrame JSON lines on stdout")
    p.add_argument("--no-ws", action="store_true", help="do not connect to core")
    p.add_argument("--no-mjpeg", action="store_true", help="no MJPEG preview server")
    p.add_argument("--mjpeg-port", type=int, default=None)
    p.add_argument("--source", choices=["camera", "synthetic"], default="camera", help="camera or synthetic frames")
    p.add_argument("--synthetic", action="store_true", help="same as --source synthetic")
    p.add_argument("--device", default=None, help="driver camera for this run (OpenCV index, path or URL)")
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
    if args.device is not None:
        cfg = _with_driver_device(cfg, args.device)
    cameras = ["driver"]
    if args.passenger == "on" or (args.passenger == "auto" and cfg.cameras.passenger.enabled):
        cameras.append("passenger")
    synthetic = args.synthetic or args.source == "synthetic"
    if not synthetic:
        log_camera_table(cfg, cameras)
    options = WorkerOptions(synthetic=synthetic, models=not args.no_models, log_level="WARNING")
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
