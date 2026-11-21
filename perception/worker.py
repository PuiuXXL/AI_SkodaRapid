"""One camera = one OS process (docs/perception.md §2): capture -> injected pipeline -> result message.

* :func:`run_camera` is the process body. It owns the camera (:class:`~perception.capture.LatestFrameCamera`) and a
  :class:`CameraPipeline` built **inside the process** by a factory (injected, so the integration can add modules
  without editing this loop), and talks to the main process through three queues:
  - ``results`` (maxsize 1): the newest result only; an unread older one is thrown away (counted: ``dropped_results``);
  - ``jpegs`` (maxsize 1): the overlay preview (``output.video_width`` px, ``output.jpeg_quality``,
    ``output.video_fps``), rendered and encoded **only while** ``want_jpeg`` is set (an MJPEG client is connected);
  - ``commands``: ``debug``, ``dialog_window``, ``calibrate``, ``rates`` (degradation rule), and anything a module
    declares (``enroll`` once identity exists). A command no module handles is only logged.
* :class:`ModularPipeline` (the default) = the feature extractor (models) + an ordered list of
  :class:`PipelineModule`. Built-in modules wrap the existing detectors: ``detectors`` (DriverPipeline), ``calibration``
  (driver only), ``phone`` (YOLO vote + geometry), ``gesture`` (dialog window), ``monitoring``. Extra modules come from
  pending ``workers.modules.<camera>`` (``"package.module:Class"``), constructed as ``Class(ctx, extractor)``.
* :class:`CameraWorker` is the main-process handle: start / stop / send, newest result and JPEG, and supervision:
  a dead process (or one silent for ``workers.stale_s``) is restarted with exponential backoff, and the camera is
  reported unavailable while it is down.

Messages are plain dicts (picklable, cheap). ``kind="frame"`` carries the pipeline output plus ``t_capture``
(``perf_counter``) and ``t_wall`` (``time.time()`` at capture); ``kind="status"`` is a heartbeat when no frame arrives
(camera unplugged, frozen driver), so the main process always knows the state. The gaze calibration state rides on
every driver frame (``calibration``: id, state, prompt, result): ``results`` keeps only the newest message, so a
one-off "done" message could be lost; a persistent state cannot.
"""

from __future__ import annotations

import contextlib
import importlib
import multiprocessing as mp
import queue
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from multiprocessing.queues import Queue
from multiprocessing.sharedctypes import Synchronized
from multiprocessing.synchronize import Event
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from perception.config import PerceptionConfig, PhoneConfig
from perception.features import FaceFeatures, FeatureFrame, HandFeatures, PhoneBox
from perception.log import get_logger

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    from perception.calibration import Calibration, CalibrationRun
    from perception.capture import Frame
    from perception.driver_cam.pipeline import DriverPipeline
    from perception.perf import PerfTracker

    Image = npt.NDArray[np.uint8]

__all__ = [
    "CameraContext",
    "CameraPipeline",
    "CameraWorker",
    "FrameInput",
    "GestureHold",
    "ModularPipeline",
    "PhoneVoter",
    "PipelineFactory",
    "PipelineModule",
    "WorkerOptions",
    "default_pipeline",
    "put_latest",
    "resolve_factory",
    "run_camera",
]

log = get_logger("perception.worker")

STATUS_EVERY_S = 0.5
WORKER_COMMANDS = frozenset({"debug", "rates"})  # handled by the loop itself (overlay flag, passenger face rate)


@dataclass(frozen=True)
class WorkerOptions:
    synthetic: bool = False  # SyntheticSource instead of the real camera (tests, CI, --source synthetic)
    models: bool = True  # False: no models (face never present): pipeline / IPC tests without model files
    log_level: str = "WARNING"


def put_latest(q: Queue[Any], item: Any) -> bool:
    """Put into a maxsize-1 queue, replacing an unread older item (the consumer only wants the newest).

    Returns True when an unread older item was thrown away.
    """
    try:
        q.put_nowait(item)
        return False
    except queue.Full:
        pass
    dropped = False
    with contextlib.suppress(queue.Empty):
        q.get_nowait()
        dropped = True
    with contextlib.suppress(queue.Full):  # the consumer raced us; what it got is newer than nothing
        q.put_nowait(item)
    return dropped


