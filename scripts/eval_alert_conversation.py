"""Who speaks when: P2's safety rules + P3's assistant in one simulated drive (no camera, no browser, no network).

Plan "alert severity vs. conversation", step 0: measure how a conversation with the assistant survives the driver's
glances away from the road, a microsleep and a talk with the passenger, BEFORE changing anything.

What runs for real: core's ``Engine`` with ``Safety`` (distraction, drowsiness, SOS, arbiter), ``Scores`` (cause),
``AssistantLink`` and P3's ``AssistantClient`` (policies, validation, follow-up question, dialog manager).
What is simulated:

* **P1** - ``scripts/fake_perception.FakePerception`` at 15 Hz, with the gaze zone, the eyes and the passenger's
  speech scripted per scenario (P1's ``off_road_ms`` semantics: the current glance away from the road);
* **the browser player** - one FIFO queue like ``dashboard/src/voice/player.js``: ``stop`` / ``pause`` / ``resume``,
  the alarm stops speech, ``speak_done`` / ``alarm_played`` go back to core; ~0.38 s per word (edge-tts at +5 %);
* **the driver** - speaks a scripted turn only when the assistant is silent (half-duplex), with the wake word;
* **the LLM** - ``scripted`` (default): fixed answers taken from the prompt's own examples / P3's fixed texts, so
  runs are repeatable; ``--llm gemini`` uses the real model (fake time does not advance while it answers). Its
  answer is delivered ``--llm-latency`` seconds of fake time after the event.

Run (repo root)::

    .venv/Scripts/python scripts/eval_alert_conversation.py                    # all scenarios, report in docs/eval/
    .venv/Scripts/python scripts/eval_alert_conversation.py --only glance_1_8s --timeline
    .venv/Scripts/python scripts/eval_alert_conversation.py --label after-step1

Writes ``docs/eval/alerts-conversation-<label>-<date>.json`` and ``.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from assistant import tts  # noqa: E402
from assistant.client import AssistantClient  # noqa: E402
from assistant.llm import make_provider  # noqa: E402
from assistant.llm.base import LLMProvider, LLMResult, TextCallback  # noqa: E402
from assistant.textutil import normalize, word_count  # noqa: E402
from core.assistant_link import AssistantLink  # noqa: E402
from core.engine import Engine  # noqa: E402
from core.hub import Hub  # noqa: E402
from core.reminders import ReminderRule  # noqa: E402
from core.safe_contact import SafeContactRule  # noqa: E402
from core.safety import Safety  # noqa: E402
from core.scorecard import TripReport  # noqa: E402
from core.scoring import Scores  # noqa: E402
from core.simulation import FakeSimulator  # noqa: E402
from scripts.fake_perception import FakePerception  # noqa: E402

T0 = 1_000_000.0
FRAME_HZ = 15.0
TICK_HZ = 10.0
STEP_S = 0.02
WORD_S = 0.38            # edge-tts ro-RO-EmilNeural at +5 %: ~2.6 words per second
SENTENCE_GAP_S = 0.15
ALARM_CLIP_S = 2.0       # thresholds.yaml sos.alarm_clip_s
RESUME_CLIP_S = 0.8      # "...cum ziceam,"
DRIVER_WAIT_MAX_S = 30.0  # the driver gives up a turn after waiting this long for silence
GAP_AFTER_SILENCE_S = 0.8  # the driver starts talking this long after the assistant fell silent
OUT_DIR = REPO_ROOT / "docs" / "eval"

#: Phrases that tell the driver to look at the road (P2's escalation or the LLM), normalised.
ROAD_WARNINGS = ("atent la drum", "ochii pe drum", "lasa telefonul")


# --- the scripted LLM -------------------------------------------------------------------------------------------------

ANSWERS: dict[str, str] = {
    "cat mai am": ("Mai ai cam douăzeci de minute până la destinație. Drumul e liber, iar după benzinăria OMV urmează "
                   "o porțiune liniștită de autostradă."),
    "ce e de vazut": ("Peste nouăzeci de kilometri e Cetatea Devei, o cetate medievală pe un deal vulcanic, cu "
                      "telecabină. Merită o pauză scurtă acolo."),
}
DEFAULT_ANSWER = "Bine, Andrei. Îți spun imediat ce găsesc ceva util pe traseu."


class ScriptedLLM(LLMProvider):
    """Fixed answers in the shape the real LLM gives (prompt examples / P3's fixed texts): repeatable runs."""

    name = "scripted"

    async def generate(self, system: str, user: str, on_text: Optional[TextCallback] = None) -> LLMResult:
        first = user.splitlines()[0] if user else ""
        event = re.match(r"EVENT: (\w+)", first)
        kind = event.group(1) if event else ""
        if kind == "driver_speech":
            said = normalize(first)
            text = next((answer for key, answer in ANSWERS.items() if key in said), DEFAULT_ANSWER)
            actions = [{"type": "speak", "to": "driver", "text": text}]
        elif kind == "cause_detected" and "passenger_talk" in user:
            # What Gemini answers with the current prompt (docs/eval/llm-cause-*.md): it stays silent while the
            # driver talks with the passenger. Before step 4 the fixed text said "Andrei, ochii pe drum, te ascult
            # și așa." when the LLM did not answer in time.
            actions = [{"type": "stay_silent", "reason": "conversation"}]
        elif kind == "cause_detected":
            # The prompt's example for passenger_showing_phone (step 4: no warning to the driver any more).
            actions = [{"type": "speak", "to": "passenger", "text": "Maria, poți să-i povestești tu?"},
                       {"type": "delegate", "to_person": "Maria", "task": "tell_story"}]
        elif kind == "trip_start":
            actions = [{"type": "speak", "to": "all", "text": "Salut, Andrei și Maria! Drum bun."}]
        elif kind == "fatigue_high":
            actions = [{"type": "ask", "to": "driver", "question": "Andrei, de la 1 la 9, cât de obosit ești?",
                        "expects": "kss"}]
        else:
            actions = [{"type": "stay_silent", "reason": "nothing_to_add"}]
        text = json.dumps({"actions": actions}, ensure_ascii=False)
        if on_text is not None:
            on_text(text)
        return LLMResult(text=text, ttft_ms=1.0, total_ms=1.0, finish_reason="STOP")


# --- P1 stand-in with a scripted gaze -----------------------------------------------------------------------------------


class ScriptedPerception(FakePerception):
    """FakePerception whose gaze zone / passenger speech follow the scenario's intervals (absolute fake time)."""

    def __init__(self, now: float, zones: list[tuple[float, float, str]],
                 passenger_talk: list[tuple[float, float]]) -> None:
        super().__init__(now=now)
        self.zones, self.passenger_talk = zones, passenger_talk
        self._t = now

    def _zone(self, dt: float) -> str:
        """The scripted zone, else the road (no automatic mirror scan: every glance is the scenario's own)."""
        for start, end, zone in self.zones:
            if start <= self._t < end:
                return zone
        return "road" if self.mode == "1" else super()._zone(dt)

    def frame(self, now: float) -> dict[str, Any]:
        self._t = now
        data = super().frame(now)
        if any(start <= now < end for start, end in self.passenger_talk):
            data["passenger"]["speaking"] = True
        return data


# --- the browser player ------------------------------------------------------------------------------------------------


@dataclass
class Utterance:
    id: str
    text: str
    source: str  # "assistant" (P3, ids u<n>) or "P2:<prefix>" (core's fixed sentences: dis, drw, sos, ...)
    is_question: bool
    duration: float
    arrived: float
    start: Optional[float] = None
    end: Optional[float] = None
    remaining: Optional[float] = None  # set while paused
    finished: Optional[float] = None
    interrupted: bool = False
    resumed: int = 0
    paused_count: int = 0


def utterance_source(utterance_id: str) -> str:
    prefix = re.match(r"[a-z]+", utterance_id)
    name = prefix.group(0) if prefix else "?"
    return "assistant" if name == "u" else f"P2:{name}"


def duration_of(text: str) -> float:
    sentences = max(1, len(re.findall(r"[.!?]", text)))
    return word_count(text) * WORD_S + (sentences - 1) * SENTENCE_GAP_S + 0.3


class FakeBrowser:
    """The voice player of dashboard/src/voice/player.js, in fake time: one queue, alarms stop speech."""

    def __init__(self, sim: Sim) -> None:
        self.sim = sim
        self.queue: list[Utterance] = []
        self.current: Optional[Utterance] = None
        self.done: list[Utterance] = []
        self.alarm_until = 0.0
        self.alarms: list[float] = []
        self.speech_over_alarm = 0
        self.queued_behind = 0  # utterances that arrived while another one was playing
        self.read = 0

    def busy(self) -> bool:
        return self.current is not None

    def pump(self, t: float) -> None:
        sent = self.sim.hub.ui_sent
        while self.read < len(sent):
            self._message(sent[self.read], t)
            self.read += 1
        if self.current is not None and self.current.remaining is None and self.current.end is not None \
                and t >= self.current.end:
            self._finish(self.current, t, interrupted=False)
        if self.current is None and self.queue:
            self._start(self.queue.pop(0), t)

    def _message(self, message: dict[str, Any], t: float) -> None:
        kind = message.get("type")
        if kind == "speak":
            utterance = Utterance(id=message["id"], text=message.get("text") or "",
                                  source=utterance_source(message["id"]),
                                  is_question=bool(message.get("is_question")),
                                  duration=duration_of(message.get("text") or ""), arrived=t)
            self.sim.log(t, utterance.source, f"<- speak{'?' if utterance.is_question else ''} {utterance.text!r}")
            if self.current is None:
                self._start(utterance, t)
            else:
                self.queued_behind += 1
                self.queue.append(utterance)
        elif kind == "speak_control":
            action = message.get("action")
            self.sim.log(t, "core", f"speak_control {action}")
            current = self.current
            if action == "stop":
                self.queue.clear()
                if current is not None:
                    self._finish(current, t, interrupted=True)
            elif action == "pause" and current is not None and current.remaining is None and current.end:
                current.remaining, current.end = max(0.0, current.end - t), None
                current.paused_count += 1
            elif action == "resume" and current is not None and current.remaining is not None:
                current.end, current.remaining = t + RESUME_CLIP_S + current.remaining, None
                current.resumed += 1
        elif kind == "alarm":
            self.sim.log(t, "core", f"ALARM {message.get('alert')} ({message.get('level')})")
            self.queue.clear()
            if self.current is not None:
                self._finish(self.current, t, interrupted=True)
            self.alarm_until = t + ALARM_CLIP_S
            self.alarms.append(t)
            self.sim.browser_message({"type": "alarm_played", "id": message["id"], "ts": t})

    def _start(self, utterance: Utterance, t: float) -> None:
        if t < self.alarm_until:
            self.speech_over_alarm += 1
        utterance.start, utterance.end = t, t + utterance.duration
        self.current = utterance

    def _finish(self, utterance: Utterance, t: float, interrupted: bool) -> None:
        utterance.finished, utterance.interrupted = t, interrupted
        self.done.append(utterance)
        self.current = None
        if interrupted:
            self.sim.log(t, utterance.source, f"   STOPPED mid-sentence: {utterance.text!r}")
        self.sim.browser_message({"type": "speak_done", "id": utterance.id, "is_question": utterance.is_question,
                                  "interrupted": interrupted, "ts": t})


# --- the simulation ------------------------------------------------------------------------------------------------------


class RecordingHub(Hub):
    def __init__(self) -> None:
        super().__init__()
        self.ui_sent: list[dict[str, Any]] = []

    def broadcast_ui(self, message: dict[str, Any]) -> bool:
        self.ui_sent.append(message)
        return True

    def send_perception(self, message: dict[str, Any]) -> bool:
        return True

    def send_phone(self, message: dict[str, Any]) -> bool:
        return True


class CountingClient:
    """Wraps AssistantClient: remembers every event it was asked to answer."""

    def __init__(self, inner: AssistantClient) -> None:
        self.inner = inner
        self.events: list[tuple[float, str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def handle_event(self, event: Any, state: Any, on_early_speech: Any = None, now: Any = None) -> Any:
        self.events.append((now or 0.0, event.type, dict(event.data)))
        return await self.inner.handle_event(event, state, on_early_speech=on_early_speech, now=now)


@dataclass
class Turn:
    text: str
    sent: Optional[float] = None
    lost: bool = False


@dataclass
class Scenario:
    name: str
    description: str
    duration_s: float
    turns: list[str]
    zones: list[tuple[float, float, str]] = field(default_factory=list)  # relative start, end, zone
    eyes_closed: list[tuple[float, float]] = field(default_factory=list)  # relative start, end
    passenger_talk: list[tuple[float, float]] = field(default_factory=list)
    answer_sos_after_s: Optional[float] = None  # "sunt bine" this long after "Ești bine?" started


class Sim:
    def __init__(self, scenario: Scenario, provider: LLMProvider, speed_kmh: float, llm_latency_s: float,
                 verbose: bool) -> None:
        self.scenario, self.llm_latency_s, self.verbose = scenario, llm_latency_s, verbose
        self.t = T0
        self.lines: list[str] = []
        self.hub = RecordingHub()
        self.engine = Engine(self.hub, FakeSimulator(clock=lambda: self.t))
        self.safety = Safety(self.engine, sos_channels={})
        self.scores = Scores(self.engine)
        SafeContactRule(self.engine, {}, Path("/nonexistent-profiles"))
        ReminderRule(self.engine)
        TripReport(self.engine)
        self.client = CountingClient(AssistantClient(provider))
        self.link = AssistantLink(self.engine, client=self.client, clock=lambda: self.t)
        self.interrupts_with_pending = 0
        original = self.link.on_safety_interrupt

        def counted_interrupt() -> None:
            if self.link.dialog is not None and self.link.dialog.has_pending(self.t):
                self.interrupts_with_pending += 1
                self.log(self.t, "core", "   pending question of the assistant DROPPED")
            original()

        self.safety.arbiter.on_interrupt = [counted_interrupt if f == original else f
                                            for f in self.safety.arbiter.on_interrupt]
        rel = [(T0 + a, T0 + b, z) for a, b, z in scenario.zones]
        self.fake = ScriptedPerception(T0, rel, [(T0 + a, T0 + b) for a, b in scenario.passenger_talk])
        self.browser = FakeBrowser(self)
        self.turns = [Turn(text) for text in scenario.turns]
        self.next_turn = 0
        self.silent_since: Optional[float] = T0
        self.waiting_since: Optional[float] = None
        self.sos_question_at: Optional[float] = None
        self.sos_answered = False
        self._next_frame = self._next_tick = T0
        self.command("scene", 5)
        self.command("speed", speed_kmh)
        self.engine.tick(T0)

    def log(self, t: float, who: str, text: str) -> None:
        line = f"{t - T0:6.2f}s  {who:<13} {text}"
        self.lines.append(line)
        if self.verbose:
            print(line)

    def command(self, cmd: str, value: Any = None) -> None:
        self.engine.on_browser_message({"type": "command", "cmd": cmd, "value": value}, self.t)

    def browser_message(self, message: dict[str, Any]) -> None:
        self.engine.on_browser_message(message, self.t)

    def _eyes(self, t: float) -> None:
        rel = t - T0
        closed = any(a <= rel < b for a, b in self.scenario.eyes_closed)
        if closed and self.fake.mode != "7":
            self.fake.press("7", t)
            self.log(t, "driver", "eyes CLOSED")
        elif not closed and self.fake.mode == "7":
            self.fake.press("1", t)
            self.log(t, "driver", "eyes open")

    def _zones_log(self, t: float) -> None:
        for a, b, zone in self.scenario.zones:
            if abs(t - (T0 + a)) < STEP_S / 2:
                self.log(t, "driver", f"looks at {zone} for {b - a:.1f} s")

    def _driver(self, t: float) -> None:
        # The SOS question: answered "sunt bine" when the scenario says so.
        sos = self.engine.safety.sos.state
        if sos == "asking" and self.sos_question_at is None:
            self.sos_question_at = t
        if (self.scenario.answer_sos_after_s is not None and self.sos_question_at is not None
                and not self.sos_answered and t - self.sos_question_at >= self.scenario.answer_sos_after_s
                and not self.browser.busy()):
            self.sos_answered = True
            self.log(t, "driver", "says 'Da, sunt bine.'")
            self.engine.on_browser_message({"type": "speech", "text": "Da, sunt bine.", "final": True,
                                            "addressed": True, "ts": t}, t)
            return
        if self.next_turn >= len(self.turns):
            return
        turn = self.turns[self.next_turn]
        if self.waiting_since is None:
            self.waiting_since = t
        asleep = self.fake.mode == "7"  # nobody asks the assistant anything with the eyes closed
        free = not self.browser.busy() and t >= self.browser.alarm_until and not self.link.queue and not asleep
        if free and self.silent_since is not None and t - self.silent_since >= GAP_AFTER_SILENCE_S \
                and t - T0 >= 3.0 and sos == "normal":
            turn.sent = t
            self.log(t, "driver", f"says {turn.text!r}")
            self.engine.on_browser_message({"type": "speech", "text": turn.text, "final": True, "addressed": True,
                                            "ts": t}, t)
            self.next_turn += 1
            self.waiting_since = None
            self.silent_since = None
        elif t - self.waiting_since > DRIVER_WAIT_MAX_S:
            turn.lost = True
            self.log(t, "driver", f"GAVE UP the turn {turn.text!r} (assistant never fell silent)")
            self.next_turn += 1
            self.waiting_since = None

    async def run(self) -> dict[str, Any]:
        end = T0 + self.scenario.duration_s
        logged_events = 0
        while self.t < end:
            t = self.t
            self._eyes(t)
            self._zones_log(t)
            while self._next_frame <= t:
                self.engine.on_perception_message(self.fake.frame(self._next_frame), self._next_frame)
                self._next_frame += 1.0 / FRAME_HZ
            while self._next_tick <= t:
                self.engine.tick(self._next_tick)
                self._next_tick += 1.0 / TICK_HZ
            if self.link.queue and t - self.link.queue[0].ts >= self.llm_latency_s:
                await self.link.drain()
            self.browser.pump(t)
            if self.browser.busy() or t < self.browser.alarm_until:
                self.silent_since = None
            elif self.silent_since is None:
                self.silent_since = t
            self._driver(t)
            for _, kind, data in self.client.events[logged_events:]:
                self.log(t, "-> assistant", f"event {kind} {data if data else ''}".rstrip())
            logged_events = len(self.client.events)
            self.t = round(t + STEP_S, 6)
        if self.browser.current is not None:  # still talking at the end: not interrupted
            self.browser.done.append(self.browser.current)
        return self.metrics()

    def _events(self, type_: str) -> list[dict[str, Any]]:
        return [m["event"] for m in self.hub.ui_sent if m.get("type") == "event" and m["event"]["type"] == type_]

    def metrics(self) -> dict[str, Any]:
        done = self.browser.done
        assistant = [u for u in done if u.source == "assistant"]
        warnings = [u for u in done if any(w in normalize(u.text) for w in ROAD_WARNINGS)]
        first_turn = min((turn.sent for turn in self.turns if turn.sent is not None), default=float("inf"))
        # answers to the driver: after the first question, without the automatic "Te mai ajut cu ceva?"
        answers = [u for u in assistant if u.arrived >= first_turn and "te mai ajut" not in normalize(u.text)]
        return {
            "scenario": self.scenario.name,
            "driver_turns": len(self.turns),
            "driver_turns_said": sum(1 for turn in self.turns if turn.sent is not None),
            "driver_turns_given_up": sum(1 for turn in self.turns if turn.lost),
            "assistant_utterances": len(assistant),
            "assistant_cut_mid_sentence": sum(1 for u in assistant if u.interrupted),
            "assistant_answers_completed": sum(1 for u in answers if not u.interrupted),
            "assistant_answers": len(answers),
            "pending_questions_dropped": self.interrupts_with_pending,
            "road_warnings_spoken": len(warnings),
            "road_warnings_by_P2": sum(1 for u in warnings if u.source.startswith("P2")),
            "road_warnings_by_assistant": sum(1 for u in warnings if u.source == "assistant"),
            "p2_visual_cues": len(self._events("visual_cue")),
            "p2_alarms": len(self.browser.alarms),
            "speech_queued_behind_other_speech": self.browser.queued_behind,
            "speech_started_over_an_alarm": self.browser.speech_over_alarm,
            "cause_events_to_assistant": sum(1 for _, kind, _ in self.client.events if kind == "cause_detected"),
            "sos_reached": self.engine.safety.sos.state,
            "timeline": self.lines,
            "utterances": [asdict(u) | {"start": _rel(u.start), "end": _rel(u.end), "finished": _rel(u.finished),
                                        "arrived": _rel(u.arrived)} for u in done],
        }


def _rel(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value - T0, 2)


# --- scenarios ----------------------------------------------------------------------------------------------------------

TALK = ["Copilot, cât mai am până la destinație?", "Și ce e de văzut pe drum?", "Bine, mulțumesc."]
# Greeting at ~3 s, first question at ~6 s, its answer from ~7 s to ~17 s (24 words): glances start 2 s into it.
GLANCE_AT = 9.0

SCENARIOS: list[Scenario] = [
    Scenario("control", "conversation, eyes on the road", 40.0, TALK),
    Scenario("glance_1_0s", "conversation + one 1.0 s glance at the infotainment during the answer", 40.0, TALK,
             zones=[(GLANCE_AT, GLANCE_AT + 1.0, "infotainment")]),
    Scenario("glance_1_8s", "conversation + one 1.8 s glance (above 1.5 s at >= 90 km/h, before the voice stage)",
             40.0, TALK, zones=[(GLANCE_AT, GLANCE_AT + 1.8, "infotainment")]),
    Scenario("glance_3_0s", "conversation + one 3.0 s glance (P2's spoken warning)", 40.0, TALK,
             zones=[(GLANCE_AT, GLANCE_AT + 3.0, "infotainment")]),
    Scenario("glances_repeated", "conversation + a 1.8 s glance every 7 s (4 times)", 50.0, TALK,
             zones=[(GLANCE_AT + 7.0 * i, GLANCE_AT + 7.0 * i + 1.8, "infotainment") for i in range(4)]),
    Scenario("passenger_talk", "conversation while Maria talks and the driver glances at her (4 x 0.8 s)", 50.0,
             TALK, zones=[(GLANCE_AT + 4.0 * i, GLANCE_AT + 4.0 * i + 0.8, "passenger") for i in range(4)],
             passenger_talk=[(GLANCE_AT - 1.0, GLANCE_AT + 16.0)]),
    Scenario("microsleep", "conversation + eyes closed 3.5 s during the answer, then 'Da, sunt bine'", 45.0, TALK,
             eyes_closed=[(GLANCE_AT, GLANCE_AT + 3.5)], answer_sos_after_s=2.5),
]


# --- report -------------------------------------------------------------------------------------------------------------

COLUMNS = [
    ("assistant_answers_completed", "answers heard to the end"),
    ("assistant_cut_mid_sentence", "assistant cut mid-sentence"),
    ("pending_questions_dropped", "questions dropped"),
    ("driver_turns_given_up", "driver turns lost"),
    ("road_warnings_by_P2", "'look at the road' by P2"),
    ("road_warnings_by_assistant", "... by the LLM"),
    ("cause_events_to_assistant", "cause events"),
    ("p2_visual_cues", "P2 cues"),
    ("p2_alarms", "alarms"),
    ("speech_queued_behind_other_speech", "speech queued behind speech"),
    ("speech_started_over_an_alarm", "speech over an alarm"),
]


def write_report(path: Path, meta: dict[str, Any], results: list[dict[str, Any]], scenarios: list[Scenario]) -> None:
    descriptions = {s.name: s.description for s in scenarios}
    lines = [
        f"# Alerts vs. conversation: {meta['label']} ({meta['date']})",
        "",
        f"Core (P2 rules) + P3 assistant in fake time, `scripts/eval_alert_conversation.py`. LLM: `{meta['llm']}` "
        f"(answer after {meta['llm_latency_s']} s). Speed {meta['speed_kmh']} km/h (off-road limit 1.5 s at >= 90 "
        "km/h, spoken warning +1 s, alarm +3 s). Driver turns: "
        + " / ".join(f"\"{t}\"" for t in TALK) + ".",
        "",
        "| Scenario | " + " | ".join(label for _, label in COLUMNS) + " |",
        "|---|" + "---|" * len(COLUMNS),
    ]
    for r in results:
        cells = []
        for key, _ in COLUMNS:
            value = r[key]
            if key == "assistant_answers_completed":
                value = f"{r['assistant_answers_completed']}/{r['assistant_answers']}"
            cells.append(str(value))
        lines.append(f"| `{r['scenario']}` | " + " | ".join(cells) + " |")
    lines += ["", "## Scenarios", ""]
    for r in results:
        lines += [f"### `{r['scenario']}`: {descriptions[r['scenario']]}", "", "```", *r["timeline"], "```", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    tts.speech_cache.prefetch = lambda *_: None  # no edge-tts synthesis: nothing is played
    scenarios = [s for s in SCENARIOS if not args.only or s.name in args.only]
    results = []
    for scenario in scenarios:
        provider = ScriptedLLM() if args.llm == "scripted" else make_provider()
        if not provider.available:
            print("No usable LLM in .env for --llm gemini.")
            return 2
        print(f"\n=== {scenario.name}: {scenario.description}")
        sim = Sim(scenario, provider, args.speed, args.llm_latency, verbose=args.timeline)
        result = await sim.run()
        results.append(result)
        summary = ", ".join(f"{label}={result[key]}" for key, label in COLUMNS[:7])
        print(f"    {summary}")
    date = time.strftime("%Y-%m-%d")
    meta = {"label": args.label, "date": date, "llm": args.llm, "llm_latency_s": args.llm_latency,
            "speed_kmh": args.speed}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.out_dir / f"alerts-conversation-{args.label}-{date}"
    stem.with_suffix(".json").write_text(json.dumps({"meta": meta, "results": results}, ensure_ascii=False,
                                                    indent=2), encoding="utf-8")
    write_report(stem.with_suffix(".md"), meta, results, scenarios)
    print(f"\nReport: {stem.with_suffix('.md')}")
    return 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Simulate who speaks when: P2's alerts vs. a conversation.")
    parser.add_argument("--only", nargs="*", help="scenario names")
    parser.add_argument("--llm", choices=["scripted", "gemini"], default="scripted")
    parser.add_argument("--llm-latency", type=float, default=1.0, help="fake seconds until the LLM answer")
    parser.add_argument("--speed", type=float, default=100.0, help="km/h")
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--timeline", action="store_true", help="print every step")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
