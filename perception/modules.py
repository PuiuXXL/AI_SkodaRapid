"""Pipeline modules that wrap the interaction modules for the camera workers (docs/notes/modules.md, integrated).

Each class follows :class:`perception.worker.PipelineModule`: ``update(ff, inp)`` returns the keys merged into the
worker's result message (namespaced) plus an optional ``frame_patch`` that ``frame_builder`` deep-merges into the
PerceptionFrame; ``handle(cmd)`` applies a command; ``draw(img, inp)`` adds to the debug overlay.

Clocks: every module works in seconds on the detector clock ``inp.t`` (``frame.t_capture - t0`` of this process).
Commands from the main process carry ``until_perf`` (``time.perf_counter()`` of the main process, the same system
clock as ``frame.t_capture``); a module converts it with ``t0 = inp.frame.t_capture - inp.t`` on the next frame.

Order in the default pipeline (perception/worker.py): detectors -> calibration (driver) -> monitor -> hands -> phone
-> head_answer -> identity -> passenger_state (passenger camera). A module reads what earlier ones put in
``inp.shared`` (``ff``, ``state``, ``monitor``, ``hands``).
"""

from __future__ import annotations

import dataclasses
import statistics
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from perception.config import REPO_ROOT
from perception.driver_cam.face import face_box_px
from perception.features import FeatureFrame
from perception.log import get_logger
from perception.module_config import (
    camera_monitor_config,
    hands_config,
    head_answer_config,
    identity_config,
    phone_config,
)

if TYPE_CHECKING:
    import numpy.typing as npt

    from perception.perf import PerfTracker
    from perception.worker import CameraContext, FrameInput

    Image = npt.NDArray[np.uint8]

__all__ = [
    "HandsModule",
    "HeadAnswerModule",
    "IdentityModule",
    "MonitorModule",
    "PassengerStateModule",
    "PhoneTrackerModule",
]

log = get_logger("perception.modules")

PROFILES_DIR = REPO_ROOT / "profiles"
IDENTITY_MAX_WIDTH = 640  # YuNet + SFace on a copy at most this wide (YuNet 24 ms on 720p, ~4x less at 640x360)
RED, AMBER, GREEN, GREY, WHITE = (60, 60, 230), (0, 190, 255), (80, 220, 80), (170, 170, 170), (255, 255, 255)


def _t0(inp: FrameInput) -> float:
    """``perf_counter`` of this process's first frame: converts a main-process deadline to the detector clock."""
    return inp.frame.t_capture - inp.t


def _face_box(ff: FeatureFrame, ctx: CameraContext) -> tuple[float, float, float, float] | None:
    return face_box_px(ff.face, ctx.width, ctx.height)


def _text(img: Image, text: str, org: tuple[int, int], colour: tuple[int, int, int], scale: float = 0.7) -> None:
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, colour, 2, cv2.LINE_AA)


# --- monitoring (AS12 / AP5) -----------------------------------------------------------------------------


class MonitorModule:
    """``monitoring_ok`` + reason + image warnings (``perception.monitoring.CameraMonitor``) for one camera."""

    name = "monitoring"
    commands: frozenset[str] = frozenset()

    def __init__(self, ctx: CameraContext, extractor: Any, on_mode_switch: Callable[[], None] | None = None) -> None:
        from perception.monitoring import CameraMonitor

        self.monitor = CameraMonitor(camera_monitor_config(ctx.cfg))
        self.on_mode_switch = on_mode_switch

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        res = self.monitor.update(inp.t, inp.frame.image, face_present=ff.face.present, face_width_px=ff.face.width_px)
        if res.mode_switched and self.on_mode_switch is not None:
            self.on_mode_switch()  # day <-> IR night: EAR references and angle filters start over
        inp.shared["monitor"] = res
        inp.shared["luma"] = res.luma
        return {"monitoring": res.to_dict(), "luma": None if res.luma is None else round(res.luma, 1)}

    def handle(self, cmd: dict[str, Any]) -> bool:
        return False

    def draw(self, img: Image, inp: FrameInput) -> None:
        res = inp.shared.get("monitor")
        if res is None:
            return
        h = img.shape[0]
        if not res.ok:
            _text(img, f"Nu te mai vad: {res.reason}", (12, h - 60), RED, 0.9)
        elif res.warnings:
            _text(img, "warning: " + ", ".join(res.warnings), (12, h - 60), AMBER)

    def close(self) -> None:
        return None


