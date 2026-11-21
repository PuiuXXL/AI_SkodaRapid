"""Can this camera still see its person? (plan AS12 / AP5, rule C7 "Nu te mai văd")

P1 reports **whether** monitoring works and **why not**; P2's rule C7 decides what to say. Reasons, most specific
first:

* ``camera_unavailable``: the camera process is down or the device delivers no frames;
* ``camera_frozen``: frames keep arriving but the image does not change (driver bug, USB stall) for
  ``monitoring.frozen_frame_s``;
* ``camera_covered``: no face for ``monitoring.face_lost_s`` and the image is dark (hand / cloth over the lens);
* ``face_lost``: no face for ``monitoring.face_lost_s`` in a normally lit image (the person left the seat, turned
  far away).

``CameraMonitor`` (below) is the standalone successor with the finer reasons of AS12 / AP5 (``no_frames``,
``frozen``, ``mode_switch``, ``occluded``, ``too_dark``, ``blurred``, ``face_lost``); ``Monitor`` stays until the worker
is switched over (docs/notes/modules.md, "De integrat").
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any, Literal

import cv2
import numpy as np
import numpy.typing as npt

from perception.config import MonitoringConfig

__all__ = [
    "CameraMonitor",
    "CameraMonitorConfig",
    "ImageStats",
    "Monitor",
    "MonitorReason",
    "MonitorState",
    "MonitoringReason",
    "MonitoringResult",
    "image_stats",
    "thumbnail",
]

MonitoringReason = Literal["camera_unavailable", "camera_frozen", "camera_covered", "face_lost"]
_THUMB = (64, 36)


def thumbnail(image: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
    """Sparse pixel sample for the frozen-frame check (no averaging, ~0.05 ms on 720p).

    Plain subsampling keeps the sensor noise: a live camera filming a static, empty scene still changes by ~1-2
    grey levels per pixel, while a frozen driver returns the same buffer (difference 0). An area-averaged thumbnail
    averaged that noise away and flagged a static dark room as frozen.
    """
    h, w = image.shape[:2]
    sample = image[:: max(1, h // _THUMB[1]), :: max(1, w // _THUMB[0])]
    grey = sample[..., 1] if sample.ndim == 3 else sample  # green channel: no colour conversion needed
    return grey.astype(np.float32)


@dataclass(frozen=True)
class MonitorState:
    ok: bool
    reason: MonitoringReason | None = None
    face_missing_s: float = 0.0


class Monitor:
    def __init__(self, cfg: MonitoringConfig) -> None:
        self.cfg = cfg
        self._last_face_t: float | None = None
        self._first_t: float | None = None
        self._prev_thumb: npt.NDArray[np.float32] | None = None
        self._still_since: float | None = None

    def update(
        self,
        t: float,
        *,
        face_present: bool,
        thumb: npt.NDArray[np.float32] | None = None,
        luma: float | None = None,
    ) -> MonitorState:
        if self._first_t is None:
            self._first_t = t
        if face_present:
            self._last_face_t = t
        frozen = False
        if thumb is not None:
            if self._prev_thumb is not None and float(np.mean(np.abs(thumb - self._prev_thumb))) < (
                self.cfg.frozen_pixel_diff
            ):
                self._still_since = self._still_since if self._still_since is not None else t
                frozen = t - self._still_since >= self.cfg.frozen_frame_s
            else:
                self._still_since = None
            self._prev_thumb = thumb
        missing = t - (self._last_face_t if self._last_face_t is not None else self._first_t)
        if frozen:
            return MonitorState(False, "camera_frozen", round(missing, 2))
        if missing >= self.cfg.face_lost_s:
            dark = luma is not None and luma < self.cfg.dark_luma
            return MonitorState(False, "camera_covered" if dark else "face_lost", round(missing, 2))
        return MonitorState(True, None, round(missing, 2))

    @staticmethod
    def unavailable() -> MonitorState:
        return MonitorState(False, "camera_unavailable")


# --- CameraMonitor: standalone module (AS12 / AP5), finer reasons ----------------------------------------

MonitorReason = Literal["no_frames", "frozen", "mode_switch", "occluded", "too_dark", "blurred", "face_lost"]
Mode = Literal["color", "mono"]


@dataclass(frozen=True)
class CameraMonitorConfig:
    """Defaults = ``perception/config/pending/modules.yaml``, section ``monitoring``."""

    no_frames_s: float = 1.0
    frozen_s: float = 1.0
    frozen_pixel_diff: float = 0.5
    face_lost_s: float = 2.0
    dark_luma: float = 60.0
    occluded_std_max: float = 8.0
    blur_var_min: float = 20.0
    mono_chroma_max: float = 2.0
    mode_switch_luma_delta: float = 50.0
    mode_switch_hold_s: float = 1.5
    min_face_width_px: float = 250.0
    analysis_width: int = 160

    def __post_init__(self) -> None:
        if min(self.no_frames_s, self.frozen_s, self.face_lost_s, self.min_face_width_px) <= 0:
            raise ValueError("monitoring: no_frames_s, frozen_s, face_lost_s, min_face_width_px must be > 0")
        if min(self.frozen_pixel_diff, self.occluded_std_max, self.blur_var_min, self.mode_switch_hold_s) < 0:
            raise ValueError("monitoring thresholds must be >= 0")
        if not 0 <= self.dark_luma <= 255 or self.mode_switch_luma_delta <= 0 or self.analysis_width < 16:
            raise ValueError("monitoring: dark_luma in [0, 255], mode_switch_luma_delta > 0, analysis_width >= 16")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> CameraMonitorConfig:
        unknown = sorted(set(data) - {f.name for f in fields(cls)})
        if unknown:
            raise ValueError(f"CameraMonitorConfig: unknown keys {unknown}")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class ImageStats:
    luma: float  # mean grey level 0-255
    std: float  # grey-level standard deviation (uniform image = lens covered)
    sharpness: float  # variance of the Laplacian (low = blurred / defocused)
    chroma: float  # mean |R-G|, |B-G| (about 0 for a monochrome / IR image)


def image_stats(image: npt.NDArray[np.uint8], width: int = 160) -> ImageStats:
    """Luma, contrast, sharpness and colourfulness on a copy resized to ``width`` px (~0.1 ms for 720p)."""
    h, w = image.shape[:2]
    small: npt.NDArray[Any] = image
    if w > width:
        small = cv2.resize(image, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)
    if small.ndim == 3 and small.shape[2] == 3:
        grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        b, g, r = (small[:, :, i].astype(np.float32) for i in range(3))
        chroma = float((np.mean(np.abs(r - g)) + np.mean(np.abs(b - g))) / 2.0)
    else:
        grey = small.reshape(small.shape[0], small.shape[1])
        chroma = 0.0
    return ImageStats(
        luma=float(np.mean(grey)),
        std=float(np.std(grey)),
        sharpness=float(cv2.Laplacian(grey, cv2.CV_64F).var()),
        chroma=chroma,
    )


@dataclass(frozen=True, slots=True)
class MonitoringResult:
    ok: bool = True  # monitoring_ok
    reason: MonitorReason | None = None  # why not ok (monitoring_reason)
    warnings: tuple[str, ...] = ()  # quality problems while ok: too_dark, blurred, face_too_small
    face_too_small: bool = False  # R-FL3: reduced confidence, NOT a monitoring failure
    confidence: float = 0.0  # face confidence from its width (R-FL3); 0 without a face
    face_missing_s: float = 0.0
    luma: float | None = None
    std: float | None = None
    sharpness: float | None = None
    chroma: float | None = None
    mode: Mode | None = None  # colour (day) / mono (IR night)
    mode_switched: bool = False  # a day/night switch happened on THIS frame: reset EAR references / filters
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CameraMonitor:
    """``monitoring_ok`` + reason for one camera. Call :meth:`update` per frame, and :meth:`tick` (or
    :meth:`update` with ``None``) when no frame arrived.

    Reasons, by priority:

    1. ``no_frames``: no frame for ``no_frames_s``;
    2. ``frozen``: identical frames (sparse pixel sample, keeps sensor noise) for ``frozen_s``;
    3. ``mode_switch``: colour <-> mono flip (IR day/night switch) or a luma jump of ``mode_switch_luma_delta``
       between consecutive frames with the image still structured; reported for ``mode_switch_hold_s``;
    4. face missing for ``face_lost_s``, explained by the image: ``occluded`` (uniform image: hand / cloth on the lens)
       > ``too_dark`` > ``blurred`` > ``face_lost`` (nothing wrong with the image: the person is gone / turned away).

    While the face is seen, darkness and blur are only ``warnings``: a working face detector is the best evidence that
    monitoring works. ``face_too_small`` (R-FL3) lowers ``confidence`` and never sets ``ok = false``.
    """

    def __init__(self, cfg: CameraMonitorConfig | None = None) -> None:
        self.cfg = cfg or CameraMonitorConfig()
        self._start_t: float | None = None
        self._last_frame_t: float | None = None
        self._last_face_t: float | None = None
        self._prev_thumb: npt.NDArray[np.float32] | None = None
        self._still_since: float | None = None
        self._mode: Mode | None = None
        self._prev_luma: float | None = None
        self._switch_until = float("-inf")
        self._last = MonitoringResult()

    def tick(self, t: float) -> MonitoringResult:
        """No new frame at time ``t``."""
        return self.update(t, None, face_present=False)

    def update(
        self,
        t: float,
        image: npt.NDArray[np.uint8] | None,
        *,
        face_present: bool,
        face_width_px: float | None = None,
    ) -> MonitoringResult:
        t0 = time.perf_counter()
        cfg = self.cfg
        if self._start_t is None:
            self._start_t = t
        if image is None:
            since = self._last_frame_t if self._last_frame_t is not None else self._start_t
            if t - since >= cfg.no_frames_s:
                self._last = MonitoringResult(
                    ok=False,
                    reason="no_frames",
                    face_missing_s=round(t - self._face_ref(), 2),
                    ms=round((time.perf_counter() - t0) * 1000.0, 3),
                )
            return self._last

        stats = image_stats(image, cfg.analysis_width)
        thumb = thumbnail(image)
        same = (
            self._prev_thumb is not None
            and self._prev_thumb.shape == thumb.shape
            and float(np.mean(np.abs(thumb - self._prev_thumb))) < cfg.frozen_pixel_diff
        )
        if same:
            self._still_since = self._still_since if self._still_since is not None else t
        else:
            self._still_since = None
        frozen = self._still_since is not None and t - self._still_since >= cfg.frozen_s
        self._prev_thumb = thumb

        # colour / luma only mean something on a structured image: a covered lens is uniform and colourless, and
        # must neither flip the mode when covered nor look like a luma jump when uncovered
        uniform = stats.std < cfg.occluded_std_max
        mode: Mode | None = self._mode
        switched = False
        if not uniform:
            mode = "mono" if stats.chroma < cfg.mono_chroma_max else "color"
            consecutive = self._last_frame_t is not None and t - self._last_frame_t < cfg.no_frames_s
            switched = (self._mode is not None and mode != self._mode) or (
                consecutive
                and self._prev_luma is not None
                and abs(stats.luma - self._prev_luma) >= cfg.mode_switch_luma_delta
            )
            self._mode = mode
        if switched:
            self._switch_until = t + cfg.mode_switch_hold_s
        self._prev_luma = None if uniform else stats.luma
        self._last_frame_t = t

        if face_present:
            self._last_face_t = t
        missing = t - self._face_ref()
        too_small = bool(face_present and face_width_px is not None and face_width_px < cfg.min_face_width_px)
        if not face_present:
            confidence = 0.0
        elif face_width_px is None:
            confidence = 1.0
        else:
            confidence = min(1.0, face_width_px / cfg.min_face_width_px)
        dark = stats.luma < cfg.dark_luma
        blurred = stats.sharpness < cfg.blur_var_min

        reason: MonitorReason | None = None
        if frozen:
            reason = "frozen"
        elif t < self._switch_until:
            reason = "mode_switch"
        elif missing >= cfg.face_lost_s:
            reason = "occluded" if uniform else "too_dark" if dark else "blurred" if blurred else "face_lost"
        warnings: tuple[str, ...] = ()
        if reason is None:
            flags = (("too_dark", dark), ("blurred", blurred), ("face_too_small", too_small))
            warnings = tuple(name for name, on in flags if on)
        self._last = MonitoringResult(
            ok=reason is None,
            reason=reason,
            warnings=warnings,
            face_too_small=too_small,
            confidence=round(confidence, 3),
            face_missing_s=round(missing, 2),
            luma=round(stats.luma, 1),
            std=round(stats.std, 1),
            sharpness=round(stats.sharpness, 1),
            chroma=round(stats.chroma, 2),
            mode=mode,
            mode_switched=switched,
            ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )
        return self._last

    def _face_ref(self) -> float:
        if self._last_face_t is not None:
            return self._last_face_t
        return self._start_t if self._start_t is not None else 0.0
