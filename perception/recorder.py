"""Record FeatureFrames (no pixels) from a live camera to JSONL, optionally gzip-compressed.

    python -m perception.recorder --record-features data/features/s1/features.jsonl.gz --seconds 60 --label "desk test"

File layout: the first line is ``{"type": "meta", ...}`` (camera, obtained resolution / fps, model files + SHA-256,
package versions, config snapshot, landmark indices, session label), then one ``{"type": "frame", ...}`` per frame.
A ``.gz`` suffix turns on gzip. Images are processed in memory and never written.

To also mark ground-truth events while recording, use ``scripts/label_session.py``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import importlib.metadata
import time
from pathlib import Path
from types import TracebackType
from typing import IO, Any

import orjson

from perception.capture import CaptureInfo, Frame, LatestFrameCamera, SyntheticSource
from perception.config import REPO_ROOT, PerceptionConfig, load_config
from perception.features import FEATURE_SCHEMA_VERSION, LANDMARK_INDICES, FeatureFrame
from perception.log import configure_logging, get_logger

__all__ = [
    "DATA_DIR",
    "FeatureWriter",
    "RecordingSession",
    "build_metadata",
    "ensure_data_dir",
    "main",
    "open_jsonl",
]

log = get_logger("perception.recorder")

DATA_DIR = REPO_ROOT / "data"

_DATA_README = """# data/ (local only, never committed)

This folder is ignored by git (see `data/.gitignore`). It holds **feature recordings, not images**:

    data/features/<session>/
        features.jsonl.gz   FeatureFrames: landmarks subset, blendshapes, head matrix, gaze angles,
                            hands/gestures, phone boxes, face presence/width. No pixels.
        labels.jsonl        ground-truth events pressed live (scripts/label_session.py), same clock as the frames

