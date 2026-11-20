from __future__ import annotations

import itertools
import threading
import time

import pytest

from perception.capture import (
    CaptureInfo,
    Frame,
    LatestFrameCamera,
    SyntheticSource,
    decode_synthetic_id,
)
from perception.config import CameraConfig, load_config


@pytest.fixture
def cam_cfg() -> CameraConfig:
    base = load_config().cameras.driver
    return base.model_copy(update={"reconnect_s": 0.02, "max_read_failures": 3})


def _collect(cam: LatestFrameCamera, n: int, timeout: float = 3.0) -> list[Frame]:
    frames: list[Frame] = []
    last = 0
    deadline = time.monotonic() + timeout
    while len(frames) < n and time.monotonic() < deadline:
        frame = cam.wait_new(last, timeout=0.5)
        if frame is None:
            continue
        frames.append(frame)
        last = frame.frame_id
    return frames


def test_synthetic_source_encodes_sequence() -> None:
    src = SyntheticSource(width=32, height=16, fps=0)
    info = src.open()
    assert info == CaptureInfo("synthetic", "RAW ", 32, 16, 0)
    first, second = src.read(), src.read()
    assert first is not None and second is not None
    assert (decode_synthetic_id(first), decode_synthetic_id(second)) == (1, 2)


def test_no_duplicate_frames(cam_cfg: CameraConfig) -> None:
    with LatestFrameCamera(cam_cfg, "test", SyntheticSource(fps=200)) as cam:
        frames = _collect(cam, 40)
    ids = [f.frame_id for f in frames]
    assert len(ids) == 40
    assert all(b > a for a, b in itertools.pairwise(ids)), "frame ids must strictly increase"
    assert len({id(f.image) for f in frames}) == len(frames)
    stamps = [f.t_capture for f in frames]
    assert stamps == sorted(stamps)


def test_wait_new_returns_none_for_already_seen_frame(cam_cfg: CameraConfig) -> None:
    with LatestFrameCamera(cam_cfg, "test", SyntheticSource(fps=200)) as cam:
        frame = cam.wait_new(0, timeout=1.0)
        assert frame is not None
        cam.stop()
        assert cam.wait_new(frame.frame_id + 10_000, timeout=0.05) is None


def test_wait_new_timeout_without_frames(cam_cfg: CameraConfig) -> None:
    cam = LatestFrameCamera(cam_cfg, "test", SyntheticSource(fps=200))  # never started
    t0 = time.perf_counter()
    assert cam.wait_new(0, timeout=0.1) is None
    assert time.perf_counter() - t0 >= 0.09


def test_slow_consumer_counts_dropped(cam_cfg: CameraConfig) -> None:
    with LatestFrameCamera(cam_cfg, "test", SyntheticSource(fps=200)) as cam:
        first = cam.wait_new(0, timeout=1.0)
        assert first is not None
        time.sleep(0.2)  # ~40 frames produced, only the newest survives
        newer = cam.wait_new(first.frame_id, timeout=1.0)
        assert newer is not None
        assert newer.frame_id > first.frame_id + 1
        assert cam.stats().dropped >= newer.frame_id - first.frame_id - 1


def test_reconnects_after_failures(cam_cfg: CameraConfig) -> None:
    # open fails twice; then reads 5..9 fail (> max_read_failures=3) -> close + reopen
    src = SyntheticSource(fps=200, open_failures=2, fail_reads=range(5, 10))
    with LatestFrameCamera(cam_cfg, "test", src) as cam:
        frames = _collect(cam, 15)
        stats = cam.stats()
    assert len(frames) == 15
    assert src.open_calls >= 4  # 2 failures + first success + reopen after the lost camera
    assert stats.reconnects >= 1
    assert stats.read_failures >= 3


def test_stop_is_clean_and_wakes_waiters(cam_cfg: CameraConfig) -> None:
    src = SyntheticSource(fps=200)
    cam = LatestFrameCamera(cam_cfg, "test", src).start()
    first = cam.wait_new(0, timeout=1.0)
    assert first is not None

    result: list[Frame | None] = []
    waiter = threading.Thread(target=lambda: result.append(cam.wait_new(10**9, timeout=5.0)))
    waiter.start()
    t0 = time.perf_counter()
    cam.stop(timeout=1.0)
    waiter.join(timeout=1.0)
    assert not waiter.is_alive(), "wait_new must return when the camera stops"
    assert time.perf_counter() - t0 < 1.0
    assert result == [None]
    assert src.close_calls >= 1 and not src.is_open
    assert cam.stats().connected is False


def test_capture_fps_is_measured(cam_cfg: CameraConfig) -> None:
    with LatestFrameCamera(cam_cfg, "test", SyntheticSource(fps=50)) as cam:
        _collect(cam, 30)
        fps = cam.stats().capture_fps
    assert 30 < fps < 70
