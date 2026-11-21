from __future__ import annotations

import itertools
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

import cv2
import numpy as np
import numpy.typing as npt
import pytest

from perception import capture
from perception.capture import (
    CameraDevice,
    CameraOpenError,
    CameraSelection,
    CaptureInfo,
    Frame,
    LatestFrameCamera,
    OpenCVSource,
    SyntheticSource,
    _list_v4l2_devices,
    _win_ids,
    assignment_rows,
    decode_synthetic_id,
    effective_bits,
    is_mono,
    match_device,
    normalize_fourcc,
    parse_usb_selector,
    resolve_device,
    select_device,
    to_bgr8,
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


# --- formats: mono -> BGR ------------------------------------------------------------------------------


def test_to_bgr8_grey_and_single_channel() -> None:
    grey = np.arange(12, dtype=np.uint8).reshape(3, 4)
    for raw in (grey, grey[:, :, None]):
        out = to_bgr8(raw)
        assert out.shape == (3, 4, 3) and out.dtype == np.uint8
        assert (out[..., 0] == grey).all() and (out[..., 1] == grey).all() and (out[..., 2] == grey).all()


def test_to_bgr8_y16_scales_by_effective_depth() -> None:
    ten_bit = np.array([[0, 512, 1023]], dtype=np.uint16)  # 10 significant bits in a 16-bit container
    assert effective_bits(ten_bit) == 10
    assert to_bgr8(ten_bit)[0, :, 0].tolist() == [0, 128, 255]
    full = np.array([[0, 65535]], dtype=np.uint16)
    assert effective_bits(full) == 16
    assert to_bgr8(full)[0, :, 0].tolist() == [0, 255]
    # a depth kept across frames: a dark 10-bit frame is not stretched to full brightness
    dark = np.array([[0, 100]], dtype=np.uint16)
    assert to_bgr8(dark, bits=10)[0, :, 0].tolist() == [0, 25]
    assert effective_bits(np.zeros((2, 2), dtype=np.uint8)) == 8


def test_to_bgr8_colour_passthrough_without_copy() -> None:
    img = np.zeros((4, 5, 3), dtype=np.uint8)
    assert to_bgr8(img) is img
    bgra = np.full((2, 2, 4), 7, dtype=np.uint8)
    assert to_bgr8(bgra).shape == (2, 2, 3)


def test_is_mono() -> None:
    grey = to_bgr8(np.random.default_rng(0).integers(0, 255, (64, 64), dtype=np.uint8))
    assert is_mono(grey)
    colour = grey.copy()
    colour[..., 2] = 255 - colour[..., 2]
    assert not is_mono(colour)


def test_normalize_fourcc_aliases() -> None:
    assert normalize_fourcc("YUYV") == normalize_fourcc("YUY2") == "YUY2"
    assert normalize_fourcc("GREY") == normalize_fourcc("Y800") == normalize_fourcc("Y8  ") == "GREY"
    assert normalize_fourcc("Y16 ") == "Y16"
    assert normalize_fourcc("mjpg") == "MJPG"


# --- OpenCVSource with a fake cv2.VideoCapture ---------------------------------------------------------


class FakeCapture:
    instances: ClassVar[list[FakeCapture]] = []
    refuse_params: ClassVar[bool] = False
    frame: ClassVar[npt.NDArray[Any]] = np.zeros((6, 8, 3), dtype=np.uint8)
    fourcc: ClassVar[str] = "MJPG"
    fps: ClassVar[float] = 30.0

    def __init__(self, device: int | str, api: int, params: list[int] | None = None) -> None:
        self.device, self.api, self.params = device, api, params
        self.sets: list[tuple[int, float]] = []
        self.opened = not (params is not None and FakeCapture.refuse_params)
        FakeCapture.instances.append(self)

    def isOpened(self) -> bool:
        return self.opened

    def set(self, prop: int, value: float) -> bool:
        self.sets.append((prop, value))
        return True

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_FOURCC:
            return float(cv2.VideoWriter.fourcc(*FakeCapture.fourcc))
        if prop == cv2.CAP_PROP_FPS:
            return FakeCapture.fps
        return 0.0

    def read(self) -> tuple[bool, npt.NDArray[Any]]:
        return True, FakeCapture.frame.copy()

    def release(self) -> None:
        self.opened = False

    def getBackendName(self) -> str:
        return "FAKE"


@pytest.fixture
def fake_cv(monkeypatch: pytest.MonkeyPatch) -> type[FakeCapture]:
    FakeCapture.instances = []
    FakeCapture.refuse_params = False
    FakeCapture.frame = np.zeros((6, 8, 3), dtype=np.uint8)
    FakeCapture.fourcc = "MJPG"
    FakeCapture.fps = 30.0
    monkeypatch.setattr(cv2, "VideoCapture", FakeCapture)  # the module capture.py uses
    monkeypatch.setattr(capture, "_PLATFORM", "linux")  # no Windows control writes, no DirectShow enumeration
    return FakeCapture


def _fake_cfg(fourcc: str = "MJPG", device: int | str = 1) -> CameraConfig:
    base = load_config().cameras.driver
    return base.model_copy(update={"fourcc": fourcc, "width": 8, "height": 6, "fps": 30, "device": device})


def _warned_differs(caplog: pytest.LogCaptureFixture) -> bool:
    return any("differs from request" in r.getMessage() for r in caplog.records)


def test_open_passes_format_at_open_and_never_sets_fourcc_after(
    fake_cv: type[FakeCapture], caplog: pytest.LogCaptureFixture
) -> None:
    src = OpenCVSource(_fake_cfg(), "driver")
    info = src.open()
    (cap,) = fake_cv.instances
    assert cap.params is not None
    pairs = dict(zip(cap.params[::2], cap.params[1::2], strict=True))
    assert pairs[cv2.CAP_PROP_FOURCC] == cv2.VideoWriter.fourcc(*"MJPG")
    assert (pairs[cv2.CAP_PROP_FRAME_WIDTH], pairs[cv2.CAP_PROP_FRAME_HEIGHT], pairs[cv2.CAP_PROP_FPS]) == (8, 6, 30)
    assert cv2.CAP_PROP_FOURCC not in [prop for prop, _ in cap.sets], "a second FOURCC set resets DirectShow to YUY2"
    assert (info.fourcc, info.width, info.height, info.raw_format, info.mono, info.device) == (
        "MJPG", 8, 6, "uint8x3", True, "1"
    )  # fmt: skip
    assert not _warned_differs(caplog)
    src.close()


def test_open_falls_back_when_params_refused(fake_cv: type[FakeCapture]) -> None:
    fake_cv.refuse_params = True
    OpenCVSource(_fake_cfg(), "driver").open()
    assert len(fake_cv.instances) == 2
    second = fake_cv.instances[1]
    assert second.params is None
    assert [prop for prop, _ in second.sets][:4] == [
        cv2.CAP_PROP_FOURCC, cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT, cv2.CAP_PROP_FPS
    ]  # fmt: skip


def test_open_y16_is_reported_and_converted(fake_cv: type[FakeCapture]) -> None:
    fake_cv.frame = np.full((6, 8), 1023, dtype=np.uint16)
    fake_cv.fourcc = "Y16 "
    src = OpenCVSource(_fake_cfg("Y16 "), "driver")
    info = src.open()
    assert (info.raw_format, info.mono, info.fourcc) == ("uint16x1", True, "Y16 ")
    first, second = src.read(), src.read()
    for img in (first, second):
        assert img is not None and img.shape == (6, 8, 3) and img.dtype == np.uint8
        assert int(img.max()) == 255


def test_unknown_backend_fps_falls_back_to_requested(fake_cv: type[FakeCapture]) -> None:
    fake_cv.fps = -1.0  # DirectShow opened with open-time parameters
    assert OpenCVSource(_fake_cfg(), "driver").open().fps == 30.0


def test_fourcc_alias_does_not_warn(fake_cv: type[FakeCapture], caplog: pytest.LogCaptureFixture) -> None:
    fake_cv.fourcc = "YUY2"
    OpenCVSource(_fake_cfg("YUYV"), "driver").open()
    assert not _warned_differs(caplog)
    OpenCVSource(_fake_cfg("MJPG"), "driver").open()
    assert _warned_differs(caplog)


# --- devices -------------------------------------------------------------------------------------------

_DEVICES = [
    CameraDevice(0, "Integrated Camera", "p0", "5986", "2175"),
    CameraDevice(1, "Logi C615", "p1", "046d", "082c"),
    CameraDevice(2, "LifeCam", "p2", "045e", "076f"),
    CameraDevice(3, "Twin A", "p3", "1234", "5678", serial="AAA"),
    CameraDevice(4, "Twin B", "p4", "1234", "5678", serial="BBB"),
]


def test_parse_usb_selector() -> None:
    assert parse_usb_selector("usb:046D:082C") == ("046d", "082c", None)
    assert parse_usb_selector("usb:1234:5678:AbC1") == ("1234", "5678", "AbC1")
    for other in ("1", "/dev/video0", "usb:46d:82c", "http://x/video"):
        assert parse_usb_selector(other) is None


def test_match_device() -> None:
    assert match_device("usb:046d:082c", _DEVICES).index == 1
    assert match_device("usb:1234:5678:bbb", _DEVICES).index == 4
    with pytest.raises(CameraOpenError, match="no camera matches"):
        match_device("usb:ffff:0001", _DEVICES)
    with pytest.raises(CameraOpenError, match="add :<serial>"):
        match_device("usb:1234:5678", _DEVICES)
    with pytest.raises(CameraOpenError, match="not a usb selector"):
        match_device("2", _DEVICES)


def test_resolve_device(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_device(1) == 1
    assert resolve_device("2") == 2
    assert resolve_device("/dev/v4l/by-id/usb-cam-video-index0") == "/dev/v4l/by-id/usb-cam-video-index0"
    monkeypatch.setattr(capture, "list_devices", lambda: _DEVICES)
    monkeypatch.setattr(capture, "_PLATFORM", "win32")
    assert resolve_device("usb:045e:076f") == 2  # DirectShow index
    monkeypatch.setattr(capture, "_PLATFORM", "linux")
    assert resolve_device("usb:045e:076f") == "p2"  # /dev/videoN path on Linux


def test_win_ids_from_device_path() -> None:
    composite = r"\\?\usb#vid_046d&pid_082c&mi_02#7&d60e892&0&0002#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\global"
    assert _win_ids(composite) == ("046d", "082c", None)
    single = r"\\?\usb#vid_1234&pid_5678#SER123#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\global"
    assert _win_ids(single) == ("1234", "5678", "ser123")
    assert _win_ids("not a usb path") == (None, None, None)


def test_list_v4l2_devices_from_sysfs(tmp_path: Path) -> None:
    def node(name: str, index: str, label: str, vid: str, pid: str, serial: str | None) -> None:
        d = tmp_path / name
        (d / "device").mkdir(parents=True)
        (d / "index").write_text(index + "\n")
        (d / "name").write_text(label + "\n")
        (d / "device" / "idVendor").write_text(vid + "\n")
        (d / "device" / "idProduct").write_text(pid + "\n")
        if serial:
            (d / "device" / "serial").write_text(serial + "\n")

    node("video0", "0", "C615", "046D", "082c", "1D727050")
    node("video1", "1", "C615 metadata", "046d", "082c", "1D727050")  # second node of the same camera: skipped
    node("video10", "0", "LifeCam", "045e", "076f", None)
    node("video2", "0", "LifeCam B", "045e", "0770", None)
    devices = _list_v4l2_devices(tmp_path, tmp_path / "no-by-id")
    assert [(d.index, d.path, d.vid, d.pid, d.serial) for d in devices] == [
        (0, "/dev/video0", "046d", "082c", "1D727050"),
        (2, "/dev/video2", "045e", "0770", None),
        (10, "/dev/video10", "045e", "076f", None),
    ]


def test_port_selector_tells_identical_cameras_apart() -> None:
    from perception.capture import CameraDevice, _win_port

    a = "\\\\?\\usb#vid_046d&pid_082c&mi_02#7&d60e892&0&0002#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\\global"
    b = "\\\\?\\usb#vid_046d&pid_082c&mi_02#7&1f2e3d4&0&0002#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\\global"
    assert _win_port(a) == "7&d60e892"
    twins = [
        CameraDevice(1, "C615", a, "046d", "082c", None, port=_win_port(a)),
        CameraDevice(2, "C615", b, "046d", "082c", None, port=_win_port(b)),
    ]
    with pytest.raises(CameraOpenError, match="@<port>"):
        match_device("usb:046d:082c", twins)
    assert match_device("usb:046d:082c@d60e892", twins).index == 1
    assert match_device("usb:046d:082c@1F2E3D4", twins).index == 2
    with pytest.raises(CameraOpenError):
        match_device("usb:046d:082c@nothere", twins)


# --- camera selection: usb -> name -> development fallback ----------------------------------------------------------

_INTEGRATED = CameraDevice(0, "Integrated Camera", "p0", "5986", "2175")
_C615 = CameraDevice(1, "Logi C615 HD WebCam", "p1", "046d", "082c")
_LIFECAM = CameraDevice(2, "Microsoft LifeCam HD-6000 for Notebooks", "p2", "045e", "076f")


@pytest.fixture(autouse=False)
def win(monkeypatch: pytest.MonkeyPatch) -> None:
    import perception.capture as capture_mod

    monkeypatch.setattr(capture_mod, "_PLATFORM", "win32")  # DirectShow numbering: the selection gives indices


def _cams(**update: Any) -> Any:
    cams = load_config().cameras
    return cams.model_copy(update=update)


def test_select_by_usb_then_by_name(win: None) -> None:
    cams = _cams()
    sel = select_device("driver", cams, [_INTEGRATED, _C615, _LIFECAM])
    assert (sel.device, sel.via) == (1, "usb")
    renamed = CameraDevice(5, "Logi C615 HD WebCam", "p5", None, None)  # ids unreadable: found by its name
    sel = select_device("driver", cams, [_INTEGRATED, renamed])
    assert (sel.device, sel.via) == (5, "name")
    assert select_device("driver", cams, [_C615]).matched == _C615


def test_missing_camera_without_fallback_is_not_found(win: None) -> None:
    with pytest.raises(CameraOpenError, match="camera not found"):
        select_device("driver", _cams(dev_fallback=False), [_INTEGRATED, _LIFECAM])


def test_fallback_goes_to_the_driver_first_and_never_to_a_claimed_camera(win: None) -> None:
    cams = _cams(dev_fallback=True)
    sel = select_device("driver", cams, [_INTEGRATED, _LIFECAM])  # C615 missing
    assert (sel.device, sel.via) == (0, "fallback")  # the integrated camera, not the passenger's LifeCam
    assert select_device("passenger", cams, [_INTEGRATED, _LIFECAM]).via == "usb"
    # both USB cameras missing, one integrated camera: the driver gets it, the passenger is unavailable
    assert select_device("driver", cams, [_INTEGRATED]).via == "fallback"
    with pytest.raises(CameraOpenError):
        select_device("passenger", cams, [_INTEGRATED])
    # only the LifeCam missing: the passenger may take the integrated camera
    assert select_device("passenger", cams, [_INTEGRATED, _C615]).device == 0


def test_explicit_index_is_used_as_is(win: None) -> None:
    cams = _cams()
    cams = cams.model_copy(update={"driver": cams.driver.model_copy(update={"device": 0})})
    assert select_device("driver", cams, []) == CameraSelection(0, "index")


def test_assignment_rows_show_every_device(win: None) -> None:
    rows, assigned = assignment_rows(_cams(), [_INTEGRATED, _C615], ["driver", "passenger"])
    assert [r["assigned"] for r in rows] == ["-", "driver (usb)"]
    assert rows[1]["vid_pid"] == "046d:082c"
    assert assigned["passenger"].startswith("NOT FOUND")
