from __future__ import annotations

import random
import statistics
from types import SimpleNamespace

import pytest

from perception.config import load_config
from perception.driver_cam.face import face_box_px, face_from_landmarks
from perception.driver_cam.head import HeadTracker, euler_from_matrix
from perception.driver_cam.mouth import MouthTracker
from perception.features import LANDMARK_GROUPS, REQUIRED_BLENDSHAPES
from tests.perception.driver_factory import FPS, H, W, face, frames, rotation_matrix

# --- head ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"yaw": 20}, {"yaw": 20}),  # face normal rotates towards image right = driver's left
        ({"pitch": -15}, {"pitch": 15}),  # face normal rotates towards +y = head up
        ({"roll": -10}, {"roll": 10}),  # head top towards image right = driver's left shoulder
    ],
)
def test_axis_signs_driver_convention(raw: dict[str, float], expected: dict[str, float]) -> None:
    pitch, yaw, roll = euler_from_matrix(rotation_matrix(**raw))
    got = {"pitch": pitch, "yaw": yaw, "roll": roll}
    for axis in ("pitch", "yaw", "roll"):
        assert got[axis] == pytest.approx(expected.get(axis, 0.0), abs=1e-6)


def test_angles_are_steady_when_still() -> None:
    cfg = load_config()
    head = HeadTracker(cfg.head, cfg.filters)
    rng = random.Random(0)
    yaws = []
    for i in range(150):
        m = rotation_matrix(yaw=5 + rng.gauss(0, 0.6), pitch=rng.gauss(0, 0.6))
        yaws.append(head.update(i / FPS, m, eyes_closing=False).yaw)
    assert statistics.pstdev([y for y in yaws[30:] if y is not None]) < 0.5  # input noise 0.6 deg -> filtered


def test_nodding_needs_closing_eyes() -> None:
    cfg = load_config()

    def run(closing: bool) -> bool:
        head = HeadTracker(cfg.head, cfg.filters)
        nod = False
        for i in range(60):  # pitch 0 deg for 1 s, then drops to -25 deg over 0.5 s
            t = i / FPS
            pitch_up = 0.0 if t < 1.0 else -25.0 * min(1.0, (t - 1.0) / 0.5)
            out = head.update(t, rotation_matrix(pitch=-pitch_up), eyes_closing=closing)  # raw sign is inverted
            nod = nod or out.nodding
        return nod

    assert run(closing=True) is True
    assert run(closing=False) is False


# --- mouth ---------------------------------------------------------------------------------------------


def _mouth() -> MouthTracker:
    cfg = load_config()
    return MouthTracker(cfg.yawn, cfg.speaking, (W, H))


def test_yawn_after_min_duration() -> None:
    m = _mouth()
    outs = [m.update(ff.t, ff.face) for ff in frames([(1.0, {}), (2.5, {"jaw": 0.8, "lip_gap": 0.25}), (1.0, {})])]
    yawn_frames = [i for i, o in enumerate(outs) if o.yawn]
    assert yawn_frames, "a 2.5 s jaw opening is a yawn"
    assert yawn_frames[0] / FPS == pytest.approx(1.0 + 1.5, abs=0.1)  # reported after min_duration_s
    assert not any(o.speaking for o in outs)  # a yawn is not speech
    assert [e.kind for e in m.events] == ["yawn"]


def test_short_jaw_opening_is_not_a_yawn() -> None:
    m = _mouth()
    outs = [m.update(ff.t, ff.face) for ff in frames([(1.0, {}), (1.0, {"jaw": 0.8}), (1.0, {})])]
    assert not any(o.yawn for o in outs)


def test_speaking_from_lip_oscillation() -> None:
    m = _mouth()
    spec: list[tuple[float, dict[str, object]]] = [(1.0, {})]
    for k in range(30):  # ~4 syllables per second: gap alternates 0.01 / 0.06
        spec.append((0.12, {"lip_gap": 0.06 if k % 2 else 0.01, "jaw": 0.15}))
    spec.append((1.5, {}))
    outs = [m.update(ff.t, ff.face) for ff in frames(spec)]
    talking = outs[round(1.8 * FPS) : round(4.4 * FPS)]
    assert sum(o.speaking for o in talking) / len(talking) > 0.9
    assert not outs[-1].speaking  # quiet again after the window
    assert not any(o.yawn for o in outs)


# --- face (R-FL3) --------------------------------------------------------------------------------------


def _points(width_px: float) -> list[SimpleNamespace]:
    pts = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(478)]
    oval = LANDMARK_GROUPS["face_oval"]
    for k, i in enumerate(oval):
        frac = k / (len(oval) - 1)
        pts[i] = SimpleNamespace(x=(640 - width_px / 2 + width_px * frac) / W, y=0.3 + 0.3 * frac, z=0.0)
    return pts


def test_face_width_below_threshold_is_too_small() -> None:
    blend = {name: 0.1 for name in REQUIRED_BLENDSHAPES}
    small, _ = face_from_landmarks(_points(180), blend, [1.0] * 16, W, H, 250)
    big, box = face_from_landmarks(_points(320), blend, [1.0] * 16, W, H, 250)
    assert small.too_small and small.width_px == pytest.approx(180, abs=0.5)
    assert small.conf == pytest.approx(180 / 250, abs=0.01)
    assert not big.too_small and big.conf == 1.0
    assert box[2] == pytest.approx(320, abs=0.5)


def test_face_box_from_feature_frame() -> None:
    box = face_box_px(face(), W, H)
    assert box is not None and box[3] > 0
    assert face_box_px(face().model_copy(update={"present": False, "landmarks": None}), W, H) is None


def test_num_faces_other_than_one_is_refused() -> None:
    from perception.driver_cam.face import FaceLandmarkerModel

    cfg = load_config()
    bad = cfg.model_copy(update={"face": cfg.face.model_construct(**{**cfg.face.model_dump(), "num_faces": 2})})
    with pytest.raises(ValueError, match="R-FL1"):
        FaceLandmarkerModel(bad)