# --- hands and gestures (AS9 / AP6) ----------------------------------------------------------------------


class HandsModule:
    """Gesture Recognizer as hand tracker: background rate (hand positions, raised hand), every frame in the window.

    Replaces the old dialog-window-only gesture: a held gesture is cleared when the window closes, and the model is
    loaded and warmed up at start (the first window no longer stalls the camera loop).
    """

    name = "hands"
    commands = frozenset({"dialog_window"})

    def __init__(self, ctx: CameraContext, extractor: Any, perf: PerfTracker | None = None) -> None:
        from perception.hands import HandTracker

        self.ctx = ctx
        cfg = hands_config(ctx.cfg)
        self.tracker = HandTracker(cfg)
        self.perf = perf
        self._pending: dict[str, Any] | None = None
        self.last_hand_t: float | None = None
        # live models: the tracker runs the Gesture Recognizer itself; loaded + warmed up now, not in the first window.
        # Without models (CI, --no-models) it only applies the hold logic to FeatureFrame.hands.
        self.live = (
            bool(ctx.options.models) and getattr(extractor, "face", None) is not None and cfg.model_path().exists()
        )
        if self.live:
            self.tracker.warmup()

    def handle(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("cmd") != "dialog_window":
            return False
        self._pending = cmd
        return True

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        if self._pending is not None:
            cmd, self._pending = self._pending, None
            until = cmd.get("until_perf")
            self.tracker.set_dialog(bool(cmd.get("open")), None if until is None else float(until) - _t0(inp))
        if self.live:
            res = self.tracker.process(inp.frame.image, inp.t, _face_box(ff, self.ctx))
        else:
            res = self.tracker.update(inp.t, ff.hands, (self.ctx.width, self.ctx.height), _face_box(ff, self.ctx))
        if res.ran and self.perf is not None:
            self.perf.add("gesture", res.ms)
        self.last_hand_t = res.last_hand_t
        inp.shared["hands"] = res
        return {
            "gesture": res.gesture,
            "dialog_open": res.mode == "dialog",
            "hands": {
                "gesture": res.gesture,
                "gesture_score": res.gesture_score,
                "candidate": res.candidate,
                "held_ms": res.held_ms,
                "mode": res.mode,
                "count": len(res.hands),
                "raised": any(h.raised for h in res.hands),
                "last_hand_t": res.last_hand_t,
            },
        }

    def draw(self, img: Image, inp: FrameInput) -> None:
        res = inp.shared.get("hands")
        if res is None:
            return
        for hand in res.hands:
            x, y, w, h = (int(v) for v in hand.box_px)
            cv2.rectangle(img, (x, y), (x + w, y + h), AMBER if hand.raised else GREY, 2)
            cv2.circle(img, (int(hand.palm_px[0]), int(hand.palm_px[1])), 6, GREEN, -1)
            cv2.circle(img, (int(hand.wrist_px[0]), int(hand.wrist_px[1])), 5, WHITE, -1)
        label = res.gesture or (f"{res.candidate} {res.held_ms:.0f} ms" if res.candidate else None)
        if label:
            _text(img, f"gesture: {label}", (12, img.shape[0] - 100), GREEN if res.gesture else AMBER)
        if res.mode == "dialog":
            _text(img, "DIALOG", (img.shape[1] - 140, 40), AMBER)

    def close(self) -> None:
        self.tracker.close()


# --- phone (AS7 / AP4) -----------------------------------------------------------------------------------


class PhoneTrackerModule:
    """YOLO26 at ``rates.phone_hz`` (time-based) + geometry with the hands + owner / foreign phone + vote.

    On the passenger camera the "other person" (the driver) sits on the passenger's left, so a phone far to that side
    is not the passenger's (``passenger_side`` flipped for this camera).
    """

    name = "phone"
    commands: frozenset[str] = frozenset()

    def __init__(self, ctx: CameraContext, extractor: Any, perf: PerfTracker | None = None) -> None:
        from perception.phone import PhoneDetector, PhoneTracker

        cfg = phone_config(ctx.cfg)
        if not ctx.is_driver:
            cfg = dataclasses.replace(cfg, passenger_side="left" if cfg.passenger_side == "right" else "right")
        self.ctx = ctx
        self.perf = perf
        self.tracker = PhoneTracker(cfg)
        self.detector: Any = None
        if ctx.options.models and getattr(extractor, "face", None) is not None:
            try:
                self.detector = PhoneDetector(cfg)
            except (FileNotFoundError, OSError) as exc:  # model not downloaded: tracker without detections
                log.warning("phone detector unavailable", extra={"fields": {"camera": ctx.name, "error": str(exc)}})
        # async: one background thread runs YOLO (ORT releases the GIL), the face pipeline never waits for it
        self._pool: Any = None
        self._future: Any = None
        if self.detector is not None and ctx.cfg.phone.async_inference:
            from concurrent.futures import ThreadPoolExecutor

            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"phone-{ctx.name}")

    @property
    def rate_hz(self) -> float:
        return float(self.detector.rate_hz) if self.detector is not None else 0.0

    def handle(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("cmd") == "rates" and "phone_hz" in cmd:
            if self.detector is not None:
                self.detector.set_rate_hz(float(cmd["phone_hz"]))
            return True
        return False

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        boxes = None
        if self._pool is not None:
            if self._future is not None and self._future.done():
                det = self._future.result()
                self._future = None
                boxes = det.boxes
                if self.perf is not None:
                    self.perf.add("phone", det.ms)
            if self._future is None and self.detector.should_run(inp.t):
                self._future = self._pool.submit(self.detector.detect, inp.frame.image, inp.t)
        elif self.detector is not None and self.detector.should_run(inp.t):
            det = self.detector.detect(inp.frame.image, inp.t)
            boxes = det.boxes
            if self.perf is not None:
                self.perf.add("phone", det.ms)
        elif self.detector is None and ff.phones is not None:
            boxes = ff.phones  # replay / extractor-provided boxes
        hands = inp.shared.get("hands")
        state = inp.shared.get("state")
        lap = bool(state is not None and self.ctx.is_driver and state.gaze.lap_pattern)
        res = self.tracker.update(
            inp.t,
            boxes,
            face_box=_face_box(ff, self.ctx),
            hands=hands.hands if hands is not None else (),
            lap_pattern=lap,
        )
        inp.shared["phone"] = res
        return {"phone": res.to_dict()}

    def draw(self, img: Image, inp: FrameInput) -> None:
        res = inp.shared.get("phone")
        if res is None:
            return
        if res.box is not None:
            x1, y1, x2, y2 = (int(v) for v in res.box)
            cv2.rectangle(img, (x1, y1), (x2, y2), RED if res.in_use else AMBER, 3)
            _text(img, f"phone {res.usage or ''} {res.votes}/{res.runs}", (x1, max(20, y1 - 8)), RED)
        if res.foreign_box is not None:
            x1, y1, x2, y2 = (int(v) for v in res.foreign_box)
            cv2.rectangle(img, (x1, y1), (x2, y2), GREY, 2)
            _text(img, "not mine", (x1, max(20, y1 - 8)), GREY)
        if res.source == "lap_pattern":
            _text(img, "phone: lap pattern", (12, img.shape[0] - 140), RED)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)


