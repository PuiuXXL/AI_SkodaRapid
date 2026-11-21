"""Camera capture: one thread per camera that keeps only the latest frame.

* :class:`FrameSource` abstracts where frames come from: :class:`OpenCVSource` (real camera) or
  :class:`SyntheticSource` (tests, CI, ``--synthetic``).
* :class:`LatestFrameCamera` reads continuously, keeps only the newest :class:`Frame` (stamped with
  ``time.perf_counter()`` right after the read), counts frames that were replaced before anyone consumed them
  (``dropped``), measures ``capture_fps``, and reconnects by itself.
* :meth:`LatestFrameCamera.wait_new` never returns the same frame twice to a consumer that passes back the last
  ``frame_id`` it got.
* Formats: the requested FOURCC / size / fps are passed **at open time** (DirectShow under OpenCV 5 ignores a FOURCC
  set after opening and falls back to YUY2, 10 fps at 720p over USB 2). Mono formats (GREY / Y8 / Y16) are
  converted to 3-channel BGR uint8 (:func:`to_bgr8`), so every consumer keeps seeing the same image type.
* Devices: ``cameras.<name>.device`` is an OpenCV index, a path / URL, or a stable USB selector
  ``usb:<vid>:<pid>[:<serial>][@<port>]`` resolved at every open (:func:`resolve_device`; DirectShow enumeration on
  Windows, sysfs on Linux), so the camera keeps its role when indices shift after re-plugging; ``@<port>`` tells two
  cameras of the same model apart (``scripts/camera_probe.py`` prints the ports).
* Selection (:func:`select_device`, used by the camera workers at every open): the ``usb:`` selector, then
  ``cameras.<name>.device_name`` (unique friendly-name substring), then, only with ``cameras.dev_fallback``, a device no
  camera claims (preferring ``cameras.fallback_name``; the driver first). Deterministic, so the start-up table
  (:func:`assignment_rows`, printed by perception/main.py) shows what the workers will open.
"""

from __future__ import annotations

import math
import re
import sys
import threading
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

import cv2
import numpy as np
import numpy.typing as npt

from perception.config import CameraConfig, CameraControls, CamerasConfig
from perception.log import get_logger
from perception.perf import RateMeter

__all__ = [
    "CAMERA_NAMES",
    "CameraDevice",
    "CameraOpenError",
    "CameraSelection",
    "CaptureInfo",
    "CaptureStats",
    "DShowControl",
    "Frame",
    "FrameSource",
    "LatestFrameCamera",
    "OpenCVSource",
    "SyntheticSource",
    "assignment_rows",
    "decode_synthetic_id",
    "dshow_apply",
    "dshow_controls",
    "dshow_settings",
    "effective_bits",
    "is_mono",
    "list_devices",
    "match_device",
    "normalize_fourcc",
    "parse_usb_selector",
    "resolve_device",
    "select_device",
    "to_bgr8",
]

Image = npt.NDArray[np.uint8]

log = get_logger("perception.capture")


class CameraOpenError(RuntimeError):
    """The camera could not be opened or delivered no first frame."""


@dataclass(frozen=True)
class Frame:
    image: Image
    frame_id: int
    t_capture: float  # time.perf_counter() right after the frame was read


@dataclass(frozen=True)
class CaptureInfo:
    """What the camera actually delivers (may differ from what was requested)."""

    backend: str
    fourcc: str
    width: int
    height: int
    fps: float
    raw_format: str = "uint8x3"  # dtype x channels of the frame as the backend delivered it, before to_bgr8
    mono: bool = False  # grey image (mono format, or a camera that switched to night / IR mode)
    device: str = ""  # the device actually opened (index / path), after resolving a usb: selector
    via: str = ""  # how it was selected: usb / name / fallback / index / path ("" = resolve_device, no selection)
    device_name: str = ""  # friendly name of the selected device, when known


@dataclass(frozen=True)
class CaptureStats:
    name: str
    connected: bool
    info: CaptureInfo | None
    capture_fps: float
    frames: int
    dropped: int
    reconnects: int
    read_failures: int
    last_error: str | None = None  # last open failure (None once a frame source is open)


class FrameSource(Protocol):
    """Where frames come from. ``open`` raises on failure, ``read`` returns ``None`` on failure."""

    def open(self) -> CaptureInfo: ...

    def read(self) -> Image | None: ...

    def close(self) -> None: ...


# --- formats -------------------------------------------------------------------------------------------

# Same pixel format, different names per platform (V4L2 vs DirectShow / Media Foundation).
_FOURCC_ALIASES: dict[str, str] = {
    "YUYV": "YUY2",
    "YUY2": "YUY2",
    "GREY": "GREY",
    "GRAY": "GREY",
    "Y800": "GREY",
    "Y8": "GREY",
    "Y16": "Y16",
    "MJPG": "MJPG",
    "MJPEG": "MJPG",
}


def normalize_fourcc(code: str) -> str:
    """Canonical FOURCC name for comparisons (``YUYV`` == ``YUY2``, ``Y800`` == ``Y8`` == ``GREY``)."""
    key = code.strip().upper()
    return _FOURCC_ALIASES.get(key, key)


def effective_bits(raw: npt.NDArray[Any]) -> int:
    """Significant bits of a 16-bit mono frame (10 / 12 / 14 / 16; 8 for 8-bit data or an all-dark frame)."""
    if raw.dtype.itemsize < 2 or raw.size == 0:
        return 8
    peak = int(raw.max())
    for bits in (8, 10, 12, 14):
        if peak < (1 << bits):
            return bits
    return 16


def to_bgr8(raw: npt.NDArray[Any], bits: int | None = None) -> Image:
    """Any frame the backend delivers -> HxWx3 BGR uint8.

    * HxWx3 uint8 (the normal colour case) is returned as is (no copy).
    * Mono 8-bit (GREY / Y8: HxW or HxWx1) is replicated to 3 channels.
    * Mono 16-bit (Y16; often 10 or 12 significant bits in a 16-bit container) is shifted down to 8 bits. ``bits`` is
      the depth to scale from; pass a value kept across frames (see :func:`effective_bits`) so brightness does not
      jump from frame to frame. ``None`` = derive it from this frame.
    * HxWx4 (BGRA) loses its alpha channel.
    """
    arr = np.asarray(raw)
    if arr.ndim == 3 and arr.shape[2] == 1:
        arr = arr[:, :, 0]
    if arr.dtype.itemsize >= 2:
        depth = bits if bits is not None else effective_bits(arr)
        arr = (arr.astype(np.uint32) >> max(0, depth - 8)).clip(0, 255).astype(np.uint8)
    elif arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)
    if arr.ndim == 2:
        return np.asarray(cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    if arr.ndim == 3 and arr.shape[2] == 4:
        return np.asarray(cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR), dtype=np.uint8)
    return arr


