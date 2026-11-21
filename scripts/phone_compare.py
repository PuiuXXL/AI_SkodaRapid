"""Live phone-detector comparison on the driver camera (P1): YOLO26n@416, YOLO26n@640, YOLO26s@640 on the SAME frames.

    python scripts/phone_compare.py            # guided: 6 positions x 10 s, then the report

Positions: at the ear, in the hand in front of the chest, in the lap, shown from the side, no phone, wallet in the
hand. Every captured frame (1080p, processed at ``cameras.driver.process_width`` like the runtime) goes through the
three variants with a low ``conf_min`` (0.10), so the threshold is chosen afterwards: per variant, the lowest threshold
with **no** false frame on "no phone" / "wallet", then the detection rate per phone position at it. Latency p50 / p95
per variant on this machine (the runtime runs the detector at ``rates.phone_hz``). Report:
docs/eval/phone-compare-<date>.md. Nothing is recorded (no frames, no images).
"""

from __future__ import annotations

import argparse
import datetime as dt
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from perception.capture import LatestFrameCamera, OpenCVSource, list_devices, select_device  # noqa: E402
from perception.config import load_config  # noqa: E402
from perception.perf import percentile  # noqa: E402
from perception.phone import PhoneConfig, PhoneDetector  # noqa: E402
from perception.worker import downscale, process_size  # noqa: E402

VARIANTS = {
    "yolo26n@416": ("perception/models/yolo26n_416.onnx", 416),
    "yolo26n@640": ("perception/models/yolo26n_640.onnx", 640),
    "yolo26s@640": ("perception/models/yolo26s_640.onnx", 640),
}
POSITIONS = [
    ("ear", "Telefonul LA URECHE (ca la un apel)", True),
    ("chest", "Telefonul IN MANA, in fata pieptului (citesti)", True),
    ("lap", "Telefonul IN POALA, privesti in jos la el", True),
    ("side", "ARATA telefonul din LATERAL, spre camera", True),
    ("none", "FARA telefon, mainile pe volan", False),
    ("wallet", "PORTOFELUL in mana, in fata pieptului (fara telefon)", False),
]
PREP_S, RECORD_S, WINDOW = 4.0, 10.0, "phone compare (nothing is recorded)"


def _banner(img: np.ndarray, lines: list[str]) -> np.ndarray:
    out = cv2.resize(img, (960, int(img.shape[0] * 960 / img.shape[1])))
    cv2.rectangle(out, (0, 0), (out.shape[1], 30 + 34 * len(lines)), (0, 0, 0), -1)
    for i, text in enumerate(lines):
        cv2.putText(out, text, (14, 34 + 34 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 220, 255), 2, cv2.LINE_AA)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--record-s", type=float, default=RECORD_S)
    args = p.parse_args(argv)
    cfg = load_config()
    cam_cfg = cfg.cameras.driver
    detectors = {
        name: PhoneDetector(PhoneConfig(device="cpu", cpu_model=path, cpu_imgsz=size, conf_min=0.10))
        for name, (path, size) in VARIANTS.items()
    }
    best: dict[str, dict[str, list[float]]] = {v: {pos: [] for pos, _, _ in POSITIONS} for v in VARIANTS}
    lat: dict[str, list[float]] = {v: [] for v in VARIANTS}
    source = OpenCVSource(cam_cfg, "driver", resolver=lambda: select_device("driver", cfg.cameras, list_devices()))
    with LatestFrameCamera(cam_cfg, "driver", source) as cam:
        first = cam.wait_new(0, timeout=15.0)
        info = cam.stats().info
        if first is None or info is None:
            print("driver camera not available", file=sys.stderr)
            return 2
        pw, ph = process_size(info.width, info.height, cam_cfg.process_width)
        print(f"capture {info.width}x{info.height} {info.fourcc}, processed at {pw}x{ph}", flush=True)
        last = first.frame_id
        while True:  # start gate: the person is in place and the window has the keyboard
            frame = cam.wait_new(last, timeout=1.0)
            if frame is not None:
                last = frame.frame_id
                cv2.imshow(WINDOW, _banner(frame.image, ["SOFER: click pe fereastra, apoi SPATIU pentru start"]))
            key = cv2.waitKey(1) & 0xFF
            if key == ord(" "):
                break
            if key in (ord("q"), 27):
                cv2.destroyAllWindows()
                return 1
        for pos, prompt, _ in POSITIONS:
            for phase, seconds in (("prep", PREP_S), ("rec", args.record_s)):
                t_end = time.monotonic() + seconds
                while time.monotonic() < t_end:
                    frame = cam.wait_new(last, timeout=1.0)
                    if frame is None:
                        continue
                    last = frame.frame_id
                    small = downscale(frame, pw, ph).image
                    status = f"PREGATESTE-TE: {t_end - time.monotonic():.0f} s" if phase == "prep" else "INREGISTREZ"
                    if phase == "rec":
                        confs = []
                        for name, det in detectors.items():
                            res = det.detect(small, time.monotonic())
                            lat[name].append(res.ms)
                            conf = max((b.score for b in res.boxes), default=0.0)
                            best[name][pos].append(conf)
                            confs.append(f"{name.split('@')[0][-1]}{name.split('@')[1]}:{conf:.2f}")
                        status += f" {t_end - time.monotonic():.0f} s  " + " ".join(confs)
                    cv2.imshow(WINDOW, _banner(frame.image, [prompt, status]))
                    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                        cv2.destroyAllWindows()
                        print("aborted")
                        return 1
    cv2.destroyAllWindows()
    return _report(best, lat, pw, ph, info.width, info.height)


