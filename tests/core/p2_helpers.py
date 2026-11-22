"""Test helpers for core (P2): a hub that records instead of sending, and a rig that drives the engine in fake time."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from assistant.client import AnswerInfo
from core import clips
from core.assistant_link import AssistantLink
from core.engine import Engine
from core.hub import Hub
from core.reminders import ReminderRule
from core.safe_contact import NoticeChannel, SafeContactRule
from core.safety import Safety
from core.safety.sos import SosChannel
from core.scorecard import TripReport
from core.scoring import Scores
from core.settings import th
from core.simulation import FakeSimulator
from scripts.fake_perception import FakePerception

T0 = 1_000_000.0
FRAME_HZ = 15.0
TICK_HZ = 10.0

# The SOS timeline without browser feedback (no alarm_played / speak_done: the fallbacks apply).
ALARM_S = th("safety", "drowsiness", "alarm_ms") / 1000.0  # eyes shut this long -> alarm
def alarm_clip_s(alert: str = "microsleep", driver: str = "andrei") -> float:
    """Length of the first alarm for ``alert`` as core counts it: the real clip (P3's clips.json) + the browser's
    beep, never under ``sos.alarm_clip_s`` (core/safety/alarm.py)."""
    clip = clips.alarm_clip(driver, alert)
    return max(th("sos", "alarm_clip_s"), (clips.duration_s(clip) or 0.0) + th("safety", "alarms", "beep_s"))


ASK_AFTER = alarm_clip_s() + th("sos", "ask_after_alarm_s")  # alarm -> "Ești bine?"
ASK_WINDOW = th("sos", "ask_clip_s") + th("sos", "answer_window_s")  # "Ești bine?" -> countdown (no answer)
COUNTDOWN = th("sos", "countdown_s")


class RecordingHub(Hub):
    """A hub without sockets: remembers what core sent."""

    def __init__(self) -> None:
        super().__init__()
        self.ui_sent: list[dict[str, Any]] = []
        self.perception_sent: list[dict[str, Any]] = []
        self.phone_sent: list[dict[str, Any]] = []

    def broadcast_ui(self, message: dict[str, Any]) -> bool:
        self.ui_sent.append(message)
        return True

    def send_perception(self, message: dict[str, Any]) -> bool:
        self.perception_sent.append(message)
        return True

    def send_phone(self, message: dict[str, Any]) -> bool:
        self.phone_sent.append(message)
        return True

    def of_type(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.ui_sent if m.get("type") == type_]

    def events(self, type_: str) -> list[dict[str, Any]]:
        return [m["event"] for m in self.of_type("event") if m["event"]["type"] == type_]


class Rig:
    """Engine + Safety + FakePerception, run in fake time: frames at 15 Hz, ticks at 10 Hz."""

    def __init__(self, scene: int = 8, sos_channels: dict[str, SosChannel] | None = None,
                 assistant: Any = None, profiles_root: Path | None = None,
                 contact_channels: dict[str, NoticeChannel] | None = None) -> None:
        self.t = T0
        self.hub = RecordingHub()
        self.engine = Engine(self.hub, FakeSimulator(clock=lambda: self.t))  # the trip moves in fake time too
        self.safety = Safety(self.engine, sos_channels)
        self.scores = Scores(self.engine)
        # profiles from a test folder only: the repo's profiles/ never leaks into a test
        self.contact = SafeContactRule(self.engine, contact_channels, profiles_root or Path("/nonexistent-profiles"))
        self.reminders = ReminderRule(self.engine)
        self.report = TripReport(self.engine)
        self.link = AssistantLink(self.engine, client=assistant, clock=lambda: self.t) if assistant else None
        self.fake = FakePerception(now=T0)
        self.patch: Any = None  # optional (frame dict, t) -> None, to shape what "P1" reports
        self._next_frame = self._next_tick = T0
        self.command("scene", scene)
        self.engine.tick(T0)  # the trip speed is known before the first frame

    @property
    def state(self) -> Any:
        return self.engine.state

    def command(self, cmd: str, value: Any = None, on: bool | None = None) -> None:
        self.engine.on_browser_message({"type": "command", "cmd": cmd, "value": value, "on": on}, self.t)

    def press(self, key: str) -> None:
        self.fake.press(key, self.t)

    def run(self, seconds: float) -> None:
        end = self.t + seconds
        while True:
            t = min(self._next_frame, self._next_tick)
            if t > end:
                break
            self.t = t
            if t == self._next_frame:
                frame = self.fake.frame(t)
                if self.patch is not None:
                    self.patch(frame, t)
                self.engine.on_perception_message(frame, t)
                self._next_frame += 1.0 / FRAME_HZ
            if t == self._next_tick:
                self.engine.tick(t)
                self._next_tick += 1.0 / TICK_HZ
        self.t = end

    def run_until(self, condition: Any, limit_s: float = 60.0, step_s: float = 0.02) -> float:
        """Run until ``condition()`` is true; returns the elapsed fake time."""
        start = self.t
        while not condition():
            if self.t - start > limit_s:
                raise AssertionError("condition not reached")
            self.run(step_s)
        return self.t - start

    def say(self, text: str, addressed: bool = True) -> None:
        self.engine.on_browser_message({"type": "speech", "text": text, "final": True, "addressed": addressed,
                                        "ts": self.t}, self.t)

    def browser(self, message: dict[str, Any]) -> None:
        self.engine.on_browser_message(message, self.t)

    def speaks(self) -> list[dict[str, Any]]:
        return self.hub.of_type("speak")


class FakeClient:
    """Stands in for P3's AssistantClient: scripted actions per event type, optional sentences while "streaming"."""

    def __init__(self, replies: dict[str, Any] | None = None, early: dict[str, list[Any]] | None = None,
                 reason: str = "ok") -> None:
        self.replies = replies or {}  # event type -> list[Action] or (event, state) -> list[Action]
        self.early = early or {}
        self.events: list[Any] = []
        self.states: list[Any] = []  # the state each event was answered with
        self.last_result = AnswerInfo(source="LLM", reason=reason, llm_ttft_ms=420.0, llm_total_ms=900.0)

    async def handle_event(self, event: Any, state: Any, on_early_speech: Any = None, now: Any = None) -> list[Any]:
        self.events.append(event)
        self.states.append(state)
        for action in self.early.get(event.type, []):
            if on_early_speech is not None:
                on_early_speech(action)
        reply = self.replies.get(event.type, [])
        actions = reply(event, state) if callable(reply) else reply
        return [action.model_copy() for action in actions]

    def reset(self) -> None:
        self.events.clear()

    def types(self) -> list[str]:
        return [event.type for event in self.events]
