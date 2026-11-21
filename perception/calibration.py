"""Per-driver gaze calibration (AS5): owl + lizard samples per zone -> ``profiles/<name>/calibration.json``.

docs/perception.md §3.4. One non-blocking state machine (:class:`CalibrationRun`) drives both ``scripts/calibrate.py``
and the ``calibrate`` command from core (run inside the driver camera worker):

* for each zone (``gaze.zones``): **owl** (turn the head) then **lizard** (eyes only, head to the road), each
  ``calibration.s_per_zone`` seconds; ``road`` gets ``road_factor`` x the data; ``passenger`` = the passenger's hands;
* "back to the road" (``transition_s``, not recorded) between steps; the first ``discard_s`` after every prompt is
  dropped (reaction time);
* frames the feature builder rejects (R-FL2 low confidence, R-FL3 face too small, no gaze, unreliable eyes) and frames
  with the eyes closed are not used; squinted eyes (R-FL4) are;
* a step with fewer than ``min_samples_per_zone`` samples is repeated once; still short -> reported as missing;
* the result keeps the raw samples, so a later yaml change (k, weights, reject factor) is applied on load without
  recalibrating; plus the blocked-LOO confusion matrix, the open-eye EAR baseline from the road samples (p90 per eye)
  and a per-zone EAR reference (stored for ``EarReference.get(side, zone)``, not used yet);
* quick recalibration (~15 s): only ``calibration.quick_zones`` (road + mirrors), merged into the existing profile.

The calibration file holds per-person features (not images); ``profiles/*/calibration.json`` is gitignored.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from perception.config import REPO_ROOT, PerceptionConfig
from perception.driver_cam.gaze_zones import FEATURES, GazeFeatureBuilder, ZoneModel, zone_head_angles
from perception.driver_cam.pipeline import DriverState
from perception.features import FeatureFrame
from perception.posture import PostureRef, face_geometry

__all__ = [
    "CALIBRATION_VERSION",
    "PROFILES_DIR",
    "CalibPrompt",
    "CalibStep",
    "Calibration",
    "CalibrationRun",
    "build_steps",
    "profile_path",
]

CALIBRATION_VERSION = 1
PROFILES_DIR = REPO_ROOT / "profiles"
WATCHED_CONFUSIONS = (("road", "mirror_left"), ("passenger", "mirror_right"))

ZONE_PROMPTS = {
    "road": "DRUM: priveste inainte, prin parbriz",
    "mirror_left": "OGLINDA STANGA",
    "mirror_right": "OGLINDA DREAPTA",
    "mirror_rear": "RETROVIZOR (oglinda din mijloc)",
    "cluster": "BORD (vitezometrul)",
    "infotainment": "ECRAN (infotainment)",
    "lap": "POALA (unde ar sta telefonul)",
    "passenger": "MAINILE PASAGERULUI",
}
MODE_PROMPTS = {"owl": "intoarce CAPUL", "lizard": "doar cu OCHII, capul spre drum"}


def profile_path(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("profile name: letters, digits, '-' or '_' only")
    return PROFILES_DIR / name / "calibration.json"


@dataclass(frozen=True)
class CalibStep:
    zone: str | None  # None = transition (not recorded)
    mode: str | None
    prompt: str
    duration_s: float
    segment: int = -1


@dataclass
class CalibPrompt:
    step: int
    steps: int
    zone: str | None
    mode: str | None
    text: str
    remaining_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "steps": self.steps,
            "zone": self.zone,
            "mode": self.mode,
            "text": self.text,
            "remaining_s": round(self.remaining_s, 1),
        }


def build_steps(cfg: PerceptionConfig, quick: bool = False) -> list[CalibStep]:
    c = cfg.gaze.calibration
    zones = list(c.quick_zones) if quick else list(cfg.gaze.zones)
    seconds = c.quick_s_per_zone if quick else c.s_per_zone
    transition = c.quick_transition_s if quick else c.transition_s
    steps: list[CalibStep] = []
    segment = 0
    for zone in zones:
        modes = ["owl"] if zone == "road" else list(c.modes)
        for mode in modes:
            if steps:
                steps.append(CalibStep(None, None, "Inapoi la DRUM", transition))
            duration = seconds * (c.road_factor if zone == "road" else 1.0)
            text = ZONE_PROMPTS[zone] if zone == "road" else f"{ZONE_PROMPTS[zone]} - {MODE_PROMPTS[mode]}"
            steps.append(CalibStep(zone, mode, text, duration, segment))
            segment += 1
    return steps


@dataclass
class Calibration:
    name: str
    samples: np.ndarray
    zones: list[str]
    modes: list[str]
    segments: list[int]
    times: list[float]
    model: ZoneModel
    ear_baseline: tuple[float, float] | None = None
    ear_ref_by_zone: dict[str, tuple[float, float]] = field(default_factory=dict)
    posture_ref: dict[str, float] | None = None  # median face centre / width / angles on the road (posture.py)
    camera: dict[str, Any] = field(default_factory=dict)
    created: str = ""
    missing: list[str] = field(default_factory=list)

    # --- quality --------------------------------------------------------------------------------------------

    def loo_confusion(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for true, pred in zip(self.zones, self.model.loo_zones, strict=True):
            row = out.setdefault(true, {})
            row[pred] = row.get(pred, 0) + 1
        return out

    def loo_accuracy(self) -> dict[str, float | None]:
        acc: dict[str, float | None] = {}
        for mode in ("owl", "lizard", "all"):
            idx = [i for i, m in enumerate(self.modes) if mode in ("all", m)]
            acc[mode] = round(sum(self.model.loo_zones[i] == self.zones[i] for i in idx) / len(idx), 4) if idx else None
        return acc

    def warnings(self, owl_min_head_deg: float = 0.0) -> list[str]:
        conf = self.loo_confusion()
        out = [f"zone without enough samples: {z}" for z in self.missing]
        for a, b in WATCHED_CONFUSIONS:
            n = conf.get(a, {}).get(b, 0) + conf.get(b, {}).get(a, 0)
            if n:
                out.append(f"{a} <-> {b}: {n} LOO confusions (recalibrate, or move the {b} target)")
        road = self._owl_head("road")
        if owl_min_head_deg > 0 and road is not None:
            for zone in dict.fromkeys(self.zones):
                head = self._owl_head(zone)
                if zone == "road" or head is None:
                    continue
                moved = float(np.hypot(head[0] - road[0], head[1] - road[1]))
                if moved < owl_min_head_deg:
                    out.append(
                        f"{zone}: the head moved only {moved:.0f} deg from the road in the OWL step (need "
                        f"{owl_min_head_deg:.0f}): recalibrate and turn the head towards the target"
                    )
        return out

    def _owl_head(self, zone: str) -> tuple[float, float] | None:
        """Median head (yaw, pitch) of the zone's OWL samples (head turned to the target), None without any."""
        idx = [i for i, (z, m) in enumerate(zip(self.zones, self.modes, strict=True)) if z == zone and m == "owl"]
        if not idx:
            return None
        med = np.median(self.samples[idx, :2], axis=0)
        return float(med[0]), float(med[1])

    # --- (de)serialisation -------------------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CALIBRATION_VERSION,
            "name": self.name,
            "created": self.created,
            "camera": self.camera,
            "features": list(FEATURES),
            "samples": np.round(self.samples, 5).tolist(),
            "zones": self.zones,
            "modes": self.modes,
            "segments": self.segments,
            "times": [round(v, 3) for v in self.times],
            "model": self.model.to_dict(),
            "ear_baseline": list(self.ear_baseline) if self.ear_baseline else None,
            "ear_ref_by_zone": {z: list(v) for z, v in self.ear_ref_by_zone.items()},
            "posture_ref": self.posture_ref,
            "loo_accuracy": self.loo_accuracy(),
            "loo_confusion": self.loo_confusion(),
            "missing": self.missing,
        }

    def save(self, path: Path | None = None) -> Path:
        path = path or profile_path(self.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")
        return path

    @classmethod
    def from_samples(
        cls,
        cfg: PerceptionConfig,
        name: str,
        samples: Sequence[Sequence[float]] | np.ndarray,
        zones: Sequence[str],
        modes: Sequence[str],
        segments: Sequence[int],
        times: Sequence[float],
        **extra: Any,
    ) -> Calibration:
        x = np.asarray(samples, dtype=np.float64)
        model = ZoneModel.fit(x, zones, segments, cfg, times)
        return cls(name, x, list(zones), list(modes), list(segments), list(times), model, **extra)

    @classmethod
    def load(cls, cfg: PerceptionConfig, path: Path) -> Calibration:
        """Load and **re-fit** with the current yaml (k, weights, reject factor apply without recalibrating)."""
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != CALIBRATION_VERSION or data.get("features") != list(FEATURES):
            raise ValueError(f"{path}: calibration version / features do not match this code; recalibrate")
        allowed = set(cfg.gaze.zones)
        keep = [i for i, z in enumerate(data["zones"]) if z in allowed]
        base = data.get("ear_baseline")
        return cls.from_samples(
            cfg,
            data["name"],
            [data["samples"][i] for i in keep],
            [data["zones"][i] for i in keep],
            [data["modes"][i] for i in keep],
            [data["segments"][i] for i in keep],
            [data["times"][i] for i in keep],
            ear_baseline=(float(base[0]), float(base[1])) if base else None,
            ear_ref_by_zone={z: (float(v[0]), float(v[1])) for z, v in data.get("ear_ref_by_zone", {}).items()},
            posture_ref=data.get("posture_ref"),
            camera=data.get("camera", {}),
            created=data.get("created", ""),
            missing=list(data.get("missing", [])),
        )

    def merged_with(self, cfg: PerceptionConfig, quick: Calibration) -> Calibration:
        """Quick recalibration: ``quick``'s zones replace this profile's samples for those zones."""
        replaced = set(quick.zones)
        keep = [i for i, z in enumerate(self.zones) if z not in replaced]
        offset = (max(self.segments) + 1) if self.segments else 0
        samples = np.vstack([self.samples[keep], quick.samples]) if keep else quick.samples
        return Calibration.from_samples(
            cfg,
            self.name,
            samples,
            [self.zones[i] for i in keep] + quick.zones,
            [self.modes[i] for i in keep] + quick.modes,
            [self.segments[i] for i in keep] + [s + offset for s in quick.segments],
            [self.times[i] for i in keep] + quick.times,
            ear_baseline=quick.ear_baseline or self.ear_baseline,
            ear_ref_by_zone={**self.ear_ref_by_zone, **quick.ear_ref_by_zone},
            posture_ref=quick.posture_ref or self.posture_ref,
            camera=quick.camera or self.camera,
            created=quick.created,
            missing=[z for z in self.missing if z not in replaced] + quick.missing,
        )


class CalibrationRun:
    """Feed it every driver frame (FeatureFrame + DriverState); it tells what to show and collects the samples."""

    def __init__(
        self,
        cfg: PerceptionConfig,
        frame_size: tuple[int, int],
        name: str,
        *,
        quick: bool = False,
        steps: list[CalibStep] | None = None,
        camera: dict[str, Any] | None = None,
    ) -> None:
        profile_path(name)  # validates the name early
        self.cfg = cfg
        self.name = name
        self.quick = quick
        self.camera = camera or {}
        self.steps = list(steps) if steps is not None else build_steps(cfg, quick)
        self.builder = GazeFeatureBuilder(cfg, frame_size)
        self.frame_size = frame_size
        self.posture: list[tuple[float, float, float, float, float, float]] = []  # road frames: posture reference
        self.index = 0
        self.t_step: float | None = None
        self.samples: list[np.ndarray] = []
        self.zones: list[str] = []
        self.modes: list[str] = []
        self.segments: list[int] = []
        self.times: list[float] = []
        self.ears: dict[str, list[tuple[float, float]]] = {}
        self.rejected: dict[str, int] = {}
        self._counts: dict[int, int] = {}
        self._repeated: set[int] = set()
        self.missing: list[str] = []

    @property
    def done(self) -> bool:
        return self.index >= len(self.steps)

    @property
    def current(self) -> CalibStep | None:
        return None if self.done else self.steps[self.index]

    def update(self, ff: FeatureFrame, state: DriverState) -> CalibPrompt | None:
        """Returns the prompt to show, or ``None`` once finished."""
        t = ff.t
        if self.done:
            return None
        if self.t_step is None:
            self.t_step = t
        step = self.steps[self.index]
        elapsed = t - self.t_step
        if elapsed >= step.duration_s:
            self._finish_step(step)
            self.index += 1
            self.t_step = t
            if self.index >= len(self.steps):
                return None
            step = self.steps[self.index]
            elapsed = 0.0
        if step.zone is not None and step.mode is not None and elapsed >= self.cfg.gaze.calibration.discard_s:
            self.collect(ff, state, step)
        remaining = step.duration_s - elapsed
        return CalibPrompt(self.index + 1, len(self.steps), step.zone, step.mode, step.prompt, remaining)

    def collect(self, ff: FeatureFrame, state: DriverState, step: CalibStep) -> None:
        """Add this frame to ``step``'s zone if it is usable (also used to rebuild a calibration from a session)."""
        if state.eyes.state == "CLOSED":
            self.rejected["eyes_closed"] = self.rejected.get("eyes_closed", 0) + 1
            return
        gaze = (
            (state.gaze.gaze_yaw, state.gaze.gaze_pitch)
            if state.gaze.gaze_yaw is not None and state.gaze.gaze_pitch is not None
            else None
        )
        hd = state.head
        x = self.builder.build(ff, *zone_head_angles(hd.yaw, hd.raw_yaw, hd.raw_pitch), gaze)
        if x is None:
            reason = self.builder.last_reason or "rejected"
            self.rejected[reason] = self.rejected.get(reason, 0) + 1
            return
        assert step.zone is not None and step.mode is not None
        self.samples.append(x)
        self.zones.append(step.zone)
        self.modes.append(step.mode)
        self.segments.append(step.segment)
        self.times.append(ff.t)
        self._counts[step.segment] = self._counts.get(step.segment, 0) + 1
        if state.eyes.ear_left is not None and state.eyes.ear_right is not None:
            self.ears.setdefault(step.zone, []).append((state.eyes.ear_left, state.eyes.ear_right))
        geom = face_geometry(ff.face, self.frame_size)
        if step.zone == "road" and geom is not None and None not in (hd.raw_yaw, hd.raw_pitch, hd.raw_roll):
            self.posture.append((*geom, float(hd.raw_yaw), float(hd.raw_pitch), float(hd.raw_roll)))  # type: ignore[arg-type]

    def _finish_step(self, step: CalibStep) -> None:
        if step.zone is None:
            return
        if self._counts.get(step.segment, 0) >= self.cfg.gaze.calibration.min_samples_per_zone:
            return
        if step.segment not in self._repeated:
            self._repeated.add(step.segment)
            again = CalibStep(step.zone, step.mode, f"DIN NOU: {step.prompt}", step.duration_s, step.segment)
            self.steps[self.index + 1 : self.index + 1] = [
                CalibStep(None, None, "Inapoi la DRUM", self.cfg.gaze.calibration.transition_s),
                again,
            ]
        else:
            self.missing.append(f"{step.zone}:{step.mode}")

    def result(self) -> Calibration:
        if not self.samples:
            raise ValueError("no calibration samples collected (face not visible?)")
        if len(set(self.zones)) < 2:
            raise ValueError("calibration needs at least two zones with samples")
        p90: dict[str, tuple[float, float]] = {
            zone: (float(np.percentile([e[0] for e in v], 90)), float(np.percentile([e[1] for e in v], 90)))
            for zone, v in self.ears.items()
            if len(v) >= 5
        }
        return Calibration.from_samples(
            self.cfg,
            self.name,
            np.vstack(self.samples),
            self.zones,
            self.modes,
            self.segments,
            self.times,
            ear_baseline=p90.get("road"),
            ear_ref_by_zone=p90,
            posture_ref=ref.to_dict() if (ref := PostureRef.median(self.posture)) else None,
            camera=self.camera,
            created=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            missing=list(self.missing),
        )

    def summary(self) -> dict[str, Any]:
        per_zone: dict[str, int] = {}
        for z in self.zones:
            per_zone[z] = per_zone.get(z, 0) + 1
        return {"samples": len(self.samples), "per_zone": per_zone, "rejected": self.rejected, "missing": self.missing}