# --- head yes / no (AS8) ---------------------------------------------------------------------------------


class HeadAnswerModule:
    """AS8 on the raw head angles; the window comes from ``dialog_window`` (main routes it to this camera)."""

    name = "head_answer"
    commands = frozenset({"dialog_window"})

    def __init__(self, ctx: CameraContext, extractor: Any) -> None:
        from perception.driver_cam.head_answer import HeadAnswerDetector

        self.ctx = ctx
        self.seat = "driver" if ctx.is_driver else "passenger"
        self.detector = HeadAnswerDetector(head_answer_config(ctx.cfg), seat=self.seat)
        self._pending: dict[str, Any] | None = None

    def handle(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("cmd") != "dialog_window":
            return False
        self._pending = cmd
        return True

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        if self._pending is not None:
            cmd, self._pending = self._pending, None
            until = cmd.get("until_perf")
            self.detector.open_window(bool(cmd.get("open")), None, None if until is None else float(until) - _t0(inp))
        state = inp.shared.get("state")
        yaw = pitch = None
        eyes_open: bool | None = None
        if state is not None:
            yaw, pitch = state.head.raw_yaw, state.head.raw_pitch
            eyes_open = None if not state.eyes.reliable else state.eyes.state != "CLOSED"
        res = self.detector.update(inp.t, yaw, pitch, eyes_open)
        inp.shared["head_answer"] = res
        patch = (
            {"driver": {"head": {"answer": res.answer}}}
            if self.ctx.is_driver
            else {"passenger": {"answer": res.answer}}
        )
        return {"head_answer": res.to_dict(), "frame_patch": patch}

    def draw(self, img: Image, inp: FrameInput) -> None:
        res = inp.shared.get("head_answer")
        if res is None or not res.active:
            return
        chip = f"answer: {res.answer}" if res.answer else f"nod {res.crossings_pitch} / shake {res.crossings_yaw}"
        _text(img, chip, (img.shape[1] - 360, 80), GREEN if res.answer == "yes" else RED if res.answer else WHITE)

    def close(self) -> None:
        return None


# --- identity + enroll (AS10 / AP1) ----------------------------------------------------------------------


class IdentityModule:
    """YuNet + SFace for this camera (``profiles/<name>/face_<camera>.npy``) + the ``enroll`` command.

    YuNet runs on a copy at most ``IDENTITY_MAX_WIDTH`` px wide (the boxes are only used for ``alignCrop`` on the same
    image). The enrollment state rides on every message (``identity.enroll``), like the calibration state, so the main
    process can turn it into ``progress`` / ``done`` / ``error`` acks even if one message is dropped.
    """

    name = "identity"
    commands = frozenset({"enroll"})

    def __init__(
        self,
        ctx: CameraContext,
        extractor: Any,
        perf: PerfTracker | None = None,
        on_profile: Callable[[str | None], None] | None = None,
    ) -> None:
        from perception.identity import FaceGallery, FaceIdentifier

        self.ctx = ctx
        self.perf = perf
        self.on_profile = on_profile
        self.cfg = identity_config(ctx.cfg)
        self.enabled = bool(ctx.options.models) and getattr(extractor, "face", None) is not None
        self.identifier = FaceIdentifier(self.cfg, FaceGallery.load(PROFILES_DIR, ctx.name), camera=ctx.name)
        self.enroller: Any = None
        self.enroll: dict[str, Any] = {"id": 0, "state": "idle"}
        self._profile: str | None = None

    def handle(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("cmd") != "enroll":
            return False
        from perception.identity import Enroller, safe_name

        enroll_id = int(self.enroll["id"]) + 1
        try:
            name = safe_name(str(cmd.get("name") or cmd.get("profile") or ""))
            if not self.enabled:
                raise ValueError("identity models are not loaded on this camera")
            self.enroller = Enroller(self.identifier)
            self.enroll = {
                "id": enroll_id,
                "state": "running",
                "name": name,
                "count": 0,
                "needed": self.cfg.enroll_frames,
            }
        except ValueError as exc:
            self.enroller = None
            self.enroll = {"id": enroll_id, "state": "error", "detail": str(exc)}
        return True

    def _small(self, image: Image) -> Image:
        h, w = image.shape[:2]
        if w <= IDENTITY_MAX_WIDTH:
            return image
        small = cv2.resize(image, (IDENTITY_MAX_WIDTH, round(h * IDENTITY_MAX_WIDTH / w)), interpolation=cv2.INTER_AREA)
        return np.asarray(small, dtype=np.uint8)

    def _enroll_step(self, inp: FrameInput) -> None:
        from perception.identity import Enroller, FaceGallery

        step = self.enroller.offer(inp.t, self._small(inp.frame.image))
        self.enroll = {**self.enroll, "count": step.count, "reason": step.reason}
        if not self.enroller.done:
            return
        name = str(self.enroll["name"])
        try:
            result = self.enroller.finish()
            path = Enroller.save(PROFILES_DIR, name, self.ctx.name, result.embedding)
            self.identifier.gallery = FaceGallery.load(PROFILES_DIR, self.ctx.name)
            self.identifier._last_run = None  # identify again now, with the new gallery
            self.enroll = {
                **self.enroll,
                "state": "done",
                "frames": result.frames,
                "consistency": result.consistency,
                "path": str(path.relative_to(REPO_ROOT)),
            }
            log.info("face enrolled", extra={"fields": {"camera": self.ctx.name, "name": name}})
        except (OSError, ValueError) as exc:
            self.enroll = {**self.enroll, "state": "error", "detail": str(exc)}
        self.enroller = None

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        if not self.enabled:
            return {"identity": {"profile": None, "reason": "no_models", "enroll": self.enroll}}
        if self.enroller is not None:
            self._enroll_step(inp)
            res = None
        else:
            res = self.identifier.update(inp.t, self._small(inp.frame.image), face_present=ff.face.present)
            if res.ran and self.perf is not None:
                self.perf.add("sface", res.ms)  # YuNet + SFace (contract perf.sface_ms_p50)
            if res.profile != self._profile:
                self._profile = res.profile
                if self.on_profile is not None:
                    self.on_profile(res.profile)
        inp.shared["identity"] = res
        out = res.to_dict() if res is not None else {"profile": self._profile, "reason": "enrolling"}
        return {"identity": {**out, "enroll": self.enroll}}

    def draw(self, img: Image, inp: FrameInput) -> None:
        res = inp.shared.get("identity")
        if self.enroller is not None:
            _text(img, f"enroll {self.enroll.get('count', 0)}/{self.enroll.get('needed')}", (12, 150), AMBER)
        elif res is not None:
            who = res.profile or ("?" if res.reason == "unknown_face" else "-")
            score = f" {res.score:.2f}" if res.score is not None else ""
            _text(img, f"{self.ctx.name}: {who}{score}", (img.shape[1] - 360, 120), GREEN if res.profile else GREY)

    def close(self) -> None:
        return None


# --- passenger asleep (AP2) ------------------------------------------------------------------------------


class PostureModule:
    """Posture on both seats (perception/posture.py): ``driver.posture`` / ``passenger.posture``.

    ``reference``: returns the calibration's ``posture_ref`` dict (driver camera: the loaded gaze profile) or None,
    in which case the tracker learns its own reference from the first ``posture.auto_ref_s`` seconds.
    """

    name = "posture"
    commands: frozenset[str] = frozenset()

    def __init__(
        self, ctx: CameraContext, extractor: Any, reference: Callable[[], dict[str, float] | None] | None = None
    ) -> None:
        from perception.posture import PostureTracker

        self.ctx = ctx
        self.tracker = PostureTracker(ctx.cfg.posture)
        self._reference = reference
        self._ref_seen: dict[str, float] | None = None

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        from perception.posture import PostureRef, face_geometry

        ref = self._reference() if self._reference is not None else None
        if ref != self._ref_seen:  # a calibration was loaded / replaced
            self._ref_seen = ref
            self.tracker.set_reference(PostureRef.from_dict(ref) if ref else None)
        state = inp.shared.get("state")
        head = state.head if state is not None else None
        out = self.tracker.update(
            inp.t,
            face_geometry(ff.face, (self.ctx.width, self.ctx.height)),
            head.raw_yaw if head else None,
            head.raw_pitch if head else None,
            head.raw_roll if head else None,
        )
        inp.shared["posture"] = out
        seat = "driver" if self.ctx.is_driver else "passenger"
        return {"posture": dataclasses.asdict(out), "frame_patch": {seat: {"posture": out.states()}}}

    def handle(self, cmd: dict[str, Any]) -> bool:
        return False

    def draw(self, img: Image, inp: FrameInput) -> None:
        out = inp.shared.get("posture")
        if out is None:
            return
        label = ", ".join(out.active()) or ("upright" if out.reference else "posture: learning")
        _text(img, f"posture: {label}", (12, img.shape[0] - 130), AMBER if out.active() else GREY)

    def close(self) -> None:
        return None


class PassengerStateModule:
    """AP2: asleep when the eyes were not seen open for ``passenger.asleep_closed_s`` while the passenger is there, or
    for ``asleep_closed_head_s`` with the head dropped by ``head_drop_deg`` below their upright pitch.

    The eye detector's ``closed_ms`` resets whenever the face is lost; a dropping head often loses the face for a
    moment, so this module keeps its own "eyes last seen open" time and keeps a sleeping passenger present while the
    face is briefly gone.
    """

    name = "passenger_state"
    commands: frozenset[str] = frozenset()

    def __init__(self, ctx: CameraContext, extractor: Any) -> None:
        self.cfg = ctx.cfg
        self._last_open: float | None = None
        self._last_face: float | None = None
        self._upright: deque[tuple[float, float]] = deque()
        self._last_pitch: tuple[float, float] | None = None
        self._asleep = False

    def update(self, ff: FeatureFrame, inp: FrameInput) -> dict[str, Any]:
        p, t = self.cfg.passenger, inp.t
        state = inp.shared.get("state")
        mon = inp.shared.get("monitor")
        camera_ok = mon is None or mon.reason not in ("no_frames", "frozen", "occluded")
        if state is not None and state.face.present:
            self._last_face = t
            if state.head.raw_pitch is not None:
                self._last_pitch = (t, state.head.raw_pitch)
            if state.eyes.reliable and state.eyes.state in ("OPEN", "SQUINT"):
                self._last_open = t
                if state.head.raw_pitch is not None:
                    self._upright.append((t, state.head.raw_pitch))
        while self._upright and t - self._upright[0][0] > p.upright_window_s:
            self._upright.popleft()
        if self._last_open is None and self._last_face is not None:
            self._last_open = self._last_face  # first sight: count from now
        seen_recently = self._last_face is not None and t - self._last_face < self.cfg.monitoring.face_lost_s
        closed_s = t - self._last_open if self._last_open is not None else 0.0
        upright = statistics.median(v for _, v in self._upright) if self._upright else None
        dropped = bool(
            upright is not None
            and self._last_pitch is not None
            and t - self._last_pitch[0] <= p.asleep_closed_s
            and self._last_pitch[1] <= upright - p.head_drop_deg
        )
        asleep_now = closed_s >= p.asleep_closed_s or (dropped and closed_s >= p.asleep_closed_head_s)
        # a sleeping passenger whose face vanished (head dropped) stays present for one more sleep period
        present = camera_ok and (
            seen_recently or (self._asleep and self._last_face is not None and t - self._last_face < p.asleep_closed_s)
        )
        self._asleep = bool(present and asleep_now)
        eyes_closed_s = round(closed_s, 2) if present else 0.0
        inp.shared["passenger_state"] = (present, not self._asleep, eyes_closed_s)
        return {
            "passenger_state": {
                "present": present,
                "awake": not self._asleep,
                "eyes_closed_s": eyes_closed_s,
                "head_dropped": dropped,
                "upright_pitch": None if upright is None else round(upright, 1),
            },
        }

    def draw(self, img: Image, inp: FrameInput) -> None:
        state = inp.shared.get("passenger_state")
        if state is None:
            return
        present, awake, closed_s = state
        label = "absent" if not present else ("awake" if awake else f"ASLEEP ({closed_s:.0f} s eyes closed)")
        _text(img, f"passenger: {label}", (12, img.shape[0] - 160), GREEN if present and awake else AMBER)

    def handle(self, cmd: dict[str, Any]) -> bool:
        return False

    def close(self) -> None:
        return None
