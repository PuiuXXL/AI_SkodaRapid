"""Benchmark every P1 model on live camera frames and write docs/benchmark/<hostname>.md (+ .json).

    python scripts/benchmark.py                    # ~300 live frames per model, driver camera
    python scripts/benchmark.py --frames 100       # quicker
    python scripts/benchmark.py --synthetic        # no camera (numbers are then only indicative)
    python scripts/benchmark.py --providers CPUExecutionProvider

Sit in front of the camera while it runs (face + a hand now and then), in the lighting you will demo in.
Timings: "inference" = the model call only; "pre+post" = conversion/crop/decoding around it (measured separately,
see perception/preprocess.py and perception/postprocess.py). Nothing is recorded: frames are only processed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import importlib.metadata
import json
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import numpy.typing as npt
import psutil

from perception.capture import CaptureInfo, Frame, LatestFrameCamera, SyntheticSource
from perception.config import REPO_ROOT, PerceptionConfig, load_config
from perception.log import configure_logging
from perception.perf import percentile
from perception.postprocess import gaze_angles, yolo26_detections
from perception.preprocess import crop_box, gaze_input, letterbox
from perception.runtime import DEFAULT_PROVIDER_ORDER, OnnxModel, available_providers

Image = npt.NDArray[np.uint8]
WARMUP_FRAMES = 10
SHORT = {"CUDAExecutionProvider": "CUDA", "OpenVINOExecutionProvider": "OpenVINO", "CPUExecutionProvider": "CPU"}


# --- data ----------------------------------------------------------------------------------------------


@dataclass
class Result:
    model: str
    backend: str
    input: str
    infer_ms: list[float] = field(default_factory=list)
    prepost_ms: list[float] = field(default_factory=list)
    note: str = ""

    def summary(self) -> dict[str, Any]:
        total = [a + b for a, b in zip(self.infer_ms, self.prepost_ms, strict=False)]
        p50_total = percentile(total, 50)
        return {
            "model": self.model,
            "backend": self.backend,
            "input": self.input,
            "frames": len(self.infer_ms),
            "infer_p50": percentile(self.infer_ms, 50),
            "infer_p95": percentile(self.infer_ms, 95),
            "prepost_p50": percentile(self.prepost_ms, 50),
            "total_p50": p50_total,
            "total_p95": percentile(total, 95),
            "max_fps": 1000.0 / p50_total if total and p50_total > 0 else float("nan"),
            "note": self.note,
        }


class FrameFeed:
    """Hands out only new frames from the live camera."""

    def __init__(self, cam: LatestFrameCamera) -> None:
        self.cam = cam
        self.last = 0

    def next(self) -> Frame:
        for _ in range(10):
            frame = self.cam.wait_new(self.last, timeout=1.0)
            if frame is not None:
                self.last = frame.frame_id
                return frame
        raise RuntimeError("camera delivered no frames for 10 s")


class VideoClock:
    """Strictly increasing millisecond timestamps for MediaPipe VIDEO mode."""

    def __init__(self) -> None:
        self.last = -1

    def __call__(self, frame: Frame) -> int:
        ts = max(int(frame.t_capture * 1000), self.last + 1)
        self.last = ts
        return ts


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


# --- model factories -----------------------------------------------------------------------------------


def _mp() -> Any:
    import mediapipe as mp

    return mp


def make_face_landmarker(cfg: PerceptionConfig) -> Any:
    from mediapipe.tasks.python import BaseOptions, vision

    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(cfg.models.path(cfg.models.face_landmarker))),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=cfg.filters.min_detection_conf,
        min_tracking_confidence=cfg.filters.min_tracking_conf,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
    )
    return vision.FaceLandmarker.create_from_options(options)


def make_gesture_recognizer(cfg: PerceptionConfig) -> Any:
    from mediapipe.tasks.python import BaseOptions, vision

    options = vision.GestureRecognizerOptions(
        base_options=BaseOptions(model_asset_path=str(cfg.models.path(cfg.models.gesture_recognizer))),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
    )
    return vision.GestureRecognizer.create_from_options(options)


def make_yunet(cfg: PerceptionConfig, size: tuple[int, int]) -> Any:
    return cv2.FaceDetectorYN.create(
        str(cfg.models.path(cfg.models.yunet)),
        "",
        size,
        cfg.identity.yunet_score_threshold,
        cfg.identity.yunet_nms_threshold,
    )


def to_mp_image(image: Image) -> Any:
    mp = _mp()
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def face_box_from_landmarks(result: Any, shape: tuple[int, ...]) -> tuple[float, float, float, float] | None:
    if not result.face_landmarks:
        return None
    h, w = shape[:2]
    xs = [p.x for p in result.face_landmarks[0]]
    ys = [p.y for p in result.face_landmarks[0]]
    x0, x1, y0, y1 = min(xs) * w, max(xs) * w, min(ys) * h, max(ys) * h
    return x0, y0, x1 - x0, y1 - y0


def yunet_largest(detector: Any, image: Image) -> npt.NDArray[np.float32] | None:
    _, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        return None
    return np.asarray(max(faces, key=lambda f: f[2] * f[3]), dtype=np.float32)


# --- per-model benchmarks ------------------------------------------------------------------------------


def bench_face_landmarker(feed: FrameFeed, cfg: PerceptionConfig, n: int) -> Result:
    landmarker, clock = make_face_landmarker(cfg), VideoClock()
    res = Result("Face Landmarker (478 lm + blendshapes)", "MediaPipe CPU", "full frame")
    found = 0
    try:
        for i in range(n + WARMUP_FRAMES):
            frame = feed.next()
            ts = clock(frame)
            t0 = time.perf_counter()
            mp_img = to_mp_image(frame.image)
            t1 = time.perf_counter()
            out = landmarker.detect_for_video(mp_img, ts)
            t2 = time.perf_counter()
            if i >= WARMUP_FRAMES:
                res.infer_ms.append((t2 - t1) * 1000.0)
                res.prepost_ms.append((t1 - t0) * 1000.0)
                found += bool(out.face_landmarks)
    finally:
        landmarker.close()
    res.note = f"face found in {100 * found / max(n, 1):.0f}% of frames"
    return res


def bench_gesture(feed: FrameFeed, cfg: PerceptionConfig, n: int) -> Result:
    recognizer, clock = make_gesture_recognizer(cfg), VideoClock()
    res = Result("Gesture Recognizer (2 hands)", "MediaPipe CPU", "full frame")
    hands = 0
    try:
        for i in range(n + WARMUP_FRAMES):
            frame = feed.next()
            ts = clock(frame)
            t0 = time.perf_counter()
            mp_img = to_mp_image(frame.image)
            t1 = time.perf_counter()
            out = recognizer.recognize_for_video(mp_img, ts)
            t2 = time.perf_counter()
            if i >= WARMUP_FRAMES:
                res.infer_ms.append((t2 - t1) * 1000.0)
                res.prepost_ms.append((t1 - t0) * 1000.0)
                hands += bool(out.hand_landmarks)
    finally:
        recognizer.close()
    res.note = f"hand visible in {100 * hands / max(n, 1):.0f}% of frames"
    return res


def bench_yunet(feed: FrameFeed, cfg: PerceptionConfig, n: int, info: CaptureInfo) -> Result:
    detector = make_yunet(cfg, (info.width, info.height))
    res = Result("YuNet face detector", "OpenCV DNN CPU", f"{info.width}x{info.height}")
    found = 0
    for i in range(n + WARMUP_FRAMES):
        frame = feed.next()
        t0 = time.perf_counter()
        _, faces = detector.detect(frame.image)
        inf = _ms(t0)
        if i >= WARMUP_FRAMES:
            res.infer_ms.append(inf)
            res.prepost_ms.append(0.0)
            found += faces is not None and len(faces) > 0
    res.note = f"face found in {100 * found / max(n, 1):.0f}% of frames"
    return res


def bench_sface(feed: FrameFeed, cfg: PerceptionConfig, n: int, info: CaptureInfo) -> Result:
    detector = make_yunet(cfg, (info.width, info.height))
    recognizer = cv2.FaceRecognizerSF.create(str(cfg.models.path(cfg.models.sface)), "")
    res = Result("SFace embedding (align + feature)", "OpenCV DNN CPU", "112x112 aligned")
    found = 0
    for i in range(n + WARMUP_FRAMES):
        frame = feed.next()
        face = yunet_largest(detector, frame.image)  # detection itself is benchmarked separately (YuNet)
        t0 = time.perf_counter()
        if face is not None:
            aligned = recognizer.alignCrop(frame.image, face)
            found += i >= WARMUP_FRAMES
        else:
            aligned = cv2.resize(frame.image, (112, 112))
        t1 = time.perf_counter()
        recognizer.feature(aligned)
        inf = _ms(t1)
        pre = (t1 - t0) * 1000.0
        if i >= WARMUP_FRAMES:
            res.infer_ms.append(inf)
            res.prepost_ms.append(pre)
    res.note = f"real face aligned in {100 * found / max(n, 1):.0f}% of frames"
    return res


def bench_gaze(feed: FrameFeed, cfg: PerceptionConfig, n: int, provider: str, info: CaptureInfo) -> Result:
    model = OnnxModel(cfg.models.path(cfg.models.gaze), providers=[provider], name="MobileGaze")
    model.warmup(5)
    size = next((d for d in model.inputs[0].shape[2:] if isinstance(d, int)), 448)
    detector = make_yunet(cfg, (info.width, info.height))
    res = Result(
        "MobileGaze MobileOne-S0",
        f"ORT {SHORT.get(provider, provider)}"
        if model.backend == "onnxruntime"
        else f"OpenVINO {model.provider.split(':')[-1]}",
        f"face crop -> {size}x{size}",
    )
    found = 0
    for i in range(n + WARMUP_FRAMES):
        frame = feed.next()
        face = yunet_largest(detector, frame.image)  # face box source, not timed
        box = (float(face[0]), float(face[1]), float(face[2]), float(face[3])) if face is not None else None
        t0 = time.perf_counter()
        crop = crop_box(frame.image, box, expand=1.2) if box else None
        if crop is None:
            h, w = frame.image.shape[:2]
            crop = frame.image[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
        tensor = gaze_input(crop, size)
        pre = _ms(t0)
        t_inf = time.perf_counter()
        outputs = model.run(tensor)
        inf = _ms(t_inf)
        t1 = time.perf_counter()
        gaze_angles(outputs[0], outputs[1])
        post = _ms(t1)
        if i >= WARMUP_FRAMES:
            res.infer_ms.append(inf)
            res.prepost_ms.append(pre + post)
            found += face is not None
    res.note = f"real face crop in {100 * found / max(n, 1):.0f}% of frames"
    return res


def bench_yolo(feed: FrameFeed, cfg: PerceptionConfig, n: int, stem: str, size: int, provider: str) -> Result:
    path = cfg.models.path(f"{stem}_{size}.onnx")
    model = OnnxModel(path, providers=[provider], name=f"{stem}_{size}")
    model.warmup(5)
    backend = (
        f"ORT {SHORT.get(provider, provider)}"
        if model.backend == "onnxruntime"
        else f"OpenVINO {model.provider.split(':')[-1]}"
    )
    res = Result(f"{stem.upper()} (phone, class {cfg.phone.class_id})", backend, f"{size}x{size}")
    phones = 0
    for i in range(n + WARMUP_FRAMES):
        frame = feed.next()
        t0 = time.perf_counter()
        tensor, meta = letterbox(frame.image, size)
        pre = _ms(t0)
        t_inf = time.perf_counter()
        outputs = model.run(tensor)
        inf = _ms(t_inf)
        t1 = time.perf_counter()
        dets = yolo26_detections(
            outputs[0], meta, frame.image.shape, conf_min=cfg.phone.conf_min, class_ids={cfg.phone.class_id}
        )
        post = _ms(t1)
        if i >= WARMUP_FRAMES:
            res.infer_ms.append(inf)
            res.prepost_ms.append(pre + post)
            phones += bool(dets)
    res.note = f"phone seen in {100 * phones / max(n, 1):.0f}% of frames"
    return res


# --- simulated driver loop -----------------------------------------------------------------------------


class GpuSampler(threading.Thread):
    """Samples nvidia-smi utilization once per second (in a thread, so it does not slow the loop)."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.samples: list[tuple[float, float]] = []  # (util %, memory MiB)
        self._stop_event = threading.Event()
        self.available = shutil.which("nvidia-smi") is not None

    def run(self) -> None:
        while self.available and not self._stop_event.wait(1.0):
            try:
                out = (
                    subprocess.run(
                        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        check=True,
                    )
                    .stdout.strip()
                    .splitlines()[0]
                )
                util, mem = (float(x) for x in out.split(","))
                self.samples.append((util, mem))
            except Exception:
                return

    def stop(self) -> None:
        self._stop_event.set()


