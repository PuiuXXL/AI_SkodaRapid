"""One camera = one OS process (docs/perception.md §2): capture -> models -> detectors -> result message.

* :func:`run_camera` is the process body. It owns the camera (:class:`~perception.capture.LatestFrameCamera`), the
  models (:class:`~perception.extractor.FeatureExtractor`) and the detectors
  (:class:`~perception.driver_cam.pipeline.DriverPipeline`), and talks to the main process through three queues:
  - ``results`` (maxsize 1): the newest result only; an unread older one is thrown away;
  - ``jpegs`` (maxsize 1): the overlay preview (``output.video_width`` px, ``output.jpeg_quality``,
    ``output.video_fps``), encoded **only while** ``want_jpeg`` is set (an MJPEG client is connected);
  - ``commands``: ``debug``, ``dialog_window``, ``rates`` (degradation rule), ``calibrate`` (gaze zones, driver only)
    from the main process.
* :class:`CameraWorker` is the main-process handle: start / stop / send, newest result and JPEG, and supervision:
  a dead process (or one silent for ``workers.stale_s``) is restarted with exponential backoff, and the camera is
  reported unavailable while it is down.

Messages are plain dicts (picklable, cheap). ``kind="frame"`` carries the detector output; ``kind="status"`` is a
heartbeat when no frame arrives (camera unplugged, frozen driver), so the main process always knows the state.
The gaze calibration state rides on every driver frame (``calibration``: id, state, prompt, result): ``results`` keeps
only the newest message, so a one-off "done" message could be lost; a persistent state cannot.
"""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import queue
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.queues import Queue
from multiprocessing.sharedctypes import Synchronized
from multiprocessing.synchronize import Event
from typing import Any

from perception.config import PerceptionConfig, PhoneConfig
from perception.features import FaceFeatures, FeatureFrame, HandFeatures, PhoneBox
from perception.log import get_logger

__all__ = ["CameraWorker", "GestureHold", "PhoneVoter", "WorkerOptions", "put_latest", "run_camera"]

log = get_logger("perception.worker")

STATUS_EVERY_S = 0.5


@dataclass(frozen=True)
class WorkerOptions:
    synthetic: bool = False  # SyntheticSource instead of the real camera (tests, CI, --synthetic)
    models: bool = True  # False: no models (face never present): pipeline / IPC tests without model files
    log_level: str = "WARNING"


def put_latest(q: Queue[Any], item: Any) -> None:
    """Put into a maxsize-1 queue, replacing an unread older item (the consumer only wants the newest)."""
    try:
        q.put_nowait(item)
        return
    except queue.Full:
        pass
    with contextlib.suppress(queue.Empty):
        q.get_nowait()
    with contextlib.suppress(queue.Full):  # the consumer raced us; what it got is newer than nothing
        q.put_nowait(item)


# --- small detectors that live with the camera ----------------------------------------------------------


class PhoneVoter:
    """AS7 / AP4 (detector part): phone in use if YOLO saw one in ``vote_min`` of the last ``vote_window`` runs."""

    def __init__(self, cfg: PhoneConfig) -> None:
        self.cfg = cfg
        self._votes: deque[bool] = deque(maxlen=cfg.vote_window)
        self._last: PhoneBox | None = None
        self.in_use = False
        self.conf = 0.0

    def update(self, phones: list[PhoneBox] | None) -> None:
        if phones is None:  # YOLO did not run on this frame: keep the last decision
            return
        best = max(phones, key=lambda b: b.score) if phones else None
        self._votes.append(best is not None)
        if best is not None:
            self._last = best
        self.in_use = sum(self._votes) >= self.cfg.vote_min
        self.conf = round(best.score, 3) if best is not None else (self.conf if self.in_use else 0.0)
        if not self.in_use:
            self._last = best

    def geometry(self, face: FaceFeatures, frame_w: int, frame_h: int) -> tuple[bool, str | None]:
        """(near_face, side): side in the person's terms (the image is not mirrored: image right = their left)."""
        if not self.in_use or self._last is None or not face.present or face.landmarks is None:
            return False, None
        from perception.driver_cam.face import face_box_px

        box = face_box_px(face, frame_w, frame_h)
        if box is None:
            return False, None
        fx, fy, fw, fh = box
        px = (self._last.x1 + self._last.x2) / 2
        py = (self._last.y1 + self._last.y2) / 2
        dist = ((px - (fx + fw / 2)) ** 2 + (py - (fy + fh / 2)) ** 2) ** 0.5
        near = dist <= self.cfg.near_face_ratio * fw
        return near, ("left" if px > fx + fw / 2 else "right")


