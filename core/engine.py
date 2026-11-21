"""The context engine (B): merges perception, the trip and core's own blocks into one ``State`` at 10 Hz.

Inputs (each handler is synchronous and fast; nothing here waits on the network):

* :meth:`Engine.on_perception_message`: ``PerceptionFrame`` / ``ack`` / ``calibration_prompt`` from P1;
* :meth:`Engine.on_browser_message`: ``command`` (director panel, key D), ``speech``, ``speech_onset``,
  ``speak_done``, ``alarm_played`` from the browser;
* :meth:`Engine.on_phone_message`: ``phone_message``, ``phone_status``, ``phone_result``, ``call`` from the bridge.

Output: :meth:`Engine.tick` builds the state; :meth:`Engine.publish` sends it on ``/ws/ui``. Every decision that the
event log must show goes through :meth:`Engine.log_event` (plan H3: source, explanation, channel, latency).

The safety rules, scores and the assistant plug in later through :meth:`Engine.add_browser_listener`,
:meth:`Engine.add_frame_listener` and :meth:`Engine.add_tick_listener` (roluri/P2 steps 3-6).
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from core.hub import Hub
from core.settings import th
from core.simulation import FakeSimulator, TripSource
from shared.contracts import (
    CONTRACT_VERSION,
    CalibrationPrompt,
    Driver,
    Event,
    Message,
    Occupant,
    Passenger,
    PerceptionAck,
    PerceptionCommand,
    PerceptionFrame,
    Perf,
    PhoneMessage,
    PhoneResult,
    PhoneStatus,
    PhoneStatusMessage,
    State,
    Trip,
    UiCommand,
    UiSpeak,
    parse_browser_message,
    parse_perception_message,
    parse_phone_event,
    to_wire,
)

log = logging.getLogger("drivemate.core.engine")

#: Fields of ``perf`` that core and the assistant fill (the rest comes from P1's frame).
CORE_PERF_FIELDS = ("alarm_ms_last", "llm_ttft_ms", "llm_total_ms", "stt_final_ms", "tts_first_audio_ms",
                    "msg_to_voice_ms")
#: Director commands forwarded to P1 as a PerceptionCommand.
PERCEPTION_COMMANDS = {"debug", "calibrate", "enroll"}
#: Director commands handled by the simulator.
SIMULATOR_COMMANDS = {"scene", "speed", "time_scale", "start", "pause", "stop_at_next_poi", "reset"}
FIRST_DECLARED_ID = 3  # 1 = driver camera, 2 = passenger camera (P1), 3+ = declared rear occupants

BrowserListener = Callable[[Any, float], None]
FrameListener = Callable[[PerceptionFrame, float], None]
TickListener = Callable[[State, float], None]


class Engine:
    """Core's state and its inputs. One instance per core process."""

    def __init__(self, hub: Hub | None = None, simulator: TripSource | None = None,
                 simulator_name: str = "FakeSimulator (core)", contact_app: bool = False) -> None:
        self.hub = hub or Hub()
        self.simulator: TripSource = simulator or FakeSimulator()
        self.simulator_name = simulator_name
        self.contact_app = contact_app
        self.state = State()
        self.frame: PerceptionFrame | None = None
        self.frame_rx: float | None = None  # time.time() when the newest frame arrived
        self.frames_received = 0
        self.invalid_messages = 0
        self.perception_connected = False
        self.declared: list[Occupant] = []
        self.core_perf: dict[str, float | None] = dict.fromkeys(CORE_PERF_FIELDS)
        self.notifications: dict[str, str] = {}  # message id -> phone notification id (for send_reply)
        self.recent_events: deque[dict[str, Any]] = deque(maxlen=50)
        self._msg_counter = 0
        self._invalid_logged: set[str] = set()
        self._browser_listeners: list[BrowserListener] = []
        self._frame_listeners: list[FrameListener] = []
        self._tick_listeners: list[TickListener] = []
        self._reset_listeners: list[Callable[[float], None]] = []
        self._utterance_counter = 0
        self.safety: Any = None  # core.safety.Safety, attached by it

    # --- plug-in points for the next steps ----------------------------------------------------------------------

    def add_browser_listener(self, listener: BrowserListener) -> None:
        """Called with every parsed browser message (speech, speak_done, alarm_played, ...) and ``now``."""
        self._browser_listeners.append(listener)

    def add_frame_listener(self, listener: FrameListener) -> None:
        """Called on every new PerceptionFrame, before the next tick: the fast safety path (alarm < 300 ms)."""
        self._frame_listeners.append(listener)

    def add_tick_listener(self, listener: TickListener) -> None:
        """Called on every tick with the state being built, before it is published (scores, rules)."""
        self._tick_listeners.append(listener)

    def add_reset_listener(self, listener: Callable[[float], None]) -> None:
        """Called after a director reset (a new trip), with ``now``."""
        self._reset_listeners.append(listener)

    # --- voice ---------------------------------------------------------------------------------------------------

    def say(self, clip_id: str | None, text: str, *, to: str = "driver", is_question: bool = False,
            expects: str | None = None, prefix: str = "c") -> str:
        """Play a fixed text through P3's voice. Returns the utterance id (it comes back in ``speak_done``).

        The pre-generated clip when it exists (local, instant). Otherwise the text as sentences for P3's TTS
        (``/tts/<id>.mp3``, edge-tts); P3's player falls back to the browser's own voice when a sentence cannot be
        fetched. A ``speak`` with neither a clip nor sentences would be silent in P3's player.
        """
        from core import clips  # here, not at the top: clips.py reads P3's clips.json once

        self._utterance_counter += 1
        utterance_id = f"{prefix}{self._utterance_counter}"
        message: dict[str, Any] = {"id": utterance_id, "to": to, "is_question": is_question, "expects": expects,
                                   "text": text, "clip_url": None, "sentences": []}
        if clip_id and clips.exists(clip_id):
            message["clip_url"] = clips.clip_url(clip_id)
        else:
            message["sentences"] = tts_sentences(text, utterance_id)
        self.hub.broadcast_ui(to_wire(UiSpeak.model_validate(message)))
        return utterance_id

    # --- events --------------------------------------------------------------------------------------------------

    def log_event(self, type_: str, now: float, *, source: str | None = "RULE", text: str | None = None,
                  explanation: str | None = None, channel: str | None = None, latency_ms: float | None = None,
                  **data: Any) -> Event:
        """Add an entry to the event log on ``/ws/ui`` (plan H3) and keep it for clients that connect later."""
        event = Event.model_validate({"type": type_, "ts": now, "data": data, "source": source, "text": text,
                                      "explanation": explanation, "channel": channel, "latency_ms": latency_ms})
        message = {"type": "event", "event": to_wire(event)}
        self.recent_events.append(message)
        self.hub.broadcast_ui(message)
        log.info("event %s %s", type_, text or explanation or "")
        return event

    def _invalid(self, where: str, exc: Exception) -> None:
        """Count a malformed message; log each kind once (P1 sends 15 Hz, a bad field must not flood the log)."""
        self.invalid_messages += 1
        key = f"{where}:{exc.__class__.__name__}:{str(exc)[:80]}"
        if key not in self._invalid_logged:
            self._invalid_logged.add(key)
            log.warning("invalid %s message: %s", where, str(exc)[:500])

    # --- perception (P1) -----------------------------------------------------------------------------------------

    def on_perception_connected(self, connected: bool, now: float) -> None:
        self.perception_connected = connected
        self.log_event("perception_connected" if connected else "perception_disconnected", now,
                       text="Percepția s-a conectat." if connected else "Percepția s-a deconectat.")

    def on_perception_message(self, data: dict[str, Any], now: float) -> None:
        try:
            message = parse_perception_message(data)
        except ValidationError as exc:
            self._invalid("perception", exc)
            return
        if isinstance(message, PerceptionFrame):
            self.frame, self.frame_rx = message, now
            self.frames_received += 1
            for listener in self._frame_listeners:
                listener(message, now)
        elif isinstance(message, PerceptionAck):
            log.info("perception ack %s: %s %s", message.cmd, message.status, message.detail or "")
            if message.cmd in ("calibrate", "enroll") and message.status in ("done", "error"):
                self.log_event(f"{message.cmd}_{message.status}", now, detail=message.detail)
        elif isinstance(message, CalibrationPrompt):
            self.log_event("calibration_prompt", now, text=message.text, zone=message.zone, step=message.step,
                           steps=message.steps)

    def send_perception_command(self, command: PerceptionCommand) -> bool:
        sent = self.hub.send_perception(to_wire(command))
        if not sent:
            log.warning("perception is not connected: %s not sent", command.cmd)
        return sent

    def perception_fresh(self, now: float) -> bool:
        stale_ms = float(th("loop", "perception_stale_ms"))
        return self.frame_rx is not None and (now - self.frame_rx) * 1000.0 <= stale_ms

    # --- browser (P4's UI, P3's voice) ---------------------------------------------------------------------------

    def on_browser_message(self, data: dict[str, Any], now: float) -> None:
        try:
            message = parse_browser_message(data)
        except ValidationError as exc:
            self._invalid("ui", exc)
            return
        if isinstance(message, UiCommand):
            self.on_command(message, now)
        for listener in self._browser_listeners:
            listener(message, now)

    def on_command(self, cmd: UiCommand, now: float) -> None:
        """Director panel / dashboard commands (plan I2)."""
        value = cmd.value if isinstance(cmd.value, dict) else {}
        if cmd.cmd in PERCEPTION_COMMANDS:
            if cmd.cmd == "debug":
                command = PerceptionCommand(cmd="debug", on=bool(cmd.on))
            elif cmd.cmd == "calibrate":
                command = PerceptionCommand(cmd="calibrate", profile=value.get("profile"),
                                            quick=bool(value.get("quick", False)))
            else:
                command = PerceptionCommand(cmd="enroll", name=value.get("name"), camera=value.get("camera"))
            self.send_perception_command(command)
        elif cmd.cmd == "llm":
            enabled = bool(cmd.on)
            self.state.safety.llm_enabled = enabled
            self.log_event("llm_toggled", now, text="LLM pornit." if enabled else "LLM oprit. Siguranța merge la fel.",
                           enabled=enabled)
        elif cmd.cmd == "declare_occupant":
            self._declare(value)
        elif cmd.cmd == "fake_message":  # a simulated message from the panel, as if the phone bridge sent it
            try:
                fake = PhoneMessage.model_validate({"app": value.get("app", "whatsapp"), "ts": now,
                                                    "from": str(value.get("from", "?")),
                                                    "text": str(value.get("text", ""))})
            except ValidationError as exc:
                self._invalid("fake_message", exc)
            else:
                self.add_phone_message(fake, now)
        if cmd.cmd in SIMULATOR_COMMANDS:
            self.simulator.command(cmd)
        if cmd.cmd == "reset":
            self.reset(now)

    def _declare(self, value: dict[str, Any]) -> None:
        """A rear occupant declared by voice or from the panel (plan G1): no camera."""
        if value.get("remove") is not None:
            self.declared = [o for o in self.declared if o.id != value["remove"]]
            return
        next_id = max([o.id for o in self.declared], default=FIRST_DECLARED_ID - 1) + 1
        role = value.get("role") if value.get("role") in ("adult", "child") else "adult"
        self.declared.append(Occupant(id=next_id, seat="rear", source="declared", profile=value.get("profile"),
                                      role=role))

    def reset(self, now: float) -> None:
        """Director reset: a new trip. The LLM switch is kept."""
        llm_enabled = self.state.safety.llm_enabled
        self.state = State()
        self.state.safety.llm_enabled = llm_enabled
        self.declared.clear()
        self.notifications.clear()
        self.core_perf = dict.fromkeys(CORE_PERF_FIELDS)
        for listener in self._reset_listeners:
            listener(now)
        self.log_event("reset", now, text="Călătorie nouă.")

    # --- phone bridge (P3) ---------------------------------------------------------------------------------------

    def on_phone_message(self, data: dict[str, Any], now: float) -> None:
        try:
            message = parse_phone_event(data)
        except ValidationError as exc:
            self._invalid("phone", exc)
            return
        if isinstance(message, PhoneStatusMessage):
            self.state.phone = PhoneStatus(connected=message.connected, battery=message.battery)
        elif isinstance(message, PhoneMessage):
            self.add_phone_message(message, now)
        elif isinstance(message, PhoneResult):
            log.info("phone result %s: ok=%s %s", message.request_id, message.ok, message.error or "")

    def add_phone_message(self, message: PhoneMessage, now: float) -> Message:
        """Queue a new message as ``pending``; the F2 timing rule (step 5) decides when it is delivered."""
        self._msg_counter += 1
        msg = Message(id=f"m{self._msg_counter}", app=message.app, state="pending", replyable=message.replyable,
                      ts=message.ts or now, text=message.text, **{"from": message.from_})
        if message.notification_id:
            self.notifications[msg.id] = message.notification_id
        self.state.messages.append(msg)
        self.log_event("message_queued", now, text=f"Mesaj de la {msg.from_} ({msg.app}).", msg_id=msg.id)
        return msg

    # --- state ---------------------------------------------------------------------------------------------------

    def tick(self, now: float) -> State:
        """Build the state for this tick (10 Hz)."""
        state = self.state
        state.ts = round(now, 3)
        state.seq += 1
        trip = self.simulator.tick()
        state.trip = trip if isinstance(trip, Trip) else Trip.model_validate(trip)

        fresh = self.perception_fresh(now)
        frame = self.frame if fresh else None
        reaction = state.driver.reaction
        if frame is not None:
            state.driver = Driver.model_validate({**frame.driver.model_dump(), "reaction": reaction.model_dump()})
            state.passenger = frame.passenger.model_copy(deep=True)
            seen = [o.model_copy() for o in frame.occupants]
            perf = {**frame.perf.model_dump(), **self.core_perf}
        else:
            reason = "no_frames" if self.perception_connected else "camera_unavailable"
            state.driver = Driver(monitoring_ok=False, monitoring_reason=reason, reaction=reaction)
            state.passenger = Passenger(present=False, monitoring_reason=reason)
            seen = []
            perf = dict(self.core_perf)
        state.occupants = seen + [o.model_copy() for o in self.declared]
        state.perf = Perf.model_validate(perf)
        state.safety.monitoring_ok = frame is not None and state.driver.monitoring_ok
        state.integrations.phone_bridge = "ok" if self.hub.phone is not None else "down"
        state.integrations.contact_app = "ok" if self.contact_app else "off"
        if not state.safety.llm_enabled:
            state.integrations.llm = "off"
        elif state.integrations.llm == "off":
            state.integrations.llm = "unknown"

        for listener in self._tick_listeners:
            listener(state, now)
        return state

    def ui_payload(self, state: State) -> dict[str, Any]:
        """The ``state`` message for ``/ws/ui``: message texts stay in core (privacy, plan section 3)."""
        data = to_wire(state)
        for message in data.get("messages", []):
            message.pop("text", None)
        return {"type": "state", "state": data}

    def publish(self, state: State) -> None:
        self.hub.broadcast_ui(self.ui_payload(state))

    def health(self, now: float) -> dict[str, Any]:
        return {
            "contract": CONTRACT_VERSION,
            "demo_mode": th("demo_mode"),
            "simulator": self.simulator_name,
            "perception": {
                "connected": self.perception_connected,
                "frames": self.frames_received,
                "last_frame_age_ms": None if self.frame_rx is None else round((now - self.frame_rx) * 1000.0, 1),
                "fresh": self.perception_fresh(now),
            },
            "invalid_messages": self.invalid_messages,
            "state_seq": self.state.seq,
            "hub": self.hub.stats(),
        }


def tts_sentences(text: str, utterance_id: str) -> list[dict[str, str]]:
    """``text`` as sentences for P3's TTS router (synthesis starts in the background when a loop is running).

    Without P3's module the browser still speaks: a URL that cannot be fetched makes P3's player use the browser's
    own voice for that sentence.
    """
    try:
        from assistant.contract import Action
        from assistant.tts import speak_message

        return list(speak_message(Action(type="speak", to="driver", text=text, source="RULE"), utterance_id)
                    ["sentences"])
    except Exception:  # P3's code or its dependencies missing on this laptop
        log.debug("P3's TTS unavailable, the browser will speak %r", text)
        return [{"id": f"{utterance_id}-local", "text": text, "url": f"/tts/{utterance_id}-local.mp3"}]