def driver_loop(
    feed: FrameFeed, cfg: PerceptionConfig, n: int, providers: Sequence[str], info: CaptureInfo
) -> dict[str, Any]:
    use_gpu = "CUDAExecutionProvider" in providers and cfg.models.phone_device in ("auto", "gpu")
    variant = cfg.models.phone_gpu if use_gpu else cfg.models.phone_cpu
    yolo_stem = Path(variant.weights).stem
    yolo_provider = "CUDAExecutionProvider" if use_gpu else next(p for p in providers if p != "CUDAExecutionProvider")
    gaze_provider = providers[0]

    landmarker, clock = make_face_landmarker(cfg), VideoClock()
    gaze = OnnxModel(cfg.models.path(cfg.models.gaze), providers=[gaze_provider], name="gaze")
    yolo = OnnxModel(cfg.models.path(f"{yolo_stem}_{variant.imgsz}.onnx"), providers=[yolo_provider], name="yolo")
    gaze.warmup(5)
    yolo.warmup(5)
    gaze_size = next((d for d in gaze.inputs[0].shape[2:] if isinstance(d, int)), 448)

    gaze_period, phone_period = 1.0 / cfg.rates.gaze_hz, 1.0 / cfg.rates.phone_hz
    last_gaze = last_phone = -1e9
    per_frame: list[float] = []
    e2e: list[float] = []
    gaze_runs = yolo_runs = 0
    proc = psutil.Process()
    sampler = GpuSampler()

    for _ in range(WARMUP_FRAMES):
        frame = feed.next()
        landmarker.detect_for_video(to_mp_image(frame.image), clock(frame))

    dropped0 = feed.cam.stats().dropped
    psutil.cpu_percent(None)
    proc.cpu_percent(None)
    sampler.start()
    started = time.perf_counter()
    try:
        for _ in range(n):
            frame = feed.next()
            t0 = time.perf_counter()
            result = landmarker.detect_for_video(to_mp_image(frame.image), clock(frame))
            box = face_box_from_landmarks(result, frame.image.shape)
            if box is not None and t0 - last_gaze >= gaze_period:
                crop = crop_box(frame.image, box, expand=1.2)
                if crop is not None:
                    pitch, yaw = gaze.run(gaze_input(crop, gaze_size))
                    gaze_angles(pitch, yaw)
                    gaze_runs += 1
                    last_gaze = t0
            if t0 - last_phone >= phone_period:
                tensor, meta = letterbox(frame.image, variant.imgsz)
                (out,) = yolo.run(tensor)[:1]
                yolo26_detections(
                    out, meta, frame.image.shape, conf_min=cfg.phone.conf_min, class_ids={cfg.phone.class_id}
                )
                yolo_runs += 1
                last_phone = t0
            done = time.perf_counter()
            per_frame.append((done - t0) * 1000.0)
            e2e.append((done - frame.t_capture) * 1000.0)
    finally:
        elapsed = time.perf_counter() - started
        sampler.stop()
        landmarker.close()

    gpu_util = [s[0] for s in sampler.samples]
    gpu_mem = [s[1] for s in sampler.samples]
    return {
        "frames": n,
        "camera_fps": info.fps,
        "loop_fps": n / elapsed if elapsed else float("nan"),
        "frame_ms_p50": percentile(per_frame, 50),
        "frame_ms_p95": percentile(per_frame, 95),
        "capture_to_features_ms_p50": percentile(e2e, 50),
        "capture_to_features_ms_p95": percentile(e2e, 95),
        "gaze_hz": gaze_runs / elapsed if elapsed else 0.0,
        "phone_hz": yolo_runs / elapsed if elapsed else 0.0,
        "gaze_backend": gaze.provider,
        "yolo": f"{yolo_stem}@{variant.imgsz} on {yolo.provider}",
        "dropped_frames": feed.cam.stats().dropped - dropped0,
        "cpu_system_pct": psutil.cpu_percent(None),
        "cpu_process_pct": proc.cpu_percent(None) / (psutil.cpu_count() or 1),
        "ram_process_mb": proc.memory_info().rss / 2**20,
        "gpu_util_pct": float(np.mean(gpu_util)) if gpu_util else None,
        "gpu_mem_mb": float(np.max(gpu_mem)) if gpu_mem else None,
    }