class GestureHold:
    """An allowed gesture with score >= ``min_score`` held for ``min_duration_s`` (AS9 / AP6)."""

    def __init__(self, allowed: list[str], min_score: float, min_duration_s: float) -> None:
        self.allowed = set(allowed)
        self.min_score = min_score
        self.min_duration_s = min_duration_s
        self._current: str | None = None
        self._since = 0.0

    def update(self, t: float, hands: list[HandFeatures] | None) -> str | None:
        if hands is None:
            return self._current if self._current and t - self._since >= self.min_duration_s else None
        seen = [
            h.gesture
            for h in hands
            if h.gesture in self.allowed and (h.gesture_score or 0.0) >= self.min_score and h.gesture is not None
        ]
        gesture = seen[0] if seen else None
        if gesture != self._current:
            self._current, self._since = gesture, t
        return gesture if gesture and t - self._since >= self.min_duration_s else None


class _NullExtractor:
    """No models: every frame has no face (IPC / main-loop tests and CI without model files)."""

    def __init__(self) -> None:
        self.models: dict[str, dict[str, str]] = {}
        self.cadence: dict[str, int] = {}

    def extract(self, frame: Any, t: float, camera: str) -> FeatureFrame:
        return FeatureFrame(
            t=round(t, 4), frame_id=frame.frame_id, camera=camera, face=FaceFeatures(present=False, conf=0.0)
        )

    def set_phone_hz(self, rate_hz: float) -> None:
        return None

    def set_gesture(self, rate_hz: float | None) -> None:
        return None

    def close(self) -> None:
        return None


# --- process body ---------------------------------------------------------------------------------------


