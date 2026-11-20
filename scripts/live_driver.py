"""Live driver camera: Face Landmarker -> eye / head / mouth detectors -> overlay window.

    python scripts/live_driver.py                       # window with the debug overlay (q / Esc to quit)
    python scripts/live_driver.py --print               # also one DriverState JSON per second in the terminal
    python scripts/live_driver.py --record-features data/features/test/features.jsonl.gz
    python scripts/live_driver.py --gaze --phone        # also run MobileGaze and YOLO (for timing)

The camera image is only shown, never stored. --record-features writes FeatureFrames (no pixels).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from perception.capture import LatestFrameCamera, SyntheticSource
from perception.config import load_config
from perception.driver_cam.pipeline import DriverPipeline
from perception.extractor import FeatureExtractor
from perception.log import configure_logging
from perception.overlay import draw_driver, mean_luma
from perception.perf import LatencyWindow, RateMeter
from perception.recorder import FeatureWriter, build_metadata


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--print", dest="print_json", action="store_true", help="print one DriverState JSON per second")
    p.add_argument("--record-features", type=Path, default=None, metavar="PATH")
    p.add_argument("--label", default="live_driver")
    p.add_argument("--seconds", type=float, default=0.0, help="0 = until q / Esc")
    p.add_argument("--gaze", action="store_true")
    p.add_argument("--phone", action="store_true")
    p.add_argument("--no-window", action="store_true")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--config", type=Path, default=None)
    args = p.parse_args(argv)

    configure_logging("WARNING", json=False)
    cfg = load_config(args.config)
    cam_cfg = cfg.cameras.driver
    source = SyntheticSource(cam_cfg.width, cam_cfg.height, cam_cfg.fps) if args.synthetic else None
    window = "DriveMate driver camera (q to quit)"
    rate = RateMeter()
    total = LatencyWindow(cfg.rates.perf_window)

    with LatestFrameCamera(cam_cfg, "driver", source) as cam:
        first = cam.wait_new(0, timeout=10.0)
        info = cam.stats().info
        if first is None or info is None:
            print("camera delivered no frame", file=sys.stderr)
            return 1
        extractor = FeatureExtractor(cfg, camera_fps=info.fps or cam_cfg.fps, gaze=args.gaze, phone=args.phone)
        pipeline = DriverPipeline(cfg, (info.width, info.height))
        writer = None
        if args.record_features:
            meta = build_metadata(
                cfg,
                "driver",
                info,
                label=args.label,
                models=extractor.models,
                cadence=extractor.cadence,
                synthetic=args.synthetic,
            )
            writer = FeatureWriter(args.record_features, meta)
        t0 = time.perf_counter()
        last_id, last_print = first.frame_id, 0.0
        print(f"camera {info.width}x{info.height} {info.fourcc} @ {info.fps:.0f} fps", flush=True)
        try:
            while not args.seconds or time.perf_counter() - t0 < args.seconds:
                frame = cam.wait_new(last_id, timeout=1.0)
                if frame is None:
                    continue
                last_id = frame.frame_id
                t = frame.t_capture - t0
                if t < 0:
                    continue
                ff = extractor.extract(frame, t, "driver")
                state = pipeline.update(ff)
                if writer:
                    writer.write(ff)
                total.add((time.perf_counter() - frame.t_capture) * 1000.0)
                rate.tick()
                if args.print_json and t - last_print >= 1.0:
                    last_print = t
                    print(state.model_dump_json(exclude={"perf"}), flush=True)
                if not args.no_window:
                    timings = {"face": extractor.face.latency.p50(), "e2e": total.p50()}
                    img = draw_driver(
                        frame.image,
                        ff,
                        state,
                        fps=rate.rate(),
                        timings=timings,
                        luma=mean_luma(frame.image),
                        dark_luma=cfg.monitoring.dark_luma,
                    )
                    cv2.imshow(window, img)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                        break
        except KeyboardInterrupt:
            pass
        finally:
            extractor.close()
            if writer:
                writer.close()
            if not args.no_window:
                cv2.destroyAllWindows()
    print(
        f"face model p50 {extractor.face.latency.p50():.1f} ms · capture->state p50 {total.p50():.1f} ms "
        f"p95 {total.p95():.1f} ms"
    )
    if writer:
        print(f"wrote {writer.count} FeatureFrames to {args.record_features}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
