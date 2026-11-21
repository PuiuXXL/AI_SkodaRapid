"""PhoneTracker geometry + 3-of-5 vote on synthetic boxes; PhoneDetector with a fake model on a mono frame."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from perception.hands import Hand
from perception.phone import PhoneConfig, PhoneDetector, PhoneResult, PhoneTracker
from perception.postprocess import Detection

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "data" / "features" / "20261121-005208_desk-test-laptop-webcam"
FACE = (540.0, 150.0, 200.0, 240.0)  # centre (640, 270), width 200
W, H = 1280, 720


def det(cx: float, cy: float, score: float = 0.8, w: float = 60.0, h: float = 110.0) -> Detection:
    return Detection(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, score, 67)


def hand_at(x: float, y: float) -> Hand:
    return Hand("Right", 0.95, None, None, (x, y + 30.0), (x, y), (x - 40, y - 40, 80, 80), False)


NEAR_FACE = det(700, 280)  # call: next to the face
IN_HAND = det(600, 560)  # below the face, a palm right under it
PASSENGER_FAR = det(250, 500)  # driver's right (image left), 390 px from the face centre
DRIVER_LEFT_FAR = det(1050, 500)  # driver's left (door side), far from the face


def vote(tracker: PhoneTracker, seq: list[bool], box: Detection = NEAR_FACE, **kw: Any) -> list[PhoneResult]:
    return [tracker.update(i * 0.2, [box] if seen else [], face_box=FACE, **kw) for i, seen in enumerate(seq)]


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError):
        PhoneConfig(vote_min=6, vote_window=5)
    with pytest.raises(ValueError):
        PhoneConfig(passenger_side="back")


def test_three_of_five_vote() -> None:
    assert not any(r.in_use for r in vote(PhoneTracker(), [True, False, True, False, False]))
    results = vote(PhoneTracker(), [True, True, False, True])
    assert [r.in_use for r in results] == [False, False, False, True]
    assert results[-1].votes == 3 and results[-1].runs == 4


def test_single_frame_flicker_is_removed() -> None:
    assert not any(r.in_use for r in vote(PhoneTracker(), [False, False, True, False, False, False, True, False]))


def test_vote_window_slides_out() -> None:
    results = vote(PhoneTracker(), [True, True, True, False, False, False])
    assert results[2].in_use and results[4].in_use  # [T,T,T,F,F]: still 3 of 5
    assert not results[5].in_use  # [T,T,F,F,F]


def test_frames_without_yolo_keep_the_decision() -> None:
    tr = PhoneTracker()
    vote(tr, [True, True, True])
    r = tr.update(1.0, None, face_box=FACE)
    assert r.in_use and not r.ran and r.runs == 3


def test_conf_is_the_mean_of_positive_runs() -> None:
    tr = PhoneTracker()
    tr.update(0.0, [det(700, 280, 0.6)], face_box=FACE)
    tr.update(0.2, [det(700, 280, 0.8)], face_box=FACE)
    r = tr.update(0.4, [det(700, 280, 1.0)], face_box=FACE)
    assert r.conf == pytest.approx(0.8)
    assert r.source == "detector"


def test_near_face_is_a_call_on_the_drivers_left() -> None:
    r = vote(PhoneTracker(), [True] * 3, NEAR_FACE)[-1]
    assert r.in_use and r.near_face and r.usage == "call"
    assert r.side == "left"  # image right of the face = the driver's left (not mirrored)
    assert r.box == pytest.approx((670.0, 225.0, 730.0, 335.0))


def test_phone_in_hand_below_the_face() -> None:
    r = vote(PhoneTracker(), [True] * 3, IN_HAND, hands=[hand_at(605, 600)])[-1]
    assert r.in_use and not r.near_face and r.usage == "hand" and r.side == "right"


def test_owned_phone_without_hand_is_visible() -> None:
    r = vote(PhoneTracker(), [True] * 3, DRIVER_LEFT_FAR)[-1]
    assert r.in_use and r.usage == "visible" and r.side == "left" and not r.foreign


def test_phone_from_the_right_far_from_the_face_is_not_the_drivers() -> None:
    results = vote(PhoneTracker(), [True] * 5, PASSENGER_FAR, hands=[hand_at(250, 540)])
    assert not any(r.in_use for r in results)
    assert results[-1].foreign and results[-1].votes == 0
    assert results[-1].foreign_box is not None


def test_passenger_side_near_the_face_is_still_the_drivers() -> None:
    r = vote(PhoneTracker(), [True] * 3, det(560, 300))[-1]  # driver's right ear
    assert r.in_use and r.near_face and r.side == "right" and r.usage == "call"


def test_driver_phone_wins_over_a_foreign_one_in_the_same_run() -> None:
    tr = PhoneTracker()
    r = None
    for i in range(3):
        r = tr.update(i * 0.2, [det(250, 500, 0.95), det(700, 280, 0.6)], face_box=FACE)
    assert r is not None and r.in_use and r.near_face and r.foreign


def test_mirrored_camera_flips_the_side() -> None:
    r = vote(PhoneTracker(PhoneConfig(mirrored=True)), [True] * 3, NEAR_FACE)[-1]
    assert r.side == "right"
    # mirrored: image left = the driver's left -> a far image-left phone is now on the door side, owned
    r = vote(PhoneTracker(PhoneConfig(mirrored=True)), [True] * 3, PASSENGER_FAR)[-1]
    assert r.in_use and r.side == "left"


def test_lap_pattern_only_without_a_voted_phone() -> None:
    tr = PhoneTracker()
    r = tr.update(0.0, [], face_box=FACE, lap_pattern=True)
    assert r.in_use and r.source == "lap_pattern" and r.usage == "lap" and r.conf == pytest.approx(0.40)
    r = vote(tr, [True] * 3, NEAR_FACE, lap_pattern=True)[-1]
    assert r.source == "detector" and r.usage == "call"


def test_no_face_box_still_votes_without_geometry() -> None:
    tr = PhoneTracker()
    r = None
    for i in range(3):
        r = tr.update(i * 0.2, [NEAR_FACE])
    assert r is not None and r.in_use and r.side is None and not r.near_face


def test_reset_clears_the_vote() -> None:
    tr = PhoneTracker()
    vote(tr, [True] * 3)
    tr.reset()
    assert not tr.update(1.0, None).in_use


class FakeYolo:
    """YOLO26 end-to-end output [1, N, 6] in letterboxed input coordinates."""

    def __init__(self) -> None:
        self.shapes: list[tuple[int, ...]] = []

    def run(self, feeds: Any) -> list[npt.NDArray[Any]]:
        self.shapes.append(feeds.shape)
        rows = [
            [100, 150, 150, 250, 0.9, 67],  # phone
            [10, 100, 60, 200, 0.95, 0],  # person: other class
            [200, 150, 250, 250, 0.2, 67],  # phone below conf_min
        ]
        return [np.array([rows], dtype=np.float32)]


def test_detector_on_a_mono_frame_with_a_fake_model() -> None:
    fake = FakeYolo()
    pd = PhoneDetector(model=fake, imgsz=416)
    out = pd.detect(np.zeros((H, W), dtype=np.uint8), 0.0)
    assert fake.shapes == [(1, 3, 416, 416)]  # GREY expanded to RGB and letterboxed
    assert len(out.boxes) == 1
    b = out.boxes[0]
    scale, pad_y = 416 / W, (416 - round(H * 416 / W)) // 2
    assert b.x1 == pytest.approx(100 / scale, abs=0.5)
    assert b.y1 == pytest.approx((150 - pad_y) / scale, abs=0.5)
    assert b.class_id == 67 and out.ms >= 0.0


def test_detector_rate() -> None:
    pd = PhoneDetector(PhoneConfig(rate_hz=5.0), model=FakeYolo())
    assert pd.should_run(0.0)
    pd.detect(np.zeros((90, 160, 3), dtype=np.uint8), 0.0)
    assert not pd.should_run(0.1)
    assert pd.should_run(0.2)
    pd.set_rate_hz(1.25)  # degraded
    assert not pd.should_run(0.5)
    assert pd.should_run(0.8)


@pytest.mark.slow
@pytest.mark.models
def test_real_yolo_on_a_black_frame(phone_detector_cpu: PhoneDetector) -> None:
    pd = phone_detector_cpu
    assert pd.imgsz == 640  # yolo26s@640 (docs/eval/phone-compare-2026-11-21.md)
    assert pd.detect(np.zeros((480, 640), dtype=np.uint8), 0.0).boxes == ()


@pytest.mark.realdata
@pytest.mark.slow
def test_vote_on_the_labelled_phone_in_a_real_session() -> None:
    """desk-test session: the phone label (held in front of the camera ~3 s) must produce an in-use vote."""
    if not (SESSION / "features.jsonl.gz").exists():
        pytest.skip("session 20261121-005208_desk-test-laptop-webcam not available")
    from perception.driver_cam.face import face_box_px
    from perception.hands import HandTracker
    from perception.labels import load_labels, to_intervals
    from perception.replay import FeatureReplay

    replay = FeatureReplay(SESSION / "features.jsonl.gz")
    cam = replay.meta["camera"]
    size = (cam["width"], cam["height"])
    _, events = load_labels(SESSION / "labels.jsonl")
    label = next(i for i in to_intervals(events) if i.label == "phone")
    hands, phone = HandTracker(), PhoneTracker()
    inside: list[bool] = []
    for ff in replay.frames():
        box = face_box_px(ff.face, *size)
        hr = hands.update(ff.t, ff.hands, size, box)
        r = phone.update(ff.t, ff.phones, face_box=box, hands=hr.hands)
        if label.start <= ff.t <= label.end:
            inside.append(r.in_use)
    assert any(inside)


def test_degenerate_face_box_does_not_make_every_phone_foreign() -> None:
    """A zero-width face box (degenerate landmarks) used to make near_face impossible and foreign always true."""
    from perception.features import PhoneBox
    from perception.phone import PhoneTracker

    g = PhoneTracker().geometry(PhoneBox(x1=560, y1=300, x2=640, y2=430, score=0.8), (640.0, 200.0, 0.0, 330.0), ())
    assert g.foreign is False and g.side is None
