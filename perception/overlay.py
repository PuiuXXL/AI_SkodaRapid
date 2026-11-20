"""Debug overlay for the driver camera (key D on the dashboard; preview / live_driver / eval windows).

Draws on a COPY of the frame: eye and mouth landmarks, EAR per eye + baseline, eyeSquint, eye state, head angles,
YAWN / SPEAKING, face width + FACE TOO SMALL (R-FL3), mean luma + TOO DARK, fps and stage timings.
Nothing is stored: the image is only shown or streamed.
"""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np
import numpy.typing as npt

from perception.driver_cam.eyes import EAR_POINTS
from perception.driver_cam.pipeline import DriverState
from perception.features import LANDMARK_GROUPS, FeatureFrame

__all__ = ["draw_driver", "mean_luma"]

Image = npt.NDArray[np.uint8]

GREEN = (80, 255, 80)
RED = (40, 40, 255)
AMBER = (0, 190, 255)
GREY = (200, 200, 200)
STATE_COLOURS = {"OPEN": GREEN, "CLOSED": RED, "SQUINT": AMBER, "UNKNOWN": GREY}
_MOUTH = LANDMARK_GROUPS["mouth_inner"] + LANDMARK_GROUPS["mouth_outer"]


def mean_luma(image: Image) -> float:
    """Mean brightness 0-255 (on a 4x downscale: cheap enough for every frame)."""
    small = image[::4, ::4]
    return float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean())


def _text(
    img: Image, text: str, org: tuple[int, int], colour: tuple[int, int, int] = GREEN, scale: float = 0.6
) -> None:
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, colour, 1, cv2.LINE_AA)


def _points(img: Image, ff: FeatureFrame, indices: Sequence[int], colour: tuple[int, int, int]) -> None:
    h, w = img.shape[:2]
    for i in indices:
        x, y, _ = ff.face.point(i)
        cv2.circle(img, (round(x * w), round(y * h)), 2, colour, -1, cv2.LINE_AA)


def draw_driver(
    image: Image,
    ff: FeatureFrame | None,
    state: DriverState | None,
    *,
    fps: float | None = None,
    timings: dict[str, float] | None = None,
    luma: float | None = None,
    dark_luma: float = 60.0,
    banner: str | None = None,
) -> Image:
    img = image.copy()
    h, w = img.shape[:2]
    if ff is not None and ff.face.present and ff.face.landmarks is not None:
        eye_colour = STATE_COLOURS[state.eyes.state] if state else GREEN
        for idx in EAR_POINTS.values():
            _points(img, ff, idx, eye_colour)
        _points(img, ff, _MOUTH, AMBER if state and state.yawn else (GREEN if state and state.speaking else GREY))

    lines: list[tuple[str, tuple[int, int, int]]] = []
    if state is not None:
        e = state.eyes
        base = (
            f"{e.baseline_left:.3f}/{e.baseline_right:.3f}{' (prov.)' if e.baseline_provisional else ''}"
            if e.baseline_left is not None and e.baseline_right is not None
            else "learning..."
        )
        lines.append((f"EYES {e.state}  closed {e.closed_ms} ms  perclos {e.perclos_60s:.2f}", STATE_COLOURS[e.state]))
        ear_l = f"{e.ear_left:.3f}" if e.ear_left is not None else "-"
        ear_r = f"{e.ear_right:.3f}" if e.ear_right is not None else "-"
        lines.append((f"EAR L {ear_l}  R {ear_r}  used {e.eye_used or '-'}  base {base}", GREEN))
        squint = f"{e.eye_squint:.2f}" if e.eye_squint is not None else "-"
        ratio = f"{e.ratio:.2f}" if e.ratio is not None else "-"
        blink = f"{e.blink_ms} ms" if e.blink_ms is not None else "-"
        rate = f"{e.blink_rate:.0f}/min" if e.blink_rate is not None else "-"
        lines.append((f"ratio {ratio}  eyeSquint {squint}  last blink {blink}  rate {rate}", GREEN))
        hd = state.head
        if hd.yaw is not None:
            nod = "  NODDING" if hd.nodding else ""
            lines.append(
                (f"yaw {hd.yaw:+6.1f}  pitch {hd.pitch:+6.1f}  roll {hd.roll:+6.1f}{nod}", RED if nod else GREEN)
            )
        flags = " ".join(f for f, on in (("YAWN", state.yawn), ("SPEAKING", state.speaking)) if on)
        lines.append((flags or "mouth: -", AMBER if state.yawn else GREEN))
        f = state.face
        if f.present:
            lines.append((f"face {f.width_px:.0f} px  conf {f.conf:.2f}", AMBER if f.too_small else GREEN))
        else:
            lines.append(("NO FACE", RED))
    perf = []
    if fps is not None:
        perf.append(f"{fps:4.1f} fps")
    for key, value in (timings or {}).items():
        perf.append(f"{key} {value:.1f}")
    if luma is not None:
        perf.append(f"luma {luma:.0f}")
    if perf:
        lines.append(("  ".join(perf), GREY))

    y = 26
    for text, colour in lines:
        _text(img, text, (12, y), colour)
        y += 24
    warnings = []
    if state is not None and state.face.too_small:
        warnings.append("FACE TOO SMALL - move closer (R-FL3)")
    if luma is not None and luma < dark_luma:
        warnings.append("TOO DARK - add light")
    for k, text in enumerate(warnings):
        _text(img, text, (12, h - 20 - 30 * k), RED, 0.8)
    if banner:
        size = cv2.getTextSize(banner, cv2.FONT_HERSHEY_SIMPLEX, 1.1, 3)[0]
        org = ((w - size[0]) // 2, h // 2 + 120)
        cv2.rectangle(img, (org[0] - 12, org[1] - size[1] - 14), (org[0] + size[0] + 12, org[1] + 14), (0, 0, 0), -1)
        cv2.putText(img, banner, org, cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3, cv2.LINE_AA)
    return img