# --- the injected interface -----------------------------------------------------------------------------


@dataclass(frozen=True)
class CameraContext:
    """What a pipeline knows about its camera; built in the worker process once the camera delivers frames."""

    name: str  # "driver" | "passenger"
    cfg: PerceptionConfig
    options: WorkerOptions
    width: int
    height: int
    fps: float
    backend: str
    modules: tuple[str, ...] = ()  # extra PipelineModule classes, "package.module:Class"

    @property
    def is_driver(self) -> bool:
        return self.name == "driver"


@dataclass
class FrameInput:
    """One captured frame as the pipeline sees it."""

    frame: Frame
    t: float  # seconds since the first frame of this process (detector clock, from perf_counter)
    t_wall: float  # time.time() at capture (contract ts)
    debug: bool = False
    shared: dict[str, Any] = field(default_factory=dict)  # live objects passed between modules within this frame


@runtime_checkable
class CameraPipeline(Protocol):
    """What :func:`run_camera` drives. Built in the worker process by a :data:`PipelineFactory`."""

    commands: frozenset[str]  # commands it handles, advertised to the main process in every message

    def process(self, inp: FrameInput) -> dict[str, Any]:
        """Run on one frame; returns the payload merged into the result message (picklable, JSON-friendly)."""
        ...

    def handle(self, cmd: dict[str, Any]) -> bool:
        """Apply a command from the main process; False when nothing handled it (the worker logs it)."""
        ...

    def render(self, inp: FrameInput, payload: dict[str, Any], *, debug: bool, fps: float) -> Image:
        """The image for the MJPEG preview (called only while a client watches)."""
        ...

    def close(self) -> None: ...


# (camera context, the process's perf tracker) -> pipeline. Must be picklable for spawn: a module-level callable, or
# a "package.module:attr" string resolved inside the worker process.
PipelineFactory = Callable[["CameraContext", "PerfTracker"], CameraPipeline]


class PipelineModule(Protocol):
    """One step of :class:`ModularPipeline`.

    ``update`` returns a dict merged into the result message (namespace your keys: ``{"identity": {...}}``), or None.
    A ``"frame_patch"`` key in it is not merged: it goes to ``msg["frame_patch"][name]`` and frame_builder deep-merges
    it into the PerceptionFrame (e.g. ``{"driver": {"head": {"answer": "yes"}}}``). Live objects for later modules go
    in ``inp.shared`` (``ff``, ``state``, ``luma``, ``banner`` are set by the built-ins). An optional
    ``draw(img, inp) -> None`` adds to the debug overlay.
    """

    name: str
    commands: frozenset[str]

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any] | None: ...

    def handle(self, cmd: dict[str, Any]) -> bool: ...

    def close(self) -> None: ...


def _import(path: str) -> Any:
    module, _, attr = path.partition(":")
    if not module or not attr:
        raise ValueError(f"expected 'package.module:attr', got {path!r}")
    return getattr(importlib.import_module(module), attr)


def resolve_factory(factory: PipelineFactory | str | None) -> PipelineFactory:
    if factory is None:
        return default_pipeline
    if isinstance(factory, str):
        resolved: PipelineFactory = _import(factory)
        return resolved
    return factory


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


# --- built-in modules (the existing detectors, unchanged behaviour) -------------------------------------


class DetectorsModule:
    """Eyes, head, mouth, gaze zones (DriverPipeline) -> ``state``; also run on the passenger camera."""

    name = "detectors"
    commands: frozenset[str] = frozenset()

    def __init__(self, ctx: CameraContext, extractor: Any) -> None:
        from perception.driver_cam.pipeline import DriverPipeline

        self.pipeline: DriverPipeline = DriverPipeline(ctx.cfg, (ctx.width, ctx.height))

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        state = self.pipeline.update(ff)
        inp.shared["state"] = state
        return {"state": state.model_dump(mode="json")}

    def handle(self, cmd: dict[str, Any]) -> bool:
        return False

    def close(self) -> None:
        return None


