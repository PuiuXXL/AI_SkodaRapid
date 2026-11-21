"""HandTracker: held gestures, rates, raised hand, positions (no camera; fake recognizer; real model under `models`)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from perception.features import HandFeatures
from perception.hands import HandsConfig, HandsResult, HandTracker, as_bgr

W, H = 1280, 720
FACE = (540.0, 150.0, 200.0, 240.0)  # x, y, w, h: face bottom at y = 390
FPS = 30.0


def hand(gesture: str | None = "Thumb_Up", score: float = 0.9, cx: float = 0.5, cy: float = 0.3) -> HandFeatures:
    """21 landmarks on a 5x5 grid around (cx, cy), normalized; cy=0.3 -> palm at y~216 px (raised)."""
    points = [(cx + 0.01 * (i % 5 - 2), cy + 0.01 * (i // 5 - 2), 0.0) for i in range(21)]
    return HandFeatures(handedness="Right", score=0.95, gesture=gesture, gesture_score=score, landmarks=points)


def feed(tracker: HandTracker, t0: float, t1: float, hands: list[HandFeatures] | None) -> list[HandsResult]:
    out = []
    n = round((t1 - t0) * FPS)
    for i in range(n):
        out.append(tracker.update(t0 + i / FPS, hands, (W, H), FACE))
    return out


def test_unknown_config_key_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        HandsConfig.from_mapping({"min_ms": 500.0, "typo": 1})


def test_gesture_reported_only_after_min_ms() -> None:
    tr = HandTracker()
    tr.set_dialog(True, until=100.0)
    results = feed(tr, 0.0, 0.8, [hand("Thumb_Up")])
    first = next(i for i, r in enumerate(results) if r.gesture == "Thumb_Up")
    assert 0.5 <= first / FPS < 0.5 + 2 / FPS
    assert all(r.gesture is None for r in results[:first])
    assert results[-1].gesture_score == pytest.approx(0.9)
    assert results[0].candidate == "Thumb_Up" and results[0].mode == "dialog"


def test_short_gesture_is_not_reported() -> None:
    tr = HandTracker()
    tr.set_dialog(True)
    results = feed(tr, 0.0, 0.3, [hand("Thumb_Down")]) + feed(tr, 0.3, 1.5, [])
    assert all(r.gesture is None for r in results)


def test_one_frame_dropout_does_not_break_the_hold() -> None:
    tr = HandTracker()
    tr.set_dialog(True)
    a = feed(tr, 0.0, 0.3, [hand("Thumb_Up")])
    b = feed(tr, 0.3, 0.3 + 1 / FPS, [hand(None)])  # recognizer flicker: hand seen, no gesture
    c = feed(tr, 0.3 + 1 / FPS, 0.7, [hand("Thumb_Up")])
    assert all(r.gesture is None for r in a + b)
    assert c[-1].gesture == "Thumb_Up"


def test_long_dropout_breaks_the_hold_and_does_not_count() -> None:
    tr = HandTracker()
    tr.set_dialog(True)
    feed(tr, 0.0, 0.3, [hand("Thumb_Up")])
    gap = feed(tr, 0.3, 0.6, [])  # 300 ms without it > dropout_ms
    assert all(r.gesture is None for r in gap)
    assert gap[-1].candidate is None
    after = feed(tr, 0.6, 1.0, [hand("Thumb_Up")])
    assert all(r.gesture is None for r in after)  # restarted at 0.6: 0.4 s < min_ms


def test_changing_gesture_restarts_the_hold() -> None:
    tr = HandTracker()
    tr.set_dialog(True)
    a = feed(tr, 0.0, 0.4, [hand("Thumb_Up")])
    b = feed(tr, 0.4, 0.8, [hand("Thumb_Down")])
    c = feed(tr, 0.8, 1.0, [hand("Thumb_Down")])
    assert all(r.gesture is None for r in a + b)
    assert c[-1].gesture == "Thumb_Down"


def test_low_score_and_other_gestures_ignored() -> None:
    tr = HandTracker()
    tr.set_dialog(True)
    results = feed(tr, 0.0, 1.0, [hand("Thumb_Up", score=0.4)]) + feed(tr, 1.0, 2.0, [hand("Victory")])
    assert all(r.gesture is None and r.candidate is None for r in results)


def test_best_of_two_hands_wins() -> None:
    tr = HandTracker()
    tr.set_dialog(True)
    results = feed(tr, 0.0, 0.7, [hand("Open_Palm", 0.7, cx=0.3), hand("Thumb_Up", 0.95, cx=0.7)])
    assert results[-1].gesture == "Thumb_Up"
    assert len(results[-1].hands) == 2


def test_background_needs_a_raised_hand() -> None:
    tr = HandTracker()  # no dialog window
    low = feed(tr, 0.0, 1.5, [hand("Thumb_Up", cy=0.9)])  # palm at y~648 px: below the chin line
    assert all(r.gesture is None for r in low)
    assert low[0].mode == "background"
    raised = feed(tr, 2.0, 3.0, [hand("Thumb_Up", cy=0.3)])
    assert raised[-1].gesture == "Thumb_Up"


def test_raised_without_face_box_uses_frame_height() -> None:
    tr = HandTracker()
    r = tr.update(0.0, [hand(cy=0.3)], (W, H), None)
    assert r.hands[0].raised
    r = tr.update(0.1, [hand(cy=0.8)], (W, H), None)
    assert not r.hands[0].raised


def test_rates_background_dialog_and_raised_boost() -> None:
    tr = HandTracker(HandsConfig(background_hz=2.0, dialog_hz=0.0, raised_boost_s=2.0))
    assert tr.should_run(0.0)
    tr.update(0.0, [hand(cy=0.9)], (W, H), FACE)  # low hand: no boost
    assert not tr.should_run(0.2)
    assert tr.should_run(0.5)
    tr.set_dialog(True, until=3.0)
    assert tr.should_run(0.53) and tr.should_run(0.56)  # every frame inside the window
    assert tr.rate_hz(1.0) == 0.0
    assert tr.mode(3.0) == "background"  # window expired
    tr.update(3.0, [hand(cy=0.3)], (W, H), FACE)  # raised hand in the background -> boost to the dialog rate
    assert tr.should_run(3.03)
    assert tr.mode(3.03) == "background"
    tr.update(5.5, [], (W, H), FACE)
    assert not tr.should_run(5.6)


def test_background_rate_zero_means_off() -> None:
    tr = HandTracker(HandsConfig(background_hz=0.0))
    assert not tr.should_run(0.0)
    tr.set_dialog(True)
    assert tr.should_run(0.0)


def test_dialog_expiry_resets_the_hold() -> None:
    tr = HandTracker()
    tr.set_dialog(True, until=1.0)
    before = feed(tr, 0.4, 1.0, [hand("Thumb_Up", cy=0.9)])
    after = feed(tr, 1.0, 1.6, [hand("Thumb_Up", cy=0.9)])  # low hand: only valid inside the window
    assert before[-1].gesture == "Thumb_Up"
    assert all(r.gesture is None for r in after)


def test_gap_between_observations_breaks_the_hold() -> None:
    tr = HandTracker()
    tr.set_dialog(True)
    tr.update(0.0, [hand()], (W, H), FACE)
    r = tr.update(0.3, None, (W, H), FACE)  # model did not run, inside max_gap_s: hold continues
    assert r.candidate == "Thumb_Up" and not r.ran
    r = tr.update(1.2, None, (W, H), FACE)  # > max_gap_s without observation
    assert r.candidate is None
    r = tr.update(1.3, [hand()], (W, H), FACE)
    assert r.held_ms == 0.0


def test_positions_in_pixels() -> None:
    tr = HandTracker()
    r = tr.update(0.0, [hand(cx=0.5, cy=0.5)], (W, H), FACE)
    h = r.hands[0]
    lm = hand(cx=0.5, cy=0.5).landmarks
    assert h.wrist_px == pytest.approx((lm[0][0] * W, lm[0][1] * H), abs=0.1)
    palm_x = sum(lm[i][0] for i in (0, 5, 9, 13, 17)) / 5 * W
    palm_y = sum(lm[i][1] for i in (0, 5, 9, 13, 17)) / 5 * H
    assert h.palm_px == pytest.approx((palm_x, palm_y), abs=0.1)
    assert r.last_hand_t == 0.0
    assert r.to_dict()["hands"][0]["handedness"] == "Right"


class FakeRecognizer:
    def __init__(self, y: float = 0.25) -> None:
        self.y = y  # 0.25: raised hand, 0.9: hand low (no boost outside the window)
        self.calls: list[tuple[tuple[int, ...], int]] = []

    def recognize_for_video(self, image: Any, ts: int) -> Any:
        self.calls.append((image.shape, ts))
        pts = [SimpleNamespace(x=0.5, y=self.y, z=0.0) for _ in range(21)]
        return SimpleNamespace(
            hand_landmarks=[pts],
            handedness=[[SimpleNamespace(category_name="Left", score=0.97)]],
            gestures=[[SimpleNamespace(category_name="Open_Palm", score=0.88)]],
        )


def test_process_runs_the_recognizer_on_a_mono_frame() -> None:
    fake = FakeRecognizer()
    tr = HandTracker(recognizer=fake)
    tr.set_dialog(True)
    grey = np.zeros((H, W), dtype=np.uint8)
    results = [tr.process(grey, i / FPS, FACE) for i in range(20)]
    assert fake.calls[0][0] == (H, W, 3)  # GREY expanded to 3 channels
    stamps = [ts for _, ts in fake.calls]
    assert stamps == sorted(set(stamps))  # strictly increasing ms (VIDEO mode)
    assert results[-1].gesture == "Open_Palm" and results[-1].ran
    assert results[-1].ms >= 0.0


def test_process_skips_when_not_scheduled() -> None:
    fake = FakeRecognizer(y=0.9)
    tr = HandTracker(HandsConfig(background_hz=2.0), recognizer=fake)
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    tr.process(frame, 0.0)
    r = tr.process(frame, 0.1)
    assert len(fake.calls) == 1 and not r.ran and len(r.hands) == 1  # last hands repeated


def test_as_bgr_shapes() -> None:
    assert as_bgr(np.zeros((4, 5), np.uint8)).shape == (4, 5, 3)
    assert as_bgr(np.zeros((4, 5, 1), np.uint8)).shape == (4, 5, 3)
    colour = np.zeros((4, 5, 3), np.uint8)
    assert as_bgr(colour) is colour


@pytest.mark.models
@pytest.mark.slow
def test_real_gesture_recognizer_on_a_black_frame() -> None:
    cfg = HandsConfig()
    if not cfg.model_path().exists():
        pytest.skip("gesture_recognizer.task not downloaded")
    tr = HandTracker(cfg)
    tr.set_dialog(True)
    try:
        r = tr.process(np.zeros((480, 640, 3), dtype=np.uint8), 0.0)
        r = tr.process(np.zeros((480, 640), dtype=np.uint8), 0.04)
    finally:
        tr.close()
    assert r.ran and r.hands == () and r.gesture is None
