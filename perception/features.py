"""FeatureFrame: what the models extract from ONE camera frame, before any detector or filter. No pixels.

Recorded by :mod:`perception.recorder`, read back by :mod:`perception.replay`, used to tune and evaluate detectors
on real data, repeatably, without ever storing images (docs/perception.md, data policy).

Conventions:
* ``t``: seconds since the start of the recording session (``time.perf_counter()`` based); labels use the same clock.
* Landmarks: MediaPipe normalized ``(x, y, z)`` (x, y in 0..1 of the frame), only the indices in
  :data:`LANDMARK_INDICES`, in that order. Pixel coordinates = ``x * width``, ``y * height`` from the session metadata.
* A model that did **not run** on this frame gives ``None``; a model that ran and found nothing gives ``[]``.
"""

from __future__ import annotations

from typing import Annotated, Self

import orjson
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "LANDMARK_GROUPS",
    "LANDMARK_INDICES",
    "REQUIRED_BLENDSHAPES",
    "FaceFeatures",
    "FeatureFrame",
    "GazeFeatures",
    "HandFeatures",
    "PhoneBox",
    "landmark_slot",
]

FEATURE_SCHEMA_VERSION = 1

# fmt: off
_FACE_OVAL = (10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
              152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109)
# fmt: on

# MediaPipe Face Mesh indices kept per frame (the rest of the 478 are not needed by the detectors).
LANDMARK_GROUPS: dict[str, tuple[int, ...]] = {
    # eye contours (include the EAR points 33,160,158,133,153,144 and 362,385,387,263,373,380)
    "right_eye": (33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246),
    "left_eye": (263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466),
    "right_iris": (468, 469, 470, 471, 472),  # 468 = centre
    "left_iris": (473, 474, 475, 476, 477),  # 473 = centre
    "mouth_outer": (61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185),
    "mouth_inner": (78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191),
    "face_oval": _FACE_OVAL,
    "nose": (1, 4, 168),
}
LANDMARK_INDICES: tuple[int, ...] = tuple(dict.fromkeys(i for group in LANDMARK_GROUPS.values() for i in group))
_SLOT = {index: slot for slot, index in enumerate(LANDMARK_INDICES)}

REQUIRED_BLENDSHAPES: tuple[str, ...] = (
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeSquintLeft",
    "eyeSquintRight",
    "eyeLookDownLeft",
    "eyeLookDownRight",
    "eyeLookInLeft",
    "eyeLookInRight",
    "eyeLookOutLeft",
    "eyeLookOutRight",
    "eyeLookUpLeft",
    "eyeLookUpRight",
    "jawOpen",
    "mouthClose",
)

Point3 = tuple[float, float, float]
Score = Annotated[float, Field(ge=0, le=1)]


def landmark_slot(mediapipe_index: int) -> int:
    """Position of a MediaPipe landmark index inside ``FaceFeatures.landmarks``."""
    return _SLOT[mediapipe_index]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FaceFeatures(_Model):
    present: bool
    conf: Score  # geometry-based (R-FL3): 1.0 at/above min_face_width_px, scaled below, 0 without a face
    width_px: Annotated[float, Field(ge=0)] | None = None
    too_small: bool = False  # R-FL3
    landmarks: list[Point3] | None = None  # LANDMARK_INDICES order, normalized
    blendshapes: dict[str, float] | None = None  # all 52 MediaPipe categories (REQUIRED_BLENDSHAPES at least)
    head_matrix: Annotated[list[float], Field(min_length=16, max_length=16)] | None = None  # 4x4, row-major

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not self.present:
            if self.landmarks or self.blendshapes or self.head_matrix:
                raise ValueError("face.present is false but face data is set")
            return self
        if self.landmarks is None or len(self.landmarks) != len(LANDMARK_INDICES):
            raise ValueError(f"face.landmarks must have {len(LANDMARK_INDICES)} points (LANDMARK_INDICES)")
        if self.blendshapes is None:
            raise ValueError("face.blendshapes missing for a present face")
        missing = [name for name in REQUIRED_BLENDSHAPES if name not in self.blendshapes]
        if missing:
            raise ValueError(f"face.blendshapes missing required categories: {missing}")
        if self.head_matrix is None:
            raise ValueError("face.head_matrix missing for a present face")
        return self

    def point(self, mediapipe_index: int) -> Point3:
        """Normalized landmark by its MediaPipe index (must be in LANDMARK_INDICES)."""
        if self.landmarks is None:
            raise ValueError("no face landmarks in this frame")
        return self.landmarks[landmark_slot(mediapipe_index)]


class GazeFeatures(_Model):
    """MobileGaze output for the face crop, in degrees."""

    pitch_deg: float
    yaw_deg: float


class HandFeatures(_Model):
    handedness: str  # "Left" / "Right" as reported by MediaPipe
    score: Score
    gesture: str | None = None  # top canned gesture, e.g. "Thumb_Up", "None"
    gesture_score: Score | None = None
    landmarks: Annotated[list[Point3], Field(min_length=21, max_length=21)]  # normalized


class PhoneBox(_Model):
    """YOLO26 class-67 box in frame pixels."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: Score


class FeatureFrame(_Model):
    t: float  # seconds since session start
    frame_id: int
    camera: str
    face: FaceFeatures
    gaze: GazeFeatures | None = None  # None = MobileGaze did not run on this frame
    hands: list[HandFeatures] | None = None  # None = Gesture Recognizer did not run
    phones: list[PhoneBox] | None = None  # None = YOLO did not run

    def to_json(self) -> bytes:
        return orjson.dumps(self.model_dump(mode="json", exclude_none=False))

    @classmethod
    def from_json(cls, data: bytes | str) -> FeatureFrame:
        return cls.model_validate(orjson.loads(data))