def _raw_format(raw: npt.NDArray[Any]) -> str:
    channels = 1 if raw.ndim == 2 else int(raw.shape[2])
    return f"{raw.dtype.name}x{channels}"


def is_mono(image: Image, tolerance: float = 1.0) -> bool:
    """True if a BGR image is grey: channel differences below ``tolerance`` grey levels on a sparse sample.

    A colour camera never reaches this (sensor noise and white balance keep the channels apart); a camera in night /
    IR mode, or a mono format replicated to 3 channels, does.
    """
    sample = image[::8, ::8].astype(np.int16)
    if sample.ndim != 3 or sample.shape[2] < 3:
        return True
    diff_br = float(np.abs(sample[..., 0] - sample[..., 2]).mean())
    diff_bg = float(np.abs(sample[..., 0] - sample[..., 1]).mean())
    return max(diff_br, diff_bg) < tolerance


# --- devices -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CameraDevice:
    """One capture device as the platform backend numbers it.

    ``index`` is the OpenCV index for the default backend (the DirectShow order on Windows, ``N`` of ``/dev/videoN``
    on Linux). ``vid`` / ``pid`` are lower-case hex; ``serial`` is ``None`` when the device has none or the platform
    does not expose it (Windows composite webcams: the interface path carries an instance id, not the serial).
    """

    index: int
    name: str
    path: str
    vid: str | None = None
    pid: str | None = None
    serial: str | None = None
    stable_path: str | None = None  # Linux: /dev/v4l/by-id/... symlink pointing at this node
    # USB port identity, for two cameras of the same model without serial: Linux = the sysfs USB path ("1-2.3"),
    # Windows = the parent part of the interface instance id ("7&d60e892"), which Windows derives from the port.
    port: str | None = None


_USB_SELECTOR = re.compile(r"^usb:(?P<vid>[0-9a-fA-F]{4}):(?P<pid>[0-9a-fA-F]{4})(?::(?P<serial>\S+))?$")
_WIN_PATH_IDS = re.compile(r"vid_(?P<vid>[0-9a-f]{4})&pid_(?P<pid>[0-9a-f]{4})(?P<rest>[^#]*)#(?P<instance>[^#]+)")


def parse_usb_selector(device: str) -> tuple[str, str, str | None] | None:
    """``"usb:046d:082c"`` / ``"usb:046d:082c:1D727050"`` -> (vid, pid, serial); anything else -> ``None``."""
    m = _USB_SELECTOR.match(device.strip())
    if m is None:
        return None
    return m["vid"].lower(), m["pid"].lower(), m["serial"]


def split_port(selector: str) -> tuple[str, str | None]:
    """``"usb:046d:082c@d60e892"`` -> (``"usb:046d:082c"``, ``"d60e892"``); no ``@`` -> (selector, None)."""
    base, sep, port = selector.strip().partition("@")
    return base, (port.strip().lower() or None) if sep else None


def match_device(selector: str, devices: Sequence[CameraDevice]) -> CameraDevice:
    """The single device matching a ``usb:<vid>:<pid>[:<serial>][@<port>]`` selector.

    ``@<port>`` tells apart two cameras of the same model without a serial (``scripts/camera_probe.py`` prints each
    camera's port): it matches when the device's :attr:`CameraDevice.port` contains it (case-insensitive). It is tied
    to the physical USB port: moving a camera to another port needs the new value.

    Raises:
        CameraOpenError: malformed selector, no match, or several matches (add the serial or the port).
    """
    base, port = split_port(selector)
    parsed = parse_usb_selector(base)
    if parsed is None:
        raise CameraOpenError(f"not a usb selector: {selector!r} (expected usb:<vid>:<pid>[:<serial>][@<port>])")
    vid, pid, serial = parsed
    hits = [d for d in devices if d.vid == vid and d.pid == pid]
    if serial is not None:
        hits = [d for d in hits if d.serial is not None and d.serial.lower() == serial.lower()]
    if port is not None:
        hits = [d for d in hits if d.port is not None and port in d.port.lower()]
    if not hits:
        seen = ", ".join(f"{d.index}:{d.name} ({d.vid}:{d.pid} port={d.port})" for d in devices) or "none"
        raise CameraOpenError(f"no camera matches {selector!r}; devices: {seen}")
    if len(hits) > 1:
        names = ", ".join(f"{d.index}:{d.name} serial={d.serial} port={d.port}" for d in hits)
        raise CameraOpenError(
            f"{selector!r} matches {len(hits)} cameras ({names}); add :<serial> or @<port> to the selector"
        )
    return hits[0]


def _win_ids(path: str) -> tuple[str | None, str | None, str | None]:
    m = _WIN_PATH_IDS.search(path.lower())
    if m is None:
        return None, None, None
    # A non-composite device's instance id is its serial; a composite interface (&mi_xx) has a generated id with '&'.
    serial = None if "&mi_" in m["rest"] or "&" in m["instance"] else m["instance"]
    return m["vid"], m["pid"], serial


def _win_port(path: str) -> str | None:
    """Port identity from a DirectShow device path: the parent part of a generated instance id ("7&d60e892" of
    "7&d60e892&0&0002"); Windows derives it from the parent device, i.e. from the USB port. None with a serial."""
    m = _WIN_PATH_IDS.search(path.lower())
    if m is None or "&" not in m["instance"]:
        return None
    parts = m["instance"].split("&")
    return "&".join(parts[:2]) if len(parts) >= 2 else m["instance"]


