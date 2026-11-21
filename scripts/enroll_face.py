"""Enroll a face for identity (AS10 / AP1): good frames -> ``profiles/<name>/face_<camera>.npy``.

    python scripts/enroll_face.py --name andrei --camera driver
    python scripts/enroll_face.py --name maria --camera passenger --device 2

Sit as in the car and look at the camera; small head movements and expressions are welcome (frames are at least
``identity.enroll_interval_s`` apart). Every frame is checked: exactly one face, YuNet score, face width, sharpness;
the embedding is the normalised mean of ``identity.enroll_frames`` (10) good frames, and every frame must agree with it.
Enroll each person **once per camera**: the two cameras see the face differently.

The embedding is biometric data: it stays on this laptop (``profiles/*/face*.npy`` is gitignored), is never committed
and never sent anywhere. No image is stored. Settings: ``perception/config/perception.yaml`` (section
``identity``, built by ``perception/module_config.py``) and the camera from the same file.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from perception.capture import LatestFrameCamera
from perception.config import REPO_ROOT, load_config
from perception.identity import (
    CAMERAS,
    Enroller,
    EnrollResult,
    FaceGallery,
    FaceIdentifier,
    embedding_path,
    safe_name,
)
from perception.log import configure_logging
from perception.module_config import identity_config

PROFILES = REPO_ROOT / "profiles"
WINDOW = "DriveMate enroll (q to abort)"


def _device(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def similar_profiles(result: EnrollResult, name: str, camera: str, threshold: float) -> list[tuple[str, float]]:
    """Other profiles of the same camera this embedding would match (they would be confused live)."""
    gallery = FaceGallery.load(PROFILES, camera)
    sims = gallery.similarities(result.embedding)
    return sorted(((n, s) for n, s in sims.items() if n != name and s >= threshold), key=lambda x: -x[1])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="profile name: letters, digits, '-' or '_'")
    p.add_argument("--camera", choices=CAMERAS, default="driver")
    p.add_argument("--device", default=None, help="override the camera device (index or path) from perception.yaml")
    p.add_argument("--frames", type=int, default=None, help="good frames to collect (default: identity.enroll_frames)")
    p.add_argument("--timeout-s", type=float, default=60.0)
    p.add_argument("--force", action="store_true", help="overwrite an existing embedding for this camera")
    p.add_argument("--no-preview", action="store_true", help="no OpenCV window (status on stdout only)")
    p.add_argument("--config", type=Path, default=None, help="perception.yaml (camera settings)")
    args = p.parse_args(argv)

    configure_logging("WARNING", json=False)
    try:
        name = safe_name(args.name)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    cfg = load_config(args.config)
    icfg = identity_config(cfg)
    if args.frames is not None:
        icfg = dataclasses.replace(icfg, enroll_frames=args.frames)
    out = embedding_path(PROFILES, name, args.camera)
    if out.exists() and not args.force:
        print(f"{out} exists; use --force to replace it", file=sys.stderr)
        return 1

    cam_cfg = getattr(cfg.cameras, args.camera)
    if args.device is not None:
        cam_cfg = cam_cfg.model_copy(update={"device": _device(args.device)})
    identifier = FaceIdentifier(icfg, FaceGallery(args.camera), camera=args.camera)
    enroller = Enroller(identifier)
    print(f"enrolling '{name}' on the {args.camera} camera: {icfg.enroll_frames} good frames, look at the camera")

    camera = LatestFrameCamera(cam_cfg, args.camera).start()
    last_id, last_reason = 0, ""
    start = time.perf_counter()
    aborted = False
    try:
        while not enroller.done:
            if time.perf_counter() - start > args.timeout_s:
                print(f"timeout after {args.timeout_s:.0f} s (last problem: {last_reason})", file=sys.stderr)
                return 2
            frame = camera.wait_new(last_id, timeout=1.0)
            if frame is None:
                continue
            last_id = frame.frame_id
            step = enroller.offer(frame.t_capture, frame.image)
            if step.reason != "too_soon":
                if step.reason != last_reason or step.accepted:
                    print(f"  {step.count}/{step.needed}  {step.reason}", flush=True)
                last_reason = step.reason
            if not args.no_preview:
                img = frame.image.copy() if frame.image.ndim == 3 else cv2.cvtColor(frame.image, cv2.COLOR_GRAY2BGR)
                colour = (0, 200, 0) if step.accepted or last_reason == "ok" else (0, 0, 255)
                text = f"{step.count}/{step.needed}  {last_reason}"
                cv2.putText(img, text, (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2, cv2.LINE_AA)
                cv2.imshow(WINDOW, img)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    aborted = True
                    break
    finally:
        camera.stop()
        if not args.no_preview:
            cv2.destroyAllWindows()
    if aborted:
        print("aborted, nothing saved")
        return 1
    try:
        result = enroller.finish()
    except ValueError as exc:
        print(f"enrollment failed: {exc}", file=sys.stderr)
        return 2
    path = Enroller.save(PROFILES, name, args.camera, result.embedding)
    print(f"saved {path.relative_to(REPO_ROOT)} ({result.frames} frames, consistency {result.consistency:.2f})")
    clash = similar_profiles(result, name, args.camera, icfg.cosine_threshold)
    for other, sim in clash:
        print(
            f"warning: similar to profile '{other}' (cosine {sim:.2f} >= {icfg.cosine_threshold}): re-enroll "
            "both with better light, or they may be confused",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
