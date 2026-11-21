"""Who is on the seat (AS10 driver / AP1 passenger): OpenCV YuNet + SFace, per-camera embeddings.

Standalone module: configuration in :class:`IdentityConfig` (defaults = ``perception/config/pending/modules.yaml``,
section ``identity``), input = a camera frame (BGR or mono) + timestamp (+ whether the Face Landmarker sees a face),
output = :class:`IdentityResult`. Face Landmarker never identifies people (R-FL5); this module does, alone.

* ``cv2.FaceDetectorYN`` finds the face (largest box), ``cv2.FaceRecognizerSF.alignCrop`` aligns it on the five
  landmarks, ``feature`` gives the 128-d embedding, L2-normalised. Cosine similarity (= SFace ``FR_COSINE``) against
  the gallery, match if >= ``cosine_threshold`` (0.363, OpenCV's value).
* **Embeddings per camera**: ``profiles/<name>/face_<camera>.npy``. The two cameras differ in optics, angle and
  light, so a driver-camera embedding is not compared with a passenger-camera frame. ``face.npy`` (the older,
  camera-less name) is used as a fallback and reported in ``FaceGallery.fallback``.
* When: on a **new face** (absent for ``lost_s``, then present), every ``recheck_s`` (~10 s) while it stays, and after
  ``retry_s`` when YuNet missed a face the Face Landmarker sees. In between the last identity is held.
* :class:`Enroller`: ``enroll_frames`` good frames (exactly one face, YuNet score, size, sharpness, spacing) ->
  mean of the normalised embeddings, re-normalised; every frame must agree with the mean (``enroll_min_consistency``).

Embeddings are biometric data: they stay on the laptop (``profiles/*/face*.npy`` is gitignored).
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal, Protocol

import cv2
import numpy as np
import numpy.typing as npt

from perception.config import REPO_ROOT
from perception.hands import as_bgr

__all__ = [
    "CAMERAS",
    "EnrollResult",
    "EnrollStep",
    "Enroller",
    "FaceGallery",
    "FaceIdentifier",
    "IdentityConfig",
    "IdentityResult",
    "YuNetFace",
    "embedding_path",
    "normalize",
    "safe_name",
]

CAMERAS = ("driver", "passenger")
Embedding = npt.NDArray[np.float32]
Reason = Literal["matched", "unknown_face", "no_face", "no_gallery", "held", "no_image"]
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


class Detector(Protocol):
    def setInputSize(self, size: tuple[int, int]) -> None: ...  # OpenCV API name
    def detect(self, image: Any) -> tuple[Any, Any]: ...


class Recognizer(Protocol):
    def alignCrop(self, image: Any, face: Any) -> Any: ...  # OpenCV API name
    def feature(self, aligned: Any) -> Any: ...


@dataclass(frozen=True)
class IdentityConfig:
    yunet_model: str = "perception/models/face_detection_yunet_2023mar.onnx"
    sface_model: str = "perception/models/face_recognition_sface_2021dec.onnx"
    cosine_threshold: float = 0.363
    score_threshold: float = 0.80
    nms_threshold: float = 0.30
    top_k: int = 50
    min_face_px: float = 60.0
    recheck_s: float = 10.0
    retry_s: float = 1.0
    lost_s: float = 1.0
    enroll_frames: int = 10
    enroll_interval_s: float = 0.2
    enroll_min_face_px: float = 120.0
    enroll_min_sharpness: float = 40.0
    enroll_min_consistency: float = 0.5

    def __post_init__(self) -> None:
        if not -1.0 < self.cosine_threshold < 1.0:
            raise ValueError("identity.cosine_threshold must be in (-1, 1)")
        if not 0.0 <= self.score_threshold <= 1.0 or not 0.0 <= self.nms_threshold <= 1.0:
            raise ValueError("identity YuNet thresholds must be in [0, 1]")
        if min(self.recheck_s, self.retry_s, self.lost_s) <= 0 or self.enroll_interval_s < 0:
            raise ValueError("identity times must be > 0")
        if not 1 <= self.enroll_frames <= 100 or self.top_k < 1:
            raise ValueError("identity.enroll_frames must be 1..100 and top_k >= 1")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> IdentityConfig:
        unknown = sorted(set(data) - {f.name for f in fields(cls)})
        if unknown:
            raise ValueError(f"IdentityConfig: unknown keys {unknown}")
        return cls(**data)

    def path(self, name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else REPO_ROOT / p


def normalize(vector: npt.ArrayLike) -> Embedding:
    v = np.asarray(vector, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    if n <= 0 or not np.isfinite(n):
        raise ValueError("embedding has zero / invalid norm")
    return np.asarray(v / n, dtype=np.float32)


def safe_name(name: str) -> str:
    """Profile name -> directory name: lower case letters, digits, '-' and '_' only (no paths)."""
    lowered = name.strip().lower()
    if not _NAME.fullmatch(lowered):
        raise ValueError("profile name: 1-32 letters, digits, '-' or '_', starting with a letter or digit")
    return lowered


def embedding_path(profiles_dir: Path, name: str, camera: str) -> Path:
    if camera not in CAMERAS:
        raise ValueError(f"camera must be one of {CAMERAS}")
    return profiles_dir / safe_name(name) / f"face_{camera}.npy"


# --- gallery --------------------------------------------------------------------------------------------


class FaceGallery:
    """Enrolled embeddings of ONE camera: ``{profile: unit vector}``."""

    def __init__(self, camera: str, embeddings: Mapping[str, npt.ArrayLike] | None = None) -> None:
        if camera not in CAMERAS:
            raise ValueError(f"camera must be one of {CAMERAS}")
        self.camera = camera
        self.embeddings: dict[str, Embedding] = {k: normalize(v) for k, v in (embeddings or {}).items()}
        self.fallback: set[str] = set()  # profiles loaded from the camera-less face.npy

    @classmethod
    def load(cls, profiles_dir: Path, camera: str) -> FaceGallery:
        gallery = cls(camera)
        if not profiles_dir.is_dir():
            return gallery
        for d in sorted(p for p in profiles_dir.iterdir() if p.is_dir()):
            per_camera, generic = d / f"face_{camera}.npy", d / "face.npy"
            path = per_camera if per_camera.is_file() else generic if generic.is_file() else None
            if path is None:
                continue
            try:
                gallery.embeddings[d.name] = normalize(np.load(path, allow_pickle=False))
            except (ValueError, OSError):
                continue  # unreadable / empty file: that profile is skipped, the others still work
            if path is generic:
                gallery.fallback.add(d.name)
        return gallery

    def __len__(self) -> int:
        return len(self.embeddings)

    def similarities(self, embedding: Embedding) -> dict[str, float]:
        return {name: float(np.dot(ref, embedding)) for name, ref in self.embeddings.items()}

    def best(self, embedding: Embedding) -> tuple[str | None, float | None]:
        sims = self.similarities(embedding)
        if not sims:
            return None, None
        name = max(sims, key=lambda k: sims[k])
        return name, sims[name]


# --- detection + recognition ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class YuNetFace:
    row: npt.NDArray[np.float32]  # the raw YuNet row (x, y, w, h, 5 landmarks, score), needed by alignCrop

    @property
    def box(self) -> tuple[float, float, float, float]:
        x, y, w, h = (float(v) for v in self.row[:4])
        return x, y, w, h

    @property
    def score(self) -> float:
        return float(self.row[14])


@dataclass(frozen=True, slots=True)
class IdentityResult:
    profile: str | None = None  # matched profile (held between runs)
    score: float | None = None  # cosine similarity of the last run's best profile
    best: str | None = None  # best profile of the last run even below the threshold (debug)
    ran: bool = False  # YuNet + SFace ran on this frame
    reason: Reason = "held"
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FaceIdentifier:
    """YuNet + SFace for one camera.

    Args:
        cfg: module configuration.
        gallery: enrolled embeddings of this camera (``FaceGallery.load(profiles_dir, camera)``).
        detector / recognizer: OpenCV objects (or test fakes); created from the config files when omitted.
    """

    def __init__(
        self,
        cfg: IdentityConfig | None = None,
        gallery: FaceGallery | None = None,
        *,
        camera: str = "driver",
        detector: Detector | None = None,
        recognizer: Recognizer | None = None,
    ) -> None:
        self.cfg = cfg or IdentityConfig()
        self.gallery = gallery if gallery is not None else FaceGallery(camera)
        self.camera = self.gallery.camera
        self._detector = detector
        self._recognizer = recognizer
        self._input_size: tuple[int, int] | None = None
        self._last_run: float | None = None
        self._last_reason: Reason = "held"
        self._absent_since: float | None = None
        self._profile: str | None = None
        self._score: float | None = None
        self._best: str | None = None

    # --- models ------------------------------------------------------------------------------------------

    @property
    def detector(self) -> Detector:
        if self._detector is None:
            cfg = self.cfg
            self._detector = cv2.FaceDetectorYN.create(
                str(cfg.path(cfg.yunet_model)), "", (320, 320), cfg.score_threshold, cfg.nms_threshold, cfg.top_k
            )
        return self._detector

    @property
    def recognizer(self) -> Recognizer:
        if self._recognizer is None:
            self._recognizer = cv2.FaceRecognizerSF.create(str(self.cfg.path(self.cfg.sface_model)), "")
        return self._recognizer

    def faces(self, image: npt.NDArray[np.uint8]) -> list[YuNetFace]:
        """YuNet faces at least ``min_face_px`` wide, largest first."""
        h, w = image.shape[:2]
        if self._input_size != (w, h):
            self.detector.setInputSize((w, h))
            self._input_size = (w, h)
        _, rows = self.detector.detect(image)
        if rows is None:
            return []
        faces = [YuNetFace(np.asarray(r, dtype=np.float32)) for r in rows]
        faces = [f for f in faces if f.box[2] >= self.cfg.min_face_px and f.score >= self.cfg.score_threshold]
        return sorted(faces, key=lambda f: f.box[2] * f.box[3], reverse=True)

    def aligned(self, image: npt.NDArray[np.uint8], face: YuNetFace) -> npt.NDArray[np.uint8]:
        return np.asarray(self.recognizer.alignCrop(image, face.row), dtype=np.uint8)

    def embed_aligned(self, aligned: npt.NDArray[np.uint8]) -> Embedding:
        return normalize(self.recognizer.feature(aligned))

    def identify(self, image: npt.NDArray[np.uint8]) -> tuple[Reason, str | None, float | None, str | None]:
        """One run: (reason, matched profile, best score, best profile)."""
        bgr = as_bgr(image)
        faces = self.faces(bgr)
        if not faces:
            return "no_face", None, None, None
        if not self.gallery:
            return "no_gallery", None, None, None
        emb = self.embed_aligned(self.aligned(bgr, faces[0]))
        best, score = self.gallery.best(emb)
        if best is not None and score is not None and score >= self.cfg.cosine_threshold:
            return "matched", best, score, best
        return "unknown_face", None, score, best

    # --- scheduling --------------------------------------------------------------------------------------

    def update(self, t: float, image: npt.NDArray[np.uint8] | None, face_present: bool | None = None) -> IdentityResult:
        """Call on every frame; runs the models only when due. ``face_present`` = Face Landmarker sees a face
        (``None``: unknown, rely on YuNet alone)."""
        t0 = time.perf_counter()
        cfg = self.cfg
        if face_present is False:
            self._absent_since = self._absent_since if self._absent_since is not None else t
            if t - self._absent_since >= cfg.lost_s:
                self._profile, self._score, self._best = None, None, None
            return self._result(False, "held", t0)
        new_face = self._last_run is None or (self._absent_since is not None and t - self._absent_since >= cfg.lost_s)
        self._absent_since = None
        due = (
            new_face
            or self._last_run is None
            or t - self._last_run >= cfg.recheck_s
            or (self._last_reason == "no_face" and t - self._last_run >= cfg.retry_s)
        )
        if not due:
            return self._result(False, "held", t0)
        if image is None:
            return self._result(False, "no_image", t0)
        reason, profile, score, best = self.identify(image)
        self._last_run, self._last_reason = t, reason
        if reason == "no_face" and not new_face:
            pass  # YuNet missed a face the landmarker sees: keep the identity, retry after retry_s
        else:
            self._profile, self._score, self._best = profile, score, best
        return self._result(True, reason, t0)

    def _result(self, ran: bool, reason: Reason, t0: float) -> IdentityResult:
        return IdentityResult(
            profile=self._profile,
            score=round(self._score, 4) if self._score is not None else None,
            best=self._best,
            ran=ran,
            reason=reason,
            ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )


# --- enrollment -----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnrollStep:
    accepted: bool
    reason: str  # "ok", "no_face", "multiple_faces", "low_score", "too_small", "blurred", "too_soon", "done"
    count: int
    needed: int
    sharpness: float | None = None


@dataclass(frozen=True, slots=True)
class EnrollResult:
    embedding: Embedding
    frames: int
    consistency: float  # minimum cosine of a frame to the mean


class Enroller:
    """Collects ``enroll_frames`` good frames of one person on one camera."""

    def __init__(self, identifier: FaceIdentifier) -> None:
        self.identifier = identifier
        self.cfg = identifier.cfg
        self.embeddings: list[Embedding] = []
        self._last_t: float | None = None

    @property
    def done(self) -> bool:
        return len(self.embeddings) >= self.cfg.enroll_frames

    def offer(self, t: float, image: npt.NDArray[np.uint8]) -> EnrollStep:
        cfg, need = self.cfg, self.cfg.enroll_frames

        def step(ok: bool, reason: str, sharp: float | None = None) -> EnrollStep:
            return EnrollStep(ok, reason, len(self.embeddings), need, sharp)

        if self.done:
            return step(False, "done")
        if self._last_t is not None and t - self._last_t < cfg.enroll_interval_s:
            return step(False, "too_soon")
        bgr = as_bgr(image)
        faces = self.identifier.faces(bgr)
        if not faces:
            return step(False, "no_face")
        if len(faces) > 1:
            return step(False, "multiple_faces")
        face = faces[0]
        if face.score < cfg.score_threshold:
            return step(False, "low_score")
        if face.box[2] < cfg.enroll_min_face_px:
            return step(False, "too_small")
        aligned = self.identifier.aligned(bgr, face)
        grey = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY) if aligned.ndim == 3 else aligned
        sharpness = float(cv2.Laplacian(grey, cv2.CV_64F).var())
        if sharpness < cfg.enroll_min_sharpness:
            return step(False, "blurred", round(sharpness, 1))
        self.embeddings.append(self.identifier.embed_aligned(aligned))
        self._last_t = t
        return step(True, "ok", round(sharpness, 1))

    def finish(self) -> EnrollResult:
        if not self.done:
            raise ValueError(f"need {self.cfg.enroll_frames} good frames, have {len(self.embeddings)}")
        mean = normalize(np.mean(np.stack(self.embeddings), axis=0))
        consistency = min(float(np.dot(e, mean)) for e in self.embeddings)
        if consistency < self.cfg.enroll_min_consistency:
            raise ValueError(
                f"enrollment frames disagree (min cosine to the mean {consistency:.2f} < "
                f"{self.cfg.enroll_min_consistency}): one person only, face the camera"
            )
        return EnrollResult(mean, len(self.embeddings), round(consistency, 4))

    @staticmethod
    def save(profiles_dir: Path, name: str, camera: str, embedding: Embedding) -> Path:
        path = embedding_path(profiles_dir, name, camera)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, normalize(embedding), allow_pickle=False)
        return path
