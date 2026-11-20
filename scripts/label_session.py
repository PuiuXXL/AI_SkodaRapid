"""Record features live AND mark what really happens, with keys. The labels are the ground truth for evaluation.

    python scripts/label_session.py --seconds 60 --label "desk, lamp on"

Keys (window must have focus; press briefly, do not hold: a key repeated within 0.6 s is ignored):
  b       blink (press when you blink)
  c       eyes closed: press when you close them, press again when you open them
  y       yawn: start / end
  s       speaking: start / end
  p       phone in use: start / end
  z1..z8  gaze zone (order of gaze.zones in perception.yaml); z0 clears
  q, Esc  stop

Writes data/features/<session>/features.jsonl.gz (FeatureFrames, no pixels) and labels.jsonl (same clock).
The camera image is only shown, never stored. Replay afterwards: python -m perception.replay <features file>.
Only record people who agreed to it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import numpy.typing as npt

from perception.config import load_config
from perception.features import FeatureFrame
from perception.labels import KeyLabeler, LabelWriter
from perception.log import configure_logging
from perception.perf import RateMeter
from perception.recorder import DATA_DIR, RecordingSession

HELP = "b blink | c closed | y yawn | s speak | p phone | z<n> zone | q quit"


def _session_dir(root: Path, label: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", label).strip("-").lower()[:40]
    return root / (f"{stamp}_{slug}" if slug else stamp)


def _overlay(image: npt.NDArray[np.uint8], lines: list[str], recording: bool) -> npt.NDArray[np.uint8]:
    img = image.copy()
    if recording:
        cv2.circle(img, (img.shape[1] - 30, 30), 10, (0, 0, 255), -1)
    y = 28
    for line in lines:
        cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 255, 80), 1, cv2.LINE_AA)
        y += 26
    return img


def _status(features: FeatureFrame | None) -> str:
    if features is None:
        return "face: -"
    face = features.face
    if not face.present:
        return "face: NOT FOUND"
    small = "  TOO SMALL (R-FL3)" if face.too_small else ""
    return f"face: {face.width_px:.0f} px, conf {face.conf:.2f}{small}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--label", default="", help="free text stored with the session (no personal data)")
    p.add_argument("--camera", choices=["driver", "passenger"], default="driver")
    p.add_argument("--out-dir", type=Path, default=DATA_DIR / "features")
    p.add_argument("--gesture-hz", type=float, default=10.0)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--config", type=Path, default=None)
    args = p.parse_args(argv)

    configure_logging("WARNING", json=False)
    cfg = load_config(args.config)
    session_dir = _session_dir(args.out_dir, args.label)
    features_path = session_dir / "features.jsonl.gz"
    labels_path = session_dir / "labels.jsonl"

    session = RecordingSession(
        cfg,
        features_path,
        camera=args.camera,
        label=args.label,
        synthetic=args.synthetic,
        gesture_hz=args.gesture_hz or None,
    )
    writer = LabelWriter(
        labels_path,
        {
            "session": session_dir.name,
            "label": args.label,
            "zones": list(cfg.gaze.zones),
            "clock": "seconds since session start",
        },
    )
    labeler = KeyLabeler(writer, cfg.gaze.zones)
    rate = RateMeter()
    last_msg = ""
    window = "DriveMate label session (q to stop)"
    print(f"recording {args.seconds:.0f} s into {session_dir}\n{HELP}", flush=True)
    try:
        while (now := session.now()) < args.seconds:
            step = session.step(timeout=1.0)
            if step is None:
                continue
            frame, features = step
            rate.tick()
            active = ", ".join(sorted(labeler.active)) or "-"
            lines = [
                f"REC {now:5.1f} / {args.seconds:.0f} s   {rate.rate():4.1f} fps   frames {session.writer.count}",
                _status(features),
                f"active: {active}   zone: {labeler.zone or '-'}",
                f"last: {last_msg}",
                HELP,
            ]
            cv2.imshow(window, _overlay(frame.image, lines, recording=True))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key != 0xFF:
                msg = labeler.on_key(chr(key), session.now())
                if msg:
                    last_msg = f"{msg} @ {session.now():.2f} s"
                    print(last_msg, flush=True)
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        labeler.finish(session.now())
        writer.close()
        session.close()
        cv2.destroyAllWindows()

    print(f"\nframes : {session.writer.count} -> {features_path}")
    print(f"labels : {writer.count} events -> {labels_path}")
    print(f"replay : python -m perception.replay {features_path}")
    return 0 if session.writer.count else 1


if __name__ == "__main__":
    raise SystemExit(main())
