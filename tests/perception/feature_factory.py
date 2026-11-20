"""Synthetic FeatureFrames for tests (no models, no camera)."""

from __future__ import annotations

from perception.features import (
    LANDMARK_INDICES,
    REQUIRED_BLENDSHAPES,
    FaceFeatures,
    FeatureFrame,
    GazeFeatures,
    HandFeatures,
    PhoneBox,
)


def make_face(i: int, *, width_px: float = 300.0, min_width: float = 250.0) -> FaceFeatures:
    blink = 0.9 if i % 30 == 0 else 0.05
    blendshapes = {name: 0.1 for name in REQUIRED_BLENDSHAPES}
    blendshapes.update(eyeBlinkLeft=blink, eyeBlinkRight=blink, jawOpen=round(0.01 * (i % 7), 4))
    return FaceFeatures(
        present=True,
        conf=min(1.0, width_px / min_width),
        width_px=width_px,
        too_small=width_px < min_width,
        landmarks=[
            (round(0.3 + 0.001 * k, 5), round(0.4 + 0.0005 * i, 5), -0.01) for k in range(len(LANDMARK_INDICES))
        ],
        blendshapes=blendshapes,
        head_matrix=[1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, -40.0, 0, 0, 0, 1.0],
    )


def make_frame(i: int, fps: float = 30.0) -> FeatureFrame:
    """Frame i of a synthetic session: face every frame, gaze every 2nd, phone every 6th, hands every 3rd."""
    no_face = i % 50 == 49
    return FeatureFrame(
        t=round(i / fps, 4),
        frame_id=i + 1,
        camera="driver",
        face=FaceFeatures(present=False, conf=0.0) if no_face else make_face(i),
        gaze=GazeFeatures(pitch_deg=-5.0 + i % 3, yaw_deg=2.5) if i % 2 == 0 and not no_face else None,
        phones=([PhoneBox(x1=100, y1=200, x2=180, y2=330, score=0.71)] if i % 12 == 0 else []) if i % 6 == 0 else None,
        hands=(
            [
                HandFeatures(
                    handedness="Right",
                    score=0.97,
                    gesture="Thumb_Up",
                    gesture_score=0.8,
                    landmarks=[(0.5, 0.5, 0.0)] * 21,
                )
            ]
            if i % 3 == 0
            else None
        ),
    )