@dataclass(frozen=True)
class DShowControl:
    """One DirectShow camera control (IAMVideoProcAmp / IAMCameraControl), as the driver reports it."""

    name: str
    minimum: int
    maximum: int
    step: int
    default: int
    value: int | None
    auto: bool | None  # current mode; None = unreadable
    can_auto: bool
    can_manual: bool


# name -> (interface, property id). VideoProcAmp ids are the KSPROPERTY_VIDEOPROCAMP ids, which the DirectShow
# kernel-streaming proxy passes through unchanged; that is how power-line frequency (13) is reachable on Windows.
_DSHOW_PROPS: dict[str, tuple[str, int]] = {
    "brightness": ("procamp", 0),
    "contrast": ("procamp", 1),
    "saturation": ("procamp", 3),
    "sharpness": ("procamp", 4),
    "gamma": ("procamp", 5),
    "white_balance": ("procamp", 7),
    "backlight_compensation": ("procamp", 8),
    "gain": ("procamp", 9),
    "power_line_frequency": ("procamp", 13),  # 0 = off, 1 = 50 Hz, 2 = 60 Hz
    "zoom": ("camctl", 3),
    "exposure": ("camctl", 4),  # log2(seconds): -6 = 1/64 s
    "focus": ("camctl", 6),
    "low_light_compensation": ("camctl", 19),
}
_DSHOW_FLAG_AUTO = 1
_DSHOW_FLAG_MANUAL = 2
_POWER_LINE_MENU = {0: 0, 50: 1, 60: 2}  # same menu values as V4L2 power_line_frequency


def dshow_settings(controls: CameraControls) -> list[tuple[str, int | None, bool]]:
    """``cameras.<name>.controls`` -> DirectShow writes ``(control, value, auto)``; ``value None`` = keep the current.

    Auto modes come first (a driver ignores manual values while the matching auto mode is on). ``null`` controls are
    left out, i.e. untouched, exactly like ``camera_setup.sh`` on Linux.
    """
    out: list[tuple[str, int | None, bool]] = []
    if controls.power_line_hz is not None:
        out.append(("power_line_frequency", _POWER_LINE_MENU[controls.power_line_hz], False))
    if controls.autofocus is True:
        out.append(("focus", None, True))
    elif controls.autofocus is False or controls.focus is not None:
        out.append(("focus", controls.focus, False))
    if controls.auto_exposure is True:
        out.append(("exposure", None, True))
    elif controls.auto_exposure is False or controls.exposure_ms is not None:
        exp = None if controls.exposure_ms is None else round(math.log2(controls.exposure_ms / 1000.0))
        out.append(("exposure", exp, False))
    if controls.auto_white_balance is True:
        out.append(("white_balance", None, True))
    elif controls.auto_white_balance is False or controls.white_balance_k is not None:
        out.append(("white_balance", controls.white_balance_k, False))
    if controls.gain is not None:
        out.append(("gain", controls.gain, False))
    return out