class CalibrationModule:
    """Gaze calibration (``calibrate`` command, driver camera): profile load at start, run, save (§3.4)."""

    name = "calibration"
    commands = frozenset({"calibrate"})

    def __init__(self, ctx: CameraContext, detectors: DetectorsModule) -> None:
        from perception.calibration import Calibration, profile_path

        self.ctx = ctx
        self.detectors = detectors
        self.camera_meta = {"width": ctx.width, "height": ctx.height, "fps": ctx.fps, "backend": ctx.backend}
        self.profile: Calibration | None = None
        self.run: CalibrationRun | None = None
        cfg = ctx.cfg
        if cfg.gaze.default_profile:
            path = profile_path(cfg.gaze.default_profile)
            try:
                self.profile = Calibration.load(cfg, path)
                detectors.pipeline.set_calibration(self.profile.model, self.profile.ear_baseline)
                log.info(
                    "gaze profile loaded",
                    extra={"fields": {"profile": self.profile.name, "tau": self.profile.model.tau}},
                )
            except (OSError, ValueError) as exc:
                log.warning("gaze profile not loaded", extra={"fields": {"path": str(path), "error": str(exc)}})
        self.status: dict[str, Any] = {
            "id": 0,
            "state": "idle",
            "profile": self.profile.name if self.profile else None,
        }

    def handle(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("cmd") != "calibrate":
            return False
        from perception.calibration import CalibrationRun, profile_path

        name = str(cmd.get("profile") or "")
        quick = bool(cmd.get("quick"))
        status_id = int(self.status["id"]) + 1
        try:
            if quick and not profile_path(name).exists():
                raise ValueError(f"quick recalibration needs an existing profile '{name}'")
            self.run = CalibrationRun(
                self.ctx.cfg, (self.ctx.width, self.ctx.height), name, quick=quick, camera=self.camera_meta
            )
            self.status = {"id": status_id, "state": "running", "profile": name, "quick": quick}
        except ValueError as exc:
            self.run = None
            self.status = {"id": status_id, "state": "error", "profile": name or None, "detail": str(exc)}
        return True

    def _finish(self, run: CalibrationRun) -> None:
        from perception.calibration import Calibration, profile_path

        cfg = self.ctx.cfg
        try:
            result = run.result()
            if run.quick:
                result = Calibration.load(cfg, profile_path(run.name)).merged_with(cfg, result)
            path = result.save()
            self.profile = result
            self.detectors.pipeline.set_calibration(result.model, result.ear_baseline)
            self.status = {
                "id": self.status["id"],
                "state": "done",
                "profile": result.name,
                "quick": run.quick,
                "loo_accuracy": result.loo_accuracy(),
                "warnings": result.warnings(),
                "samples": run.summary(),
                "path": str(path),
            }
            log.info("gaze calibration saved", extra={"fields": self.status})
        except (OSError, ValueError) as exc:
            self.status = {"id": self.status["id"], "state": "error", "profile": run.name, "detail": str(exc)}
            log.warning("gaze calibration failed", extra={"fields": self.status})

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        if self.run is not None:
            prompt = self.run.update(ff, inp.shared["state"])
            if prompt is None:
                self._finish(self.run)
                self.run = None
            else:
                self.status = {**self.status, "prompt": prompt.to_dict()}
                inp.shared["banner"] = prompt.text
        return {"calibration": self.status}

    def close(self) -> None:
        return None


class PhoneModule:
    """AS7 / AP4 detector part: 3-of-5 YOLO vote + near_face / side; applies the degraded YOLO rate."""

    name = "phone"
    commands: frozenset[str] = frozenset()

    def __init__(self, ctx: CameraContext, extractor: Any) -> None:
        self.ctx = ctx
        self.extractor = extractor
        self.voter = PhoneVoter(ctx.cfg.phone)

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        self.voter.update(ff.phones)
        near_face, side = self.voter.geometry(ff.face, self.ctx.width, self.ctx.height)
        return {"phone": {"in_use": self.voter.in_use, "conf": self.voter.conf, "near_face": near_face, "side": side}}

    def handle(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("cmd") == "rates" and "phone_hz" in cmd:
            self.extractor.set_phone_hz(float(cmd["phone_hz"]))
            return True
        return False

    def close(self) -> None:
        return None


class GestureModule:
    """AS9 / AP6: Gesture Recognizer on only inside the dialog window; gesture held ``min_duration_s``."""

    name = "gesture"
    commands = frozenset({"dialog_window"})

    def __init__(self, ctx: CameraContext, extractor: Any) -> None:
        cfg = ctx.cfg
        self.cfg = cfg
        self.extractor = extractor
        self.hold = GestureHold(list(cfg.gesture.allowed), cfg.gesture.min_score, cfg.gesture.min_duration_s)
        self.dialog_until: float | None = None  # perf_counter

    def handle(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("cmd") != "dialog_window":
            return False
        if cmd.get("open"):
            self.dialog_until = cmd.get("until_perf") or (time.perf_counter() + 6.0)
            self.extractor.set_gesture(self.cfg.rates.gaze_hz)
        else:
            self.dialog_until = None
            self.extractor.set_gesture(None)
        return True

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        if self.dialog_until is not None and time.perf_counter() > self.dialog_until:
            self.dialog_until = None
            self.extractor.set_gesture(None)
        return {"gesture": self.hold.update(inp.t, ff.hands), "dialog_open": self.dialog_until is not None}

    def close(self) -> None:
        return None


class MonitoringModule:
    """AS12 / AP5: camera frozen / covered / face lost (perception/monitoring.py) + mean luma."""

    name = "monitoring"
    commands: frozenset[str] = frozenset()

    def __init__(self, ctx: CameraContext, extractor: Any) -> None:
        from perception.monitoring import Monitor

        self.monitor = Monitor(ctx.cfg.monitoring)

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        from perception.monitoring import thumbnail
        from perception.overlay import mean_luma

        image = inp.frame.image
        luma = mean_luma(image)
        inp.shared["luma"] = luma
        mon = self.monitor.update(inp.t, face_present=ff.face.present, thumb=thumbnail(image), luma=luma)
        inp.shared["monitoring"] = mon
        return {
            "monitoring": {"ok": mon.ok, "reason": mon.reason, "face_missing_s": mon.face_missing_s},
            "luma": round(luma, 1),
        }

    def handle(self, cmd: dict[str, Any]) -> bool:
        return False

    def close(self) -> None:
        return None


# --- the default pipeline -------------------------------------------------------------------------------


class ModularPipeline:
    """Feature extractor + ordered modules. Built-in module errors propagate (the process restarts); an extra
    module that raises is logged once and skipped for that frame, so it cannot stop the camera."""

    def __init__(
        self,
        ctx: CameraContext,
        perf: PerfTracker,
        extractor: Any,
        modules: Sequence[PipelineModule],
        *,
        builtin: int,
    ) -> None:
        self.ctx = ctx
        self.perf = perf
        self.extractor = extractor
        self.modules = list(modules)
        self._builtin = {m.name for m in self.modules[:builtin]}
        self._failed: set[str] = set()
        self.debug = False
        self.commands = frozenset({"debug"}).union(*(m.commands for m in self.modules))
        for model, attr in (
            ("phone", "phone_latency"),
            ("gesture", "gesture_latency"),
            ("eye_state", "eye_state_latency"),
            ("gaze", "gaze_latency"),
        ):
            window = getattr(extractor, attr, None)
            if window is not None:
                perf.attach(model, window)
        face = getattr(extractor, "face", None)
        if face is not None:
            perf.attach("face", face.latency)

    @property
    def cadence(self) -> dict[str, int]:
        cadence: dict[str, int] = getattr(self.extractor, "cadence", {})
        return cadence

    def process(self, inp: FrameInput) -> dict[str, Any]:
        with self.perf.time("extract"):
            ff = self.extractor.extract(inp.frame, inp.t, self.ctx.name)
        inp.shared["ff"] = ff
        payload: dict[str, Any] = {}
        patches: dict[str, Any] = {}
        with self.perf.time("detectors"):
            for m in self.modules:
                with self.perf.time(f"{m.name}_module"):
                    try:
                        out = m.update(ff, inp)
                    except Exception:
                        if m.name in self._builtin:
                            raise
                        if m.name not in self._failed:
                            self._failed.add(m.name)
                            log.exception("extra module failed (skipped)", extra={"fields": {"module": m.name}})
                        continue
                if out:
                    patch = out.pop("frame_patch", None)
                    if patch:
                        patches[m.name] = patch
                    payload.update(out)
        payload["modules"] = [m.name for m in self.modules]
        if patches:
            payload["frame_patch"] = patches
        return payload

    def handle(self, cmd: dict[str, Any]) -> bool:
        handled = False
        if cmd.get("cmd") == "debug":
            self.debug = bool(cmd.get("on"))
            handled = True
        for m in self.modules:
            try:
                handled = m.handle(cmd) or handled
            except Exception:
                if m.name in self._builtin:
                    raise
                log.exception("extra module failed on a command", extra={"fields": {"module": m.name}})
        return handled

    def render(self, inp: FrameInput, payload: dict[str, Any], *, debug: bool, fps: float) -> Image:
        import cv2

        from perception.overlay import draw_driver

        banner = inp.shared.get("banner")
        state = inp.shared.get("state")
        if debug or banner is not None:
            img = draw_driver(
                inp.frame.image,
                inp.shared.get("ff"),
                state,
                fps=fps,
                luma=inp.shared.get("luma"),
                dark_luma=self.ctx.cfg.monitoring.dark_luma,
                banner=banner,
            )
            for m in self.modules:
                draw = getattr(m, "draw", None)
                if draw is not None:
                    draw(img, inp)
            return img
        img = inp.frame.image.copy()
        mon = payload.get("monitoring") or {}
        eyes = state.eyes.state if state is not None else ""
        label = f"{self.ctx.name} {eyes} {'' if mon.get('ok', True) else mon.get('reason') or ''}"
        cv2.putText(img, label, (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        return img

    def close(self) -> None:
        for m in self.modules:
            with contextlib.suppress(Exception):
                m.close()
        self.extractor.close()


def make_extractor(ctx: CameraContext) -> Any:
    """FeatureExtractor when the model files exist (and models are on), else a no-face stand-in."""
    cfg = ctx.cfg
    if ctx.options.models and cfg.models.path(cfg.models.face_landmarker).exists():
        from perception.extractor import FeatureExtractor

        # MobileGaze (gaze zones, AS5) on the driver camera only
        return FeatureExtractor(cfg, camera_fps=ctx.fps, camera=ctx.name, gaze=ctx.is_driver, phone=True)
    if ctx.options.models:
        log.warning("model files missing: running without models", extra={"fields": {"camera": ctx.name}})
    return _NullExtractor()


def default_pipeline(ctx: CameraContext, perf: PerfTracker) -> ModularPipeline:
    """Built-in modules for the camera, then the extra ones from ``ctx.modules`` (pending ``workers.modules``)."""
    extractor = make_extractor(ctx)
    detectors = DetectorsModule(ctx, extractor)
    modules: list[PipelineModule] = [detectors]
    if ctx.is_driver:
        modules.append(CalibrationModule(ctx, detectors))
    modules += [PhoneModule(ctx, extractor), GestureModule(ctx, extractor), MonitoringModule(ctx, extractor)]
    builtin = len(modules)
    for path in ctx.modules:
        cls = _import(path)
        modules.append(cls(ctx, extractor))
        log.info("extra module loaded", extra={"fields": {"camera": ctx.name, "module": path}})
    return ModularPipeline(ctx, perf, extractor, modules, builtin=builtin)


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
    factory: PipelineFactory | str | None = None,
    modules: tuple[str, ...] = (),
) -> None:
    """Process body (spawn). Returns when ``stop`` is set; exits with code 2 if the camera never delivers a frame."""
    from perception.capture import LatestFrameCamera, SyntheticSource
    from perception.log import configure_logging
    from perception.perf import PerfTracker

    configure_logging(options.log_level, json=False)
    cfg = PerceptionConfig.model_validate(cfg_data)
    cam_cfg = getattr(cfg.cameras, name)
    out = cfg.output
    source = SyntheticSource(cam_cfg.width, cam_cfg.height, cam_cfg.fps) if options.synthetic else None
    is_driver = name == "driver"
    advertised: list[str] = []

    def status(connected: bool, reason: str) -> dict[str, Any]:
        return {
            "kind": "status",
            "camera": name,
            "t_capture": time.perf_counter(),
            "connected": connected,
            "reason": reason,
            "commands": advertised,
        }

    with LatestFrameCamera(cam_cfg, name, source) as cam:
        first = cam.wait_new(0, timeout=cfg.workers.first_frame_timeout_s)
        info = cam.stats().info
        if first is None or info is None:
            put_latest(results, status(False, "no_frame"))
            raise SystemExit(2)
        ctx = CameraContext(
            name=name,
            cfg=cfg,
            options=options,
            width=info.width,
            height=info.height,
            fps=info.fps or cam_cfg.fps,
            backend=info.backend,
            modules=tuple(modules),
        )
        perf = PerfTracker(cfg.rates.perf_window)
        pipeline = resolve_factory(factory)(ctx, perf)
        advertised = sorted(pipeline.commands | WORKER_COMMANDS)

        face_hz = 0.0 if is_driver else cfg.rates.passenger_face_hz  # 0 = every frame (driver: never degraded)
        debug = False
        t0 = first.t_capture
        last_id = first.frame_id - 1
        last_processed = 0.0
        last_status = 0.0
        last_jpeg = 0.0
        seq = 0
        dropped_results = 0

        def handle(cmd: dict[str, Any]) -> None:
            nonlocal debug, face_hz
            kind = cmd.get("cmd")
            handled = kind in WORKER_COMMANDS
            if kind == "debug":
                debug = bool(cmd.get("on"))
            elif kind == "rates" and "face_hz" in cmd and not is_driver:
                face_hz = float(cmd["face_hz"])
            handled = pipeline.handle(cmd) or handled
            if not handled:
                log.info("command not handled by any module", extra={"fields": {"camera": name, "cmd": kind}})

        try:
            while not stop.is_set():
                while True:
                    try:
                        handle(commands.get_nowait())
                    except queue.Empty:
                        break
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
                t_wall = time.time() - (time.perf_counter() - frame.t_capture)
                inp = FrameInput(frame=frame, t=frame.t_capture - t0, t_wall=t_wall, debug=debug)
                payload = pipeline.process(inp)
                perf.add("e2e_worker", (time.perf_counter() - frame.t_capture) * 1000.0)
                perf.rate.tick()
                stats = cam.stats()
                seq += 1
                msg = {
                    **payload,
                    "kind": "frame",
                    "camera": name,
                    "seq": seq,
                    "t_capture": frame.t_capture,
                    "t_wall": round(t_wall, 4),
                    "connected": stats.connected,
                    "commands": advertised,
                    "perf": {
                        "models": perf.snapshot(),
                        "capture_fps": round(stats.capture_fps, 1),
                        "process_fps": round(perf.rate.rate(), 1),
                        "dropped_frames": stats.dropped,
                        "dropped_results": dropped_results,
                        "reconnects": stats.reconnects,
                    },
                    "rates": {"face_hz": face_hz or ctx.fps, "phone_every": getattr(pipeline, "cadence", {})},
                }
                if put_latest(results, msg):
                    dropped_results += 1
                if want_jpeg.value and now - last_jpeg >= 1.0 / out.video_fps:
                    last_jpeg = now
                    with perf.time("jpeg"):
                        img = pipeline.render(inp, payload, debug=debug, fps=perf.rate.rate())
                        put_latest(jpegs, _jpeg(img, out.video_width, out.jpeg_quality))
        finally:
            pipeline.close()


# --- main-process handle --------------------------------------------------------------------------------


class CameraWorker:
    """Start, supervise and talk to one camera process.

    ``poll()`` must be called regularly by the owner (the main loop): it drains the queues and restarts a dead or
    hung process with exponential backoff. ``available`` is False while the process is down or the camera does not
    deliver frames. ``factory`` injects the pipeline (default :func:`default_pipeline`); ``modules`` adds extra
    :class:`PipelineModule` classes to the default pipeline.
    """

    def __init__(
        self,
        name: str,
        cfg: PerceptionConfig,
        options: WorkerOptions | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        factory: PipelineFactory | str | None = None,
        modules: Sequence[str] = (),
    ) -> None:
        self.name = name
        self.cfg = cfg
        self.options = options or WorkerOptions()
        self.factory = factory
        self.modules = tuple(modules)
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
        self.capabilities: frozenset[str] | None = None  # commands the pipeline handles (None until it reports)

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
                self.factory,
                self.modules,
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
            if new.get("commands"):
                self.capabilities = frozenset(new["commands"])
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
