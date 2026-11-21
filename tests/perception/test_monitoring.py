"""CameraMonitor on synthetic frames: black, dark, frozen, blurred, day/night switch, no frames, R-FL3."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
import yaml

from perception.monitoring import CameraMonitor, CameraMonitorConfig, MonitoringResult, image_stats

PENDING = Path(__file__).resolve().parents[2] / "perception" / "config" / "pending" / "modules.yaml"
H, W = 180, 320
FPS = 30.0
Image = npt.NDArray[np.uint8]
_RNG = np.random.default_rng(0)


def _noise(sigma: float, shape: tuple[int, ...]) -> npt.NDArray[np.float64]:
    return _RNG.normal(0.0, sigma, shape)


def scene(luma: float = 128.0, amp: float = 60.0, colour: bool = True) -> Image:
    """Sharp, structured scene (8 px checkerboard) with fresh sensor noise on every call."""
    yy, xx = np.mgrid[0:H, 0:W]
    board = np.where(((yy // 8) + (xx // 8)) % 2 == 0, amp, -amp)
    grey = luma + board + _noise(2.0, (H, W))
    if not colour:
        return np.clip(grey, 0, 255).astype(np.uint8)
    bgr = np.stack([grey - 20, grey, grey + 25], axis=2)  # tinted: clearly coloured
    return np.clip(bgr, 0, 255).astype(np.uint8)


def black() -> Image:
    """Lens covered: almost uniform, only sensor noise."""
    return np.clip(2.0 + _noise(1.0, (H, W, 3)), 0, 255).astype(np.uint8)


def blurred() -> Image:
    """Defocused: smooth gradient (contrast, but no edges)."""
    grad = np.tile(np.linspace(40, 220, W), (H, 1)) + _noise(0.7, (H, W))
    return np.clip(np.stack([grad - 10, grad, grad + 10], axis=2), 0, 255).astype(np.uint8)


def run(
    mon: CameraMonitor,
    t0: float,
    t1: float,
    make: Callable[[], Image],
    face: bool,
    width: float | None = 300.0,
) -> list[tuple[float, MonitoringResult]]:
    out = []
    for i in range(round((t1 - t0) * FPS)):
        t = t0 + i / FPS
        out.append((t, mon.update(t, make(), face_present=face, face_width_px=width if face else None)))
    return out


def test_pending_yaml_matches_defaults() -> None:
    section = yaml.safe_load(PENDING.read_text(encoding="utf-8"))["monitoring"]
    assert CameraMonitorConfig.from_mapping(section) == CameraMonitorConfig()


def test_good_frames_with_a_face_are_ok() -> None:
    r = run(CameraMonitor(), 0.0, 3.0, scene, face=True)[-1][1]
    assert r.ok and r.reason is None and r.warnings == () and r.mode == "color"
    assert r.confidence == 1.0 and r.luma is not None and r.ms >= 0.0


def test_black_frame_without_face_is_occluded_after_face_lost_s() -> None:
    mon = CameraMonitor()
    run(mon, 0.0, 1.0, scene, face=True)
    results = run(mon, 1.0, 3.5, black, face=False)
    assert all(r.ok for t, r in results if t < 1.0 + 1.9)
    assert results[-1][1].reason == "occluded" and not results[-1][1].ok
    assert not any(r.mode_switched for _, r in results)
    back = run(mon, 3.5, 4.0, scene, face=True)  # uncovered: no luma-jump "mode switch"
    assert back[-1][1].ok and not any(r.mode_switched for _, r in back)


def test_dark_structured_scene_without_face_is_too_dark() -> None:
    mon = CameraMonitor()
    r = run(mon, 0.0, 3.0, lambda: scene(luma=30.0, amp=20.0), face=False)[-1][1]
    assert r.reason == "too_dark"


def test_dark_scene_with_a_face_is_only_a_warning() -> None:
    r = run(CameraMonitor(), 0.0, 3.0, lambda: scene(luma=30.0, amp=20.0), face=True)[-1][1]
    assert r.ok and r.warnings == ("too_dark",)


def test_blurred_without_face_and_with_face() -> None:
    r = run(CameraMonitor(), 0.0, 3.0, blurred, face=False)[-1][1]
    assert r.reason == "blurred"
    r = run(CameraMonitor(), 0.0, 3.0, blurred, face=True)[-1][1]
    assert r.ok and r.warnings == ("blurred",)


def test_good_image_without_face_is_face_lost() -> None:
    results = run(CameraMonitor(), 0.0, 3.0, scene, face=False)
    assert all(r.ok for t, r in results if t < 1.9)
    assert results[-1][1].reason == "face_lost" and results[-1][1].face_missing_s >= 2.0


def test_frozen_frames_even_with_a_face() -> None:
    still = scene()
    results = run(CameraMonitor(), 0.0, 2.0, lambda: still, face=True)
    assert results[10][1].ok
    assert results[-1][1].reason == "frozen"


def test_static_live_scene_is_not_frozen() -> None:
    base = scene()

    def live() -> Image:  # same scene, only sensor noise changes
        return np.clip(base.astype(np.float64) + _noise(1.5, base.shape), 0, 255).astype(np.uint8)

    assert run(CameraMonitor(), 0.0, 3.0, live, face=True)[-1][1].ok


def test_no_frames() -> None:
    mon = CameraMonitor()
    run(mon, 0.0, 1.0, scene, face=True)
    assert mon.tick(1.5).ok  # last result repeated within no_frames_s
    r = mon.tick(2.1)
    assert not r.ok and r.reason == "no_frames"
    assert mon.update(2.2, scene(), face_present=True).ok  # frames are back


def test_no_frames_from_the_start() -> None:
    mon = CameraMonitor()
    assert mon.tick(0.0).ok
    assert mon.tick(1.0).reason == "no_frames"


def test_colour_to_mono_switch_is_a_mode_switch() -> None:
    mon = CameraMonitor()
    run(mon, 0.0, 1.0, scene, face=True)
    results = run(mon, 1.0, 3.5, lambda: scene(colour=False), face=True)
    first = results[0][1]
    assert first.mode_switched and first.reason == "mode_switch" and first.mode == "mono"
    assert all(r.reason == "mode_switch" for t, r in results if t < 1.0 + 1.45)
    assert sum(r.mode_switched for _, r in results) == 1
    assert results[-1][1].ok


def test_grey_three_channel_frames_count_as_mono() -> None:
    def grey3() -> Image:
        g = scene(colour=False)
        return np.stack([g, g, g], axis=2)

    r = run(CameraMonitor(), 0.0, 1.0, grey3, face=True)[-1][1]
    assert r.mode == "mono" and r.ok and not r.mode_switched


def test_luma_jump_with_structure_is_a_mode_switch_but_a_covered_lens_is_not() -> None:
    mon = CameraMonitor()
    run(mon, 0.0, 1.0, lambda: scene(luma=70.0, amp=30.0), face=True)
    r = mon.update(1.0, scene(luma=180.0, amp=30.0), face_present=True)
    assert r.mode_switched and r.reason == "mode_switch"
    mon = CameraMonitor()
    run(mon, 0.0, 1.0, scene, face=True)
    r = mon.update(1.0, black(), face_present=False)
    assert not r.mode_switched


def test_mode_switch_hold_zero_disables_it() -> None:
    mon = CameraMonitor(CameraMonitorConfig(mode_switch_hold_s=0.0))
    run(mon, 0.0, 1.0, scene, face=True)
    r = mon.update(1.0, scene(colour=False), face_present=True)
    assert r.mode_switched and r.ok


def test_face_too_small_lowers_confidence_only() -> None:
    r = run(CameraMonitor(), 0.0, 1.0, scene, face=True, width=150.0)[-1][1]
    assert r.ok and r.face_too_small and r.confidence == pytest.approx(0.6)
    assert r.warnings == ("face_too_small",)


def test_image_stats_on_mono_and_colour() -> None:
    s = image_stats(scene(colour=False))
    assert s.chroma == 0.0 and s.std > 30 and s.sharpness > 100
    c = image_stats(np.zeros((720, 1280, 3), np.uint8))
    assert c.luma == 0.0 and c.std == 0.0


def test_reason_priority_frozen_over_face_lost() -> None:
    still = black()
    r = run(CameraMonitor(), 0.0, 3.0, lambda: still, face=False)[-1][1]
    assert r.reason == "frozen"