def _report(best: dict[str, dict[str, list[float]]], lat: dict[str, list[float]], pw: int, ph: int, w: int,
            h: int) -> int:  # fmt: skip
    phone_pos = [pos for pos, _, has in POSITIONS if has]
    rows, summary = [], {}
    for name in VARIANTS:
        false_max = max((c for pos, _, has in POSITIONS if not has for c in best[name][pos]), default=0.0)
        thr = max(0.25, round(false_max + 0.02, 2))  # lowest threshold with zero false frames (never below 0.25)
        rates = {
            pos: 100.0 * sum(c >= thr for c in best[name][pos]) / max(1, len(best[name][pos])) for pos in phone_pos
        }
        p50, p95 = statistics.median(lat[name]), percentile(lat[name], 95)
        summary[name] = (statistics.mean(rates.values()), thr, p50, p95)
        rows.append(
            f"| {name} | {p50:.1f} / {p95:.1f} | {false_max:.2f} | {thr:.2f} | "
            + " | ".join(f"{rates[pos]:.0f}" for pos in phone_pos)
            + f" | {summary[name][0]:.0f} |"
        )
    # the best mean detection whose p95 still leaves the driver face >= 20 fps at rates.phone_hz (<= 60 ms p95)
    fit = {n: s for n, s in summary.items() if s[3] <= 60.0} or summary
    choice = max(fit, key=lambda n: (fit[n][0], -fit[n][3]))
    stamp = dt.date.today().isoformat()
    path = ROOT / "docs" / "eval" / f"phone-compare-{stamp}.md"
    lines = [
        f"# Phone detector comparison, driver camera ({stamp})",
        "",
        f"- capture {w}x{h}, processed at {pw}x{ph} (as the runtime); frames per position: "
        + ", ".join(f"{pos} {len(best['yolo26n@416'][pos])}" for pos, _, _ in POSITIONS),
        "- threshold per variant = lowest one with **zero** false frames on `none` + `wallet` (min 0.25)",
        "- detection % = frames with a phone box at that threshold (the runtime adds the 3-of-5 vote on top)",
        "",
        "| variant | ms p50 / p95 | max false conf | threshold | "
        + " | ".join(f"{p} %" for p in phone_pos)
        + " | mean % |",
        "|---|---|---|---|" + "---|" * len(phone_pos) + "---|",
        *rows,
        "",
        f"**Choice: {choice}, conf_min {summary[choice][1]:.2f}** (best mean detection with p95 <= 60 ms).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(rows))
    print(f"choice: {choice} conf_min {summary[choice][1]:.2f}\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