# --- system info ---------------------------------------------------------------------------------------


def cpu_name() -> str:
    try:  # Windows: registry (winreg imported dynamically so mypy on Linux does not flag it)
        winreg: Any = importlib.import_module("winreg")
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError):
        pass
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def gpu_name() -> str:
    if not shutil.which("nvidia-smi"):
        return "none (no nvidia-smi)"
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except Exception as exc:
        return f"nvidia-smi failed: {exc}"
    return out.replace(", ", " · driver ", 1)


def versions() -> dict[str, str]:
    names = [
        "mediapipe",
        "opencv-python",
        "opencv-contrib-python",
        "numpy",
        "onnxruntime",
        "onnxruntime-gpu",
        "openvino",
        "ultralytics",
        "torch",
    ]
    found: dict[str, str] = {}
    for name in names:
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return found


def openvino_devices() -> str:
    try:
        import openvino as ov
    except ImportError:
        return "not installed"
    core = ov.Core()
    return ", ".join(f"{d} ({core.get_property(d, 'FULL_DEVICE_NAME')})" for d in core.available_devices)


def system_info(info: CaptureInfo, synthetic: bool) -> dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "date": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "cpu": f"{cpu_name()} · {psutil.cpu_count(logical=False)} cores / {psutil.cpu_count()} threads",
        "ram_gb": round(vm.total / 2**30, 1),
        "gpu": gpu_name(),
        "python": platform.python_version(),
        "packages": versions(),
        "providers": available_providers(),
        "openvino_devices": openvino_devices(),
        "camera": ("synthetic " if synthetic else "")
        + f"{info.width}x{info.height} {info.fourcc} @ {info.fps:.0f} fps ({info.backend})",
    }


