"""Synthetic driver FeatureFrames with a chosen EAR, blendshapes, lip gap and head pose (no models, no camera)."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence

from perception.driver_cam.eyes import EAR_POINTS
from perception.features import LANDMARK_INDICES, REQUIRED_BLENDSHAPES, FaceFeatures, FeatureFrame, landmark_slot

W, H = 1280, 720
FPS = 30.0
FACE_HEIGHT_PX = 330.0


def rotation_matrix(pitch: float = 0.0, yaw: float = 0.0, roll: float = 0.0) -> list[float]:
    """Row-major 4x4 R = Rz(roll) @ Ry(yaw) @ Rx(pitch), angles in degrees (raw camera-frame rotations)."""
    a, b, c = (math.radians(v) for v in (pitch, yaw, roll))
    rx: list[list[float]] = [[1.0, 0.0, 0.0], [0.0, math.cos(a), -math.sin(a)], [0.0, math.sin(a), math.cos(a)]]
    ry: list[list[float]] = [[math.cos(b), 0.0, math.sin(b)], [0.0, 1.0, 0.0], [-math.sin(b), 0.0, math.cos(b)]]
    rz: list[list[float]] = [[math.cos(c), -math.sin(c), 0.0], [math.sin(c), math.cos(c), 0.0], [0.0, 0.0, 1.0]]

    def mul(p: list[list[float]], q: list[list[float]]) -> list[list[float]]:
        return [[sum(p[i][k] * q[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    r = mul(rz, mul(ry, rx))
    return [*r[0], 0.0, *r[1], 0.0, *r[2], -40.0, 0.0, 0.0, 0.0, 1.0]


def face(
    ear_left: float = 0.30,
    ear_right: float | None = None,
    *,
    blink: float = 0.05,
    squint: float = 0.05,
    jaw: float = 0.02,
    lip_gap: float = 0.01,
    width_px: float = 300.0,
    min_width: float = 250.0,
    matrix: list[float] | None = None,
) -> FaceFeatures:
    pts: list[tuple[float, float, float]] = [(0.5, 0.5, 0.0)] * len(LANDMARK_INDICES)

    def put(index: int, x_px: float, y_px: float) -> None:
        pts[landmark_slot(index)] = (x_px / W, y_px / H, 0.0)

    for side, ear, cx in (
        ("left", ear_left, 700.0),
        ("right", ear_right if ear_right is not None else ear_left, 580.0),
    ):
        p1, p2, p3, p4, p5, p6 = EAR_POINTS[side]
        dx, cy = 25.0, 330.0  # half eye width in px (eye width 50 px)
        v = ear * dx  # EAR = vertical / horizontal = (2v + 2v) / (2 * 2dx)
        put(p1, cx - dx, cy)
        put(p4, cx + dx, cy)
        put(p2, cx - dx / 3, cy - v)
        put(p6, cx - dx / 3, cy + v)
        put(p3, cx + dx / 3, cy - v)
        put(p5, cx + dx / 3, cy + v)
    top_y = 200.0
    put(10, 640.0, top_y)
    put(152, 640.0, top_y + FACE_HEIGHT_PX)
    put(13, 640.0, 450.0)
    put(14, 640.0, 450.0 + lip_gap * FACE_HEIGHT_PX)
    blend = {name: 0.05 for name in REQUIRED_BLENDSHAPES}
    blend.update(eyeBlinkLeft=blink, eyeBlinkRight=blink, eyeSquintLeft=squint, eyeSquintRight=squint, jawOpen=jaw)
    return FaceFeatures(
        present=True,
        conf=min(1.0, width_px / min_width),
        width_px=width_px,
        too_small=width_px < min_width,
        landmarks=pts,
        blendshapes=blend,
        head_matrix=matrix or rotation_matrix(),
    )


def frame(i: int, f: FaceFeatures, fps: float = FPS) -> FeatureFrame:
    return FeatureFrame(t=round(i / fps, 6), frame_id=i + 1, camera="driver", face=f)


def frames(
    spec: Sequence[tuple[float, Mapping[str, object]]], fps: float = FPS, start: int = 0
) -> Iterator[FeatureFrame]:
    """``spec`` = [(duration_s, face kwargs), ...] played back to back."""
    i = start
    for duration, kwargs in spec:
        for _ in range(round(duration * fps)):
            yield frame(i, face(**kwargs), fps)  # type: ignore[arg-type]
            i += 1
