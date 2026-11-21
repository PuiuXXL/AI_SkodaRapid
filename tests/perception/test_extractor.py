from __future__ import annotations

import numpy as np
import pytest

from perception.capture import Frame
from perception.config import load_config
from perception.extractor import every_n_frames

pytest.importorskip("mediapipe")


def test_every_n_frames() -> None:
    assert every_n_frames(30, 15) == 2
    assert every_n_frames(30, 5) == 6
    assert every_n_frames(30, 10) == 3
    assert every_n_frames(30, 60) == 1
    assert every_n_frames(30, 0) == 1


@pytest.mark.models
@pytest.mark.slow
def test_extractor_on_blank_frame_reports_no_face() -> None:
    cfg = load_config()
    if not cfg.models.path(cfg.models.face_landmarker).exists():
        pytest.skip("models not downloaded (scripts/download_models.sh)")
    from perception.extractor import FeatureExtractor

    extractor = FeatureExtractor(cfg, camera_fps=30, gesture_hz=10)
    try:
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        frames = [extractor.extract(Frame(image, i + 1, 1.0 + i / 30), i / 30, "driver") for i in range(6)]
    finally:
        extractor.close()
    assert all(not f.face.present and f.face.conf == 0.0 for f in frames)
    assert all(f.gaze is None for f in frames)  # no face -> no gaze crop
    assert frames[0].phones == [] and frames[1].phones is None  # phone runs every 6th frame
    assert frames[0].hands == [] and frames[1].hands is None  # gestures every 3rd frame
