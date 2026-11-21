"""Posture from the face alone (no extra model): leaning forward / sideways, slumped, out of position.

Compared with a reference posture: the driver's comes from the gaze calibration (the ``road`` samples: face centre,
face width and head angles, stored in the profile as ``posture_ref``); without one (the passenger, or a driver not
calibrated yet) the reference is the median of the first ``posture.auto_ref_s`` seconds with the face seen. Distances
are in reference face widths, so the rules do not depend on the camera resolution or the seat distance.

* ``leaning_forward``: face width >= ``forward_width_ratio`` x the reference (the head came closer to the camera);
* ``leaning_side``: face centre shifted sideways by >= ``side_shift_ratio`` face widths, or roll beyond
  ``side_roll_deg``;
* ``slumped``: face centre lower by >= ``slumped_drop_ratio`` face widths AND pitch down by >= ``slumped_pitch_deg``;
* ``out_of_position``: face centre >= ``out_shift_ratio`` face widths away, or width ratio outside ``out_width_ratio``.

Each state needs ``min_duration_s`` (a glance at a mirror or a quick reach is not a posture). Thresholds in yaml.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass

from perception.config import PostureConfig
from perception.features import FaceFeatures

__all__ = ["POSTURE_STATES", "PostureOutput", "PostureRef", "PostureTracker", "face_geometry"]

POSTURE_STATES: tuple[str, ...] = ("leaning_forward", "leaning_side", "slumped", "out_of_position")
_TOP, _CHIN = 10, 152  # forehead top and chin landmarks: their midpoint is the face centre


@dataclass(frozen=True)
class PostureRef:
    cx: float  # face centre, px
    cy: float
    width: float  # face width, px
    yaw: float
    pitch: float
    roll: float

    def to_dict(self) -> dict[str, float]:
        return {k: round(v, 3) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> PostureRef:
        return cls(**{k: float(data[k]) for k in ("cx", "cy", "width", "yaw", "pitch", "roll")})

    @classmethod
    def median(cls, samples: list[tuple[float, float, float, float, float, float]]) -> PostureRef | None:
        if not samples:
            return None
        return cls(*(statistics.median(s[i] for s in samples) for i in range(6)))


@dataclass
class PostureOutput:
    leaning_forward: bool = False
    leaning_side: bool = False
    slumped: bool = False
    out_of_position: bool = False
    reference: str | None = None  # "calibration" / "auto" / None (still learning)
    width_ratio: float | None = None  # debug: face width / reference
    shift_x: float | None = None  # debug: face centre offsets in reference face widths (x > 0 = image right)
    shift_y: float | None = None  # (y > 0 = lower)

    def states(self) -> dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in POSTURE_STATES}

    def active(self) -> list[str]:
        return [name for name in POSTURE_STATES if getattr(self, name)]


def face_geometry(face: FaceFeatures, frame_size: tuple[int, int]) -> tuple[float, float, float] | None:
    """(centre x px, centre y px, face width px) of a seen face, or None."""
    if not face.present or face.landmarks is None or not face.width_px:
        return None
    w, h = frame_size
    (x1, y1, _), (x2, y2, _) = face.point(_TOP), face.point(_CHIN)
    return (x1 + x2) / 2.0 * w, (y1 + y2) / 2.0 * h, float(face.width_px)


class PostureTracker:
    def __init__(self, cfg: PostureConfig) -> None:
        self.cfg = cfg
        self.calibrated: PostureRef | None = None
        self._auto: PostureRef | None = None
        self._auto_samples: list[tuple[float, float, float, float, float, float]] = []
        self._auto_t0: float | None = None
        self._since: dict[str, float | None] = dict.fromkeys(POSTURE_STATES)

    def set_reference(self, ref: PostureRef | None) -> None:
        """Reference from the calibration profile (None = back to the automatic one)."""
        self.calibrated = ref

    @property
    def reference(self) -> PostureRef | None:
        return self.calibrated or self._auto

    def _learn(self, t: float, sample: tuple[float, float, float, float, float, float]) -> None:
        if self._auto is not None:
            return
        if self._auto_t0 is None:
            self._auto_t0 = t
        self._auto_samples.append(sample)
        if t - self._auto_t0 >= self.cfg.auto_ref_s:
            self._auto = PostureRef.median(self._auto_samples)
            self._auto_samples = []

    def update(
        self,
        t: float,
        geometry: tuple[float, float, float] | None,
        yaw: float | None,
        pitch: float | None,
        roll: float | None,
    ) -> PostureOutput:
        if geometry is None or yaw is None or pitch is None or roll is None:
            self._since = dict.fromkeys(POSTURE_STATES)  # no face: no posture claim (monitoring reports the loss)
            return PostureOutput(reference=self._ref_name())
        cx, cy, width = geometry
        self._learn(t, (cx, cy, width, yaw, pitch, roll))
        ref = self.reference
        if ref is None or ref.width <= 0:
            return PostureOutput(reference=None)
        c = self.cfg
        ratio = width / ref.width
        dx, dy = (cx - ref.cx) / ref.width, (cy - ref.cy) / ref.width
        raw = {
            "leaning_forward": ratio >= c.forward_width_ratio,
            "leaning_side": abs(dx) >= c.side_shift_ratio or abs(roll - ref.roll) >= c.side_roll_deg,
            "slumped": dy >= c.slumped_drop_ratio and (ref.pitch - pitch) >= c.slumped_pitch_deg,
            "out_of_position": (dx * dx + dy * dy) ** 0.5 >= c.out_shift_ratio
            or not c.out_width_ratio[0] <= ratio <= c.out_width_ratio[1],
        }
        out = PostureOutput(
            reference=self._ref_name(), width_ratio=round(ratio, 3), shift_x=round(dx, 3), shift_y=round(dy, 3)
        )
        for name, now in raw.items():
            if not now:
                self._since[name] = None
                continue
            start = self._since[name]
            if start is None:
                self._since[name] = start = t
            setattr(out, name, t - start >= c.min_duration_s)
        return out

    def _ref_name(self) -> str | None:
        return "calibration" if self.calibrated else ("auto" if self._auto else None)
