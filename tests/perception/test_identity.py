"""FaceIdentifier / FaceGallery / Enroller on synthetic embeddings with fake YuNet + SFace (real models: `models`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from perception.identity import (
    Enroller,
    FaceGallery,
    FaceIdentifier,
    IdentityConfig,
    embedding_path,
    normalize,
    safe_name,
)

H, W = 360, 640
_BASE = {k: normalize(np.random.default_rng(k).normal(size=128)) for k in range(1, 5)}


def frame(person: int, *, sharp: bool = True) -> npt.NDArray[np.uint8]:
    """A frame whose pixel (0, 0) encodes the person (read back by the fake recognizer)."""
    img = np.full((H, W, 3), 100, dtype=np.uint8)
    if sharp:
        img[::2, ::2] = 200  # fine texture: high Laplacian variance on the aligned crop
    img[0, 0] = person
    return img


def row(x: float = 200, y: float = 80, w: float = 180, h: float = 220, score: float = 0.95) -> list[float]:
    lm = [x + 0.3 * w, y + 0.4 * h, x + 0.7 * w, y + 0.4 * h, x + 0.5 * w, y + 0.6 * h, x + 0.35 * w, y + 0.8 * h]
    return [x, y, w, h, *lm, x + 0.65 * w, y + 0.8 * h, score]


class FakeDetector:
    def __init__(self, rows: list[list[float]] | None = None) -> None:
        self.rows = [row()] if rows is None else rows
        self.sizes: list[tuple[int, int]] = []
        self.channels: list[int] = []

    def setInputSize(self, size: tuple[int, int]) -> None:  # OpenCV method name
        self.sizes.append(size)

    def detect(self, image: Any) -> tuple[Any, Any]:
        self.channels.append(image.shape[2] if image.ndim == 3 else 1)
        return 1, (np.array(self.rows, dtype=np.float32) if self.rows else None)


class FakeRecognizer:
    def __init__(self, noise: float = 0.02) -> None:
        self.rng = np.random.default_rng(0)
        self.noise = noise

    def alignCrop(self, image: Any, face: Any) -> Any:  # OpenCV method name
        return image[:112, :112].copy()

    def feature(self, aligned: Any) -> Any:
        person = int(aligned[0, 0, 0])
        return (_BASE[person] + self.noise * self.rng.normal(size=128)).reshape(1, 128)


def identifier(gallery: FaceGallery | None = None, rows: list[list[float]] | None = None) -> FaceIdentifier:
    gallery = gallery if gallery is not None else FaceGallery("driver", {"andrei": _BASE[1], "maria": _BASE[2]})
    return FaceIdentifier(gallery=gallery, detector=FakeDetector(rows), recognizer=FakeRecognizer())


def test_gallery_loads_per_camera_with_fallback(tmp_path: Path) -> None:
    for name, file, vec in (
        ("andrei", "face_driver.npy", _BASE[1]),
        ("maria", "face.npy", _BASE[2]),
        ("ion", "face_passenger.npy", _BASE[3]),
    ):
        (tmp_path / name).mkdir()
        np.save(tmp_path / name / file, vec * 3.0)  # stored unnormalised on purpose
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "face_driver.npy").write_bytes(b"not a npy file")
    driver = FaceGallery.load(tmp_path, "driver")
    assert sorted(driver.embeddings) == ["andrei", "maria"]
    assert driver.fallback == {"maria"}
    assert np.linalg.norm(driver.embeddings["andrei"]) == pytest.approx(1.0)
    passenger = FaceGallery.load(tmp_path, "passenger")
    assert sorted(passenger.embeddings) == ["ion", "maria"]
    assert len(FaceGallery.load(tmp_path / "missing", "driver")) == 0


def test_cosine_threshold_decides_the_match() -> None:
    e1, e2 = np.eye(128, dtype=np.float32)[0], np.eye(128, dtype=np.float32)[1]
    gallery = FaceGallery("driver", {"andrei": e1})
    for cos, expected in ((0.37, "andrei"), (0.35, None)):
        probe = normalize(cos * e1 + np.sqrt(1 - cos**2) * e2)
        name, score = gallery.best(probe)
        assert score == pytest.approx(cos, abs=1e-5)
        matched = name if score is not None and score >= IdentityConfig().cosine_threshold else None
        assert matched == expected


def test_identify_matched_unknown_and_no_gallery() -> None:
    ident = identifier()
    reason, profile, score, _ = ident.identify(frame(1))
    assert reason == "matched" and profile == "andrei" and score is not None and score > 0.9
    reason, profile, _, best = ident.identify(frame(3))
    assert reason == "unknown_face" and profile is None and best in ("andrei", "maria")
    empty = FaceIdentifier(gallery=FaceGallery("driver"), detector=FakeDetector(), recognizer=FakeRecognizer())
    assert empty.identify(frame(1))[0] == "no_gallery"
    assert identifier(rows=[]).identify(frame(1))[0] == "no_face"


def test_largest_face_is_used_and_small_faces_ignored() -> None:
    ident = identifier(rows=[row(w=40, h=50), row(x=300, w=200, h=240)])
    faces = ident.faces(frame(1))
    assert len(faces) == 1 and faces[0].box[2] == 200  # the 40 px face is below min_face_px


def test_mono_frame_is_expanded() -> None:
    ident = identifier()
    grey = frame(1)[:, :, 0].copy()
    ident.identify(grey)
    assert ident.detector.channels == [3]  # type: ignore[attr-defined]


def test_runs_on_new_face_and_every_recheck() -> None:
    ident = identifier()
    r = ident.update(0.0, frame(1), True)
    assert r.ran and r.profile == "andrei" and r.reason == "matched"
    r = ident.update(5.0, frame(2), True)
    assert not r.ran and r.profile == "andrei" and r.reason == "held"
    r = ident.update(10.0, frame(2), True)  # recheck_s
    assert r.ran and r.profile == "maria"
    ident.update(10.5, None, False)
    r = ident.update(10.7, frame(2), True)  # absent 0.2 s < lost_s: same face, not re-run
    assert not r.ran and r.profile == "maria"
    ident.update(11.0, None, False)
    r = ident.update(12.1, None, False)  # absent >= lost_s: identity dropped
    assert r.profile is None
    r = ident.update(12.2, frame(1), True)  # new face: identified at once, long before the next recheck
    assert r.ran and r.profile == "andrei"


def test_yunet_miss_keeps_identity_and_retries_soon() -> None:
    ident = identifier()
    ident.update(0.0, frame(1), True)
    ident.detector.rows = []  # type: ignore[attr-defined]
    r = ident.update(10.0, frame(1), True)
    assert r.ran and r.reason == "no_face" and r.profile == "andrei"
    assert not ident.update(10.5, frame(1), True).ran
    ident.detector.rows = [row()]  # type: ignore[attr-defined]
    r = ident.update(11.0, frame(1), True)  # retry_s
    assert r.ran and r.reason == "matched"


def test_due_without_image_waits() -> None:
    ident = identifier()
    r = ident.update(0.0, None, True)
    assert not r.ran and r.reason == "no_image"
    assert ident.update(0.1, frame(1), True).ran


def test_enroller_rejects_bad_frames_and_saves_the_mean(tmp_path: Path) -> None:
    cfg = IdentityConfig(enroll_frames=10)
    det = FakeDetector()
    ident = FaceIdentifier(cfg, FaceGallery("driver"), detector=det, recognizer=FakeRecognizer())
    enr = Enroller(ident)
    det.rows = []
    assert enr.offer(0.0, frame(1)).reason == "no_face"
    det.rows = [row(), row(x=420)]
    assert enr.offer(0.3, frame(1)).reason == "multiple_faces"
    det.rows = [row(w=100, h=120)]
    assert enr.offer(0.6, frame(1)).reason == "too_small"
    det.rows = [row()]
    blurred = enr.offer(0.9, frame(1, sharp=False))
    assert blurred.reason == "blurred" and blurred.sharpness is not None and blurred.sharpness < 40.0
    assert enr.offer(1.2, frame(1)).accepted
    assert enr.offer(1.3, frame(1)).reason == "too_soon"
    t = 1.5
    while not enr.done:
        enr.offer(t, frame(1))
        t += 0.25
    assert enr.offer(t, frame(1)).reason == "done"
    result = enr.finish()
    assert result.frames == 10 and result.consistency > 0.9
    assert float(np.dot(result.embedding, _BASE[1])) > 0.99
    path = Enroller.save(tmp_path, "Andrei", "driver", result.embedding)
    assert path == tmp_path / "andrei" / "face_driver.npy"
    assert FaceGallery.load(tmp_path, "driver").best(_BASE[1])[0] == "andrei"


def test_enrollment_of_two_people_fails() -> None:
    ident = FaceIdentifier(
        IdentityConfig(enroll_frames=4), FaceGallery("driver"), detector=FakeDetector(), recognizer=FakeRecognizer(0.0)
    )
    enr = Enroller(ident)
    for i, person in enumerate((1, 2, 3, 4)):
        assert enr.offer(i * 0.5, frame(person)).accepted
    with pytest.raises(ValueError, match="disagree"):
        enr.finish()


def test_finish_needs_enough_frames() -> None:
    with pytest.raises(ValueError, match="good frames"):
        Enroller(identifier()).finish()


def test_names_and_paths_are_safe(tmp_path: Path) -> None:
    assert safe_name(" Andrei ") == "andrei"
    for bad in ("", "../etc", "a/b", "a b", "-x", "x" * 40):
        with pytest.raises(ValueError):
            safe_name(bad)
    with pytest.raises(ValueError):
        embedding_path(tmp_path, "andrei", "rear")
    with pytest.raises(ValueError):
        normalize(np.zeros(128))


@pytest.mark.models
@pytest.mark.slow
def test_real_yunet_sface_on_a_black_frame() -> None:
    cfg = IdentityConfig()
    if not (cfg.path(cfg.yunet_model).exists() and cfg.path(cfg.sface_model).exists()):
        pytest.skip("YuNet / SFace not downloaded")
    ident = FaceIdentifier(cfg, FaceGallery("driver", {"x": _BASE[1]}))
    r = ident.update(0.0, np.zeros((480, 640, 3), dtype=np.uint8), True)
    assert r.ran and r.reason == "no_face" and r.profile is None
