"""Eye-state CNN: crop / input preparation and its fusion with the EAR detector (synthetic, no model file needed).

The CNN output is injected through ``FaceFeatures.eye_closed_p``, exactly where the extractor puts it live.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pytest

from perception.config import load_config
from perception.driver_cam.eye_cnn import eye_crop, eye_input
from perception.driver_cam.eyes import EyeOutput, EyeTracker
from tests.perception.driver_factory import FPS, H, W, face, frames

OPEN = 0.30


def _run(spec: Sequence[tuple[float, Mapping[str, object]]]) -> tuple[EyeTracker, list[EyeOutput]]:
    tracker = EyeTracker(load_config().eyes, (W, H), (OPEN, OPEN))
    return tracker, [tracker.update(ff) for ff in frames(spec)]


# hard squint from the held-out session: ratio ~0.4 (below the squint band) and eyeBlink ~0.55, like a closure
HARD_SQUINT = {"ear_left": OPEN * 0.40, "blink": 0.55, "squint": 0.7}


def test_without_cnn_a_hard_squint_reads_as_closed() -> None:
    """The problem the CNN is there for (documents the EAR-only limitation)."""
    _tracker, outs = _run([(2.0, {"ear_left": OPEN}), (3.0, HARD_SQUINT)])
    assert outs[-1].state == "CLOSED"
    assert outs[-1].cnn_closed is None


def test_cnn_open_vetoes_the_hard_squint() -> None:
    tracker, outs = _run(
        [(2.0, {"ear_left": OPEN}), (3.0, {**HARD_SQUINT, "cnn": [0.1, 0.12]}), (1.0, {"ear_left": OPEN})]
    )
    assert "CLOSED" not in {o.state for o in outs[round(2.5 * FPS) :]}
    assert max(o.closed_ms for o in outs) < tracker.cfg.blink_max_ms
    assert [e for e in tracker.events if e.kind == "closure"] == []
    assert outs[round(4 * FPS)].cnn_closed == pytest.approx(0.1)


def test_cnn_closed_confirms_a_low_contrast_closure() -> None:
    """EAR barely drops (ratio 0.6, in the squint band) and eyeBlink is weak, but the pixels show a closed eye."""
    closed = {"ear_left": OPEN * 0.6, "blink": 0.35, "cnn": [0.9, 0.92]}
    _tracker, outs = _run([(2.0, {"ear_left": OPEN}), (2.0, closed)])
    assert outs[-1].state == "CLOSED" and outs[-1].closed_ms > 1500


def test_cnn_is_bilateral_like_the_ear() -> None:
    """One eye closed for the CNN, the other open: the most open eye decides (not closed)."""
    _tracker, outs = _run([(2.0, {"ear_left": OPEN}), (3.0, {**HARD_SQUINT, "cnn": [0.95, 0.1]})])
    assert outs[-1].cnn_closed == pytest.approx(0.1)
    assert outs[-1].state != "CLOSED"


def test_blinks_do_not_need_the_cnn() -> None:
    """Fast blinks are detected from the EAR shape alone, whatever the CNN says on the few blink frames."""
    tracker, _ = _run(
        [(1.0, {"ear_left": OPEN}), (0.15, {"ear_left": 0.06, "cnn": [0.2, 0.2]}), (1.0, {"ear_left": OPEN})]
    )
    assert [e.kind for e in tracker.events] == ["blink"]


def test_eye_crop_and_input() -> None:
    img = np.random.default_rng(0).integers(0, 255, size=(H, W, 3), dtype=np.uint8)
    f = face()
    crop = eye_crop(img, f, "left", 1.6)
    assert crop is not None and crop.shape[0] == crop.shape[1] == round(50 * 1.6)  # factory eyes are 50 px wide
    x = eye_input(crop)
    assert x.shape == (1, 3, 32, 32) and x.dtype == np.float32
    assert float(x.min()) >= -0.51 and float(x.max()) <= 0.51  # (x - 127) / 255
    assert eye_crop(img, f, "left", 60.0) is None  # leaves the frame
