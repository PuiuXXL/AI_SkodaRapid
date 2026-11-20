"""Read recorded FeatureFrames back, with their original timing or faster, as input for detectors.

    python -m perception.replay data/features/<session>/features.jsonl.gz            # summary (+ labels if present)
    python -m perception.replay data/features/<session>/features.jsonl.gz --play 4   # replay at 4x, print progress

Used by tests, evaluation and threshold tuning.

WARNING: NOT USED IN THE DEMO (R3). The demo always runs on the live camera; replay is for development and
evaluation only (docs/hackathon-requirements.md, docs/perception.md).
"""

from __future__ import annotations

import argparse
import math
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import orjson

from perception.features import FeatureFrame
from perception.labels import load_labels, to_intervals
from perception.log import configure_logging, get_logger
from perception.recorder import open_jsonl

__all__ = ["R3_WARNING", "FeatureReplay", "main"]

log = get_logger("perception.replay")

R3_WARNING = "feature replay is for development and evaluation only; it is never used in the demo (R3)"


class FeatureReplay:
    """A recorded session: ``meta`` plus FeatureFrames (validated on read)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"feature recording not found: {self.path}")
        log.warning(R3_WARNING, extra={"fields": {"file": str(self.path)}})
        with open_jsonl(self.path, "r") as fh:
            first = orjson.loads(fh.readline() or b"{}")
        if first.get("type") != "meta":
            raise ValueError(f"{self.path}: first line must be the meta record")
        first.pop("type")
        self.meta: dict[str, Any] = first

    def frames(self) -> Iterator[FeatureFrame]:
        """All frames, as fast as possible."""
        with open_jsonl(self.path, "r") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = orjson.loads(line)
                if record.pop("type", None) == "frame":
                    yield FeatureFrame.model_validate(record)

    def play(
        self,
        speed: float = 1.0,
        *,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Iterator[FeatureFrame]:
        """Yield frames at their recorded times divided by ``speed`` (``speed <= 0`` or ``inf`` = no waiting)."""
        realtime = speed > 0 and math.isfinite(speed)
        start_wall: float | None = None
        start_t = 0.0
        for frame in self.frames():
            if realtime:
                if start_wall is None:
                    start_wall, start_t = clock(), frame.t
                due = start_wall + (frame.t - start_t) / speed
                delay = due - clock()
                if delay > 0:
                    sleep(delay)
            yield frame

    def labels_path(self) -> Path:
        return self.path.parent / "labels.jsonl"

    def summary(self) -> dict[str, Any]:
        n = face = small = gaze = hands = phones = phone_hits = 0
        first_t = last_t = 0.0
        widths: list[float] = []
        for frame in self.frames():
            if n == 0:
                first_t = frame.t
            last_t = frame.t
            n += 1
            face += frame.face.present
            small += frame.face.too_small
            if frame.face.width_px is not None:
                widths.append(frame.face.width_px)
            gaze += frame.gaze is not None
            hands += frame.hands is not None
            if frame.phones is not None:
                phones += 1
                phone_hits += bool(frame.phones)
        duration = last_t - first_t
        widths.sort()
        return {
            "frames": n,
            "duration_s": round(duration, 2),
            "fps": round((n - 1) / duration, 2) if duration > 0 else 0.0,
            "face_present_pct": round(100 * face / n, 1) if n else 0.0,
            "face_too_small_pct": round(100 * small / n, 1) if n else 0.0,
            "face_width_px_median": widths[len(widths) // 2] if widths else None,
            "gaze_runs": gaze,
            "gesture_runs": hands,
            "phone_runs": phones,
            "phone_runs_with_box": phone_hits,
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", type=Path)
    p.add_argument("--play", type=float, default=None, metavar="SPEED", help="replay with timing at SPEED x")
    args = p.parse_args(argv)
    configure_logging("WARNING", json=False)

    replay = FeatureReplay(args.path)
    camera = replay.meta.get("camera", {})
    print(f"session : {replay.meta.get('label') or '-'} ({replay.meta.get('created')})")
    print(f"camera  : {camera.get('name')} {camera.get('width')}x{camera.get('height')} @ {camera.get('fps')} fps")
    models = ", ".join(f"{name}={info.get('backend')}" for name, info in replay.meta.get("models", {}).items())
    print(f"models  : {models}")
    for key, value in replay.summary().items():
        print(f"{key:22s}: {value}")

    labels_path = replay.labels_path()
    if labels_path.exists():
        _, events = load_labels(labels_path)
        intervals = to_intervals(events)
        counts: dict[str, int] = {}
        for interval in intervals:
            name = f"zone:{interval.value}" if interval.value else interval.label
            counts[name] = counts.get(name, 0) + 1
        print(f"labels  : {len(events)} events -> {len(intervals)} intervals {counts}")

    if args.play:
        t0 = time.perf_counter()
        n = 0
        for frame in replay.play(args.play):
            n += 1
            if n % 150 == 0:
                print(f"  t={frame.t:7.2f} s  frame {frame.frame_id}  face={frame.face.present}", flush=True)
        print(f"replayed {n} frames in {time.perf_counter() - t0:.1f} s at {args.play}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