def _jpeg(image: Any, width: int, quality: int) -> bytes:
    import cv2

    h, w = image.shape[:2]
    if w != width:
        image = cv2.resize(image, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return bytes(buf) if ok else b""


def run_camera(
    name: str,
    cfg_data: dict[str, Any],
    options: WorkerOptions,
    results: Queue[Any],
    jpegs: Queue[Any],
    commands: Queue[Any],
    stop: Event,
    want_jpeg: Synchronized[int],
) -> None:
    """Process body (spawn). Returns when ``stop`` is set; exits with code 2 if the camera never delivers a frame."""
    import cv2

    from perception.calibration import Calibration, CalibrationRun, profile_path
    from perception.capture import LatestFrameCamera, SyntheticSource
    from perception.driver_cam.pipeline import DriverPipeline
    from perception.log import configure_logging
    from perception.monitoring import Monitor, thumbnail
    from perception.overlay import draw_driver, mean_luma
    from perception.perf import PerfTracker

    configure_logging(options.log_level, json=False)
    cfg = PerceptionConfig.model_validate(cfg_data)
    cam_cfg = getattr(cfg.cameras, name)
    out = cfg.output
    source = SyntheticSource(cam_cfg.width, cam_cfg.height, cam_cfg.fps) if options.synthetic else None
    is_driver = name == "driver"

    def status(connected: bool, reason: str) -> dict[str, Any]:
        return {
            "kind": "status",
            "camera": name,
            "t_capture": time.perf_counter(),
            "connected": connected,
            "reason": reason,
        }

    with LatestFrameCamera(cam_cfg, name, source) as cam:
        first = cam.wait_new(0, timeout=cfg.workers.first_frame_timeout_s)
        info = cam.stats().info
        if first is None or info is None:
            put_latest(results, status(False, "no_frame"))
            raise SystemExit(2)
        camera_fps = info.fps or cam_cfg.fps
        face_model = cfg.models.path(cfg.models.face_landmarker)
        extractor: Any
        if options.models and face_model.exists():
            from perception.extractor import FeatureExtractor

            # MobileGaze (gaze zones, AS5) on the driver camera only
            extractor = FeatureExtractor(cfg, camera_fps=camera_fps, camera=name, gaze=is_driver, phone=True)
        else:
            if options.models:
                log.warning("model files missing: running without models", extra={"fields": {"camera": name}})
            extractor = _NullExtractor()
        pipeline = DriverPipeline(cfg, (info.width, info.height))
        camera_meta = {"width": info.width, "height": info.height, "fps": camera_fps, "backend": info.backend}
        profile: Calibration | None = None
        if is_driver and cfg.gaze.default_profile:
            path = profile_path(cfg.gaze.default_profile)
            try:
                profile = Calibration.load(cfg, path)
                pipeline.set_calibration(profile.model, profile.ear_baseline)
                log.info("gaze profile loaded", extra={"fields": {"profile": profile.name, "tau": profile.model.tau}})
            except (OSError, ValueError) as exc:
                log.warning("gaze profile not loaded", extra={"fields": {"path": str(path), "error": str(exc)}})
        calib: CalibrationRun | None = None
        calib_status: dict[str, Any] = {"id": 0, "state": "idle", "profile": profile.name if profile else None}
        monitor = Monitor(cfg.monitoring)
        voter = PhoneVoter(cfg.phone)
        gestures = GestureHold(list(cfg.gesture.allowed), cfg.gesture.min_score, cfg.gesture.min_duration_s)
        perf = PerfTracker(cfg.rates.perf_window)
        if hasattr(extractor, "face"):
            perf.attach("face", extractor.face.latency)
            if extractor.phone_latency is not None:
                perf.attach("phone", extractor.phone_latency)
            perf.attach("gesture", extractor.gesture_latency)
            if extractor.eye_state_latency is not None:
                perf.attach("eye_state", extractor.eye_state_latency)
            if extractor.gaze_latency is not None:
                perf.attach("gaze", extractor.gaze_latency)

        face_hz = 0.0 if is_driver else cfg.rates.passenger_face_hz  # 0 = every frame (driver: never degraded)
        debug = False
        dialog_until: float | None = None
        t0 = first.t_capture
        last_id = first.frame_id - 1
        last_processed = 0.0
        last_status = 0.0
        last_jpeg = 0.0
        seq = 0

        def start_calibration(cmd: dict[str, Any]) -> None:
            nonlocal calib, calib_status
            name_ = str(cmd.get("profile") or "")
            quick = bool(cmd.get("quick"))
            status_id = int(calib_status["id"]) + 1
            try:
                if not is_driver:
                    raise ValueError("gaze calibration runs on the driver camera")
                if quick and not profile_path(name_).exists():
                    raise ValueError(f"quick recalibration needs an existing profile '{name_}'")
                calib = CalibrationRun(cfg, (info.width, info.height), name_, quick=quick, camera=camera_meta)
                calib_status = {"id": status_id, "state": "running", "profile": name_, "quick": quick}
            except ValueError as exc:
                calib = None
                calib_status = {"id": status_id, "state": "error", "profile": name_ or None, "detail": str(exc)}

        def finish_calibration(run: CalibrationRun) -> None:
            nonlocal profile, calib_status
            try:
                result = run.result()
                if run.quick:
                    result = Calibration.load(cfg, profile_path(run.name)).merged_with(cfg, result)
                path = result.save()
                profile = result
                pipeline.set_calibration(result.model, result.ear_baseline)
                calib_status = {
                    "id": calib_status["id"],
                    "state": "done",
                    "profile": result.name,
                    "quick": run.quick,
                    "loo_accuracy": result.loo_accuracy(),
                    "warnings": result.warnings(),
                    "samples": run.summary(),
                    "path": str(path),
                }
                log.info("gaze calibration saved", extra={"fields": calib_status})
            except (OSError, ValueError) as exc:
                calib_status = {"id": calib_status["id"], "state": "error", "profile": run.name, "detail": str(exc)}
                log.warning("gaze calibration failed", extra={"fields": calib_status})

        def handle(cmd: dict[str, Any]) -> None:
            nonlocal debug, dialog_until, face_hz
            kind = cmd.get("cmd")
            if kind == "calibrate":
                start_calibration(cmd)
            elif kind == "debug":
                debug = bool(cmd.get("on"))
            elif kind == "dialog_window":
                if cmd.get("open"):
                    dialog_until = cmd.get("until_perf") or (time.perf_counter() + 6.0)
                    extractor.set_gesture(cfg.rates.gaze_hz)  # gestures only inside the dialog window (AS9)
                else:
                    dialog_until = None
                    extractor.set_gesture(None)
            elif kind == "rates":
                if "phone_hz" in cmd:
                    extractor.set_phone_hz(float(cmd["phone_hz"]))
                if "face_hz" in cmd and not is_driver:
                    face_hz = float(cmd["face_hz"])

        while not stop.is_set():
            while True:
                try:
                    handle(commands.get_nowait())
                except queue.Empty:
                    break
            if dialog_until is not None and time.perf_counter() > dialog_until:
                dialog_until = None
                extractor.set_gesture(None)
            frame = cam.wait_new(last_id, timeout=0.25)
            now = time.perf_counter()
            if frame is None:
                if now - last_status >= STATUS_EVERY_S:
                    last_status = now
                    stats = cam.stats()
                    put_latest(results, status(stats.connected, "no_new_frame"))
                continue
            last_id = frame.frame_id
            if face_hz and now - last_processed < 1.0 / face_hz:
                continue  # passenger camera at its (degradable) rate
            last_processed = now
            t = frame.t_capture - t0
            with perf.time("extract"):
                ff = extractor.extract(frame, t, name)
            with perf.time("detectors"):
                state = pipeline.update(ff)
                if calib is not None:
                    prompt = calib.update(ff, state)
                    if prompt is None:
                        finish_calibration(calib)
                        calib = None
                    else:
                        calib_status = {**calib_status, "prompt": prompt.to_dict()}
                voter.update(ff.phones)
                near_face, side = voter.geometry(ff.face, info.width, info.height)
                gesture = gestures.update(t, ff.hands)
                luma = mean_luma(frame.image)
                mon = monitor.update(t, face_present=ff.face.present, thumb=thumbnail(frame.image), luma=luma)
            perf.add("e2e_worker", (time.perf_counter() - frame.t_capture) * 1000.0)
            perf.rate.tick()
            stats = cam.stats()
            seq += 1
            put_latest(
                results,
                {
                    "kind": "frame",
                    "camera": name,
                    "seq": seq,
                    "t_capture": frame.t_capture,
                    "connected": stats.connected,
                    "state": state.model_dump(mode="json"),
                    "phone": {"in_use": voter.in_use, "conf": voter.conf, "near_face": near_face, "side": side},
                    "gesture": gesture,
                    "calibration": calib_status,
                    "dialog_open": dialog_until is not None,
                    "monitoring": {"ok": mon.ok, "reason": mon.reason, "face_missing_s": mon.face_missing_s},
                    "luma": round(luma, 1),
                    "perf": {
                        "models": perf.snapshot(),
                        "capture_fps": round(stats.capture_fps, 1),
                        "process_fps": round(perf.rate.rate(), 1),
                        "dropped_frames": stats.dropped,
                        "reconnects": stats.reconnects,
                    },
                    "rates": {"face_hz": face_hz or camera_fps, "phone_every": getattr(extractor, "cadence", {})},
                },
            )
            if want_jpeg.value and now - last_jpeg >= 1.0 / out.video_fps:
                last_jpeg = now
                with perf.time("jpeg"):
                    if debug or calib is not None:
                        prompt_text = calib_status.get("prompt", {}).get("text") if calib is not None else None
                        img = draw_driver(
                            frame.image,
                            ff,
                            state,
                            fps=perf.rate.rate(),
                            luma=luma,
                            dark_luma=cfg.monitoring.dark_luma,
                            banner=prompt_text,
                        )
                    else:
                        img = frame.image.copy()
                        label = f"{name} {state.eyes.state} {'' if mon.ok else mon.reason or ''}"
                        cv2.putText(
                            img, label, (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA
                        )
                    put_latest(jpegs, _jpeg(img, out.video_width, out.jpeg_quality))
        extractor.close()


# --- main-process handle --------------------------------------------------------------------------------


class CameraWorker:
    """Start, supervise and talk to one camera process.

    ``poll()`` must be called regularly by the owner (the main loop): it drains the queues and restarts a dead or
    hung process with exponential backoff. ``available`` is False while the process is down or the camera does not
    deliver frames.
    """

    def __init__(
        self,
        name: str,
        cfg: PerceptionConfig,
        options: WorkerOptions | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.cfg = cfg
        self.options = options or WorkerOptions()
        self._ctx = mp.get_context("spawn")
        self._clock = clock
        self._proc: Any = None
        self._results: Queue[Any] | None = None
        self._jpegs: Queue[Any] | None = None
        self._commands: Queue[Any] | None = None
        self._stop: Event | None = None
        self._want_jpeg: Synchronized[int] = self._ctx.Value("b", 0)
        self._started_at = 0.0
        self._last_msg_at = 0.0
        self._got_frame = False  # stale detection only after the first frame (startup is slow)
        self._restart_at: float | None = None
        self._backoff = cfg.workers.restart_backoff_s
        self._stopping = False
        self._persist: dict[str, dict[str, Any]] = {}  # commands re-sent after a restart (rates, debug)
        self.latest: dict[str, Any] | None = None
        self.latest_jpeg: bytes | None = None
        self.jpeg_seq = 0
        self.restarts = 0
        self.available = False

    # lifecycle ---------------------------------------------------------------------------------------------

    def start(self) -> CameraWorker:
        self._stopping = False
        self._spawn()
        return self

    def _spawn(self) -> None:
        self._results = self._ctx.Queue(maxsize=1)
        self._jpegs = self._ctx.Queue(maxsize=1)
        self._commands = self._ctx.Queue()
        self._stop = self._ctx.Event()
        self._proc = self._ctx.Process(
            target=run_camera,
            name=f"perception-{self.name}",
            args=(
                self.name,
                self.cfg.model_dump(mode="json"),
                self.options,
                self._results,
                self._jpegs,
                self._commands,
                self._stop,
                self._want_jpeg,
            ),
            daemon=True,
        )
        self._proc.start()
        now = self._clock()
        self._started_at = self._last_msg_at = now
        self._got_frame = False
        self._restart_at = None
        for cmd in self._persist.values():
            self._commands.put(cmd)
        log.info("camera process started", extra={"fields": {"camera": self.name, "pid": self._proc.pid}})

    def stop(self, timeout: float = 5.0) -> int | None:
        """Ask the process to stop, wait, kill it if needed; returns its exit code."""
        self._stopping = True
        self.available = False
        proc = self._proc
        if proc is None:
            return None
        if self._stop is not None:
            self._stop.set()
        proc.join(timeout)
        if proc.is_alive():
            proc.terminate()
            proc.join(2.0)
        self._close_queues()
        self._proc = None
        return int(proc.exitcode) if proc.exitcode is not None else None

    def _close_queues(self) -> None:
        for q in (self._results, self._jpegs, self._commands):
            if q is not None:
                q.cancel_join_thread()
                q.close()

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    # communication -----------------------------------------------------------------------------------------

    def send(self, cmd: dict[str, Any], *, persist: bool = False) -> None:
        if persist:
            self._persist[str(cmd.get("cmd"))] = cmd
        if self._commands is not None and self.alive:
            self._commands.put(cmd)

    def want_jpeg(self, on: bool) -> None:
        self._want_jpeg.value = 1 if on else 0

    def poll(self) -> dict[str, Any] | None:
        """Drain the queues (newest result / JPEG) and supervise. Returns a new result or None."""
        now = self._clock()
        new: dict[str, Any] | None = None
        if self._results is not None and self._proc is not None:
            try:
                new = self._results.get_nowait()
            except (queue.Empty, OSError, ValueError):
                new = None
        if self._jpegs is not None and self._proc is not None:
            try:
                self.latest_jpeg = self._jpegs.get_nowait()
                self.jpeg_seq += 1
            except (queue.Empty, OSError, ValueError):
                pass
        if new is not None:
            self._last_msg_at = now
            self._got_frame = self._got_frame or new["kind"] == "frame"
            self.latest = new
            self.available = new["kind"] == "frame" and bool(new.get("connected", True))
            if now - self._started_at > 30.0:
                self._backoff = self.cfg.workers.restart_backoff_s  # healthy for a while: reset the backoff
        self._supervise(now)
        return new

    def _supervise(self, now: float) -> None:
        if self._stopping:
            return
        silence = self.cfg.workers.stale_s if self._got_frame else self.cfg.workers.startup_s
        if self._proc is not None and self._proc.is_alive() and now - self._last_msg_at > silence:
            log.warning("camera process hung: restarting", extra={"fields": {"camera": self.name}})
            self._proc.terminate()
            self._proc.join(2.0)
        if self._proc is not None and not self._proc.is_alive():
            log.warning(
                "camera process stopped",
                extra={"fields": {"camera": self.name, "exitcode": self._proc.exitcode, "retry_s": self._backoff}},
            )
            self._close_queues()
            self._proc = None
            self.available = False
            self.latest = None
            self._restart_at = now + self._backoff
            self._backoff = min(self._backoff * 2, self.cfg.workers.restart_backoff_max_s)
        if self._proc is None and self._restart_at is not None and now >= self._restart_at:
            self.restarts += 1
            self._spawn()
