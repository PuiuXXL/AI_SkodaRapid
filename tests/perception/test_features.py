from __future__ import annotations

import pytest
from pydantic import ValidationError

from perception.features import (
    LANDMARK_GROUPS,
    LANDMARK_INDICES,
    FaceFeatures,
    FeatureFrame,
    landmark_slot,
)
from tests.perception.feature_factory import make_face, make_frame


def test_landmark_indices_cover_ear_and_iris_points() -> None:
    ear = {33, 160, 158, 133, 153, 144, 362, 385, 387, 263, 373, 380}
    assert ear <= set(LANDMARK_INDICES)
    assert {468, 473} <= set(LANDMARK_INDICES)  # iris centres
    assert len(LANDMARK_INDICES) == len(set(LANDMARK_INDICES))
    assert set(LANDMARK_GROUPS["face_oval"]) <= set(LANDMARK_INDICES)


def test_json_round_trip_is_identical() -> None:
    frame = make_frame(6)
    assert frame.phones is not None and frame.hands is not None and frame.gaze is not None
    assert FeatureFrame.from_json(frame.to_json()) == frame


def test_point_lookup_by_mediapipe_index() -> None:
    face = make_face(0)
    assert face.landmarks is not None
    assert face.point(468) == face.landmarks[landmark_slot(468)]


def test_present_face_needs_required_blendshapes() -> None:
    data = make_face(0).model_dump()
    del data["blendshapes"]["eyeSquintLeft"]
    with pytest.raises(ValidationError, match="eyeSquintLeft"):
        FaceFeatures.model_validate(data)


def test_present_face_needs_all_landmarks() -> None:
    data = make_face(0).model_dump()
    data["landmarks"] = data["landmarks"][:-1]
    with pytest.raises(ValidationError, match="landmarks"):
        FaceFeatures.model_validate(data)


def test_absent_face_carries_no_face_data() -> None:
    FaceFeatures(present=False, conf=0.0)
    with pytest.raises(ValidationError, match="present is false"):
        FaceFeatures(present=False, conf=0.0, blendshapes={"jawOpen": 0.1})


def test_unknown_fields_rejected() -> None:
    data = make_frame(0).model_dump()
    data["image"] = [[0, 0, 0]]
    with pytest.raises(ValidationError, match="image"):
        FeatureFrame.model_validate(data)


def test_no_pixel_fields_in_schema() -> None:
    def fields(model: type) -> set[str]:
        names = set(model.model_fields)  # type: ignore[attr-defined]
        return names

    for model in (FeatureFrame, FaceFeatures):
        assert not {"image", "pixels", "crop", "jpeg"} & fields(model)
