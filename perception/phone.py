"""Phone in use (AS7 driver / AP4 passenger): YOLO26 class 67 + geometry with the hands and the face + 3-of-5 vote.

Standalone module, two classes:

* :class:`PhoneDetector`: YOLO26 through :class:`perception.runtime.OnnxModel` (``n`` at 416 px on CPU, ``s`` at
  640 px on GPU, chosen by ``device``), class 67 only, at ``rate_hz``. Input: a camera frame (BGR or mono; mono /
  IR frames are expanded to 3 channels) + timestamp. Output: :class:`PhoneDetections` with the inference time.
* :class:`PhoneTracker`: geometry and voting on the boxes of one YOLO run (from :class:`PhoneDetector` or from a
  recorded ``FeatureFrame.phones``), the face box, the hands (:mod:`perception.hands`) and the lap pattern (from
  the gaze zones, ``DriverGaze.lap_pattern``). Output: :class:`PhoneResult`.

Geometry, in the **driver's** terms (the image is not mirrored: image right = the driver's left):

* ``near_face``: phone centre within ``near_face_ratio`` x face width of the face centre -> usage ``"call"``;
* in a hand: a palm / wrist within ``hand_radius_ratio`` x face width of the box -> usage ``"hand"`` (texting);
* seen, owned, neither near the face nor in a seen hand -> usage ``"visible"`` (the hands are sampled sparsely);
* **not the driver's**: on the passenger side, farther than ``foreign_dx_ratio`` x face width from the face centre
  and not near the face (a phone coming in from the right is the passenger's). It does not vote (``foreign=True``);
* lap pattern (glances at the lap, hands unseen) -> ``source="lap_pattern"``, usage ``"lap"``, ``lap_conf``, only
  while the vote sees no phone.

Voting: in use only if an owned phone was seen in ``vote_min`` of the last ``vote_window`` YOLO runs (single-frame
flicker removed). A frame where YOLO did not run (``boxes=None``) keeps the decision.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
import numpy.typing as npt

from perception.config import REPO_ROOT
from perception.hands import Hand, as_bgr
from perception.postprocess import Detection, yolo26_detections
from perception.preprocess import letterbox

__all__ = [
    "PhoneBoxGeometry",
    "PhoneConfig",
    "PhoneDetections",
    "PhoneDetector",
    "PhoneResult",
    "PhoneTracker",
    "Usage",
]

CUDA = "CUDAExecutionProvider"
Box = tuple[float, float, float, float]  # x, y, w, h in pixels
Usage = Literal["call", "hand", "visible", "lap"]
Side = Literal["left", "right"]


class BoxLike(Protocol):
    """A phone box in frame pixels (``perception.postprocess.Detection`` or ``perception.features.PhoneBox``)."""

    @property
    def x1(self) -> float: ...
    @property
    def y1(self) -> float: ...
    @property
    def x2(self) -> float: ...
    @property
    def y2(self) -> float: ...
    @property
    def score(self) -> float: ...


class InferenceModel(Protocol):
    def run(self, feeds: Any) -> list[npt.NDArray[Any]]: ...


@dataclass(frozen=True)
class PhoneConfig:
    class_id: int = 67
    conf_min: float = 0.48  # yolo26s@640, live comparison 2026-11-21 (docs/eval/phone-compare-2026-11-21.md)
    device: str = "auto"  # auto | cpu | gpu
    cpu_model: str = "perception/models/yolo26s_640.onnx"
    cpu_imgsz: int = 640
    gpu_model: str = "perception/models/yolo26s_640.onnx"
    gpu_imgsz: int = 640
    cpu_providers: tuple[str, ...] = ("OpenVINOExecutionProvider", "CPUExecutionProvider")
    rate_hz: float = 5.0
    vote_window: int = 5
    vote_min: int = 3
    near_face_ratio: float = 1.2
    hand_radius_ratio: float = 0.6
    foreign_dx_ratio: float = 1.5
    passenger_side: str = "right"
    mirrored: bool = False
    owned_needs_contact: bool = True  # a driver phone must be near the face or in a hand ("visible" alone never votes)
    lap_conf: float = 0.40
    threads: int = 2  # CPU threads for the detector model (0 = the process-wide onnx_threads)

    def __post_init__(self) -> None:
        if not 0 <= self.class_id <= 79:
            raise ValueError("phone.class_id must be a COCO class (0..79)")
        if not 0.0 <= self.conf_min <= 1.0 or not 0.0 <= self.lap_conf <= 1.0:
            raise ValueError("phone.conf_min / lap_conf must be in [0, 1]")
        if self.device not in ("auto", "cpu", "gpu"):
            raise ValueError("phone.device must be auto, cpu or gpu")
        if not 1 <= self.vote_min <= self.vote_window <= 30:
            raise ValueError("phone: need 1 <= vote_min <= vote_window <= 30")
        if self.passenger_side not in ("left", "right"):
            raise ValueError("phone.passenger_side must be left or right")
        if min(self.near_face_ratio, self.hand_radius_ratio, self.foreign_dx_ratio) <= 0 or self.rate_hz < 0:
            raise ValueError("phone ratios must be > 0 and rate_hz >= 0")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PhoneConfig:
        unknown = sorted(set(data) - {f.name for f in fields(cls)})
        if unknown:
            raise ValueError(f"PhoneConfig: unknown keys {unknown}")
        kwargs: dict[str, Any] = {k: tuple(v) if isinstance(v, list) else v for k, v in data.items()}
        return cls(**kwargs)

    def path(self, name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else REPO_ROOT / p


# --- detector -------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhoneDetections:
    boxes: tuple[Detection, ...] = ()
    ms: float = 0.0  # letterbox + inference + decoding


class PhoneDetector:
    """YOLO26 phone detector for one camera.

    Args:
        cfg: module configuration.
        model: an object with ``run(tensor) -> [output]`` (``OnnxModel`` API) and ``imgsz`` its input size; built
            from the config when omitted (tests pass a fake).
        imgsz: input size for an injected model (default: the CPU variant's).
    """

    def __init__(
        self, cfg: PhoneConfig | None = None, *, model: InferenceModel | None = None, imgsz: int | None = None
    ) -> None:
        self.cfg = cfg or PhoneConfig()
        self.rate_hz = self.cfg.rate_hz  # changed at run time by the degradation rule (set_rate_hz)
        self._last_run: float | None = None
        if model is not None:
            self.model: InferenceModel = model
            self.imgsz = imgsz or self.cfg.cpu_imgsz
            self.provider = "injected"
            return
        from perception.runtime import OnnxModel, available_providers

        cfg = self.cfg
        use_gpu = cfg.device == "gpu" or (cfg.device == "auto" and CUDA in available_providers())
        path = cfg.path(cfg.gpu_model if use_gpu else cfg.cpu_model)
        providers = [CUDA, "CPUExecutionProvider"] if use_gpu else list(cfg.cpu_providers)
        onnx = OnnxModel(path, providers=providers, name="phone", threads=cfg.threads or None)
        self.model = onnx
        self.imgsz = cfg.gpu_imgsz if use_gpu else cfg.cpu_imgsz
        self.provider = onnx.provider

    def set_rate_hz(self, rate_hz: float) -> None:
        """Degradation rule (plan §8): lower / restore the YOLO rate; the vote is per run, so it stays valid."""
        self.rate_hz = max(0.0, rate_hz)

    def should_run(self, t: float) -> bool:
        rate = self.rate_hz
        if rate <= 0:
            return True
        return self._last_run is None or t - self._last_run >= 1.0 / rate - 1e-6

    def detect(self, image: npt.NDArray[np.uint8], t: float) -> PhoneDetections:
        t0 = time.perf_counter()
        bgr = as_bgr(image)
        tensor, meta = letterbox(bgr, self.imgsz)
        raw = self.model.run(tensor)[0]
        boxes = yolo26_detections(raw, meta, bgr.shape, conf_min=self.cfg.conf_min, class_ids={self.cfg.class_id})
        self._last_run = t
        return PhoneDetections(tuple(boxes), round((time.perf_counter() - t0) * 1000.0, 3))


# --- geometry + vote ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhoneBoxGeometry:
    box: tuple[float, float, float, float]  # x1, y1, x2, y2
    score: float
    near_face: bool
    side: Side | None  # driver's terms; None without a face box
    in_hand: bool
    foreign: bool  # not the driver's (passenger side, far from the face)
    usage: Usage


@dataclass(frozen=True, slots=True)
class PhoneResult:
    in_use: bool = False
    conf: float = 0.0
    source: Literal["detector", "lap_pattern"] | None = None
    usage: Usage | None = None
    near_face: bool = False
    side: Side | None = None
    box: tuple[float, float, float, float] | None = None  # the voted phone (overlay)
    foreign: bool = False  # this run saw a phone that is not the driver's (overlay, debug)
    foreign_box: tuple[float, float, float, float] | None = None
    votes: int = 0  # owned sightings in the vote window
    runs: int = 0  # YOLO runs in the vote window
    ran: bool = False  # YOLO ran on this frame
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _point_box_distance(px: float, py: float, box: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = box
    dx = max(x1 - px, 0.0, px - x2)
    dy = max(y1 - py, 0.0, py - y2)
    return math.hypot(dx, dy)


class PhoneTracker:
    """Geometry + vote for one camera; call :meth:`update` on every frame (``boxes=None`` when YOLO did not run)."""

    def __init__(self, cfg: PhoneConfig | None = None) -> None:
        self.cfg = cfg or PhoneConfig()
        self._votes: deque[PhoneBoxGeometry | None] = deque(maxlen=self.cfg.vote_window)
        self._foreign: PhoneBoxGeometry | None = None

    def geometry(self, box: BoxLike, face_box: Box | None, hands: Sequence[Hand]) -> PhoneBoxGeometry:
        cfg = self.cfg
        if face_box is not None and (face_box[2] <= 1.0 or face_box[3] <= 1.0):
            # degenerate landmark box: near_face (<= ratio x 0) could never hold and every phone would be "foreign"
            face_box = None
        xyxy = (float(box.x1), float(box.y1), float(box.x2), float(box.y2))
        px, py = (xyxy[0] + xyxy[2]) / 2.0, (xyxy[1] + xyxy[3]) / 2.0
        scale = face_box[2] if face_box is not None else max(xyxy[2] - xyxy[0], xyxy[3] - xyxy[1])
        in_hand = any(
            min(_point_box_distance(*h.palm_px, xyxy), _point_box_distance(*h.wrist_px, xyxy))
            <= cfg.hand_radius_ratio * scale
            for h in hands
        )
        near_face, foreign = False, False
        side: Side | None = None
        if face_box is not None:
            fx, fy, fw, fh = face_box
            fcx, fcy = fx + fw / 2.0, fy + fh / 2.0
            near_face = math.hypot(px - fcx, py - fcy) <= cfg.near_face_ratio * fw
            # not mirrored: image right = the driver's left; mirrored: image right = the driver's right
            drivers_left = (px > fcx) != cfg.mirrored
            side = "left" if drivers_left else "right"
            foreign = not near_face and side == cfg.passenger_side and abs(px - fcx) > cfg.foreign_dx_ratio * fw
        usage: Usage = "call" if near_face else "hand" if in_hand else "visible"
        return PhoneBoxGeometry(
            box=(round(xyxy[0], 1), round(xyxy[1], 1), round(xyxy[2], 1), round(xyxy[3], 1)),
            score=round(float(box.score), 3),
            near_face=near_face,
            side=side,
            in_hand=in_hand,
            foreign=foreign,
            usage=usage,
        )

    def update(
        self,
        t: float,
        boxes: Sequence[BoxLike] | None,
        *,
        face_box: Box | None = None,
        hands: Sequence[Hand] = (),
        lap_pattern: bool = False,
    ) -> PhoneResult:
        """One frame. ``boxes``: this frame's YOLO class-67 boxes, ``None`` if YOLO did not run on it."""
        t0 = time.perf_counter()
        ran = boxes is not None
        if boxes is not None:
            geoms = [self.geometry(b, face_box, hands) for b in boxes]
            # the driver's phone needs the driver's geometry (plan AS7): near the face or in a hand. A box that is
            # neither (a shoulder / bag read as a phone, a phone lying around) never votes for "in use"
            contact = not self.cfg.owned_needs_contact
            owned = [g for g in geoms if not g.foreign and (g.near_face or g.in_hand or contact)]
            foreign = [g for g in geoms if g.foreign]
            # the driver's phone: near the face first, then in a hand, then the highest score
            best = max(owned, key=lambda g: (g.near_face, g.in_hand, g.score)) if owned else None
            self._votes.append(best)
            self._foreign = max(foreign, key=lambda g: g.score) if foreign else None
        positives = [g for g in self._votes if g is not None]
        voted = positives[-1] if len(positives) >= self.cfg.vote_min else None
        lap = voted is None and lap_pattern
        if voted is not None:
            conf = round(sum(g.score for g in positives) / len(positives), 3)
        else:
            conf = self.cfg.lap_conf if lap else 0.0
        return PhoneResult(
            in_use=voted is not None or lap,
            conf=conf,
            source="detector" if voted is not None else "lap_pattern" if lap else None,
            usage=voted.usage if voted is not None else "lap" if lap else None,
            near_face=voted.near_face if voted is not None else False,
            side=voted.side if voted is not None else None,
            box=voted.box if voted is not None else None,
            foreign=self._foreign is not None,
            foreign_box=self._foreign.box if self._foreign is not None else None,
            votes=len(positives),
            runs=len(self._votes),
            ran=ran,
            ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )

    def reset(self) -> None:
        self._votes.clear()
        self._foreign = None
