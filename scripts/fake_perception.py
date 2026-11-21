"""Fake perception for core (P2): ``PerceptionFrame`` at 15 Hz on ``/ws/perception``, one key per demo situation.

It stands in for P1 (roluri/P2-context-siguranta.md, step 1) and for ``run.sh --fake``. Every frame is validated
with ``shared.contracts.PerceptionFrame`` before it is sent, so core receives exactly what P1 would send.

Usage (from the repo root)::

    python scripts/fake_perception.py                      # -> ws://localhost:8000/ws/perception (CORE_URL in .env)
    python scripts/fake_perception.py --print --no-ws      # frames as JSON lines on stdout, no core needed
    python scripts/fake_perception.py --script "0:1,3:2,8:7" --duration 15   # key 1 at 0 s, 2 at 3 s, 7 at 8 s
    python scripts/fake_perception.py --auto-answer        # answer every dialog window with a nod
    python scripts/fake_perception.py --no-keys --script "0:7"   # in the background (run.sh --fake), no keyboard

Keys (no Enter needed in a terminal; with piped stdin every character is a key):

    1 normal              2 mirror glance          3 phone in hand         4 passenger x3 + passenger's phone
    5 fixed gaze          6 yawns + slow blinks + passenger asleep         7 eyes closed
    8 head down, no answer                         9 camera covered
    y / n head yes / no   h open palm (stop)       g thumbs up             b thumbs down
    c conversation on/off p passenger in / out     ? help                  q quit

Commands from core (``dialog_window``, ``calibrate``, ``debug``, ``enroll``) are answered with an ``ack`` like P1 does.
``y`` / ``n`` / gestures go to the person the open dialog window is addressed to (the driver otherwise).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import json
import math
import os
import random
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from shared.contracts import PerceptionCommand, PerceptionFrame, to_wire  # noqa: E402

DRIVER_ID = 1
PASSENGER_ID = 2

[float, float], ...] = ((0.0, 1.0), (3.5, 4.5), (7.0, 8.0))


@dataclass
class Timed:
    """A value that holds until ``until`` (time.time()), for ``target`` (``driver`` / ``passenger``)."""

    value: str
    until: float
    target: str = "driver"


class FakePerception:
    """Builds PerceptionFrames for the current situation. Pure: every method takes ``now`` (time.time())."""

    def __init__(
        self,
        driver: str = "andrei",
        passenger: str = "maria",
        *,
        auto_answer: bool = False,
        seed: int = 0,
        now: float | None = None,
    ) -> None:
        now = time.time() if now is None else now
        self.driver_profile = driver
        self.passenger_profile = passenger
        self.auto_answer = auto_answer
        self.rng = random.Random(seed)
        self.mode = "1"
        self.mode_since = now
        self.start = now
        self.conversation = False
        self.passenger_present = True
        self.passenger_holding_phone = False
        self.answer: Timed | None = None
        self.gesture: Timed | None = None
        self.pending_answer: Timed | None = None  # auto-answer scheduled for later (value, at time)
        self.dialog_open = False
        self.dialog_to = "driver"
        self.dialog_until = 0.0
        self.seq = 0
        self.closed_since: float | None = None
        self.last_blink_ms: float | None = None
        self.eye_samples: deque[tuple[float, bool]] = deque()  # (t, closed) for PERCLOS
        self.zone_samples: deque[tuple[float, str]] = deque()  # (t, zone) for entropy and off_road_60s
        self.off_road_since: float | None = None
        self.mirror_since: float | None = None
        self.glances: deque[tuple[float, float]] = deque()  # completed off-road glances (end t, ms), for VATS
        self.prev_zone = "road"
        self.last_gaze_t: float | None = None

    # --- input -----------------------------------------------------------------------------------------------------

    def press(self, key: str, now: float) -> str | None:
        """Apply one key; returns a line describing what changed (None for an unknown key)."""
        if key in MODES:
            self.mode, self.mode_since = key, now
            if key == "1":
                self.passenger_holding_phone = False
            if key == "4":
                self.passenger_holding_phone = True
            return f"[{key}] {MODES[key]}"
        target = self.dialog_to if self._dialog_active(now) else "driver"
        if key in ANSWER_KEYS:
            self.answer = Timed(ANSWER_KEYS[key], now + ANSWER_HOLD_S, target)
            window = "" if self._dialog_active(now) else " (fereastra de dialog e închisă)"
            return f"[{key}] răspuns din cap: {ANSWER_KEYS[key]} -> {target}{window}"
        if key in GESTURE_KEYS:
            self.gesture = Timed(GESTURE_KEYS[key], now + ANSWER_HOLD_S, target)
            return f"[{key}] gest {GESTURE_KEYS[key]} -> {target}"
        if key == "c":
            self.conversation = not self.conversation
            return f"[c] conversație {'pornită' if self.conversation else 'oprită'}"
        if key == "p":
            self.passenger_present = not self.passenger_present
            return f"[p] pasager {'prezent' if self.passenger_present else 'absent'}"
        return None

    def on_command(self, data: dict[str, Any], now: float) -> list[dict[str, Any]]:
        """Handle a command from core; returns the acks to send back (same format as P1)."""
        try:
            cmd = PerceptionCommand.model_validate(data)
        except ValidationError as exc:
            name = data.get("cmd") or data.get("type")
            return [{"type": "ack", "cmd": name, "status": "error", "detail": str(exc.errors()[0]["msg"])}]
        if cmd.cmd == "dialog_window":
            self.dialog_open = cmd.open
            self.dialog_to = "passenger" if cmd.to in ("passenger", PASSENGER_ID) else "driver"
            self.dialog_until = cmd.until if cmd.until is not None else now + 6.0
            if cmd.open and self.auto_answer and self.dialog_to == "driver":
                delay = self._reaction_delay_s()
                if delay is not None:
                    self.pending_answer = Timed("yes", now + delay, "driver")
            return [{"type": "ack", "cmd": cmd.cmd, "status": "ok", "detail": None}]
        if cmd.cmd in ("calibrate", "enroll"):
            detail = {"fake": True, "profile": cmd.profile or cmd.name}
            return [
                {"type": "ack", "cmd": cmd.cmd, "status": "started", "detail": None},
                {"type": "ack", "cmd": cmd.cmd, "status": "done", "detail": detail},
            ]
        return [{"type": "ack", "cmd": cmd.cmd, "status": "ok", "detail": None}]

    def _dialog_active(self, now: float) -> bool:
        return self.dialog_open and now < self.dialog_until

    def _reaction_delay_s(self) -> float | None:
        """Auto-answer delay: normal, slow (keys 5, 6) or never (keys 7-9)."""
        if self.mode in ("7", "8", "9"):
            return None
        return 2.5 if self.mode in ("5", "6") else 0.7

    # --- the situation at time t -----------------------------------------------------------------------------------

    def _zone(self, dt: float) -> str:
        if self.mode == "9":
            return "unknown"
        if self.mode == "2":
            if dt < MIRROR_GLANCE_S:
                return "mirror_left"
            return self._scan(dt)
        if self.mode == "3":
            return "lap" if dt % 2.5 < 1.8 else "road"  # texting: 1.8 s down, 0.7 s up
        if self.mode == "4":
            if any(a <= dt < b for a, b in PASSENGER_GLANCES):
                return "passenger"
            return "road"
        if self.mode in ("5", "6", "7"):
            return "road"
        if self.mode == "8":
            return "unknown" if dt > 0.8 else "lap"
        return self._scan(dt)

    def _scan(self, dt: float) -> str:
        phase = dt % 10.0
        for a, b, zone in NORMAL_SCAN:
            if a <= phase < b:
                return zone
        return "road"

    def _eyes_closed(self, now: float) -> tuple[bool, float]:
        """(closed, blink length ms) for the blink pattern of the mode."""
        if self.mode in ("7", "8"):
            return True, 0.0
        period, length = (3.0, 450.0) if self.mode == "6" else (6.0, 140.0) if self.mode == "5" else (4.0, 150.0)
        phase = (now - self.start) % period
        return phase < length / 1000.0, length

    # --- frame -----------------------------------------------------------------------------------------------------

    def frame(self, now: float) -> dict[str, Any]:
        """The next PerceptionFrame as a JSON-ready dict, validated against the contract."""
        dt = now - self.mode_since
        self.seq += 1
        if self.pending_answer is not None and now >= self.pending_answer.until:
            self.answer = Timed(self.pending_answer.value, now + ANSWER_HOLD_S, self.pending_answer.target)
            self.pending_answer = None
        if self.answer is not None and now >= self.answer.until:
            self.answer = None
        if self.gesture is not None and now >= self.gesture.until:
            self.gesture = None
        if self.dialog_open and now >= self.dialog_until:
            self.dialog_open = False

        covered = self.mode == "9"
        zone = self._zone(dt)
        closed, _ = self._eyes_closed(now)
        self._track_eyes(now, closed, covered)
        gaze = self._track_gaze(now, zone)
        driver: dict[str, Any] = {
            "eyes": self._eyes_block(now, closed, covered),
            "head": self._head_block(zone, dt, covered),
            "gaze": gaze,
            "yawn": self.mode == "6" and (dt % 20.0) >= 1.0 and (dt % 20.0) < 3.5,
            "speaking": self._speaking(now, "driver"),
            "phone": self._phone_block(zone),
            "gesture": self._timed(self.gesture, "driver"),
            "monitoring_ok": not covered,
            "monitoring_reason": "occluded" if covered else None,
            "monitoring_warnings": [],
            "face_too_small": False,
            "face_conf": 0.0 if covered else 1.0,
            "camera_mode": "color",
            "gesture_score": 0.9 if self._timed(self.gesture, "driver") else None,
        }
        occupants: list[dict[str, Any]] = []
        if not (covered and dt >= FACE_LOST_S):
            occupants.append(
                {"id": DRIVER_ID, "seat": "driver", "source": "cam_driver", "profile": self.driver_profile}
            )
        if self.passenger_present:
            occupants.append(
                {"id": PASSENGER_ID, "seat": "front_right", "source": "cam_passenger",
                 "profile": self.passenger_profile}
            )
        data = {
            "ts": round(now, 3),
            "seq": self.seq,
            "occupants": occupants,
            "driver": driver,
            "passenger": self._passenger_block(now, dt),
            "perf": self._perf_block(now),
        }
        return to_wire(PerceptionFrame.model_validate(data))

    def _timed(self, item: Timed | None, who: str) -> str | None:
        return item.value if item is not None and item.target == who else None

    def _speaking(self, now: float, who: str) -> bool:
        if self.mode == "4" and who == "passenger":
            return self.passenger_present and now - self.mode_since < 8.0
        if not self.conversation or (who == "passenger" and not self.passenger_present):
            return False
        driver_turn = int((now - self.start) // 2.0) % 2 == 0  # turns of 2 s
        return driver_turn if who == "driver" else not driver_turn

    def _track_eyes(self, now: float, closed: bool, covered: bool) -> None:
        if covered:
            self.closed_since = None
            return
        if closed and self.closed_since is None:
            self.closed_since = now
        elif not closed and self.closed_since is not None:
            duration_ms = (now - self.closed_since) * 1000.0
            if duration_ms <= BLINK_MAX_MS:  # a longer closure is not a blink (P1: eyes.blink_max_ms)
                self.last_blink_ms = round(duration_ms, 1)
            self.closed_since = None
        self.eye_samples.append((now, closed))
        while self.eye_samples and self.eye_samples[0][0] < now - WINDOW_S:
            self.eye_samples.popleft()

    def _eyes_block(self, now: float, closed: bool, covered: bool) -> dict[str, Any]:
        if covered:
            return {"ear": None, "eye_used": None, "reliable": False, "state": "UNKNOWN", "closed_ms": 0.0}
        closed_ms = (now - self.closed_since) * 1000.0 if self.closed_since is not None else 0.0
        perclos = sum(1 for _, c in self.eye_samples if c) / len(self.eye_samples) if self.eye_samples else 0.0
        blink_rate = {"5": 10.0, "6": 20.0}.get(self.mode, 15.0)
        return {
            "ear": round(0.08 if closed else 0.28 + 0.01 * self.rng.uniform(-1, 1), 3),
            "eye_used": "left",
            "perclos_60s": round(perclos, 3),
            "blink_ms": self.last_blink_ms,
            "microsleep": False,  # like P1: core decides from closed_ms
            "reliable": True,
            "closed_ms": round(closed_ms, 1),
            "state": "CLOSED" if closed else "OPEN",
            "squint": False,
            "long_closure": closed_ms > 500.0,
            "blink_rate": blink_rate,
            "open_baseline": 0.29,
        }

    def _head_block(self, zone: str, dt: float, covered: bool) -> dict[str, Any]:
        if covered:
            return {"yaw": None, "pitch": None, "roll": None, "nodding": False, "answer": None}
        if self.mode == "8":
            pitch = -35.0 * min(1.0, dt / 0.8)
            return {"yaw": 3.0, "pitch": round(pitch, 1), "roll": 10.0, "nodding": dt < 1.5, "answer": None}
        yaw, pitch = ZONE_HEAD.get(zone, (0.0, 0.0))
        jitter = 0.0 if self.mode == "5" else 1.0
        return {
            "yaw": round(yaw + jitter * self.rng.uniform(-1, 1), 1),
            "pitch": round(pitch + jitter * self.rng.uniform(-1, 1), 1),
            "roll": round(jitter * self.rng.uniform(-1, 1), 1),
            "nodding": False,
            "answer": self._timed(self.answer, "driver"),
        }

    def _track_gaze(self, now: float, zone: str) -> dict[str, Any]:
        """off_road_ms, VATS, entropy and off_road_60s computed like P1 (gaze_metrics.py)."""
        if zone == "unknown" and self.off_road_since is not None and self.last_gaze_t is not None:
            self.off_road_since += now - self.last_gaze_t  # P1: unknown freezes the counters
        self.last_gaze_t = now
        if zone != "unknown":
            self.zone_samples.append((now, zone))
        while self.zone_samples and self.zone_samples[0][0] < now - WINDOW_S:
            self.zone_samples.popleft()
        while self.glances and self.glances[0][0] < now - WINDOW_S:
            self.glances.popleft()

        if zone in MIRRORS:
            self.mirror_since = self.mirror_since if self.prev_zone == zone else now
            mirror_ms = (now - self.mirror_since) * 1000.0
            off_road = mirror_ms > MIRROR_GLANCE_MAX_MS  # a long mirror glance counts, from its start
            if off_road and self.off_road_since is None:
                self.off_road_since = self.mirror_since
        else:
            self.mirror_since = None
            off_road = zone not in ("road", "unknown")
            if off_road and self.off_road_since is None:
                self.off_road_since = now
        if zone == "road" and self.off_road_since is not None:
            self.glances.append((now, (now - self.off_road_since) * 1000.0))
            self.off_road_since = None
        self.prev_zone = zone

        off_road_ms = (now - self.off_road_since) * 1000.0 if self.off_road_since is not None else 0.0
        counts: dict[str, float] = {}
        off_60 = 0.0
        for (t0, z), (t1, _) in itertools.pairwise(self.zone_samples):
            counts[z] = counts.get(z, 0.0) + (t1 - t0)
            if z not in ("road", *MIRRORS):
                off_60 += (t1 - t0) * 1000.0
        total = sum(counts.values())
        entropy = -sum(v / total * math.log2(v / total) for v in counts.values() if v > 0) if total > 0 else None
        return {
            "zone": zone,
            "conf": 0.0 if zone == "unknown" else 0.9,
            "source": None if zone == "unknown" else "face",
            "off_road_ms": round(off_road_ms, 1),
            "vats_60s": sum(1 for _, ms in self.glances if ms < VATS_MAX_MS),
            "entropy_60s": round(entropy, 3) if entropy is not None else None,
            "calibrated": True,
            "off_road_60s_ms": round(off_60 + off_road_ms, 1),
            "lap_pattern": False,
        }

    def _phone_block(self, zone: str) -> dict[str, Any]:
        if self.mode == "3":
            return {"in_use": True, "conf": 0.85, "source": "detector", "near_face": False, "side": "right",
                    "usage": "hand", "foreign_seen": False}
        return {"in_use": False, "conf": 0.05, "source": None, "near_face": False, "side": None, "usage": None,
                "foreign_seen": self.passenger_holding_phone and zone == "passenger"}

    def _passenger_block(self, now: float, dt: float) -> dict[str, Any]:
        if not self.passenger_present:
            return {"present": False, "monitoring_reason": "face_lost"}
        asleep = self.mode == "6"
        return {
            "present": True,
            "awake": not asleep,
            "eyes_closed_s": round(12.0 + dt, 1) if asleep else 0.0,
            "speaking": self._speaking(now, "passenger"),
            "holding_phone": self.passenger_holding_phone,
            "gesture": self._timed(self.gesture, "passenger"),
            "answer": self._timed(self.answer, "passenger"),
            "monitoring_reason": None,
        }

    def _perf_block(self, now: float) -> dict[str, Any]:
        cam = {"capture_ts": round(now, 3), "age_ms": 5.0, "dropped_results": 0, "available": True}
        return {
            "cameras": {
                "driver": {"capture_fps": 30.0, "process_fps": 24.0, "dropped_frames": 0, **cam},
                "passenger": {"capture_fps": 25.0, "process_fps": 10.0, "dropped_frames": 0, **cam},
            },
            "face_driver_ms_p50": 9.0,
            "face_passenger_ms_p50": 8.0,
            "phone_ms_p50": 18.0,
            "gesture_ms_p50": 7.0,
            "e2e_ms_p95": 40.0,
            "degrade_level": 0,
            "publish_ts": round(now, 3),
        }


# =====================================================================================================================
# Keyboard
# =====================================================================================================================


def start_key_reader(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[str]) -> None:
    """Read single keys in a daemon thread: raw terminal on Linux/macOS, msvcrt on Windows, characters when piped."""

    def put(ch: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ch)

    def run() -> None:
        if not sys.stdin.isatty():
            while ch := sys.stdin.read(1):
                if not ch.isspace():
                    put(ch)
            return
        if os.name == "nt":
            import msvcrt

            while True:
                put(msvcrt.getwch())
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while ch := sys.stdin.read(1):
                put(ch)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    threading.Thread(target=run, name="keys", daemon=True).start()


def restore_terminal_on_exit() -> None:
    """The reader thread is a daemon: make sure the terminal is not left in cbreak mode."""
    if os.name == "nt" or not sys.stdin.isatty():
        return
    import atexit
    import termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    atexit.register(lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old))


# =====================================================================================================================
# Main loop
# =====================================================================================================================


def log(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def default_url() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
    except ImportError:
        pass
    base = os.environ.get("CORE_URL", "http://localhost:8000").rstrip("/")
    return base.replace("https://", "wss://").replace("http://", "ws://") + "/ws/perception"


def parse_script(text: str) -> list[tuple[float, str]]:
    """``"0:1,3:2,8:7"`` -> [(0.0, "1"), (3.0, "2"), (8.0, "7")]."""
    steps = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        at, _, key = part.partition(":")
        if not key:
            raise argparse.ArgumentTypeError(f"--script: '{part}' is not <seconds>:<key>")
        steps.append((float(at), key))
    return sorted(steps)


async def run(args: argparse.Namespace) -> None:
    fake = FakePerception(args.driver, args.passenger, auto_answer=args.auto_answer, seed=args.seed)
    loop = asyncio.get_running_loop()
    keys: asyncio.Queue[str] = asyncio.Queue()
    outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
    stop = asyncio.Event()
    started = time.time()

    def handle_key(key: str) -> None:
        if key == "q":
            stop.set()
            return
        if key == "?":
            log(__doc__.split("Keys", 1)[1].split("Commands", 1)[0].rstrip())
            return
        line = fake.press(key, time.time())
        if line:
            log(line)

    async def key_task() -> None:
        while True:
            handle_key(await keys.get())

    async def script_task() -> None:
        for at, key in parse_script(args.script):
            await asyncio.sleep(max(0.0, started + at - time.time()))
            handle_key(key)

    async def frame_task() -> None:
        period = 1.0 / args.hz
        next_t = time.time()
        while not stop.is_set():
            frame = fake.frame(time.time())
            if args.print:
                print(json.dumps(frame, ensure_ascii=False), flush=True)
            if not args.no_ws:
                if outbox.full():
                    outbox.get_nowait()  # drop the oldest: core wants the newest frame
                outbox.put_nowait(frame)
            next_t += period
            await asyncio.sleep(max(0.0, next_t - time.time()))
            if args.duration and time.time() - started >= args.duration:
                stop.set()

    async def ws_task() -> None:
        import websockets

        backoff = 0.5
        while not stop.is_set():
            try:
                async with websockets.connect(args.url, open_timeout=3, ping_interval=10) as ws:
                    log(f"conectat la {args.url}")
                    backoff = 0.5
                    while not outbox.empty():
                        outbox.get_nowait()

                    async def sender() -> None:
                        while True:
                            await ws.send(json.dumps(await outbox.get(), ensure_ascii=False))

                    async def receiver() -> None:
                        async for raw in ws:
                            try:
                                data = json.loads(raw)
                            except ValueError:
                                continue
                            if not isinstance(data, dict):
                                continue
                            for ack in fake.on_command(data, time.time()):
                                log(f"comandă {ack['cmd']}: {ack['status']}")
                                await ws.send(json.dumps(ack))

                    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
                    waiter = asyncio.create_task(stop.wait())
                    try:
                        done, _ = await asyncio.wait([*tasks, waiter], return_when=asyncio.FIRST_COMPLETED)
                    finally:  # never leave a child task behind, even when this task is cancelled
                        for task in (*tasks, waiter):
                            task.cancel()
                        await asyncio.gather(*tasks, waiter, return_exceptions=True)
                    for task in done:
                        if task in tasks and not task.cancelled() and task.exception() is not None:
                            raise task.exception()  # type: ignore[misc]
            except (TimeoutError, OSError) as exc:
                log(f"core indisponibil ({exc.__class__.__name__}), reîncerc în {backoff:.1f} s")
            except Exception as exc:
                log(f"conexiune închisă ({exc.__class__.__name__}), reîncerc în {backoff:.1f} s")
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except TimeoutError:
                backoff = min(backoff * 2, 5.0)

    if not args.no_keys:
        restore_terminal_on_exit()
        start_key_reader(loop, keys)
    log(f"fake_perception: {args.hz} Hz, șofer={args.driver}, pasager={args.passenger}. Tasta ? = ajutor, q = ieșire.")
    log(f"[1] {MODES['1']}")
    tasks = [asyncio.create_task(frame_task()), asyncio.create_task(key_task())]
    if args.script:
        tasks.append(asyncio.create_task(script_task()))
    ws = None if args.no_ws else asyncio.create_task(ws_task())
    await stop.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if ws is not None:  # it sees `stop` and closes the connection cleanly; cancel only if it hangs
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(ws, timeout=3)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fake PerceptionFrame source for core (P2).")
    parser.add_argument("--url", default=None, help="core WebSocket (default: CORE_URL from .env + /ws/perception)")
    parser.add_argument("--hz", type=float, default=15.0, help="frames per second (default 15)")
    parser.add_argument("--print", action="store_true", help="print every frame as a JSON line on stdout")
    parser.add_argument("--no-ws", action="store_true", help="do not connect to core")
    parser.add_argument("--driver", default="andrei", help="driver profile name")
    parser.add_argument("--passenger", default="maria", help="passenger profile name")
    parser.add_argument("--auto-answer", action="store_true", help="answer every dialog window with a nod")
    parser.add_argument("--no-keys", action="store_true", help="do not read the keyboard (background runs, tests)")
    parser.add_argument("--script", default="", help='timed keys, e.g. "0:1,3:2,8:7" (seconds:key)')
    parser.add_argument("--duration", type=float, default=0.0, help="stop after this many seconds (0 = never)")
    parser.add_argument("--seed", type=int, default=0, help="random seed for the small jitter")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.url = args.url or default_url()
    if args.script:
        parse_script(args.script)  # fail early on a bad script
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
