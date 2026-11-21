"""posture.py: leaning forward / sideways, slumped, out of position vs. a reference, with a minimum duration."""

from __future__ import annotations

import pytest

from perception.config import load_config
from perception.posture import PostureRef, PostureTracker, face_geometry
from tests.perception.driver_factory import FPS, H, W, face

REF = PostureRef(cx=640.0, cy=360.0, width=300.0, yaw=0.0, pitch=0.0, roll=0.0)


def _hold(geometry: tuple[float, float, float], seconds: float, pitch: float = 0.0, roll: float = 0.0) -> list[str]:
    tracker = PostureTracker(load_config().posture)
    tracker.set_reference(REF)
    out = None
    for i in range(round(seconds * FPS)):
        out = tracker.update(i / FPS, geometry, 0.0, pitch, roll)
    assert out is not None
    return out.active()


@pytest.mark.parametrize(
    ("geometry", "pitch", "roll", "expected"),
    [
        ((640.0, 360.0, 300.0), 0.0, 0.0, []),  # upright
        ((640.0, 360.0, 390.0), 0.0, 0.0, ["leaning_forward"]),  # face 30 % wider
        ((850.0, 360.0, 300.0), 0.0, 0.0, ["leaning_side"]),  # 0.7 face widths sideways
        ((640.0, 360.0, 300.0), 0.0, 20.0, ["leaning_side"]),  # head rolled 20 deg
        ((640.0, 500.0, 300.0), -15.0, 0.0, ["slumped"]),  # lower and pitched down
        ((640.0, 360.0, 150.0), 0.0, 0.0, ["out_of_position"]),  # far back: half the width
    ],
)
def test_each_posture_state(
    geometry: tuple[float, float, float], pitch: float, roll: float, expected: list[str]
) -> None:
    assert _hold(geometry, 1.5, pitch, roll) == expected


def test_short_moves_are_not_a_posture() -> None:
    assert _hold((850.0, 360.0, 300.0), 0.5) == []  # a 0.5 s reach / mirror check: below min_duration_s


def test_automatic_reference_without_calibration() -> None:
    cfg = load_config().posture
    tracker = PostureTracker(cfg)
    n_ref = round((cfg.auto_ref_s + 0.1) * FPS)
    for i in range(n_ref):
        out = tracker.update(i / FPS, (640.0, 360.0, 300.0), 0.0, 0.0, 0.0)
    assert out.reference == "auto" and out.active() == []
    for i in range(n_ref, n_ref + round(1.5 * FPS)):
        out = tracker.update(i / FPS, (640.0, 360.0, 400.0), 0.0, 0.0, 0.0)
    assert out.active() == ["leaning_forward"]


def test_face_geometry_from_landmarks() -> None:
    cx, cy, width = face_geometry(face(width_px=300.0), (W, H)) or (0.0, 0.0, 0.0)
    assert cx == pytest.approx(640.0) and width == 300.0 and 0 < cy < H
