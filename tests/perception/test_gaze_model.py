"""MobileGaze wrapper: pre-processing identical to yakhyo/gaze-estimation, decoding, signs, smoothing."""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from perception.config import load_config
from perception.driver_cam.gaze_model import GAZE_SIGNS, GazeSmoother, driver_gaze
from perception.features import GazeFeatures
from perception.postprocess import gaze_angles, gaze_from_outputs
from perception.preprocess import crop_box, gaze_input


def _yakhyo_preprocess(image: np.ndarray, size: int = 448) -> np.ndarray:
    """Transcribed from yakhyo/gaze-estimation onnx_inference.py (GazeEstimationONNX.preprocess)."""
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image = cv2.resize(image, (size, size))
    image = image.astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    image = (image - mean) / std
    image = np.transpose(image, (2, 0, 1))
    return np.asarray(np.expand_dims(image, axis=0), dtype=np.float32)


def _yakhyo_decode(yaw_logits: np.ndarray, pitch_logits: np.ndarray) -> tuple[float, float]:
    """Transcribed from GazeEstimationONNX.decode (returns degrees here; they convert to radians at the end)."""
    idx = np.arange(90, dtype=np.float32)

    def softmax(x: np.ndarray) -> np.ndarray:
        e = np.exp(x - np.max(x, axis=1, keepdims=True))
        return np.asarray(e / e.sum(axis=1, keepdims=True))

    yaw = np.sum(softmax(yaw_logits) * idx, axis=1) * 4 - 180
    pitch = np.sum(softmax(pitch_logits) * idx, axis=1) * 4 - 180
    return float(yaw[0]), float(pitch[0])


def test_preprocessing_matches_yakhyo() -> None:
    rng = np.random.default_rng(0)
    crop = rng.integers(0, 256, (233, 187, 3), dtype=np.uint8)  # non-square: squashed to 448x448 like theirs
    ours = gaze_input(crop, 448)
    ref = _yakhyo_preprocess(crop, 448)
    assert ours.shape == ref.shape == (1, 3, 448, 448)
    assert ours.dtype == np.float32
    np.testing.assert_allclose(ours, ref, atol=1e-5)


def test_decoding_matches_yakhyo_and_reads_outputs_by_name() -> None:
    rng = np.random.default_rng(1)
    yaw_logits = rng.normal(0, 3, (1, 90)).astype(np.float32)
    pitch_logits = rng.normal(0, 3, (1, 90)).astype(np.float32)
    ref_yaw, ref_pitch = _yakhyo_decode(yaw_logits, pitch_logits)
    pitch, yaw = gaze_from_outputs(["yaw", "pitch"], [yaw_logits, pitch_logits])  # the export order
    assert yaw == pytest.approx(ref_yaw, abs=1e-3)
    assert pitch == pytest.approx(ref_pitch, abs=1e-3)


def test_one_hot_bin_decodes_to_bin_angle() -> None:
    for k in (0, 30, 45, 89):
        logits = np.full(90, -50.0, dtype=np.float32)
        logits[k] = 50.0
        pitch, yaw = gaze_angles(logits, logits)
        assert pitch == pytest.approx(k * 4 - 180, abs=1e-6)
        assert yaw == pytest.approx(k * 4 - 180, abs=1e-6)


def test_crop_expand_one_is_the_face_box() -> None:
    image = np.arange(720 * 1280 * 3, dtype=np.uint32).reshape(720, 1280, 3).astype(np.uint8)
    crop = crop_box(image, (400.0, 200.0, 300.0, 340.0), expand=1.0)
    assert crop is not None
    assert crop.shape[:2] == (340, 300)
    np.testing.assert_array_equal(crop, image[200:540, 400:700])


def test_signs_map_raw_angles_to_the_driver_convention() -> None:
    # on a non-mirrored camera the raw yaw is the opposite of the driver's left (measured: corr -0.51 with head yaw)
    assert GAZE_SIGNS == {"yaw": -1.0, "pitch": 1.0}
    assert driver_gaze(GazeFeatures(yaw_deg=-20.0, pitch_deg=-10.0)) == (20.0, -10.0)


def test_smoother_holds_the_last_value_for_max_age_only() -> None:
    sm = GazeSmoother(min_cutoff=0.5, beta=0.0, d_cutoff=1.0, max_age_ms=250)
    assert sm.update(0.0, None) is None
    assert sm.update(0.0, GazeFeatures(yaw_deg=-10.0, pitch_deg=5.0)) == (10.0, 5.0)
    assert sm.update(0.2, None) == (10.0, 5.0)  # 200 ms: still fresh
    assert sm.update(0.3, None) is None  # 300 ms: too old


def test_smoother_reduces_noise_at_rest() -> None:
    cfg = load_config()
    f = cfg.filters.one_euro_gaze
    sm = GazeSmoother(f.min_cutoff, f.beta, f.d_cutoff, cfg.gaze.max_age_ms)
    rng = np.random.default_rng(2)
    raw = rng.normal(0.0, 4.3, 300)  # the raw yaw noise measured with the head still
    out = []
    for i, v in enumerate(raw):
        smoothed = sm.update(i / 15.0, GazeFeatures(yaw_deg=float(v), pitch_deg=0.0))
        assert smoothed is not None
        out.append(smoothed[0])
    assert float(np.std(out[30:])) < 0.5 * float(np.std(raw))


def test_smoother_follows_a_glance() -> None:
    cfg = load_config()
    f = cfg.filters.one_euro_gaze
    sm = GazeSmoother(f.min_cutoff, f.beta, f.d_cutoff, cfg.gaze.max_age_ms)
    for i in range(30):
        sm.update(i / 15.0, GazeFeatures(yaw_deg=0.0, pitch_deg=0.0))
    reached = None
    for i in range(30, 60):
        out = sm.update(i / 15.0, GazeFeatures(yaw_deg=-40.0, pitch_deg=0.0))  # 40 deg to the driver's left
        if out is not None and out[0] > 30.0 and reached is None:
            reached = (i - 30) / 15.0
    assert reached is not None and reached <= 0.2  # 75 % of a mirror glance within 200 ms


@pytest.mark.models
def test_real_model_returns_plausible_angles() -> None:
    cfg = load_config()
    if not cfg.models.path(cfg.models.gaze).exists():
        pytest.skip("MobileGaze model missing (scripts/download_models.sh)")
    from perception.driver_cam.gaze_model import MobileGazeModel

    model = MobileGazeModel(cfg)
    image = np.full((720, 1280, 3), 128, dtype=np.uint8)
    out = model.estimate(image, (500.0, 200.0, 280.0, 320.0))
    assert out is not None
    assert -180.0 <= out.yaw_deg <= 180.0 and -180.0 <= out.pitch_deg <= 180.0
    assert math.isfinite(model.latency.p50())
