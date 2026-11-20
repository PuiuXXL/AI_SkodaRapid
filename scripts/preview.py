"""Live camera preview with capture fps, display fps and capture->display latency.

    python scripts/preview.py                       # driver camera from perception.yaml
    python scripts/preview.py --camera passenger
    python scripts/preview.py --synthetic           # no camera needed
    python scripts/preview.py --seconds 15          # stop by itself (q / Esc also quit)
    python scripts/preview.py --no-window --seconds 10   # headless: stats only

Nothing is recorded: frames are only shown.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from perception.capture import Frame, LatestFrameCamera, SyntheticSource
from perception.config import load_config
from perception.log import configure_logging
from perception.perf import LatencyWindow, RateMeter


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--camera", choices=["driver", "passenger"], default="driver")
    p.add_argument("--config", type=Path, default=None, help="perception.yaml (default: perception/config/)")
    p.add_argument("--synthetic", action="store_true", help="use generated frames instead of a camera")
    p.add_argument("--seconds", type=float, default=0.0, help="stop after N seconds (0 = until q/Esc)")
    p.add_argument("--no-window", action="store_true", help="do not open a window; print stats only")
    return p.parse_args(argv)


def _overlay(frame: Frame, lines: list[str]) -> cv2.typing.MatLike:
    img = frame.image.copy()  # the camera's frame is shared: never draw on it
    y = 28
    for line in lines:
        cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 255, 80), 1, cv2.LINE_AA)
        y += 26
    return img


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    configure_logging("INFO", json=False)
    cfg = load_config(args.config)
    cam_cfg = getattr(cfg.cameras, args.camera)
    source = SyntheticSource(cam_cfg.width, cam_cfg.height, cam_cfg.fps) if args.synthetic else None

    latency = LatencyWindow(maxlen=600)
    display = RateMeter(window_s=1.0)
    window = f"DriveMate preview: {args.camera} (q / Esc to quit)"
    show = not args.no_window
    started = time.perf_counter()
    last_print = started
    shown = 0

    with LatestFrameCamera(cam_cfg, args.camera, source) as cam:
        last_id = 0
        while True:
            if args.seconds and time.perf_counter() - started >= args.seconds:
                break
            frame = cam.wait_new(last_id, timeout=1.0)
            if frame is None:
                if not cam.stats().connected:
                    print("waiting for camera...", flush=True)
                continue
            last_id = frame.frame_id
            stats = cam.stats()
            info = stats.info
            if show:
                fmt = f"{info.width}x{info.height} {info.fourcc} {info.backend}" if info else "?"
                lines = [
                    f"{args.camera}  {fmt}",
                    f"capture {stats.capture_fps:5.1f} fps   display {display.rate():5.1f} fps",
                    f"capture->display  p50 {latency.p50():5.1f} ms   p95 {latency.p95():5.1f} ms",
                    f"dropped {stats.dropped}   reconnects {stats.reconnects}",
                ]
                cv2.imshow(window, _overlay(frame, lines))
                key = cv2.waitKey(1) & 0xFF
                latency.add((time.perf_counter() - frame.t_capture) * 1000.0)
                if key in (ord("q"), 27):
                    break
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
            else:
                latency.add((time.perf_counter() - frame.t_capture) * 1000.0)
            display.tick()
            shown += 1
            now = time.perf_counter()
            if not show and now - last_print >= 2.0:
                last_print = now
                print(
                    f"capture {stats.capture_fps:5.1f} fps | display {display.rate():5.1f} fps | "
                    f"latency p50 {latency.p50():5.1f} ms p95 {latency.p95():5.1f} ms | dropped {stats.dropped}",
                    flush=True,
                )
        final = cam.stats()

    if show:
        cv2.destroyAllWindows()
    elapsed = time.perf_counter() - started
    info = final.info
    print("\n== preview summary ==")
    print(f"camera      : {args.camera} ({'synthetic' if args.synthetic else f'device {cam_cfg.device}'})")
    if info:
        print(f"obtained    : {info.width}x{info.height} {info.fourcc} @ {info.fps:.1f} fps ({info.backend})")
    print(f"requested   : {cam_cfg.width}x{cam_cfg.height} {cam_cfg.fourcc} @ {cam_cfg.fps} fps")
    print(f"frames shown: {shown} in {elapsed:.1f} s ({shown / elapsed if elapsed else 0:.1f} fps)")
    print(f"capture fps : {final.capture_fps:.1f}   captured {final.frames}   dropped {final.dropped}")
    print(f"latency     : capture->display p50 {latency.p50():.1f} ms, p95 {latency.p95():.1f} ms")
    print(f"reconnects  : {final.reconnects}")
    return 0 if shown else 1


if __name__ == "__main__":
    raise SystemExit(main())