# --- report --------------------------------------------------------------------------------------------


def _f(value: Any, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "-"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def render_markdown(
    sysinfo: dict[str, Any],
    rows: list[dict[str, Any]],
    loop: dict[str, Any] | None,
    skipped: list[str],
    frames: int,
    cfg: PerceptionConfig,
) -> str:
    lines = [
        f"# Perception benchmark: {sysinfo['hostname']}",
        "",
        f"Generated by `scripts/benchmark.py` on {sysinfo['date']}, {frames} live frames per model "
        f"(first {WARMUP_FRAMES} discarded as warm-up). Timings in milliseconds.",
        "",
        "## System",
        "",
        "| | |",
        "|---|---|",
        f"| OS | {sysinfo['os']} |",
        f"| CPU | {sysinfo['cpu']} |",
        f"| RAM | {sysinfo['ram_gb']} GB |",
        f"| GPU | {sysinfo['gpu']} |",
        f"| Python | {sysinfo['python']} |",
        f"| Packages | {', '.join(f'{k} {v}' for k, v in sysinfo['packages'].items())} |",
        f"| ONNX providers | {', '.join(sysinfo['providers'])} |",
        f"| OpenVINO devices | {sysinfo['openvino_devices']} |",
        f"| Camera (obtained) | {sysinfo['camera']} |",
        "",
        "## Models",
        "",
        "*inference* = model call only · *pre+post* = colour conversion / crop / letterbox / decoding · "
        "*max fps* = 1000 / total p50 (one model alone on one core path).",
        "",
        "| Model | Backend | Input | Inference p50 | Inference p95 | Pre+post p50 | Total p50 | Total p95 "
        "| Max fps | Note |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['model']} | {r['backend']} | {r['input']} | {_f(r['infer_p50'])} | {_f(r['infer_p95'])} | "
            f"{_f(r['prepost_p50'])} | {_f(r['total_p50'])} | {_f(r['total_p95'])} | {_f(r['max_fps'], 0)} | "
            f"{r['note']} |"
        )
    if skipped:
        lines += ["", "Skipped: " + "; ".join(skipped)]
    if loop:
        budget = 1000.0 / loop["camera_fps"] if loop["camera_fps"] else float("nan")
        lines += [
            "",
            "## Simulated driver loop",
            "",
            f"Face Landmarker on every frame + MobileGaze at `rates.gaze_hz` = {cfg.rates.gaze_hz} Hz + "
            f"YOLO at `rates.phone_hz` = {cfg.rates.phone_hz} Hz, single thread, on live frames.",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Camera fps (obtained) | {_f(loop['camera_fps'])} (budget {_f(budget)} ms/frame) |",
            f"| Loop fps achieved | {_f(loop['loop_fps'])} |",
            f"| Processing per frame p50 / p95 | {_f(loop['frame_ms_p50'])} / {_f(loop['frame_ms_p95'])} ms |",
            f"| Capture → features p50 / p95 | {_f(loop['capture_to_features_ms_p50'])} / "
            f"{_f(loop['capture_to_features_ms_p95'])} ms |",
            f"| Gaze rate achieved | {_f(loop['gaze_hz'])} Hz on {loop['gaze_backend']} |",
            f"| YOLO rate achieved | {_f(loop['phone_hz'])} Hz, {loop['yolo']} |",
            f"| Frames dropped by the camera thread | {loop['dropped_frames']} |",
            f"| CPU system / this process (of all cores) | {_f(loop['cpu_system_pct'])}% / "
            f"{_f(loop['cpu_process_pct'])}% |",
            f"| RAM (process) | {_f(loop['ram_process_mb'], 0)} MB |",
            f"| GPU util / memory | {_f(loop['gpu_util_pct'])}% / {_f(loop['gpu_mem_mb'], 0)} MiB |",
        ]
    lines += [
        "",
        "## Conditions",
        "",
        "- Live camera frames, a person in front of the camera, indoor lighting; nothing recorded.",
        "- Re-run on the demo laptop and in the venue lighting before quoting numbers on a slide: "
        "`python scripts/benchmark.py`.",
        "- Raw numbers: the `.json` file next to this one.",
        "",
    ]
    return "\n".join(lines)


# --- main ----------------------------------------------------------------------------------------------


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--frames", type=int, default=300)
    p.add_argument("--camera", choices=["driver", "passenger"], default="driver")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--providers", nargs="*", default=None, help="ONNX providers to test (default: all available)")
    p.add_argument("--out", type=Path, default=None, help="default: docs/benchmark/<hostname>.md")
    p.add_argument("--skip-loop", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    configure_logging("WARNING", json=False)
    cfg = load_config(args.config)
    cam_cfg = getattr(cfg.cameras, args.camera)
    providers = args.providers or [p for p in DEFAULT_PROVIDER_ORDER if p in available_providers()]
    out_md = args.out or REPO_ROOT / "docs" / "benchmark" / f"{socket.gethostname()}.md"
    n = args.frames
    source = SyntheticSource(cam_cfg.width, cam_cfg.height, cam_cfg.fps) if args.synthetic else None

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    loop: dict[str, Any] | None = None

    def run(label: str, fn: Callable[[], Result]) -> None:
        print(f"-> {label} ...", flush=True)
        try:
            result = fn()
        except FileNotFoundError as exc:
            skipped.append(f"{label}: {exc} (run scripts/download_models.sh)")
            print(f"   skipped: {exc}", flush=True)
            return
        except Exception as exc:
            skipped.append(f"{label}: {type(exc).__name__}: {exc}")
            print(f"   failed: {exc}", flush=True)
            return
        summary = result.summary()
        rows.append(summary)
        print(
            f"   {result.backend}: inference p50 {summary['infer_p50']:.1f} ms, p95 {summary['infer_p95']:.1f} ms,"
            f" total p50 {summary['total_p50']:.1f} ms ({result.note})",
            flush=True,
        )

    with LatestFrameCamera(cam_cfg, args.camera, source) as cam:
        feed = FrameFeed(cam)
        first = feed.next()
        info = cam.stats().info or CaptureInfo("?", "?", first.image.shape[1], first.image.shape[0], 0.0)
        print(
            f"camera: {info.width}x{info.height} {info.fourcc} @ {info.fps:.0f} fps ({info.backend}); "
            f"providers: {providers}",
            flush=True,
        )

        run("Face Landmarker", lambda: bench_face_landmarker(feed, cfg, n))
        run("Gesture Recognizer", lambda: bench_gesture(feed, cfg, n))
        for provider in providers:
            run(f"MobileGaze [{SHORT.get(provider, provider)}]", partial(bench_gaze, feed, cfg, n, provider, info))
        for stem, size in (("yolo26n", 320), ("yolo26n", 416), ("yolo26n", 640), ("yolo26s", 640)):
            for provider in providers:
                run(
                    f"{stem}@{size} [{SHORT.get(provider, provider)}]",
                    partial(bench_yolo, feed, cfg, n, stem, size, provider),
                )
        run("YuNet", lambda: bench_yunet(feed, cfg, n, info))
        run("SFace", lambda: bench_sface(feed, cfg, n, info))
        if not args.skip_loop:
            print("-> simulated driver loop ...", flush=True)
            try:
                loop = driver_loop(feed, cfg, n, providers, info)
                print(f"   loop {loop['loop_fps']:.1f} fps, frame p50 {loop['frame_ms_p50']:.1f} ms", flush=True)
            except Exception as exc:
                skipped.append(f"driver loop: {type(exc).__name__}: {exc}")
                print(f"   failed: {exc}", flush=True)

    sysinfo = system_info(info, args.synthetic)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(sysinfo, rows, loop, skipped, n, cfg), encoding="utf-8")
    out_md.with_suffix(".json").write_text(
        json.dumps({"system": sysinfo, "models": rows, "driver_loop": loop, "skipped": skipped}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nwrote {out_md}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
