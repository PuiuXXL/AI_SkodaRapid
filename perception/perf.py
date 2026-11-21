"""Timing helpers shared by capture, runtime, the camera workers and benchmark (plan §J1).

* :class:`LatencyWindow`: ``perf_counter`` durations in a ``deque(maxlen=120)``, p50 / p95.
* :class:`RateMeter`: events per second over a sliding window (fps).
* :class:`PerfTracker`: named windows per model and per stage, one picklable :meth:`PerfTracker.snapshot`.
* :class:`SystemMonitor`: CPU %, RAM (this process tree) and GPU % (pynvml, optional), sampled at most once a second.
* :func:`build_perf_block`: the contract's ``perf`` block (``perf.cameras.*``, ``perf.*_ms_p50``, ``e2e_ms_p95``,
  CPU / RAM / GPU) from the newest worker messages. The degradation rule that acts on ``e2e_ms_p95`` lives in
  :mod:`perception.degrade` (passenger rate first, then YOLO; the driver face never).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from typing import Any

__all__ = [
    "MODEL_FIELDS",
    "LatencyWindow",
    "PerfTracker",
    "RateMeter",
    "SystemMonitor",
    "build_perf_block",
    "percentile",
    "round_or_none",
]

# worker latency window -> contract field (driver camera, passenger camera). A model the camera does not run has no
# window, so its field stays None. A new module that attaches a window under one of these names (e.g. ``sface`` for
# identity, ``pose`` for rear_seat) fills the field without any change here.
MODEL_FIELDS: dict[str, tuple[str, str | None]] = {
    "face": ("face_driver_ms_p50", "face_passenger_ms_p50"),
    "pose": ("pose_ms_p50", "pose_ms_p50"),
    "phone": ("phone_ms_p50", "phone_ms_p50"),
    "gesture": ("gesture_ms_p50", "gesture_ms_p50"),
    "sface": ("sface_ms_p50", "sface_ms_p50"),
}


def round_or_none(value: float | None, digits: int = 1) -> float | None:
    """Round, mapping None / NaN to None (JSON-friendly)."""
    if value is None or math.isnan(value):
        return None
    return round(value, digits)


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (``q`` in 0..100) of an unsorted list; NaN if empty."""
    if not values:
        return float("nan")
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