class _DShow:  # pragma: no cover - needs Windows + DirectShow
    """Minimal raw-COM access to DirectShow video input devices through ctypes (no comtypes dependency).

    Devices come in the system device enumerator's order, which is the order OpenCV's CAP_DSHOW uses for indices.
    """

    def __init__(self) -> None:
        import ctypes
        from ctypes import c_ubyte, c_ulong, c_ushort, c_void_p

        self.ct = ctypes

        class GUID(ctypes.Structure):
            _fields_ = (("d1", c_ulong), ("d2", c_ushort), ("d3", c_ushort), ("d4", c_ubyte * 8))

        class VARIANT(ctypes.Structure):
            _fields_ = (("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort), ("v1", c_void_p),
                        ("v2", c_void_p))  # fmt: skip

        self.GUID, self.VARIANT = GUID, VARIANT
        self.ole32 = ctypes.OleDLL("ole32")
        self.oleaut32 = ctypes.WinDLL("oleaut32")
        self.iid = {
            "dev_enum": self.guid("{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}"),
            "create_dev_enum": self.guid("{29840822-5B84-11D0-BD3B-00A0C911CE86}"),
            "video_inputs": self.guid("{860BB310-5D01-11d0-BD3B-00A0C911CE86}"),
            "property_bag": self.guid("{55272A00-42CB-11CE-8135-00AA004BB851}"),
            "base_filter": self.guid("{56A86895-0AD4-11CE-B03A-0020AF0BA770}"),
            "procamp": self.guid("{C6E13360-30AC-11d0-A18C-00A0C9118956}"),
            "camctl": self.guid("{C6E13370-30AC-11d0-A18C-00A0C9118956}"),
        }
        self.initialized = False
        try:
            self.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
            self.initialized = True
        except OSError:
            pass  # already initialised in another mode on this thread: COM is usable as is

    def close(self) -> None:
        if self.initialized:
            self.ole32.CoUninitialize()
            self.initialized = False

    def guid(self, text: str) -> Any:
        g = self.GUID()
        self.ole32.CLSIDFromString(self.ct.c_wchar_p(text), self.ct.byref(g))
        return g

    def method(self, obj: Any, index: int, *argtypes: Any) -> Any:
        ct = self.ct
        vtbl = ct.cast(obj, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
        fn = ct.WINFUNCTYPE(ct.HRESULT, ct.c_void_p, *argtypes)(vtbl[index])
        return lambda *args: fn(obj, *args)

    def release(self, obj: Any) -> None:
        ct = self.ct
        if obj:
            vtbl = ct.cast(obj, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
            ct.WINFUNCTYPE(ct.c_ulong, ct.c_void_p)(vtbl[2])(obj)

    def monikers(self) -> list[Any]:
        """Device monikers in enumeration order (the caller releases them), skipping those without a property bag."""
        ct = self.ct
        dev_enum, enum_monikers = ct.c_void_p(), ct.c_void_p()
        out: list[Any] = []
        try:
            self.ole32.CoCreateInstance(
                ct.byref(self.iid["dev_enum"]), None, 1, ct.byref(self.iid["create_dev_enum"]), ct.byref(dev_enum)
            )
            self.method(dev_enum, 3, ct.POINTER(self.GUID), ct.POINTER(ct.c_void_p), ct.c_ulong)(
                ct.byref(self.iid["video_inputs"]), ct.byref(enum_monikers), 0
            )
            if not enum_monikers:  # S_FALSE: no video input device at all
                return out
            next_moniker = self.method(enum_monikers, 3, ct.c_ulong, ct.POINTER(ct.c_void_p), ct.POINTER(ct.c_ulong))
            while True:
                moniker, fetched = ct.c_void_p(), ct.c_ulong(0)
                next_moniker(1, ct.byref(moniker), ct.byref(fetched))
                if fetched.value == 0:
                    break
                if self.properties(moniker) is None:
                    self.release(moniker)  # OpenCV does not count these either
                    continue
                out.append(moniker)
        finally:
            self.release(enum_monikers)
            self.release(dev_enum)
        return out

    def properties(self, moniker: Any) -> dict[str, str] | None:
        ct = self.ct
        bag = ct.c_void_p()
        try:
            self.method(moniker, 9, ct.c_void_p, ct.c_void_p, ct.POINTER(self.GUID), ct.POINTER(ct.c_void_p))(
                None, None, ct.byref(self.iid["property_bag"]), ct.byref(bag)
            )  # IMoniker::BindToStorage
        except OSError:
            return None
        props: dict[str, str] = {}
        read = self.method(bag, 3, ct.c_wchar_p, ct.POINTER(self.VARIANT), ct.c_void_p)
        for key in ("FriendlyName", "DevicePath"):
            var = self.VARIANT()
            try:
                read(key, ct.byref(var), None)
                if var.vt == 8 and var.v1:  # VT_BSTR
                    props[key] = ct.wstring_at(var.v1)
            except OSError:
                pass
            finally:
                self.oleaut32.VariantClear(ct.byref(var))
        self.release(bag)
        return props

    def interfaces(self, moniker: Any) -> tuple[Any, dict[str, Any]]:
        """(IBaseFilter, {"procamp": IAMVideoProcAmp, "camctl": IAMCameraControl}) for one device; release all."""
        ct = self.ct
        flt = ct.c_void_p()
        self.method(moniker, 8, ct.c_void_p, ct.c_void_p, ct.POINTER(self.GUID), ct.POINTER(ct.c_void_p))(
            None, None, ct.byref(self.iid["base_filter"]), ct.byref(flt)
        )  # IMoniker::BindToObject
        found: dict[str, Any] = {}
        for key in ("procamp", "camctl"):
            itf = ct.c_void_p()
            try:
                self.method(flt, 0, ct.POINTER(self.GUID), ct.POINTER(ct.c_void_p))(
                    ct.byref(self.iid[key]), ct.byref(itf)
                )  # IUnknown::QueryInterface
                found[key] = itf
            except OSError:
                continue
        return flt, found

    def read_control(self, itf: Any, prop: int, name: str) -> DShowControl | None:
        ct = self.ct
        lp = ct.POINTER(ct.c_long)
        lo, hi, step, default, caps, value, flags = (ct.c_long() for _ in range(7))
        try:
            self.method(itf, 3, ct.c_long, lp, lp, lp, lp, lp)(
                prop, ct.byref(lo), ct.byref(hi), ct.byref(step), ct.byref(default), ct.byref(caps)
            )
        except OSError:
            return None  # not supported by this camera
        current: int | None = None
        auto: bool | None = None
        try:
            self.method(itf, 5, ct.c_long, lp, lp)(prop, ct.byref(value), ct.byref(flags))
            current, auto = value.value, bool(flags.value & _DSHOW_FLAG_AUTO)
        except OSError:
            pass
        return DShowControl(
            name, lo.value, hi.value, step.value, default.value, current, auto,
            can_auto=bool(caps.value & _DSHOW_FLAG_AUTO), can_manual=bool(caps.value & _DSHOW_FLAG_MANUAL),
        )  # fmt: skip

    def write_control(self, itf: Any, prop: int, value: int, auto: bool) -> None:
        ct = self.ct
        flag = _DSHOW_FLAG_AUTO if auto else _DSHOW_FLAG_MANUAL
        self.method(itf, 4, ct.c_long, ct.c_long, ct.c_long)(prop, value, flag)


def _with_dshow_device(index: int, action: Callable[[_DShow, dict[str, Any]], Any]) -> Any:  # pragma: no cover
    """Run ``action(com, interfaces)`` on DirectShow device ``index``; COM objects are released afterwards."""
    com = _DShow()
    monikers: list[Any] = []
    try:
        monikers = com.monikers()
        if not 0 <= index < len(monikers):
            raise CameraOpenError(f"no DirectShow device with index {index} ({len(monikers)} found)")
        flt, itfs = com.interfaces(monikers[index])
        try:
            return action(com, itfs)
        finally:
            for itf in itfs.values():
                com.release(itf)
            com.release(flt)
    finally:
        for moniker in monikers:
            com.release(moniker)
        com.close()


def _list_dshow_devices() -> list[CameraDevice]:  # pragma: no cover - needs Windows + DirectShow
    """Video input devices in DirectShow order (= OpenCV's CAP_DSHOW indices)."""
    com = _DShow()
    devices: list[CameraDevice] = []
    try:
        for index, moniker in enumerate(com.monikers()):
            props = com.properties(moniker) or {}
            com.release(moniker)
            path = props.get("DevicePath", "")
            vid, pid, serial = _win_ids(path)
            devices.append(
                CameraDevice(index, props.get("FriendlyName", "?"), path, vid, pid, serial, port=_win_port(path))
            )
    finally:
        com.close()
    return devices


def dshow_controls(index: int) -> list[DShowControl]:  # pragma: no cover - needs Windows + DirectShow
    """Read-only: every supported control of DirectShow device ``index`` with range, default, value and mode."""

    def read_all(com: _DShow, itfs: dict[str, Any]) -> list[DShowControl]:
        out: list[DShowControl] = []
        for name, (group, prop) in _DSHOW_PROPS.items():
            if group in itfs and (ctrl := com.read_control(itfs[group], prop, name)) is not None:
                out.append(ctrl)
        return out

    result: list[DShowControl] = _with_dshow_device(index, read_all)
    return result


def dshow_apply(
    index: int, settings: Sequence[tuple[str, int | None, bool]]
) -> tuple[dict[str, str], list[str]]:  # pragma: no cover - needs Windows + DirectShow
    """Write :func:`dshow_settings` to DirectShow device ``index``. Returns (applied, skipped with reasons).

    The Windows camera driver keeps these values after the process exits (docs/perception.md §2.1).
    """

    def write_all(com: _DShow, itfs: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
        applied: dict[str, str] = {}
        skipped: list[str] = []
        for name, value, auto in settings:
            group, prop = _DSHOW_PROPS[name]
            ctrl = com.read_control(itfs[group], prop, name) if group in itfs else None
            if ctrl is None:
                skipped.append(f"{name}: not supported by this camera")
                continue
            if auto and not ctrl.can_auto:
                skipped.append(f"{name}: no auto mode")
                continue
            target = value if value is not None else (ctrl.value if ctrl.value is not None else ctrl.default)
            if not ctrl.minimum <= target <= ctrl.maximum:
                skipped.append(f"{name}={target}: outside [{ctrl.minimum}..{ctrl.maximum}]")
                continue
            try:
                com.write_control(itfs[group], prop, target, auto)
            except OSError as exc:
                skipped.append(f"{name}={target}: rejected ({exc})")
                continue
            after = com.read_control(itfs[group], prop, name)
            mode = "?" if after is None or after.auto is None else ("auto" if after.auto else "manual")
            applied[name] = f"{after.value if after else target} ({mode})"
        return applied, skipped

    result: tuple[dict[str, str], list[str]] = _with_dshow_device(index, write_all)
    return result


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _list_v4l2_devices(
    sys_root: Path = Path("/sys/class/video4linux"), by_id_root: Path = Path("/dev/v4l/by-id")
) -> list[CameraDevice]:
    """Capture nodes (``index`` file == 0, the first node of each camera) from sysfs, with USB ids and by-id links."""
    by_id: dict[str, str] = {}
    if by_id_root.is_dir():
        for link in sorted(by_id_root.iterdir()):
            target = link.resolve().name if link.is_symlink() else None
            if target and link.name.endswith("-index0"):
                by_id[target] = str(link)
    devices: list[CameraDevice] = []
    nodes = sorted(sys_root.glob("video*"), key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else 1 << 30)
    for node in nodes:
        if not node.name[5:].isdigit() or _read_text(node / "index") not in (None, "0"):
            continue
        usb: Path | None = None
        for candidate in ((node / "device").resolve(), *(node / "device").resolve().parents):
            if (candidate / "idVendor").exists():
                usb = candidate
                break
        vid = _read_text(usb / "idVendor") if usb else None
        pid = _read_text(usb / "idProduct") if usb else None
        serial = _read_text(usb / "serial") if usb else None
        devices.append(
            CameraDevice(
                index=int(node.name[5:]),
                name=_read_text(node / "name") or node.name,
                path=f"/dev/{node.name}",
                vid=vid.lower() if vid else None,
                pid=pid.lower() if pid else None,
                serial=serial,
                stable_path=by_id.get(node.name),
                port=usb.name if usb else None,
            )
        )
    return devices


def list_devices() -> list[CameraDevice]:
    """Capture devices of this machine in the default backend's order (empty where enumeration is unsupported)."""
    if _PLATFORM == "win32":
        try:
            return _list_dshow_devices()
        except OSError as exc:  # pragma: no cover - COM failure
            log.warning("DirectShow device enumeration failed", extra={"fields": {"error": str(exc)}})
            return []
    if _PLATFORM.startswith("linux"):
        return _list_v4l2_devices()
    return []


def resolve_device(device: int | str, backend: str = "auto") -> int | str:
    """Config ``device`` -> what ``cv2.VideoCapture`` takes: an index, a path / URL, or a resolved usb selector.

    A ``usb:`` selector becomes the DirectShow index on Windows and ``/dev/videoN`` on Linux.

    Raises:
        CameraOpenError: the selector matches no camera, or several.
    """
    if isinstance(device, int):
        return device
    if device.isdigit():
        return int(device)
    if parse_usb_selector(split_port(device)[0]) is None:
        return device
    if _PLATFORM == "win32" and backend not in ("auto", "dshow"):
        log.warning(
            "usb selector resolves to a DirectShow index; other backends may number cameras differently",
            extra={"fields": {"device": device, "backend": backend}},
        )
    found = match_device(device, list_devices())
    return found.path if _PLATFORM.startswith("linux") else found.index


# --- camera selection ----------------------------------------------------------------------------------

CAMERA_NAMES: tuple[str, ...] = ("driver", "passenger")  # fallback priority: the driver camera first


@dataclass(frozen=True)
class CameraSelection:
    """What a camera opens: ``device`` for ``cv2.VideoCapture`` and how it was found."""

    device: int | str
    via: str  # usb / name / fallback / index / path
    matched: CameraDevice | None = None


def _open_target(dev: CameraDevice) -> int | str:
    return dev.path if _PLATFORM.startswith("linux") else dev.index


def _explicit(device: int | str) -> CameraSelection | None:
    """An OpenCV index or a path / URL: used as is (``--device``)."""
    if isinstance(device, int) or device.isdigit():
        return CameraSelection(int(device), "index")
    if parse_usb_selector(split_port(device)[0]) is None:
        return CameraSelection(device, "path")
    return None


def _by_name(cfg: CameraConfig, devices: Sequence[CameraDevice]) -> list[CameraDevice]:
    if not cfg.device_name:
        return []
    key = cfg.device_name.lower()
    return [d for d in devices if key in d.name.lower()]


def _claimed(cfg: CameraConfig, devices: Sequence[CameraDevice]) -> CameraDevice | None:
    """The device a camera finds without the fallback (usb selector, then a unique name match), or None."""
    if isinstance(cfg.device, str) and _explicit(cfg.device) is None:
        try:
            return match_device(cfg.device, devices)
        except CameraOpenError:
            pass
    hits = _by_name(cfg, devices)
    return hits[0] if len(hits) == 1 else None


def _fallback(name: str, cameras: CamerasConfig, devices: Sequence[CameraDevice]) -> CameraDevice | None:
    """Development fallback: the cameras that need one (driver first) take the free devices in order, the ones whose
    name contains ``fallback_name`` first. A free device = not claimed by any enabled camera (selector, name or an
    explicit index)."""
    taken: set[int] = set()
    needing: list[str] = []
    for cam in CAMERA_NAMES:
        cfg: CameraConfig = getattr(cameras, cam)
        if not cfg.enabled:
            continue
        explicit = _explicit(cfg.device)
        if explicit is not None:
            if isinstance(explicit.device, int):
                taken.add(explicit.device)
            continue
        hit = _claimed(cfg, devices)
        if hit is not None:
            taken.add(hit.index)
        else:
            needing.append(cam)
    free = [d for d in devices if d.index not in taken]
    if cameras.fallback_name:
        key = cameras.fallback_name.lower()
        preferred = [d for d in free if key in d.name.lower()]
        free = preferred + [d for d in free if d not in preferred]
    if name not in needing:
        return None
    pos = needing.index(name)
    return free[pos] if pos < len(free) else None


def select_device(name: str, cameras: CamerasConfig, devices: Sequence[CameraDevice]) -> CameraSelection:
    """The device camera ``name`` opens: explicit index / path, ``usb:`` selector, ``device_name``, then (only with
    ``cameras.dev_fallback``) the development fallback.

    Raises:
        CameraOpenError: the camera is not there (the worker reports ``camera_unavailable`` and retries).
    """
    cfg: CameraConfig = getattr(cameras, name)
    explicit = _explicit(cfg.device)
    if explicit is not None:
        return explicit
    reasons: list[str] = []
    try:
        hit = match_device(str(cfg.device), devices)
        return CameraSelection(_open_target(hit), "usb", hit)
    except CameraOpenError as exc:
        reasons.append(str(exc))
    if cfg.device_name:
        hits = _by_name(cfg, devices)
        if len(hits) == 1:
            return CameraSelection(_open_target(hits[0]), "name", hits[0])
        reasons.append(f"device_name {cfg.device_name!r} matches {len(hits)} devices")
    if cameras.dev_fallback:
        fb = _fallback(name, cameras, devices)
        if fb is not None:
            log.warning(
                "camera not found: using the development fallback device",
                extra={"fields": {"camera": name, "device": fb.index, "name": fb.name}},
            )
            return CameraSelection(_open_target(fb), "fallback", fb)
        reasons.append("no free device for the fallback")
    raise CameraOpenError(f"{name}: camera not found ({'; '.join(reasons)})")


def assignment_rows(
    cameras: CamerasConfig, devices: Sequence[CameraDevice], names: Sequence[str]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Start-up table: one row per device (index, name, vid:pid, assigned camera + how) and, per camera in ``names``,
    what it opens or why it does not ("not found: ...")."""
    assigned: dict[str, str] = {}
    by_index: dict[int, str] = {}
    for cam in names:
        try:
            sel = select_device(cam, cameras, devices)
        except CameraOpenError as exc:
            assigned[cam] = f"NOT FOUND -> camera_unavailable ({exc})"
            continue
        target = sel.matched.index if sel.matched is not None else sel.device
        assigned[cam] = f"{sel.via}: {sel.device}" + (f" ({sel.matched.name})" if sel.matched is not None else "")
        if isinstance(target, int):
            by_index[target] = f"{cam} ({sel.via})"
    rows = [
        {
            "index": d.index,
            "name": d.name,
            "vid_pid": f"{d.vid}:{d.pid}" if d.vid and d.pid else "?",
            "assigned": by_index.get(d.index, "-"),
        }
        for d in devices
    ]
    return rows, assigned


# --- OpenCV source -------------------------------------------------------------------------------------

_BACKENDS: dict[str, int] = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
    "any": cv2.CAP_ANY,
}


# Typed as plain str so mypy does not prune the other platform's branch as unreachable.
_PLATFORM: str = sys.platform


def _backend_flag(name: str) -> int:
    if name == "auto":
        if _PLATFORM.startswith("linux"):
            return int(cv2.CAP_V4L2)
        if _PLATFORM == "win32":
            return int(cv2.CAP_DSHOW)  # DSHOW honours MJPG + 720p reliably; MSMF often ignores FOURCC
        return int(cv2.CAP_ANY)
    return int(_BACKENDS[name])


def _fourcc_to_str(value: float) -> str:
    code = int(value)
    chars = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))
    return chars if chars.isprintable() and code else "?"


def _apply_controls_opencv(cap: cv2.VideoCapture, controls: CameraControls, name: str) -> None:
    """Best-effort fixed controls through OpenCV properties (used on Windows, where v4l2-ctl does not exist).

    DirectShow conventions: CAP_PROP_AUTO_EXPOSURE 0.25 = manual / 0.75 = auto; CAP_PROP_EXPOSURE = log2(seconds).
    Power-line frequency is not exposed by OpenCV on Windows.
    """
    wanted: list[tuple[str, int, float]] = []
    if controls.autofocus is not None:
        wanted.append(("autofocus", cv2.CAP_PROP_AUTOFOCUS, 1.0 if controls.autofocus else 0.0))
    if controls.focus is not None:
        wanted.append(("focus", cv2.CAP_PROP_FOCUS, float(controls.focus)))
    if controls.auto_exposure is not None:
        wanted.append(("auto_exposure", cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if controls.auto_exposure else 0.25))
    if controls.exposure_ms is not None:
        wanted.append(("exposure", cv2.CAP_PROP_EXPOSURE, float(round(math.log2(controls.exposure_ms / 1000.0)))))
    if controls.gain is not None:
        wanted.append(("gain", cv2.CAP_PROP_GAIN, float(controls.gain)))
    if controls.auto_white_balance is not None:
        wanted.append(("auto_white_balance", cv2.CAP_PROP_AUTO_WB, 1.0 if controls.auto_white_balance else 0.0))
    if controls.white_balance_k is not None:
        wanted.append(("white_balance_k", cv2.CAP_PROP_WB_TEMPERATURE, float(controls.white_balance_k)))

    applied: dict[str, float] = {}
    skipped: list[str] = []
    for label, prop, value in wanted:
        if cap.set(prop, value):
            applied[label] = float(cap.get(prop))
        else:
            skipped.append(label)
    if controls.power_line_hz is not None:
        skipped.append("power_line_hz (not available through OpenCV on Windows)")
    log.info("camera controls", extra={"fields": {"camera": name, "applied": applied, "skipped": skipped}})


class OpenCVSource:
    """Real camera through ``cv2.VideoCapture``.

    The requested FOURCC / size / fps are passed as open-time parameters (the only way DirectShow under OpenCV 5
    honours MJPG); if the backend refuses them, the camera is reopened and they are set one by one as before.
    Frames are normalised by :func:`to_bgr8`, so mono formats (GREY / Y8 / Y16) arrive as 3-channel BGR uint8.
    """

    def __init__(
        self, cfg: CameraConfig, name: str = "camera", resolver: Callable[[], CameraSelection] | None = None
    ) -> None:
        """``resolver``: picks the device at every open (the workers use :func:`select_device`); None = the config
        ``device`` through :func:`resolve_device`."""
        self._cfg = cfg
        self._name = name
        self._resolver = resolver
        self._cap: cv2.VideoCapture | None = None
        self._first: Image | None = None
        self._bits: int = 8  # significant bits of a 16-bit mono stream, kept across frames (stable brightness)

    def _open_capture(self, device: int | str) -> cv2.VideoCapture:
        cfg = self._cfg
        api = _backend_flag(cfg.backend)
        fourcc = int(cv2.VideoWriter.fourcc(*cfg.fourcc))
        params = [
            cv2.CAP_PROP_FOURCC, fourcc,
            cv2.CAP_PROP_FRAME_WIDTH, cfg.width,
            cv2.CAP_PROP_FRAME_HEIGHT, cfg.height,
            cv2.CAP_PROP_FPS, cfg.fps,
        ]  # fmt: skip
        cap = cv2.VideoCapture(device, api, params)
        if cap.isOpened():
            return cap
        cap.release()
        # Fallback: backends / sources that reject open-time parameters (some URLs, virtual cameras).
        cap = cv2.VideoCapture(device, api)
        if not cap.isOpened():
            cap.release()
            raise CameraOpenError(f"{self._name}: cannot open device {cfg.device!r} (backend {cfg.backend})")
        log.info(
            "open-time format parameters refused, setting them after open", extra={"fields": {"camera": self._name}}
        )
        # Order matters: FOURCC first, otherwise some drivers fall back to YUYV and cap the frame rate.
        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        cap.set(cv2.CAP_PROP_FPS, cfg.fps)
        return cap

    def open(self) -> CaptureInfo:
        cfg = self._cfg
        if self._resolver is not None:
            sel = self._resolver()
            device, via = sel.device, sel.via
            label = sel.matched.name if sel.matched is not None else ""
        else:
            device, via, label = resolve_device(cfg.device, cfg.backend), "", ""
        cap = self._open_capture(device)
        # Never set FOURCC / size again here: on DirectShow a second FOURCC set resets the stream to YUY2.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, cfg.buffer_size)
        if _PLATFORM == "win32":
            _apply_controls_opencv(cap, cfg.controls, self._name)

        ok, raw = cap.read()
        if not ok or raw is None:
            cap.release()
            raise CameraOpenError(f"{self._name}: device {cfg.device!r} opened but delivered no frame")
        raw_arr = np.asarray(raw)
        self._bits = effective_bits(raw_arr)
        img = to_bgr8(raw_arr, self._bits)
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if fps <= 0:
            # DirectShow opened with open-time parameters reports -1. Model cadences are derived from this value
            # (every_n_frames), so fall back to the requested rate; the measured rate is CaptureStats.capture_fps.
            log.info("backend reports no frame rate, assuming the requested one", extra={"fields": {"fps": cfg.fps}})
            fps = float(cfg.fps)
        info = CaptureInfo(
            backend=str(cap.getBackendName()),
            fourcc=_fourcc_to_str(cap.get(cv2.CAP_PROP_FOURCC)),
            width=int(img.shape[1]),
            height=int(img.shape[0]),
            fps=fps,
            raw_format=_raw_format(raw_arr),
            mono=is_mono(img),
            device=str(device),
            via=via,
            device_name=label,
        )
        requested = (cfg.fourcc, cfg.width, cfg.height, float(cfg.fps))
        obtained = (info.fourcc, info.width, info.height, round(info.fps, 2))
        same = (
            normalize_fourcc(cfg.fourcc) == normalize_fourcc(info.fourcc)
            and (cfg.width, cfg.height) == (info.width, info.height)
            and abs(info.fps - cfg.fps) < 0.5
        )
        if not same:
            log.warning(
                "camera format differs from request",
                extra={"fields": {"camera": self._name, "requested": requested, "obtained": obtained}},
            )
        self._cap = cap
        self._first = img
        return info

    def read(self) -> Image | None:
        if self._first is not None:
            first, self._first = self._first, None
            return first
        if self._cap is None:
            return None
        ok, raw = self._cap.read()
        if not ok or raw is None:
            return None
        raw_arr = np.asarray(raw)
        if raw_arr.dtype.itemsize >= 2:
            self._bits = max(self._bits, effective_bits(raw_arr))
        return to_bgr8(raw_arr, self._bits)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._first = None


# --- synthetic source ----------------------------------------------------------------------------------


def decode_synthetic_id(image: Image) -> int:
    """Read back the sequence number :class:`SyntheticSource` writes into the first pixels."""
    return int.from_bytes(bytes(image[0, :8, 0].tolist()), "little")


class SyntheticSource:
    """Generated frames for tests and camera-less runs.

    Each frame carries its sequence number in the first 8 pixels (see :func:`decode_synthetic_id`) and a moving
    bar so a preview visibly updates. Failures are scriptable: the first ``open_failures`` calls to ``open`` raise,
    and the read calls whose 0-based index is in ``fail_reads`` return ``None``.
    """

    def __init__(
        self,
        width: int = 320,
        height: int = 240,
        fps: float = 30.0,
        *,
        open_failures: int = 0,
        fail_reads: Collection[int] = (),
    ) -> None:
        self._width = width
        self._height = height
        self._period = 1.0 / fps if fps > 0 else 0.0
        self._fps = fps
        self._open_failures = open_failures
        self._fail_reads = frozenset(fail_reads)
        self._read_calls = 0
        self._seq = 0
        self._next_t = 0.0
        self.open_calls = 0
        self.close_calls = 0
        self.is_open = False

    def open(self) -> CaptureInfo:
        self.open_calls += 1
        if self.open_calls <= self._open_failures:
            raise CameraOpenError(f"synthetic open failure {self.open_calls}/{self._open_failures}")
        self.is_open = True
        self._next_t = time.perf_counter()
        return CaptureInfo("synthetic", "RAW ", self._width, self._height, self._fps)

    def read(self) -> Image | None:
        if not self.is_open:
            return None
        index = self._read_calls
        self._read_calls += 1
        if self._period:
            self._next_t += self._period
            delay = self._next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                self._next_t = time.perf_counter()
        if index in self._fail_reads:
            return None
        self._seq += 1
        img = np.full((self._height, self._width, 3), 40, dtype=np.uint8)
        x = (self._seq * 4) % self._width
        img[:, x : x + 8] = (0, 200, 255)
        img[0, :8, 0] = np.frombuffer(self._seq.to_bytes(8, "little"), dtype=np.uint8)
        return img

    def close(self) -> None:
        self.close_calls += 1
        self.is_open = False


# --- latest-frame camera -------------------------------------------------------------------------------


class LatestFrameCamera:
    """Background reader that keeps only the newest frame.

    Example::

        with LatestFrameCamera(cfg.cameras.driver, "driver") as cam:
            last = 0
            while True:
                frame = cam.wait_new(last, timeout=1.0)
                if frame is None:
                    continue
                last = frame.frame_id
                ...
    """

    def __init__(
        self,
        cfg: CameraConfig,
        name: str = "driver",
        source: FrameSource | None = None,
        *,
        quiet_open_errors: bool = False,
    ) -> None:
        """``quiet_open_errors``: open failures go to DEBUG and :attr:`CaptureStats.last_error`; the owner reports
        them at its own pace (the camera workers: ``camera_unavailable`` every ``workers.unavailable_report_s``)."""
        self._cfg = cfg
        self._name = name
        self._quiet_open_errors = quiet_open_errors
        self._last_error: str | None = None
        self._source: FrameSource = source if source is not None else OpenCVSource(cfg, name)
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rate = RateMeter(window_s=1.0)
        # guarded by _cond
        self._frame: Frame | None = None
        self._next_id = 0
        self._delivered_id = 0
        self._dropped = 0
        self._connected = False
        self._info: CaptureInfo | None = None
        self._reconnects = 0
        self._read_failures = 0

    @property
    def name(self) -> str:
        return self._name

    # lifecycle ----------------------------------------------------------------------------------------

    def start(self) -> LatestFrameCamera:
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"capture-{self._name}", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the reader thread, release the camera and wake up any ``wait_new`` caller."""
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning("capture thread did not stop in time", extra={"fields": {"camera": self._name}})
            self._thread = None

    def __enter__(self) -> LatestFrameCamera:
        return self.start()

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.stop()

    # consumer API -------------------------------------------------------------------------------------

    def wait_new(self, last_id: int, timeout: float) -> Frame | None:
        """Block until a frame newer than ``last_id`` exists; ``None`` on timeout or after ``stop``."""
        with self._cond:
            self._cond.wait_for(self._newer_or_stopped(last_id), timeout)
            frame = self._frame
            if frame is None or frame.frame_id <= last_id:
                return None
            self._delivered_id = max(self._delivered_id, frame.frame_id)
            return frame

    def latest(self) -> Frame | None:
        """Newest frame without waiting (may be one already returned before)."""
        with self._cond:
            return self._frame

    def stats(self) -> CaptureStats:
        with self._cond:
            return CaptureStats(
                name=self._name,
                connected=self._connected,
                info=self._info,
                capture_fps=self._rate.rate(),
                frames=self._next_id,
                dropped=self._dropped,
                reconnects=self._reconnects,
                read_failures=self._read_failures,
                last_error=self._last_error,
            )

    # internals ----------------------------------------------------------------------------------------

    def _newer_or_stopped(self, last_id: int) -> Callable[[], bool]:
        def predicate() -> bool:
            return self._stop.is_set() or (self._frame is not None and self._frame.frame_id > last_id)

        return predicate

    def _run(self) -> None:
        failures = 0
        opened_once = False
        try:
            while not self._stop.is_set():
                if not self._connected:
                    try:
                        info = self._source.open()
                    except Exception as exc:
                        with self._cond:
                            self._last_error = str(exc)
                        (log.debug if self._quiet_open_errors else log.warning)(
                            "camera open failed",
                            extra={
                                "fields": {
                                    "camera": self._name,
                                    "error": str(exc),
                                    "retry_s": self._cfg.reconnect_s,
                                }
                            },
                        )
                        self._stop.wait(self._cfg.reconnect_s)
                        continue
                    with self._cond:
                        self._connected = True
                        self._info = info
                        self._last_error = None
                        if opened_once:
                            self._reconnects += 1
                    opened_once = True
                    failures = 0
                    log.info(
                        "camera opened",
                        extra={
                            "fields": {
                                "camera": self._name,
                                "backend": info.backend,
                                "fourcc": info.fourcc,
                                "width": info.width,
                                "height": info.height,
                                "fps": info.fps,
                                "device": info.device,
                                "via": info.via,
                                "reconnects": self._reconnects,
                            }
                        },
                    )

                image = self._source.read()
                if image is None:
                    failures += 1
                    with self._cond:
                        self._read_failures += 1
                    if failures >= self._cfg.max_read_failures:
                        log.warning(
                            "camera lost, reconnecting",
                            extra={"fields": {"camera": self._name, "failed_reads": failures}},
                        )
                        self._source.close()
                        with self._cond:
                            self._connected = False
                        self._stop.wait(self._cfg.reconnect_s)
                    continue

                failures = 0
                t_capture = time.perf_counter()
                with self._cond:
                    previous = self._frame
                    if previous is not None and previous.frame_id > self._delivered_id:
                        self._dropped += 1
                    self._next_id += 1
                    self._frame = Frame(image=image, frame_id=self._next_id, t_capture=t_capture)
                    self._cond.notify_all()
                self._rate.tick(t_capture)
        finally:
            self._source.close()
            with self._cond:
                self._connected = False
                self._cond.notify_all()
