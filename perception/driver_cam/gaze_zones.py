"""Gaze zones: per-driver calibrated kNN on head pose + MobileGaze + eyeLook blendshapes + iris offset (AS5).

docs/perception.md §3.4.

* :class:`GazeFeatureBuilder` turns a FeatureFrame (+ head and smoothed gaze angles) into the 14-feature vector
  :data:`FEATURES`. The **same** function feeds the calibration and the live classifier. It returns ``None`` (zone
  ``unknown``, never a guessed zone) when the frame is not trustworthy: no face, R-FL3 ``face_too_small``, face
  confidence below ``filters.unknown_below_conf`` (R-FL2), implausible head angles, no fresh MobileGaze value, no
  reliable eye. Squinted eyes (R-FL4) stay valid. The head angles are the **unfiltered** ones
  (:func:`zone_head_angles`): the head One Euro is tuned for jitter (min cutoff 0.05 Hz) and lags fast glances, while
  the raw noise (0.1-0.2 deg) is negligible next to the zone spacing.
* :class:`ZoneModel`: z-score with the calibration statistics (std floored per group), group weights, distance-weighted
  kNN (1/d). Rejection: the mean distance to the k neighbours above tau, with tau = p95 of the **blocked
  leave-one-out** distances x ``reject_factor``: every sample is classified without the frames of its own calibration
  segment within ``gaze.loo_exclude_s`` (excluding only the sample itself would compare it with its near-identical
  neighbour frames and give a far too small tau; excluding the whole segment would leave road, recorded as one segment,
  without any road neighbour). A vote share below ``min_conf`` is rejected too. A rejected frame with the head
  beyond the calibrated range by ``away_margin_deg`` is ``away`` (off-road), otherwise ``unknown`` (never an alert).
* :class:`ZoneTracker`: a new zone is accepted after ``zone_min_frames`` frames; during a blink the previous zone is
  held for at most ``eyes.blink_max_ms``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from perception.config import PerceptionConfig
from perception.features import FeatureFrame

__all__ = [
    "EYE_CORNERS",
    "FEATURES",
    "FEATURE_GROUPS",
    "IRIS_CENTRES",
    "GazeFeatureBuilder",
    "ZoneModel",
    "ZoneResult",
    "ZoneTracker",
    "iris_offset",
    "zone_head_angles",
]

EYE_LOOK = (
    "eyeLookInLeft",
    "eyeLookInRight",
    "eyeLookOutLeft",
    "eyeLookOutRight",
    "eyeLookUpLeft",
    "eyeLookUpRight",
    "eyeLookDownLeft",
    "eyeLookDownRight",
)
FEATURES: tuple[str, ...] = ("head_yaw", "head_pitch", "gaze_yaw", "gaze_pitch", *EYE_LOOK, "iris_x", "iris_y")
FEATURE_GROUPS: dict[str, tuple[int, ...]] = {
    "head": (0, 1),
    "gaze": (2, 3),
    "eye_look": tuple(range(4, 4 + len(EYE_LOOK))),
    "iris": (12, 13),
}
# corners ordered image-left -> image-right for both eyes (right eye: outer 33 -> inner 133; left: inner 362 -> outer
# 263), so the x axis of both points to the image right = the driver's left on a non-mirrored camera
EYE_CORNERS = {"right": (33, 133), "left": (362, 263)}
IRIS_CENTRES = {"right": 468, "left": 473}

Vector = npt.NDArray[np.float64]


def zone_head_angles(
    filtered_yaw: float | None, raw_yaw: float | None, raw_pitch: float | None
) -> tuple[float | None, float | None]:
    """Head (yaw, pitch) for the zone features: the raw angles, ``None`` when the head tracker reports them unknown."""
    if filtered_yaw is None:  # implausible pose or no face
        return None, None
    return raw_yaw, raw_pitch


def iris_offset(ff: FeatureFrame, side: str, w: int, h: int) -> tuple[float, float, float] | None:
    """(x, y, eye width px) of the iris centre relative to the eye-corner midpoint, in eye widths.

    x > 0 = towards the driver's left (image right), y > 0 = up.
    """
    face = ff.face
    if face.landmarks is None:
        return None
    a_idx, b_idx = EYE_CORNERS[side]
    ax, ay, _ = face.point(a_idx)
    bx, by, _ = face.point(b_idx)
    ix, iy, _ = face.point(IRIS_CENTRES[side])
    a = np.array([ax * w, ay * h])
    b = np.array([bx * w, by * h])
    c = np.array([ix * w, iy * h])
    width = float(np.linalg.norm(b - a))
    if width <= 1e-6:
        return None
    u = (b - a) / width
    v = np.array([-u[1], u[0]])  # u rotated +90 deg in image coordinates: points down
    d = c - (a + b) / 2
    return float(d @ u) / width, -float(d @ v) / width, width


class GazeFeatureBuilder:
    def __init__(self, cfg: PerceptionConfig, frame_size: tuple[int, int]) -> None:
        self.w, self.h = frame_size
        self.min_conf = cfg.filters.unknown_below_conf
        self.min_eye_width_px = cfg.eyes.min_eye_width_px
        self.unilateral_ratio = cfg.eyes.unilateral_width_ratio
        self.last_reason: str | None = None

    def build(
        self,
        ff: FeatureFrame,
        head_yaw: float | None,
        head_pitch: float | None,
        gaze: tuple[float, float] | None,
    ) -> Vector | None:
        """14 features, or ``None`` with :attr:`last_reason` set."""
        face = ff.face
        reason: str | None = None
        if not face.present or face.landmarks is None or face.blendshapes is None:
            reason = "no_face"
        elif face.too_small:
            reason = "face_too_small"  # R-FL3
        elif face.conf < self.min_conf:
            reason = "low_conf"  # R-FL2
        elif head_yaw is None or head_pitch is None:
            reason = "head_unknown"
        elif gaze is None:
            reason = "no_gaze"
        self.last_reason = reason
        if reason is not None or head_yaw is None or head_pitch is None or gaze is None or face.blendshapes is None:
            return None
        iris = self._iris(ff)
        if iris is None:
            self.last_reason = "eyes_unreliable"
            return None
        blend = face.blendshapes
        values = [head_yaw, head_pitch, gaze[0], gaze[1], *(float(blend.get(n, 0.0)) for n in EYE_LOOK), *iris]
        return np.asarray(values, dtype=np.float64)

    def _iris(self, ff: FeatureFrame) -> tuple[float, float] | None:
        offsets = {side: iris_offset(ff, side, self.w, self.h) for side in ("right", "left")}
        widths = {side: o[2] for side, o in offsets.items() if o is not None}
        if not widths:
            return None
        widest = max(widths.values())
        reliable = [
            offsets[side]
            for side, width in widths.items()
            if width >= self.min_eye_width_px and width >= self.unilateral_ratio * widest
        ]
        good = [o for o in reliable if o is not None]
        if not good:
            return None
        return float(np.mean([o[0] for o in good])), float(np.mean([o[1] for o in good]))


@dataclass
class ZoneResult:
    zone: str  # a calibrated zone, "away" or "unknown"
    conf: float
    distance: float | None  # mean weighted-z distance to the k neighbours
    nearest: str | None  # best kNN zone before rejection


def _group_vector(values: Any, n: int = len(FEATURES)) -> Vector:
    out = np.ones(n, dtype=np.float64)
    for group, idx in FEATURE_GROUPS.items():
        out[list(idx)] = float(getattr(values, group))
    return out


@dataclass
class ZoneModel:
    """Distance-weighted kNN with rejection. Build it with :meth:`fit` (calibration) or from saved statistics."""

    samples: Vector  # raw features (N, F)
    zones: list[str]
    segments: npt.NDArray[np.int64]
    times: Vector  # sample time (s); blocked LOO excludes same-segment samples within loo_exclude_s
    mean: Vector
    std: Vector
    weights: Vector
    k: int
    tau: float
    min_conf: float
    away_margin_deg: float
    loo_exclude_s: float = 0.0
    loo_zones: list[str] = field(default_factory=list)  # blocked-LOO prediction per sample
    _z: Vector = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._z = self.transform(self.samples)
        hy, hp = self.samples[:, 0], self.samples[:, 1]
        self.head_range = (float(np.min(hy)), float(np.max(hy)), float(np.min(hp)), float(np.max(hp)))

    # --- fit ------------------------------------------------------------------------------------------------

    @classmethod
    def fit(
        cls,
        samples: Sequence[Sequence[float]] | Vector,
        zones: Sequence[str],
        segments: Sequence[int],
        cfg: PerceptionConfig,
        times: Sequence[float] | None = None,
    ) -> ZoneModel:
        """``times`` = sample times in seconds (``None``: the whole segment is left out in the LOO)."""
        x = np.asarray(samples, dtype=np.float64)
        n = len(x)
        if x.ndim != 2 or x.shape[1] != len(FEATURES) or len(zones) != n or len(segments) != n:
            raise ValueError(f"need (N, {len(FEATURES)}) samples with one zone and one segment each")
        if times is not None and len(times) != n:
            raise ValueError("need one time per sample")
        g = cfg.gaze
        std = np.maximum(x.std(axis=0), _group_vector(g.std_floor))
        model = cls(
            samples=x,
            zones=list(zones),
            segments=np.asarray(segments, dtype=np.int64),
            times=np.asarray(times, dtype=np.float64) if times is not None else np.full(n, np.nan),
            mean=x.mean(axis=0),
            std=std,
            weights=_group_vector(g.feature_weights),
            k=g.k,
            tau=float("inf"),
            min_conf=g.min_conf,
            away_margin_deg=g.away_margin_deg,
            loo_exclude_s=g.loo_exclude_s,
        )
        dists, preds = model.blocked_loo()
        model.loo_zones = preds
        finite = dists[np.isfinite(dists)]
        model.tau = float(np.percentile(finite, 95) * g.reject_factor) if finite.size else float("inf")
        return model

    def transform(self, x: Vector) -> Vector:
        return np.asarray((x - self.mean) / self.std * self.weights, dtype=np.float64)

    def blocked_loo(self, chunk: int = 512) -> tuple[Vector, list[str]]:
        """Mean kNN distance and predicted zone of every sample, without its same-segment neighbours in time."""
        n = len(self._z)
        out_d = np.full(n, np.inf)
        out_z: list[str] = ["unknown"] * n
        for start in range(0, n, chunk):
            block = self._z[start : start + chunk]
            sq = (block**2).sum(axis=1)[:, None] + (self._z**2).sum(axis=1)[None, :] - 2.0 * block @ self._z.T
            d = np.sqrt(np.maximum(sq, 0.0))
            same = self.segments[start : start + chunk, None] == self.segments[None, :]
            dt = np.abs(self.times[start : start + chunk, None] - self.times[None, :])
            d[same & ~(dt > self.loo_exclude_s)] = np.inf  # NaN times (unknown) -> the whole segment
            for row in range(len(block)):
                zone, _, dist = self._vote(d[row])
                if dist is not None:
                    out_d[start + row] = dist
                    out_z[start + row] = zone
        return out_d, out_z

    # --- classify -------------------------------------------------------------------------------------------

    def _vote(self, d: Vector) -> tuple[str, float, float | None]:
        valid = np.isfinite(d)
        count = int(valid.sum())
        if count == 0:
            return "unknown", 0.0, None
        k = min(self.k, count)
        idx = np.argpartition(np.where(valid, d, np.inf), k - 1)[:k]
        w = 1.0 / (d[idx] + 1e-6)
        votes: dict[str, float] = {}
        for i, wi in zip(idx, w, strict=True):
            votes[self.zones[int(i)]] = votes.get(self.zones[int(i)], 0.0) + float(wi)
        zone = max(votes, key=lambda z: votes[z])
        return zone, votes[zone] / float(w.sum()), float(d[idx].mean())

    def classify(self, x: Vector) -> ZoneResult:
        z = self.transform(x[None, :])[0]
        d = np.sqrt(((self._z - z) ** 2).sum(axis=1))
        zone, conf, dist = self._vote(d)
        if dist is None:
            return ZoneResult("unknown", 0.0, None, None)
        if dist <= self.tau and conf >= self.min_conf:
            return ZoneResult(zone, conf, dist, zone)
        y_min, y_max, p_min, p_max = self.head_range
        m = self.away_margin_deg
        yaw, pitch = float(x[0]), float(x[1])
        if yaw > y_max + m or yaw < y_min - m or pitch > p_max + m or pitch < p_min - m:
            return ZoneResult("away", 0.0, dist, zone)
        return ZoneResult("unknown", 0.0, dist, zone)

    # --- (de)serialisation ------------------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": list(FEATURES),
            "mean": self.mean.round(6).tolist(),
            "std": self.std.round(6).tolist(),
            "weights": self.weights.tolist(),
            "k": self.k,
            "tau": self.tau,
            "min_conf": self.min_conf,
            "away_margin_deg": self.away_margin_deg,
        }


class ZoneTracker:
    """Stable zone: a new candidate must persist ``min_frames`` frames; blinks hold the zone for ``blink_hold_s``."""

    def __init__(self, min_frames: int, blink_hold_s: float) -> None:
        self.min_frames = max(1, min_frames)
        self.blink_hold_s = blink_hold_s
        self.zone = "unknown"
        self.conf = 0.0
        self.t_change: float | None = None
        self._pending: str | None = None
        self._count = 0
        self._closed_since: float | None = None

    def update(self, t: float, result: ZoneResult | None, eyes_closed: bool = False) -> str:
        if eyes_closed:
            if self._closed_since is None:
                self._closed_since = t
            if t - self._closed_since > self.blink_hold_s and self.zone != "unknown":
                self.zone, self.conf, self.t_change = "unknown", 0.0, t
            self._pending, self._count = None, 0
            return self.zone
        self._closed_since = None
        candidate = result.zone if result is not None else "unknown"
        if candidate == self.zone:
            self._pending, self._count = None, 0
            if result is not None:
                self.conf = result.conf
            return self.zone
        if candidate == self._pending:
            self._count += 1
        else:
            self._pending, self._count = candidate, 1
        if self._count >= self.min_frames:
            self.zone = candidate
            self.conf = result.conf if result is not None else 0.0
            self.t_change = t
            self._pending, self._count = None, 0
        return self.zone

    def reset(self) -> None:
        self.zone, self.conf, self.t_change = "unknown", 0.0, None
        self._pending, self._count, self._closed_since = None, 0, None
