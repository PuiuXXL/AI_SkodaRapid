from __future__ import annotations

import numpy as np
import pytest

from perception.postprocess import gaze_angles, yolo26_detections
from perception.preprocess import crop_box, gaze_input, letterbox


def test_letterbox_shape_scale_and_padding() -> None:
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    tensor, meta = letterbox(frame, 640)
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert meta.scale == pytest.approx(0.5)
    assert (meta.pad_x, meta.pad_y) == (0, 140)
    # padding rows are grey (114/255), image rows are black
    assert tensor[0, 0, 0, 0] == pytest.approx(114 / 255)
    assert tensor[0, 0, 320, 320] == pytest.approx(0.0)


def test_letterbox_converts_bgr_to_rgb() -> None:
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frame[:, :, 0] = 255  # blue in BGR
    tensor, _ = letterbox(frame, 10)
    assert tensor[0, 2].max() == pytest.approx(1.0)  # channel 2 = B in RGB
    assert tensor[0, 0].max() == pytest.approx(0.0)


def test_yolo_boxes_mapped_back_and_filtered() -> None:
    frame_shape = (720, 1280, 3)
    _, meta = letterbox(np.zeros(frame_shape, dtype=np.uint8), 640)
    rows = np.array(
        [
            [100, 240, 200, 340, 0.9, 67],  # phone, kept
            [100, 240, 200, 340, 0.2, 67],  # phone, low score
            [100, 240, 200, 340, 0.9, 0],  # person, other class
        ],
        dtype=np.float32,
    )[None]
    dets = yolo26_detections(rows, meta, frame_shape, conf_min=0.4, class_ids={67})
    assert len(dets) == 1
    d = dets[0]
    assert (d.x1, d.y1, d.x2, d.y2) == pytest.approx((200, 200, 400, 400))
    assert d.class_id == 67 and d.score == pytest.approx(0.9)
    assert d.center == pytest.approx((300, 300))


def test_yolo_boxes_are_clipped() -> None:
    frame_shape = (100, 100, 3)
    _, meta = letterbox(np.zeros(frame_shape, dtype=np.uint8), 100)
    rows = np.array([[-20, -20, 150, 150, 0.8, 67]], dtype=np.float32)
    (d,) = yolo26_detections(rows, meta, frame_shape, conf_min=0.5)
    assert (d.x1, d.y1, d.x2, d.y2) == (0, 0, 100, 100)


def test_gaze_angles_from_one_hot_bins() -> None:
    pitch = np.full(90, -50.0)
    yaw = np.full(90, -50.0)
    pitch[45] = 50.0  # 45 * 4 - 180 = 0 degrees
    yaw[50] = 50.0  # 50 * 4 - 180 = 20 degrees
    p, y = gaze_angles(pitch, yaw)
    assert p == pytest.approx(0.0, abs=1e-6)
    assert y == pytest.approx(20.0, abs=1e-6)


def test_gaze_input_normalization() -> None:
    face = np.full((60, 40, 3), 128, dtype=np.uint8)
    tensor = gaze_input(face, size=448)
    assert tensor.shape == (1, 3, 448, 448)
    assert tensor[0, 0, 0, 0] == pytest.approx((128 / 255 - 0.485) / 0.229, rel=1e-4)


def test_crop_box_clips_and_expands() -> None:
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    crop = crop_box(img, (80, 80, 40, 40), expand=1.0)
    assert crop is not None and crop.shape[:2] == (20, 20)
    assert crop_box(img, (200, 200, 10, 10)) is None
