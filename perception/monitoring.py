"""Can this camera still see its person? (plan AS12 / AP5, rule C7 "Nu te mai văd")

P1 reports **whether** monitoring works and **why not**; P2's rule C7 decides what to say. Reasons, most specific
first:

* ``camera_unavailable``: the camera process is down or the device delivers no frames;
* ``camera_frozen``: frames keep arriving but the image does not change (driver bug, USB stall) for
  ``monitoring.frozen_frame_s``;
* ``camera_covered``: no face for ``monitoring.face_lost_s`` and the image is dark (hand / cloth over the lens);
* ``face_lost``: no face for ``monitoring.face_lost_s`` in a normally lit image (the person left the seat, turned
  far away).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from perception.config import MonitoringConfig

__all__ = ["Monitor", "MonitorState", "MonitoringReason", "thumbnail"]

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
