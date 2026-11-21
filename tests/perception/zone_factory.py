"""Synthetic gaze-zone FeatureFrames: head pose + MobileGaze + iris + eyeLook per zone and mode (no models)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import numpy as np

from perception.calibration import Calibration, CalibrationRun
from perception.config import PerceptionConfig
from perception.driver_cam.gaze_model import GAZE_SIGNS
from perception.driver_cam.pipeline import DriverPipeline
from perception.features import FeatureFrame, GazeFeatures
from tests.perception.driver_factory import FPS, H, W, face, rotation_matrix

# zone -> mode -> (head yaw, head pitch, gaze yaw, gaze pitch, iris x, iris y), driver convention (left / up > 0)
PROTOTYPES: dict[str, dict[str, tuple[float, float, float, float, float, float]]] = {
    "road": {"owl": (0, 0, 0, 0, 0.0, 0.0), "lizard": (0, 0, 0, 0, 0.0, 0.0)},
    "mirror_left": {"owl": (35, -5, 45, -5, 0.08, 0.0), "lizard": (6, -2, 38, -5, 0.28, 0.0)},
    "mirror_right": {"owl": (-50, -8, -58, -8, -0.08, 0.0), "lizard": (-8, -3, -45, -8, -0.3, 0.0)},
    "mirror_rear": {"owl": (-22, 14, -28, 16, -0.05, 0.08), "lizard": (-4, 3, -24, 14, -0.18, 0.12)},
    "cluster": {"owl": (0, -18, 0, -24, 0.0, -0.06), "lizard": (0, -4, 0, -20, 0.0, -0.18)},
    "infotainment": {"owl": (-25, -24, -30, -28, -0.06, -0.06), "lizard": (-5, -6, -26, -24, -0.2, -0.16)},
    "lap": {"owl": (0, -38, 0, -45, 0.0, -0.08), "lizard": (0, -10, 0, -36, 0.0, -0.25)},
    "passenger": {"owl": (-52, -28, -60, -34, -0.08, -0.05), "lizard": (-12, -8, -48, -30, -0.3, -0.15)},
}
ZONES = list(PROTOTYPES)


def zone_frame(
    i: int,
    zone: str,
    mode: str = "owl",
    rng: np.random.Generator | None = None,
    *,
    noise: float = 1.0,
    fps: float = FPS,
    width_px: float = 300.0,
    closed: bool = False,
    offset: tuple[float, float] = (0.0, 0.0),
) -> FeatureFrame:
    """One frame looking at ``zone``; ``noise`` scales the per-feature jitter, ``offset`` shifts head yaw / pitch."""
    rng = rng or np.random.default_rng(i)
    hy, hp, gy, gp, ix, iy = PROTOTYPES[zone][mode]
    n = rng.normal(0.0, 1.0, 6) * noise
    hy, hp = hy + offset[0] + 0.7 * n[0], hp + offset[1] + 0.7 * n[1]
    gy, gp = gy + offset[0] + 2.0 * n[2], gp + offset[1] + 2.0 * n[3]
    ix, iy = ix + 0.01 * n[4], iy + 0.01 * n[5]
    look = {
        "eyeLookOutLeft": max(0.0, ix) * 2,
        "eyeLookInRight": max(0.0, ix) * 2,
        "eyeLookInLeft": max(0.0, -ix) * 2,
        "eyeLookOutRight": max(0.0, -ix) * 2,
        "eyeLookUpLeft": max(0.0, iy) * 2,
        "eyeLookUpRight": max(0.0, iy) * 2,
        "eyeLookDownLeft": max(0.0, -iy) * 2,
        "eyeLookDownRight": max(0.0, -iy) * 2,
    }
    f = face(
        0.05 if closed else 0.30,
        blink=0.9 if closed else 0.05,
        width_px=width_px,
        matrix=rotation_matrix(pitch=-hp, yaw=hy),  # raw rotations; AXIS_SIGNS: pitch -1, yaw +1
        iris=(ix, iy),
        eye_look=look,
    )
    raw = GazeFeatures(yaw_deg=round(gy / GAZE_SIGNS["yaw"], 2), pitch_deg=round(gp / GAZE_SIGNS["pitch"], 2))
    return FeatureFrame(t=round(i / fps, 6), frame_id=i + 1, camera="driver", face=f, gaze=raw)


def zone_frames(
    spec: Sequence[tuple[str, str, float]],
    seed: int = 0,
    *,
    noise: float = 1.0,
    fps: float = FPS,
    start: int = 0,
) -> Iterator[tuple[FeatureFrame, str, str]]:
    """``spec`` = [(zone, mode, seconds), ...] -> (frame, zone, mode)."""
    rng = np.random.default_rng(seed)
    i = start
    for zone, mode, seconds in spec:
        for _ in range(round(seconds * fps)):
            yield zone_frame(i, zone, mode, rng, noise=noise, fps=fps), zone, mode
            i += 1


def calibrate_synthetic(
    cfg: PerceptionConfig, seed: int = 0, *, noise: float = 1.0, name: str = "synthetic", quick: bool = False
) -> tuple[Calibration, CalibrationRun]:
    """Run the real CalibrationRun + DriverPipeline on synthetic frames that follow the prompts."""
    pipeline = DriverPipeline(cfg, (W, H))
    run = CalibrationRun(cfg, (W, H), name, quick=quick)
    rng = np.random.default_rng(seed)
    i = 0
    while not run.done:
        step = run.current
        assert step is not None
        zone, mode = (step.zone, step.mode or "owl") if step.zone is not None else ("road", "owl")
        ff = zone_frame(i, zone, mode, rng, noise=noise)
        run.update(ff, pipeline.update(ff))
        i += 1
    return run.result(), run