class LatencyWindow:
    """Rolling window of durations in milliseconds. Thread-safe."""

    def __init__(self, maxlen: int = 120) -> None:
        self._values: deque[float] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._total = 0

    def add(self, ms: float) -> None:
        with self._lock:
            self._values.append(ms)
            self._total += 1

    @contextmanager
    def time(self) -> Iterator[None]:
        """``with window.time(): ...`` records the block's duration."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.add((time.perf_counter() - t0) * 1000.0)

    def snapshot(self) -> list[float]:
        with self._lock:
            return list(self._values)

    @property
    def count(self) -> int:
        """Total samples ever added (not only the ones still in the window)."""
        with self._lock:
            return self._total

    def p50(self) -> float:
        return percentile(self.snapshot(), 50)

    def p95(self) -> float:
        return percentile(self.snapshot(), 95)

    def mean(self) -> float:
        values = self.snapshot()
        return sum(values) / len(values) if values else float("nan")


class RateMeter:
    """Events per second over a sliding time window (default 1 s). Thread-safe."""

    def __init__(self, window_s: float = 1.0, clock: Callable[[], float] = time.perf_counter) -> None:
        self._window_s = window_s
        self._clock = clock
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def tick(self, t: float | None = None) -> None:
        now = self._clock() if t is None else t
        with self._lock:
            self._stamps.append(now)
            self._trim(now)

    def rate(self) -> float:
        now = self._clock()
        with self._lock:
            self._trim(now)
            if len(self._stamps) < 2:
                return 0.0
            span = self._stamps[-1] - self._stamps[0]
            return (len(self._stamps) - 1) / span if span > 0 else 0.0

    def _trim(self, now: float) -> None:
        while self._stamps and now - self._stamps[0] > self._window_s:
            self._stamps.popleft()


class PerfTracker:
    """Named latency windows (models and pipeline stages) plus a frame-rate meter, for one camera process.

    ``with perf.time("face"): ...`` or ``perf.add("e2e", ms)``; :meth:`snapshot` returns plain floats only, so it can
    cross a process boundary inside a queue message.
    """

    def __init__(self, maxlen: int = 120) -> None:
        self._maxlen = maxlen
        self._windows: dict[str, LatencyWindow] = {}
        self.rate = RateMeter()

    def window(self, name: str) -> LatencyWindow:
        if name not in self._windows:
            self._windows[name] = LatencyWindow(self._maxlen)
        return self._windows[name]

    def add(self, name: str, ms: float) -> None:
        self.window(name).add(ms)

    @contextmanager
    def time(self, name: str) -> Iterator[None]:
        with self.window(name).time():
            yield

    def attach(self, name: str, window: LatencyWindow) -> None:
        """Use a window owned by a model wrapper (e.g. ``OnnxModel.latency``) under ``name``."""
        self._windows[name] = window

    def snapshot(self) -> dict[str, dict[str, float | None]]:
        """``{name: {"p50": ms, "p95": ms, "n": count}}``; empty windows give None."""
        return {
            name: {"p50": round_or_none(w.p50(), 2), "p95": round_or_none(w.p95(), 2), "n": float(w.count)}
            for name, w in self._windows.items()
        }


class SystemMonitor:
    """CPU %, RAM MB and GPU % for the perception process tree.

    * CPU: ``psutil.cpu_percent`` of the whole machine (what competes with the models), non-blocking.
    * RAM: resident memory of this process and its children (the camera workers), in MB.
    * GPU: utilisation of GPU 0 via ``pynvml`` when an NVIDIA driver is present, otherwise None.
    Values are cached for ``min_interval_s`` so a 15 Hz publisher does not poll the OS 15 times a second.
    """

    def __init__(self, min_interval_s: float = 1.0) -> None:
        import psutil

        self._psutil = psutil
        self._proc = psutil.Process()
        self._min_interval_s = min_interval_s
        self._last_t = 0.0
        self._cache: dict[str, float | None] = {"cpu": None, "ram_mb": None, "gpu": None}
        self._nvml: Any = None
        self._gpu_handle: Any = None
        try:
            import pynvml  # type: ignore[import-untyped]  # optional: NVIDIA only

            pynvml.nvmlInit()
            self._gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._nvml = pynvml
        except Exception:  # no NVIDIA driver / library: GPU stays None
            self._nvml = None
        psutil.cpu_percent(None)  # prime the non-blocking measurement

    def sample(self) -> dict[str, float | None]:
        now = time.monotonic()
        if now - self._last_t < self._min_interval_s:
            return dict(self._cache)
        self._last_t = now
        ram = 0
        try:
            procs = [self._proc, *self._proc.children(recursive=True)]
            for p in procs:
                try:
                    ram += p.memory_info().rss
                except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
                    continue
        except self._psutil.NoSuchProcess:
            pass
        gpu: float | None = None
        if self._nvml is not None:
            try:
                gpu = float(self._nvml.nvmlDeviceGetUtilizationRates(self._gpu_handle).gpu)
            except Exception:
                gpu = None
        self._cache = {
            "cpu": round(float(self._psutil.cpu_percent(None)), 1),
            "ram_mb": round(ram / 1e6, 1),
            "gpu": gpu,
        }
        return dict(self._cache)

    def close(self) -> None:
        if self._nvml is not None:
            with suppress(Exception):
                self._nvml.nvmlShutdown()
            self._nvml = None


def _model_p50(msg: Mapping[str, Any] | None, model: str) -> float | None:
    if not msg:
        return None
    value = msg.get("perf", {}).get("models", {}).get(model, {}).get("p50")
    return float(value) if value is not None else None


def build_perf_block(
    cameras: Mapping[str, bool],
    msgs: Mapping[str, Mapping[str, Any] | None],
    *,
    e2e_ms_p95: float | None,
    system: Mapping[str, float | None],
    proposed: bool,
    degrade_level: int = 0,
    timing: Mapping[str, tuple[float | None, float | None]] | None = None,
    publish_ts: float | None = None,
) -> dict[str, Any]:
    """The contract's ``perf`` block (plan §7 / J1).

    Args:
        cameras: enabled camera -> available (process running and its newest result fresh).
        msgs: camera -> its newest **fresh** ``kind="frame"`` worker message, or None.
        e2e_ms_p95: capture of the newest driver frame -> its publication, p95 over the last ``perf_window``.
        system: ``SystemMonitor.sample()`` (cpu, ram_mb, gpu).
        proposed: also write the fields proposed for the contract (docs/notes/output.md, CONTRACT texts).
        timing: camera -> (capture_ts = ``time.time()`` at capture, age_ms at publication) of its newest result,
            fresh or not (proposed fields only).
        publish_ts: ``time.time()`` of this publication (proposed field only).
    """
    perf: dict[str, Any] = {"cameras": {}}
    for name, available in cameras.items():
        msg = msgs.get(name)
        cam: dict[str, Any] = {"capture_fps": 0.0, "process_fps": 0.0, "dropped_frames": 0}
        if msg is not None:
            p = msg["perf"]
            cam = {
                "capture_fps": p["capture_fps"],
                "process_fps": p["process_fps"],
                "dropped_frames": p["dropped_frames"],
            }
        if proposed:
            capture_ts, age_ms = (timing or {}).get(name, (None, None))
            cam.update(
                available=available,
                capture_ts=capture_ts,
                age_ms=age_ms,
                dropped_results=int(msg["perf"].get("dropped_results", 0)) if msg is not None else 0,
            )
        perf["cameras"][name] = cam
    fields: dict[str, float | None] = {}
    for model, (driver_field, passenger_field) in MODEL_FIELDS.items():
        fields.setdefault(driver_field, None)
        if passenger_field is not None:
            fields.setdefault(passenger_field, None)
        driver_p50 = _model_p50(msgs.get("driver"), model)
        passenger_p50 = _model_p50(msgs.get("passenger"), model)
        if driver_field == passenger_field:  # one field for both cameras: the driver's value, else the passenger's
            fields[driver_field] = driver_p50 if driver_p50 is not None else passenger_p50
        else:
            fields[driver_field] = driver_p50
            if passenger_field is not None:
                fields[passenger_field] = passenger_p50
    perf.update(fields)
    perf.update(e2e_ms_p95=e2e_ms_p95, cpu=system.get("cpu"), ram_mb=system.get("ram_mb"), gpu=system.get("gpu"))
    if proposed:
        perf["degrade_level"] = degrade_level
        perf["stages_ms"] = {name: msg["perf"]["models"] for name, msg in msgs.items() if msg is not None}
        perf["publish_ts"] = round(publish_ts, 3) if publish_ts is not None else None
    return perf
