"""Camera capture: one thread per camera that keeps only the latest frame.

* :class:`FrameSource` abstracts where frames come from: :class:`OpenCVSource` (real camera) or
  :class:`SyntheticSource` (tests, CI, ``--synthetic``).
* :class:`LatestFrameCamera` reads continuously, keeps only the newest :class:`Frame` (stamped with
  ``time.perf_counter()`` right after the read), counts frames that were replaced before anyone consumed them
  (``dropped``), measures ``capture_fps``, and reconnects by itself.
* :meth:`LatestFrameCamera.wait_new` never returns the same frame twice to a consumer that passes back the last
  ``frame_id`` it got.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol

import cv2
import numpy as np
import numpy.typing as npt

from perception.config import CameraConfig, CameraControls
from perception.log import get_logger
from perception.perf import RateMeter

__all__ = [
    "CameraOpenError",
    "CaptureInfo",
    "CaptureStats",
    "Frame",
    "FrameSource",
    "LatestFrameCamera",
    "OpenCVSource",
    "SyntheticSource",
    "decode_synthetic_id",
]

Image = npt.NDArray[np.uint8]

log = get_logger("perception.capture")


class CameraOpenError(RuntimeError):
    """The camera could not be opened or delivered no first frame."""


@dataclass(frozen=True)
class Frame:
    image: Image
    frame_id: int
    t_capture: float  # time.perf_counter() right after the frame was read


@dataclass(frozen=True)
class CaptureInfo:
    """What the camera actually delivers (may differ from what was requested)."""

    backend: str
    fourcc: str
    width: int
    height: int
    fps: float


@dataclass(frozen=True)
class CaptureStats:
    name: str
    connected: bool
    info: CaptureInfo | None
    capture_fps: float
    frames: int
    dropped: int
    reconnects: int
    read_failures: int


class FrameSource(Protocol):
    """Where frames come from. ``open`` raises on failure, ``read`` returns ``None`` on failure."""

    def open(self) -> CaptureInfo: ...

    def read(self) -> Image | None: ...

    def close(self) -> None: ...


# --- OpenCV source -------------------------------------------------------------------------------------

_BACKENDS: dict[str, int] = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
    "any": cv2.CAP_ANY,
}


# Typed as plain str so mypy does not prune the other platform's branch as unreachable.
_PLATFORM: str = sys.platform


def _backend_flag(name: str) -> int:
    if name == "auto":
        if _PLATFORM.startswith("linux"):
            return int(cv2.CAP_V4L2)
        if _PLATFORM == "win32":
            return int(cv2.CAP_DSHOW)  # DSHOW honours MJPG + 720p reliably; MSMF often ignores FOURCC
        return int(cv2.CAP_ANY)
    return int(_BACKENDS[name])


def _fourcc_to_str(value: float) -> str:
    code = int(value)
    chars = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))
    return chars if chars.isprintable() and code else "?"


def _apply_controls_opencv(cap: cv2.VideoCapture, controls: CameraControls, name: str) -> None:
    """Best-effort fixed controls through OpenCV properties (used on Windows, where v4l2-ctl does not exist).

    DirectShow conventions: CAP_PROP_AUTO_EXPOSURE 0.25 = manual / 0.75 = auto; CAP_PROP_EXPOSURE = log2(seconds).
    Power-line frequency is not exposed by OpenCV on Windows.
    """
    wanted: list[tuple[str, int, float]] = []
    if controls.autofocus is not None:
        wanted.append(("autofocus", cv2.CAP_PROP_AUTOFOCUS, 1.0 if controls.autofocus else 0.0))
    if controls.focus is not None:
        wanted.append(("focus", cv2.CAP_PROP_FOCUS, float(controls.focus)))
    if controls.auto_exposure is not None:
        wanted.append(("auto_exposure", cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if controls.auto_exposure else 0.25))
    if controls.exposure_ms is not None:
        wanted.append(("exposure", cv2.CAP_PROP_EXPOSURE, float(round(math.log2(controls.exposure_ms / 1000.0)))))
    if controls.gain is not None:
        wanted.append(("gain", cv2.CAP_PROP_GAIN, float(controls.gain)))
    if controls.auto_white_balance is not None:
        wanted.append(("auto_white_balance", cv2.CAP_PROP_AUTO_WB, 1.0 if controls.auto_white_balance else 0.0))
    if controls.white_balance_k is not None:
        wanted.append(("white_balance_k", cv2.CAP_PROP_WB_TEMPERATURE, float(controls.white_balance_k)))

    applied: dict[str, float] = {}
    skipped: list[str] = []
    for label, prop, value in wanted:
        if cap.set(prop, value):
            applied[label] = float(cap.get(prop))
        else:
            skipped.append(label)
    if controls.power_line_hz is not None:
        skipped.append("power_line_hz (not available through OpenCV on Windows)")
    log.info("camera controls", extra={"fields": {"camera": name, "applied": applied, "skipped": skipped}})


class OpenCVSource:
    """Real camera through ``cv2.VideoCapture``. Requested format/size/fps are set before the first read."""

    def __init__(self, cfg: CameraConfig, name: str = "camera") -> None:
        self._cfg = cfg
        self._name = name
        self._cap: cv2.VideoCapture | None = None
        self._first: Image | None = None

    def open(self) -> CaptureInfo:
        cfg = self._cfg
        device: int | str = int(cfg.device) if isinstance(cfg.device, str) and cfg.device.isdigit() else cfg.device
        cap = cv2.VideoCapture(device, _backend_flag(cfg.backend))
        if not cap.isOpened():
            cap.release()
            raise CameraOpenError(f"{self._name}: cannot open device {cfg.device!r} (backend {cfg.backend})")
        # Order matters: FOURCC first, otherwise some drivers fall back to YUYV and cap the frame rate.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*cfg.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        cap.set(cv2.CAP_PROP_FPS, cfg.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, cfg.buffer_size)
        if _PLATFORM == "win32":
            _apply_controls_opencv(cap, cfg.controls, self._name)

        ok, img = cap.read()
        if not ok or img is None:
            cap.release()
            raise CameraOpenError(f"{self._name}: device {cfg.device!r} opened but delivered no frame")
        info = CaptureInfo(
            backend=str(cap.getBackendName()),
            fourcc=_fourcc_to_str(cap.get(cv2.CAP_PROP_FOURCC)),
            width=int(img.shape[1]),
            height=int(img.shape[0]),
            fps=float(cap.get(cv2.CAP_PROP_FPS)),
        )
        requested = (cfg.fourcc, cfg.width, cfg.height, float(cfg.fps))
        obtained = (info.fourcc, info.width, info.height, round(info.fps, 2))
        same = requested[:3] == obtained[:3] and abs(info.fps - cfg.fps) < 0.5
        if not same:
            log.warning(
                "camera format differs from request",
                extra={"fields": {"camera": self._name, "requested": requested, "obtained": obtained}},
            )
        self._cap = cap
        self._first = np.asarray(img, dtype=np.uint8)
        return info

    def read(self) -> Image | None:
        if self._first is not None:
            first, self._first = self._first, None
            return first
        if self._cap is None:
            return None
        ok, raw = self._cap.read()
        return np.asarray(raw, dtype=np.uint8) if ok and raw is not None else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._first = None


# --- synthetic source ----------------------------------------------------------------------------------


def decode_synthetic_id(image: Image) -> int:
    """Read back the sequence number :class:`SyntheticSource` writes into the first pixels."""
    return int.from_bytes(bytes(image[0, :8, 0].tolist()), "little")


class SyntheticSource:
    """Generated frames for tests and camera-less runs.

    Each frame carries its sequence number in the first 8 pixels (see :func:`decode_synthetic_id`) and a moving
    bar so a preview visibly updates. Failures are scriptable: the first ``open_failures`` calls to ``open`` raise,
    and the read calls whose 0-based index is in ``fail_reads`` return ``None``.
    """

    def __init__(
        self,
        width: int = 320,
        height: int = 240,
        fps: float = 30.0,
        *,
        open_failures: int = 0,
        fail_reads: Collection[int] = (),
    ) -> None:
        self._width = width
        self._height = height
        self._period = 1.0 / fps if fps > 0 else 0.0
        self._fps = fps
        self._open_failures = open_failures
        self._fail_reads = frozenset(fail_reads)
        self._read_calls = 0
        self._seq = 0
        self._next_t = 0.0
        self.open_calls = 0
        self.close_calls = 0
        self.is_open = False

    def open(self) -> CaptureInfo:
        self.open_calls += 1
        if self.open_calls <= self._open_failures:
            raise CameraOpenError(f"synthetic open failure {self.open_calls}/{self._open_failures}")
        self.is_open = True
        self._next_t = time.perf_counter()
        return CaptureInfo("synthetic", "RAW ", self._width, self._height, self._fps)

    def read(self) -> Image | None:
        if not self.is_open:
            return None
        index = self._read_calls
        self._read_calls += 1
        if self._period:
            self._next_t += self._period
            delay = self._next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                self._next_t = time.perf_counter()
        if index in self._fail_reads:
            return None
        self._seq += 1
        img = np.full((self._height, self._width, 3), 40, dtype=np.uint8)
        x = (self._seq * 4) % self._width
        img[:, x : x + 8] = (0, 200, 255)
        img[0, :8, 0] = np.frombuffer(self._seq.to_bytes(8, "little"), dtype=np.uint8)
        return img

    def close(self) -> None:
        self.close_calls += 1
        self.is_open = False


# --- latest-frame camera -------------------------------------------------------------------------------


class LatestFrameCamera:
    """Background reader that keeps only the newest frame.

    Example::

        with LatestFrameCamera(cfg.cameras.driver, "driver") as cam:
            last = 0
            while True:
                frame = cam.wait_new(last, timeout=1.0)
                if frame is None:
                    continue
                last = frame.frame_id
                ...
    """

    def __init__(self, cfg: CameraConfig, name: str = "driver", source: FrameSource | None = None) -> None:
        self._cfg = cfg
        self._name = name
        self._source: FrameSource = source if source is not None else OpenCVSource(cfg, name)
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rate = RateMeter(window_s=1.0)
        # guarded by _cond
        self._frame: Frame | None = None
        self._next_id = 0
        self._delivered_id = 0
        self._dropped = 0
        self._connected = False
        self._info: CaptureInfo | None = None
        self._reconnects = 0
        self._read_failures = 0

    @property
    def name(self) -> str:
        return self._name

    # lifecycle ----------------------------------------------------------------------------------------

    def start(self) -> LatestFrameCamera:
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"capture-{self._name}", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the reader thread, release the camera and wake up any ``wait_new`` caller."""
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning("capture thread did not stop in time", extra={"fields": {"camera": self._name}})
            self._thread = None

    def __enter__(self) -> LatestFrameCamera:
        return self.start()

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.stop()

    # consumer API -------------------------------------------------------------------------------------

    def wait_new(self, last_id: int, timeout: float) -> Frame | None:
        """Block until a frame newer than ``last_id`` exists; ``None`` on timeout or after ``stop``."""
        with self._cond:
            self._cond.wait_for(self._newer_or_stopped(last_id), timeout)
            frame = self._frame
            if frame is None or frame.frame_id <= last_id:
                return None
            self._delivered_id = max(self._delivered_id, frame.frame_id)
            return frame

    def latest(self) -> Frame | None:
        """Newest frame without waiting (may be one already returned before)."""
        with self._cond:
            return self._frame

    def stats(self) -> CaptureStats:
        with self._cond:
            return CaptureStats(
                name=self._name,
                connected=self._connected,
                info=self._info,
                capture_fps=self._rate.rate(),
                frames=self._next_id,
                dropped=self._dropped,
                reconnects=self._reconnects,
                read_failures=self._read_failures,
            )

    # internals ----------------------------------------------------------------------------------------

    def _newer_or_stopped(self, last_id: int) -> Callable[[], bool]:
        def predicate() -> bool:
            return self._stop.is_set() or (self._frame is not None and self._frame.frame_id > last_id)

        return predicate

    def _run(self) -> None:
        failures = 0
        opened_once = False
        try:
            while not self._stop.is_set():
                if not self._connected:
                    try:
                        info = self._source.open()
                    except Exception as exc:
                        log.warning(
                            "camera open failed",
                            extra={
                                "fields": {
                                    "camera": self._name,
                                    "error": str(exc),
                                    "retry_s": self._cfg.reconnect_s,
                                }
                            },
                        )
                        self._stop.wait(self._cfg.reconnect_s)
                        continue
                    with self._cond:
                        self._connected = True
                        self._info = info
                        if opened_once:
                            self._reconnects += 1
                    opened_once = True
                    failures = 0
                    log.info(
                        "camera opened",
                        extra={
                            "fields": {
                                "camera": self._name,
                                "backend": info.backend,
                                "fourcc": info.fourcc,
                                "width": info.width,
                                "height": info.height,
                                "fps": info.fps,
                                "reconnects": self._reconnects,
                            }
                        },
                    )

                image = self._source.read()
                if image is None:
                    failures += 1
                    with self._cond:
                        self._read_failures += 1
                    if failures >= self._cfg.max_read_failures:
                        log.warning(
                            "camera lost, reconnecting",
                            extra={"fields": {"camera": self._name, "failed_reads": failures}},
                        )
                        self._source.close()
                        with self._cond:
                            self._connected = False
                        self._stop.wait(self._cfg.reconnect_s)
                    continue

                failures = 0
                t_capture = time.perf_counter()
                with self._cond:
                    previous = self._frame
                    if previous is not None and previous.frame_id > self._delivered_id:
                        self._dropped += 1
                    self._next_id += 1
                    self._frame = Frame(image=image, frame_id=self._next_id, t_capture=t_capture)
                    self._cond.notify_all()
                self._rate.tick(t_capture)
        finally:
            self._source.close()
            with self._cond:
                self._connected = False
                self._cond.notify_all()