Recorded with `scripts/label_session.py` or `python -m perception.recorder`; read back with
`python -m perception.replay <file>`. Used for detector tuning, tests and evaluation only,
**never in the demo (R3)**. Only record team members who agreed to it. See docs/perception.md (data policy).
"""


def ensure_data_dir(path: Path, data_root: Path = DATA_DIR) -> None:
    """If ``path`` is inside ``data_root``, make sure the folder ignores itself in git and has its README."""
    try:
        path.resolve().relative_to(data_root.resolve())
    except ValueError:
        return
    data_root.mkdir(parents=True, exist_ok=True)
    gitignore = data_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "# local feature recordings: never commit (docs/perception.md, data policy)\n*\n", encoding="utf-8"
        )
    readme = data_root / "README.md"
    if not readme.exists():
        readme.write_text(_DATA_README, encoding="utf-8")


def open_jsonl(path: Path, mode: str) -> IO[bytes]:
    """Binary file handle; gzip when the name ends with ``.gz``."""
    if path.suffix == ".gz":
        return gzip.open(path, mode + "b")  # type: ignore[return-value]
    return path.open(mode + "b")


class FeatureWriter:
    """Writes a meta line, then FeatureFrames, to JSONL (gzip if the path ends in ``.gz``)."""

    def __init__(self, path: str | Path, meta: dict[str, Any]) -> None:
        self.path = Path(path)
        ensure_data_dir(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open_jsonl(self.path, "w")
        self._fh.write(orjson.dumps({"type": "meta", **meta}) + b"\n")
        self.count = 0

    def write(self, frame: FeatureFrame) -> None:
        self._fh.write(orjson.dumps({"type": "frame", **frame.model_dump(mode="json")}) + b"\n")
        self.count += 1

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> FeatureWriter:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()


def _sha256(path: Path) -> str | None:
    sums = path.parent / "SHA256SUMS"
    if sums.exists():
        for line in sums.read_text(encoding="utf-8").splitlines():
            digest, _, name = line.partition("  ")
            if name == path.name:
                return digest
    if path.exists():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return None


def _versions() -> dict[str, str]:
    found: dict[str, str] = {}
    for name in ("mediapipe", "opencv-python", "onnxruntime", "onnxruntime-gpu", "openvino", "numpy"):
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return found


def build_metadata(
    cfg: PerceptionConfig,
    camera: str,
    info: CaptureInfo,
    *,
    label: str,
    models: dict[str, dict[str, str]],
    cadence: dict[str, int],
    synthetic: bool = False,
) -> dict[str, Any]:
    cam_cfg = getattr(cfg.cameras, camera)
    return {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "created": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "t0_epoch": time.time(),
        "label": label,
        "camera": {
            "name": camera,
            "device": "synthetic" if synthetic else str(cam_cfg.device),
            "backend": info.backend,
            "fourcc": info.fourcc,
            "width": info.width,
            "height": info.height,
            "fps": info.fps,
        },
        "models": {name: {**m, "sha256": _sha256(cfg.models.path(m["file"]))} for name, m in models.items()},
        "cadence_frames": cadence,
        "packages": _versions(),
        "landmark_indices": list(LANDMARK_INDICES),
        "config": cfg.model_dump(mode="json"),
    }


class RecordingSession:
    """Live camera -> FeatureExtractor -> FeatureWriter. Call :meth:`step` in a loop; :meth:`close` at the end."""

    def __init__(
        self,
        cfg: PerceptionConfig,
        out_path: Path,
        *,
        camera: str = "driver",
        label: str = "",
        synthetic: bool = False,
        gesture_hz: float | None = 10.0,
    ) -> None:
        from perception.extractor import FeatureExtractor  # heavy (MediaPipe); imported only when recording

        cam_cfg = getattr(cfg.cameras, camera)
        source = SyntheticSource(cam_cfg.width, cam_cfg.height, cam_cfg.fps) if synthetic else None
        self.camera_name = camera
        self.camera = LatestFrameCamera(cam_cfg, camera, source).start()
        first = self.camera.wait_new(0, timeout=10.0)
        if first is None:
            self.camera.stop()
            raise RuntimeError(f"camera {camera!r} delivered no frame in 10 s")
        info = self.camera.stats().info
        assert info is not None
        self.info = info
        self.extractor = FeatureExtractor(cfg, camera_fps=info.fps or cam_cfg.fps, gesture_hz=gesture_hz)
        meta = build_metadata(
            cfg,
            camera,
            info,
            label=label,
            models=self.extractor.models,
            cadence=self.extractor.cadence,
            synthetic=synthetic,
        )
        self.writer = FeatureWriter(out_path, meta)
        self.t0 = time.perf_counter()  # session clock origin, shared with labels
        self._last_id = first.frame_id
        self.last: FeatureFrame | None = None

    def now(self) -> float:
        """Seconds since session start (the clock used by FeatureFrame.t and labels)."""
        return time.perf_counter() - self.t0

    def step(self, timeout: float = 1.0) -> tuple[Frame, FeatureFrame] | None:
        frame = self.camera.wait_new(self._last_id, timeout)
        if frame is None:
            return None
        self._last_id = frame.frame_id
        t = frame.t_capture - self.t0
        if t < 0:  # captured before the session started
            return None
        features = self.extractor.extract(frame, t, self.camera_name)
        self.writer.write(features)
        self.last = features
        return frame, features

    def close(self) -> None:
        self.writer.close()
        self.extractor.close()
        self.camera.stop()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--record-features", type=Path, required=True, metavar="PATH", help=".jsonl or .jsonl.gz")
    p.add_argument("--camera", choices=["driver", "passenger"], default="driver")
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--label", default="", help="session label stored in the metadata")
    p.add_argument("--gesture-hz", type=float, default=10.0, help="0 = do not run the Gesture Recognizer")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--config", type=Path, default=None)
    args = p.parse_args(argv)

    configure_logging("INFO", json=False)
    cfg = load_config(args.config)
    session = RecordingSession(
        cfg,
        args.record_features,
        camera=args.camera,
        label=args.label,
        synthetic=args.synthetic,
        gesture_hz=args.gesture_hz or None,
    )
    print(f"recording features to {args.record_features} for {args.seconds:.0f} s (Ctrl+C to stop)", flush=True)
    try:
        while session.now() < args.seconds:
            session.step()
    except KeyboardInterrupt:
        pass
    finally:
        session.close()
    print(f"wrote {session.writer.count} frames to {args.record_features}")
    return 0 if session.writer.count else 1


if __name__ == "__main__":
    raise SystemExit(main())
