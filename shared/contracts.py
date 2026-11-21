"""DriveMate JSON contract v2.0: every message that crosses a module boundary.

Owner: P2. Source: ``DriveMate-PLAN-FINAL.md`` section 6 (actions), section 7 (state) and section 13 (interfaces).
Changing it: ``CONTRACT: <field>, <type>, <who writes it>, <why>`` on the group, new fields optional with a
default, bump :data:`CONTRACT_VERSION`, update ``tests/core/fixtures/state_example.json``. Nothing is renamed or
deleted before Sunday.

What is in here:

* **PerceptionFrame** (P1 -> core, ``/ws/perception``, 15 Hz) and the perception messages: :class:`PerceptionCommand`
  (core -> P1), :class:`PerceptionAck` and :class:`CalibrationPrompt` (P1 -> core).
* **State** (core -> everyone, ``/ws/ui`` at 10 Hz, and in process to the assistant), field by field as in section 7.
* **Event**: what core passes to ``assistant.handle_event(event, state)`` and what it logs on ``/ws/ui``.
* **Action** (section 6): the flat model the LLM fills, plus one typed model per action type (:data:`TypedAction`)
  that core's validator (C8) uses.
* **WebSocket messages**: :data:`UiMessage` (``/ws/ui``), :data:`PhoneEvent` / :data:`PhoneCommand` (``/ws/phone``).
* **Reports**: :class:`SosReport` (``place_sos_call``, ``push_sos``) and :class:`SafeContactNotice`
  (``push_safe_contact``).

Rules every model follows:

1. **Every state / frame field has a default**, so each module sends only what it has. The only required fields are
   the ids of list items (an occupant, message, reminder or POI without an id cannot be referenced) and the
   parameters of the typed actions (that is what validating an action means).
2. **Unknown fields are kept** (``extra="allow"``), so a newer module never breaks an older one.
3. Keys that are Python keywords use an alias: ``from`` is ``from_`` in Python. Serialize with :func:`to_wire`
   (``by_alias=True``) so the JSON says ``"from"``.
4. Enum-like fields whose vocabulary is still moving (``monitoring_reason``, ``cause.label``, event types, director
   commands) are plain strings; the known values are listed in the ``*_REASONS`` / ``*_LABELS`` / ``*_TYPES`` tuples.

The temporary copies (``assistant/_TEMP_contract_DELETE_LATER.py``, the provisional models in
``perception/contract.py``) switch to this file automatically when it exists.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

#: Bumped on every contract change (section 13).
CONTRACT_VERSION = "2.1"


class ContractModel(BaseModel):
    """Base of every contract model: unknown fields are kept, aliased fields accept the Python name too."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


def to_wire(model: BaseModel) -> dict[str, Any]:
    """JSON-ready dict of a contract model, with the wire names (``"from"``, not ``"from_"``)."""
    return model.model_dump(mode="json", by_alias=True)


# =====================================================================================================================
# Vocabularies
# =====================================================================================================================

#: Gaze zones (section 7). ``unknown`` never triggers an alert; ``away`` = outside every calibrated zone, off-road.
GAZE_ZONES: tuple[str, ...] = (
    "road", "mirror_left", "mirror_right", "mirror_rear", "cluster", "infotainment",
    "lap", "passenger", "rear_seat", "away", "unknown",
)
GazeZone = Literal[
    "road", "mirror_left", "mirror_right", "mirror_rear", "cluster", "infotainment",
    "lap", "passenger", "rear_seat", "away", "unknown",
]

#: Priority levels (section 5). P0 = most critical. A higher level interrupts everything below it.
SAFETY_LEVELS: tuple[str, ...] = ("P0", "P1", "P2", "P3", "P4")
SafetyLevel = Literal["P0", "P1", "P2", "P3", "P4"]
#: Levels where the LLM is silent (C8 veto).
LLM_VETO_LEVELS: frozenset[str] = frozenset({"P0", "P1", "P2"})

Seat = Literal["driver", "front_right", "rear"]
OccupantSource = Literal["cam_driver", "cam_passenger", "declared"]
PersonRole = Literal["adult", "child"]
HeadAnswer = Literal["yes", "no"]
EyeState = Literal["OPEN", "CLOSED", "SQUINT", "UNKNOWN"]
DecisionSource = Literal["RULE", "LLM"]

#: Gesture names from MediaPipe Gesture Recognizer, as P1 reports them in ``driver.gesture`` / ``passenger.gesture``.
GESTURES: tuple[str, ...] = ("Thumb_Up", "Thumb_Down", "Open_Palm")

#: ``driver.monitoring_reason`` / ``passenger.monitoring_reason`` values. P1 is moving from the first four to the
#: rest (docs/notes/modules.md); both are accepted.
MONITORING_REASONS: tuple[str, ...] = (
    "camera_unavailable", "camera_frozen", "camera_covered", "face_lost",
    "no_frames", "frozen", "mode_switch", "occluded", "too_dark", "blurred",
)

#: ``cause.label`` values (B4).
CAUSE_LABELS: tuple[str, ...] = (
    "passenger_showing_phone", "passenger_talk", "incoming_message", "phone", "child_activity",
)

#: ``safety.sos.state``: the state machine for a driver who does not answer (C4, C5).
SosState = Literal["normal", "alarm", "asking", "countdown", "sos_sent"]


# =====================================================================================================================
# Trip (simulator, P4)
# =====================================================================================================================


class Position(ContractModel):
    """GPS position of the (simulated) car."""

    lat: float = 0.0
    lon: float = 0.0


class Poi(ContractModel):
    """A point of interest on the route (``simulator/stops.json``). ``dist_km`` is from the car's position."""

    id: str
    category: str
    name: str | None = None
    dist_km: float | None = None
    km: float | None = None
    lat: float | None = None
    lon: float | None = None


class Trip(ContractModel):
    """Simulated trip context (B7), returned by ``simulator.Simulator.tick()``."""

    speed_kmh: float = 0.0
    road: str = "city"
    elapsed_min: float = 0.0
    pos: Position = Field(default_factory=Position)
    eta_min: float | None = None
    scene: int | None = None
    stopped: bool = False
    at_poi: Poi | None = None
    next_poi: Poi | None = None


# =====================================================================================================================
# Perception (P1): PerceptionFrame and the parts of State it fills
# =====================================================================================================================


class Occupant(ContractModel):
    """One person in the car. The seat comes from the camera that sees the person, or from a declaration."""

    id: int
    seat: Seat
    source: OccupantSource = "declared"
    profile: str | None = None
    role: PersonRole = "adult"
    profile_score: float | None = None  # SFace cosine similarity of the recognised profile (P1, debug)


class Eyes(ContractModel):
    """Driver eye metrics (AS2). ``microsleep`` is decided by P2 from ``closed_ms``; P1 always sends ``false``."""

    ear: float | None = None
    eye_used: Literal["left", "right"] | None = None
    perclos_60s: float = 0.0
    blink_ms: float | None = None
    microsleep: bool = False
    reliable: bool = False  # no data = not reliable; AS14: only head metrics are used then
    # P1 additions (docs/perception.md section 9)
    closed_ms: float = 0.0  # duration of the current eye closure; P2's microsleep rule reads it
    state: EyeState = "UNKNOWN"
    squint: bool = False  # lowered but not closed: not in PERCLOS, not in closed_ms
    long_closure: bool = False  # current closure longer than a blink (> 500 ms)
    blink_rate: float | None = None  # blinks per minute over 60 s (fatigue term)
    open_baseline: float | None = None  # open-eye EAR reference


class Head(ContractModel):
    """Head pose in degrees (AS4) and the nod / shake answer (AS8, only inside the dialog window).

    The angles are ``null`` when the face is missing: 0 would mean "straight ahead".
    """

    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None
    nodding: bool = False  # slow fatigue drop of the head, not a "yes"
    answer: HeadAnswer | None = None


class Gaze(ContractModel):
    """Gaze zone and glance statistics (AS5, AS6). ``source``: ``face`` (landmarks) or ``body`` (rear-seat rule)."""

    zone: GazeZone = "unknown"
    conf: float = 0.0
    source: Literal["face", "body"] | None = None
    off_road_ms: float = 0.0  # current glance away from the road
    vats_60s: int = 0  # off-road glances shorter than 2 s in the last 60 s
    entropy_60s: float | None = None
    # P1 additions
    calibrated: bool = False  # a calibration profile is loaded; without it the zone is always unknown
    off_road_60s_ms: float = 0.0  # total off-road time in the last 60 s (short mirror glances excluded)
    lap_pattern: bool = False  # >= 3 lap glances in 20 s or one > 2 s, hands unseen


class Phone(ContractModel):
    """Phone in the driver's hand (AS7). ``source``: ``detector`` (seen) or ``lap_pattern`` (glances at the lap)."""

    in_use: bool = False
    conf: float = 0.0
    source: Literal["detector", "lap_pattern"] | None = None
    # P1 additions
    near_face: bool = False
    side: Literal["left", "right"] | None = None
    usage: Literal["call", "hand", "visible", "lap"] | None = None
    foreign_seen: bool = False  # a phone that is not the driver's (passenger's, far from the driver's face)


class DriverPerception(ContractModel):
    """What P1 reports about the driver (the ``driver`` block of a PerceptionFrame)."""

    eyes: Eyes = Field(default_factory=Eyes)
    head: Head = Field(default_factory=Head)
    gaze: Gaze = Field(default_factory=Gaze)
    yawn: bool = False
    speaking: bool = False
    phone: Phone = Field(default_factory=Phone)
    gesture: str | None = None  # one of GESTURES, held; only inside the dialog window or with a raised hand
    # P1 additions
    monitoring_ok: bool = True  # the driver camera sees the face; source of safety.monitoring_ok (C7)
    monitoring_reason: str | None = None  # one of MONITORING_REASONS
    monitoring_warnings: list[str] = Field(default_factory=list)  # too_dark / blurred / face_too_small, face seen
    face_too_small: bool = False
    face_conf: float | None = None  # 0..1 from the face width (R-FL3); null = no monitoring result yet
    camera_mode: Literal["color", "mono"] | None = None
    gesture_score: float | None = None


class Passenger(ContractModel):
    """Front-right passenger, from the passenger camera (A-P). ``answer`` only in a window addressed to them."""

    present: bool = False
    awake: bool = True
    eyes_closed_s: float = 0.0
    speaking: bool = False
    holding_phone: bool = False
    gesture: str | None = None
    answer: HeadAnswer | None = None
    # P1 additions: the passenger camera's own monitoring, same meaning as for the driver
    monitoring_reason: str | None = None  # why the passenger camera does not see anyone
    monitoring_ok: bool = True
    monitoring_warnings: list[str] = Field(default_factory=list)
    camera_mode: Literal["color", "mono"] | None = None
    face_conf: float | None = None


class CameraPerf(ContractModel):
    """Per-camera performance (J1)."""

    capture_fps: float = 0.0
    process_fps: float = 0.0
    dropped_frames: int = 0
    # P1 additions
    available: bool = True
    capture_ts: float | None = None  # time.time() of the newest frame used from this camera
    age_ms: float | None = None  # age of the camera's result at publication
    dropped_results: int = 0


class PerceptionPerf(ContractModel):
    """The ``perf`` fields P1 fills: fps per camera, ms per model (p50), end-to-end latency, CPU / RAM / GPU."""

    cameras: dict[str, CameraPerf] = Field(default_factory=dict)
    face_driver_ms_p50: float | None = None
    face_passenger_ms_p50: float | None = None
    pose_ms_p50: float | None = None
    phone_ms_p50: float | None = None
    gesture_ms_p50: float | None = None
    sface_ms_p50: float | None = None
    e2e_ms_p95: float | None = None
    cpu: float | None = None
    ram_mb: float | None = None
    gpu: float | None = None
    # P1 additions
    degrade_level: int = 0
    stages_ms: dict[str, Any] = Field(default_factory=dict)  # camera -> model -> {p50, p95, n}
    publish_ts: float | None = None


class PerceptionFrame(ContractModel):
    """One message on ``/ws/perception`` (P1 -> core, 15 Hz). Frames have no ``type`` key.

    ``ts`` = ``time.time()`` at the capture of the newest driver frame (publication time when the driver camera has
    no fresh data).
    """

    ts: float = 0.0
    seq: int = 0
    occupants: list[Occupant] = Field(default_factory=list)
    driver: DriverPerception = Field(default_factory=DriverPerception)
    passenger: Passenger = Field(default_factory=Passenger)
    perf: PerceptionPerf = Field(default_factory=PerceptionPerf)


# =====================================================================================================================
# State (core -> everyone): the blocks P2 computes
# =====================================================================================================================


class Reaction(ContractModel):
    """Reaction times on 3 channels vs. the personal baseline (B1). No answer = ``missed`` + the maximum value."""

    visual_ms: float | None = None  # visual_cue -> gaze back on the road
    verbal_ms: float | None = None  # speak_done of a question -> speech_onset
    gesture_ms: float | None = None  # proposal -> gesture / head answer
    baseline_ms: dict[str, float] = Field(default_factory=dict)  # visual / verbal / gesture: median of the first 3-5
    missed: int = 0
    response_rate_10min: float | None = None


class Driver(DriverPerception):
    """The ``driver`` block of State: P1's perception plus P2's reaction times."""

    reaction: Reaction = Field(default_factory=Reaction)


class Cause(ContractModel):
    """Cause of the distraction, fused from both cameras and the context (B4)."""

    target: str | None = None  # passenger / phone / message / rear
    person_id: int | None = None
    label: str | None = None  # one of CAUSE_LABELS
    glances_30s: int = 0
    conf: float = 0.0
    sources: list[str] = Field(default_factory=list)  # cam_driver, cam_passenger, phone, declared


class Assessment(ContractModel):
    """Scores 0-1 (attention, fatigue F, disengagement D) and risk 0-3 (B2, B3)."""

    attention: float = 1.0
    fatigue: float = 0.0
    disengagement: float = 0.0
    risk: int = 0


class SosStatus(ContractModel):
    """Where the unresponsive-driver state machine is (C4, C5): normal -> alarm -> asking -> countdown -> sos_sent."""

    state: SosState = "normal"
    since_ts: float | None = None  # when the current state started
    countdown_s: float | None = None  # seconds left, only in ``countdown``


class Safety(ContractModel):
    """Safety status (C). ``llm_allowed`` is the veto (C8); ``llm_enabled`` is the director's switch (C6).

    ``level`` is the highest active priority; ``null`` = nothing active (treated as P4).
    """

    level: SafetyLevel | None = None
    alert: str | None = None  # short code of the active alert, e.g. "microsleep", "phone", "monitoring_lost"
    llm_allowed: bool = True
    llm_enabled: bool = True
    monitoring_ok: bool = True
    alarm_ms_last: float | None = None  # threshold crossed -> alarm_played in the browser
    sos: SosStatus = Field(default_factory=SosStatus)  # P2 addition


class LastInput(ContractModel):
    """Last multimodal input (E3): who, on which channel (voice / nod / shake / gesture), what value."""

    from_: int | None = Field(default=None, alias="from")
    channel: str | None = None
    value: str | None = None
    ts: float | None = None


class Interaction(ContractModel):
    """Dialog status (E1, E3). ``addressed_to`` is an ``occupants[].id``."""

    state: str | None = None  # idle / speaking / listening
    addressed_to: int | None = None
    dialog_window_open: bool = False
    last_input: LastInput | None = None


class AssistantStatus(ContractModel):
    """Silence after a refusal (C10, D10): P3-P4 are quiet until ``muted_until``. Safety is never affected."""

    muted_until: float | None = None
    mute_reason: str | None = None  # "driver_refused"


class SafeContact(ContractModel):
    """Trusted contact from the profile (C10). The phone number is only in ``.env``."""

    name: str | None = None
    configured: bool = False
    consent: bool = False
    announce: bool = True  # tell the driver "Îi dau de veste lui {contact}."
    notified_ts: float | None = None  # last notification, for the cooldown
    last_reply_msg_id: str | None = None


class PhoneStatus(ContractModel):
    """The driver's phone over KDE Connect (F1)."""

    connected: bool = False
    battery: int | None = None


class Message(ContractModel):
    """A message in the queue (F). ``app``: sms / whatsapp / contact_app.

    ``text`` is only in the state passed in process to the assistant; core leaves it out of the ``/ws/ui`` broadcast.
    """

    id: str
    app: Literal["sms", "whatsapp", "contact_app"] = "sms"
    from_: str = Field(default="", alias="from")
    state: Literal["pending", "deferred", "read", "replied"] = "pending"
    deferred_reason: str | None = None  # high_speed / high_risk / distraction (F2)
    replyable: bool = False
    ts: float | None = None
    text: str | None = None


class ReminderTrigger(ContractModel):
    """When a reminder fires (K1). Only ``stop_at_category`` is M; ``arrive_destination`` / ``any_stop`` are S."""

    type: str = "stop_at_category"
    category: str | None = None  # a category from simulator/stops.json


class Reminder(ContractModel):
    """A route reminder (K). ``state``: proposed (waits for the confirmation) / active / done."""

    id: str
    task: str
    trigger: ReminderTrigger = Field(default_factory=ReminderTrigger)
    state: Literal["proposed", "active", "done"] = "proposed"
    created_ts: float | None = None


class Media(ContractModel):
    """What is playing (D8)."""

    playing: bool = False
    track_id: str | None = None
    title: str | None = None
    volume: float | None = None
    reason: str | None = None  # disengagement (D8, counts for D6) / driver_request / quiz_offer
    kid_safe: bool = False
    source: str | None = None  # P3 addition (D11): "catalog" (local mp3) or "youtube"


class Intervention(ContractModel):
    """Measured effect of the interventions (D6): attention (and D or F) before vs. after."""

    last: str | None = None  # e.g. music_energetic, delegate, quiz
    effect_pct: float | None = None
    stats: dict[str, float] = Field(default_factory=dict)  # intervention type -> mean effect (0.18 = +18 %)


class AbCounter(ContractModel):
    """The live counter "simple threshold vs. DriveMate" (B8, H4)."""

    naive_alerts: int = 0
    our_alerts: int = 0


class BlindMeters(ContractModel):
    """Meters driven without looking at the road (B6): last glance and whole trip."""

    last: float = 0.0
    trip: float = 0.0


class Scorecard(ContractModel):
    """Trip scorecard (J2, J3)."""

    longest_focus_min: float = 0.0
    hands_free_messages: int = 0
    phone_touches: int = 0
    suggestions_accepted: int = 0
    suggestions_rejected: int = 0
    reminders_done: int = 0


class Integrations(ContractModel):
    """Health of the external pieces: ok / down / off / unknown."""

    phone_bridge: str = "unknown"
    twilio: str = "unknown"
    contact_app: str = "unknown"
    llm: str = "unknown"


class Perf(PerceptionPerf):
    """The full ``perf`` block (J1): P1's fields plus the ones core and the assistant measure."""

    alarm_ms_last: float | None = None
    llm_ttft_ms: float | None = None
    llm_total_ms: float | None = None
    stt_final_ms: float | None = None
    tts_first_audio_ms: float | None = None
    msg_to_voice_ms: float | None = None


class State(ContractModel):
    """The full state built by core at ~10 Hz (section 7). Sent as ``{"type": "state", "state": ...}``."""

    ts: float = 0.0
    seq: int = 0
    trip: Trip = Field(default_factory=Trip)
    occupants: list[Occupant] = Field(default_factory=list)
    driver: Driver = Field(default_factory=Driver)
    passenger: Passenger = Field(default_factory=Passenger)
    conversation: bool = False
    cause: Cause = Field(default_factory=Cause)
    assessment: Assessment = Field(default_factory=Assessment)
    safety: Safety = Field(default_factory=Safety)
    interaction: Interaction = Field(default_factory=Interaction)
    assistant: AssistantStatus = Field(default_factory=AssistantStatus)
    safe_contact: SafeContact = Field(default_factory=SafeContact)
    phone: PhoneStatus = Field(default_factory=PhoneStatus)
    messages: list[Message] = Field(default_factory=list)
    call: dict[str, Any] | None = None  # incoming call (F4, S)
    reminders: list[Reminder] = Field(default_factory=list)
    media: Media = Field(default_factory=Media)
    intervention: Intervention = Field(default_factory=Intervention)
    ab: AbCounter = Field(default_factory=AbCounter)
    blind_m: BlindMeters = Field(default_factory=BlindMeters)
    scorecard: Scorecard = Field(default_factory=Scorecard)
    integrations: Integrations = Field(default_factory=Integrations)
    perf: Perf = Field(default_factory=Perf)


# =====================================================================================================================
# Events
# =====================================================================================================================

#: Events core passes to ``assistant.handle_event`` (proposed by P3, docs/assistant.md section 3.2).
EVENT_TYPES: tuple[str, ...] = (
    "trip_start",              # occupants recognised at start (scene 1)
    "driver_speech",           # addressed driver utterance                    data: text
    "passenger_speech",        # addressed passenger utterance                 data: text, person_id
    "cause_detected",          # D2: state.cause.label is set
    "fatigue_high",            # D3/D10: F above threshold
    "disengagement_high",      # D8: D above threshold, monotonous context
    "media_declined",          # D8: the driver refused the music (no LLM: quiz offer)
    "kss_answer",              # D3: KSS answer                                data: value (1-9)
    "message_received",        # F2 allowed the delivery                      data: msg_id, delivery ("ask"|"read")
    "safe_contact_reply",      # F8: reply of the trusted contact             data: msg_id, delivery
    "message_reply_dictated",  # F3: the driver dictated a reply              data: msg_id, text
    "stop_suggested",          # K3/D3: P2's rule picked a stop               data: poi_id, poi_name, dist_km, task,
                               #                                                    poi_options
    "alert_explain",           # D5: explain the last alert                   data: explanation
    "driver_refused",          # D10: refusal recognised by core (no LLM)     data: text
)

#: Events core only logs on ``/ws/ui`` (event log H3, visual cue C2); they never go to the LLM.
CORE_EVENT_TYPES: tuple[str, ...] = (
    "visual_cue",             # C2: discrete signal, the UI flashes a light / border   data: alert, level
    "distraction_end",        # C2: the distraction is over                  latency_ms = time to come back
    "naive_alert",            # B8: the simple threshold would have alerted  data: reason
    "cause",                  # B4: a new cause of distraction               data: label, target, person_id, conf
    "intervention_effect",    # D2, D6: effect of a remedy, before vs after  data: kind, effect_pct, helped
    "intervention_skipped",   # D6: not enough data before the remedy        data: kind
    "alert",                  # an alert was raised                          data: level, alert
    "alarm",                  # C3: the alarm clip was sent                  data: alarm_id, clip
    "alarm_played",           # C3: the browser played it                    latency_ms = alarm_ms, data: on_target
    "are_you_ok",             # C4: "Ești bine?" asked
    "sos_countdown",          # C5: countdown started                        data: countdown_s
    "sos_cancelled",          # C5: cancelled                                channel: voice / nod / gesture
    "sos_sent",               # F6: call + SMS + Contact page                data: call_ok, sms_ok, page_ok
    "monitoring_lost",        # C7: "Nu te mai văd"                          data: reason
    "monitoring_restored",    # C7
    "reminder_due",           # K2: stopped at a POI of the category         data: reminder_id, poi_id
    "reminder_done", "reminder_kept",  # K2: the answer (or none)   data: reminder_ids, channel
    "trip_report",            # J2, J3: end of the trip (end_trip / reset)   data: report
    "message_deferred",       # F2: "Ți-l citesc imediat ce e liniște."      data: msg_id, reason
    "safe_contact_notified",  # C10: SMS + yellow notice sent                data: contact, sms_ok
    "assistant_action",       # an action was executed                       data: action
    "action_rejected",        # C8: an LLM action was rejected               data: action, reason
    "input",                  # E3: an answer / request arrived              channel, data: value, from
    "llm_toggled",            # C6: director switched the LLM                data: enabled
    "safe_contact_skipped",   # C10: the contact is not told   data: reason (no_contact / no_consent / cooldown)
    "assistant_unmuted",      # C10: the silence after a refusal is over
    "message_queued",         # a new message entered the queue (phone / Contact page / panel)   data: msg_id
    "perception_connected",   # P1 connected to /ws/perception
    "perception_disconnected",
    "phone_bridge_connected", "phone_bridge_disconnected",  # P3's bridge on /ws/phone
    "calibration_prompt",     # P1 calibration step, for the voice           data: zone, step, steps
    "calibrate_done", "calibrate_error", "enroll_done", "enroll_error",  # P1 acks   data: detail
    "reset",                  # director reset: a new trip
)

ALL_EVENT_TYPES: tuple[str, ...] = EVENT_TYPES + tuple(t for t in CORE_EVENT_TYPES if t not in EVENT_TYPES)


class Event(ContractModel):
    """An event: passed to ``assistant.handle_event`` or logged on ``/ws/ui`` (wrapped in :class:`UiEvent`).

    ``type`` is one of :data:`ALL_EVENT_TYPES` (unknown values are tolerated). The optional fields are for the event
    log (H3): who decided (``source``), the one-sentence explanation (principle 4), the input channel, the latency.
    """

    type: str
    ts: float = 0.0
    data: dict[str, Any] = Field(default_factory=dict)
    source: DecisionSource | None = None
    text: str | None = None
    explanation: str | None = None  # e.g. "ai privit în jos 2,1 s la 110 km/h"
    channel: str | None = None
    latency_ms: float | None = None


# =====================================================================================================================
# Actions (section 6): the only things the LLM may ask for
# =====================================================================================================================

ActionType = Literal[
    "speak", "ask", "suggest_media", "play_media", "stop_media", "read_message",
    "reply_message", "create_reminder", "complete_reminder", "suggest_stop",
    "delegate", "show_on_screen", "set_preference", "stay_silent",
    "search_media",  # P3 addition (D11): internal to the assistant, see ASSISTANT_INTERNAL_ACTIONS
]
ACTION_TYPES: tuple[str, ...] = (
    "speak", "ask", "suggest_media", "play_media", "stop_media", "read_message",
    "reply_message", "create_reminder", "complete_reminder", "suggest_stop",
    "delegate", "show_on_screen", "set_preference", "stay_silent",
    "search_media",
)

#: Actions the assistant resolves inside ``handle_event`` (D11: ``search_media`` becomes an ``ask`` with
#: ``expects="choice"``). They never reach core: if one does, core's validator (C8) rejects it.
ASSISTANT_INTERNAL_ACTIONS: frozenset[str] = frozenset({"search_media"})

#: Who an utterance is addressed to.
Addressee = Literal["driver", "passenger", "rear", "all"]
#: ``choice`` (D11) only comes from the assistant's rules, never from the LLM, and always with ``options``.
Expects = Literal["yes_no", "kss", "free", "choice"]
MediaKind = Literal["music", "podcast"]

_ANY_LEVEL: frozenset[str] = frozenset(SAFETY_LEVELS)
_P3_P4: frozenset[str] = frozenset({"P3", "P4"})

#: Section 6, column "Permisă la": the safety levels at which each action may run. ``safety.level = null`` counts as
#: P4. ``stop_media``, ``complete_reminder``, ``show_on_screen`` and ``stay_silent`` are allowed at any level.
ACTION_ALLOWED_LEVELS: dict[str, frozenset[str]] = {
    "speak": _P3_P4,
    "ask": _P3_P4,
    "suggest_media": frozenset({"P4"}),
    "play_media": frozenset({"P4"}),
    "stop_media": _ANY_LEVEL,
    "read_message": _P3_P4,  # + the F2 timing rule
    "reply_message": _P3_P4,
    "create_reminder": _P3_P4,
    "complete_reminder": _ANY_LEVEL,
    "suggest_stop": _P3_P4,
    "delegate": frozenset({"P3"}),
    "show_on_screen": _ANY_LEVEL,
    "set_preference": frozenset({"P4"}),
    "stay_silent": _ANY_LEVEL,
    "search_media": frozenset({"P4"}),  # D11, comfort; internal to the assistant
}

#: Section 6, column "Cere confirmare". ``read_message`` needs one only when passengers are present.
ACTION_NEEDS_CONFIRMATION: frozenset[str] = frozenset({
    "suggest_media", "reply_message", "create_reminder", "complete_reminder", "suggest_stop", "set_preference",
})
ACTION_CONFIRM_IF_PASSENGERS: frozenset[str] = frozenset({"read_message"})
#: ``set_preference`` keys that run without "Bine?" (D11): the driver asked explicitly ("mai încet") and it is undone
#: just as easily. Every other preference still needs a confirmation.
NO_CONFIRMATION_PREFERENCES: frozenset[str] = frozenset({"volume"})


class Action(ContractModel):
    """One action, flat: the shape the LLM fills and the assistant returns from ``handle_event``.

    Which fields each ``type`` needs is defined by the typed models below; :meth:`typed` checks them.

    Extra fields (not in the section 6 table):
        source: ``"LLM"`` or ``"RULE"`` (principle 5; fixed texts are RULE).
        clip_id: a pre-generated clip that says exactly ``text``; core plays it instead of TTS.
        needs_confirmation: core runs the action only after a "yes" (voice, nod or thumbs-up).
        streamed: this speak / ask was already sent to TTS while the LLM was streaming; do not say it twice.
        volume: for ``play_media``.

    YouTube media (P3, D11, ``docs/assistant.md`` section 6.1):
        query, kind: for ``search_media`` (internal to the assistant, never reaches core).
        options: for ``ask`` with ``expects="choice"``: the search results
            (``[{track_id, title, full_title, channel, duration_s, offered}]``).
        title: for ``play_media``: the short spoken title; ``track_id`` may be ``"yt:<video id>"``, played from
            ``assistant.music.track_url(track_id)`` (``/media/yt/<id>.m4a``).
    """

    type: ActionType
    to: Addressee | None = None
    text: str | None = None
    question: str | None = None
    expects: Expects | None = None
    options: list[dict[str, Any]] | None = None
    track_id: str | None = None
    title: str | None = None
    query: str | None = None
    kind: MediaKind | None = None
    volume: float | None = None
    reason: str | None = None
    msg_id: str | None = None
    task: str | None = None
    trigger: ReminderTrigger | None = None
    reminder_id: str | None = None
    poi_id: str | None = None
    to_person: str | None = None
    target: str | None = None
    key: str | None = None
    value: Any | None = None
    source: DecisionSource = "LLM"
    clip_id: str | None = None
    needs_confirmation: bool = False
    streamed: bool = False

    def typed(self) -> TypedAction:
        """The typed model of this action; raises ``pydantic.ValidationError`` when a parameter is missing."""
        return parse_action(self.model_dump(exclude_none=True))


class _TypedActionBase(ContractModel):
    source: DecisionSource = "LLM"
    clip_id: str | None = None
    needs_confirmation: bool = False
    streamed: bool = False


class SpeakAction(_TypedActionBase):
    """Say something. At most 15 words to the driver."""

    type: Literal["speak"] = "speak"
    to: Addressee = "driver"
    text: str


class AskAction(_TypedActionBase):
    """Ask a question; core opens the dialog window after ``speak_done``. A ``choice`` question carries its options."""

    type: Literal["ask"] = "ask"
    to: Addressee = "driver"
    question: str
    expects: Expects
    options: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def _choice_has_options(self) -> AskAction:
        if self.expects == "choice" and not self.options:
            raise ValueError("an ask with expects='choice' needs options")
        return self


class SuggestMediaAction(_TypedActionBase):
    """Propose a track from the catalog (filtered on profile and cabin). Needs a confirmation."""

    type: Literal["suggest_media"] = "suggest_media"
    track_id: str
    reason: str


class PlayMediaAction(_TypedActionBase):
    """Play a catalog track (``t07``) or a YouTube result (``yt:<video id>``, D11)."""

    type: Literal["play_media"] = "play_media"
    track_id: str
    volume: float | None = None
    title: str | None = None


class StopMediaAction(_TypedActionBase):
    type: Literal["stop_media"] = "stop_media"
    track_id: str | None = None


class ReadMessageAction(_TypedActionBase):
    """Read a queued message aloud (after the F2 rule; confirmation if passengers are present)."""

    type: Literal["read_message"] = "read_message"
    msg_id: str


class ReplyMessageAction(_TypedActionBase):
    """Reply through the driver's phone. Needs a confirmation."""

    type: Literal["reply_message"] = "reply_message"
    msg_id: str
    text: str


class CreateReminderAction(_TypedActionBase):
    """K1: a route reminder. The category must exist in stops.json. Needs a confirmation."""

    type: Literal["create_reminder"] = "create_reminder"
    task: str
    trigger: ReminderTrigger


class CompleteReminderAction(_TypedActionBase):
    type: Literal["complete_reminder"] = "complete_reminder"
    reminder_id: str


class SuggestStopAction(_TypedActionBase):
    """Propose a stop; only a POI proposed by P2's rule (K3). Needs a confirmation."""

    type: Literal["suggest_stop"] = "suggest_stop"
    poi_id: str


class DelegateAction(_TypedActionBase):
    """Hand a task to a passenger ("Maria, poți să-i povestești tu?")."""

    type: Literal["delegate"] = "delegate"
    to_person: str
    task: str


class ShowOnScreenAction(_TypedActionBase):
    """Text on the dashboard, for the passenger (the driver never reads)."""

    type: Literal["show_on_screen"] = "show_on_screen"
    text: str
    target: str = "passenger"


class SetPreferenceAction(_TypedActionBase):
    """Change a preference within fixed limits (only P3-P4 thresholds). Needs a confirmation."""

    type: Literal["set_preference"] = "set_preference"
    key: str
    value: Any


class StaySilentAction(_TypedActionBase):
    """Say nothing, with the reason in the log (e.g. ``conversation``, ``driver_refused``, ``safety_veto``)."""

    type: Literal["stay_silent"] = "stay_silent"
    reason: str


class SearchMediaAction(_TypedActionBase):
    """D11: search YouTube. Internal to the assistant (see ASSISTANT_INTERNAL_ACTIONS); core never executes it."""

    type: Literal["search_media"] = "search_media"
    query: str
    kind: MediaKind = "music"


TypedAction = Annotated[
    (
        SpeakAction | AskAction | SuggestMediaAction | PlayMediaAction | StopMediaAction | ReadMessageAction
        | ReplyMessageAction | CreateReminderAction | CompleteReminderAction | SuggestStopAction | DelegateAction
        | ShowOnScreenAction | SetPreferenceAction | StaySilentAction | SearchMediaAction
    ),
    Field(discriminator="type"),
]

#: Action type -> its typed model.
ACTION_MODELS: dict[str, type[_TypedActionBase]] = {
    "speak": SpeakAction,
    "ask": AskAction,
    "suggest_media": SuggestMediaAction,
    "play_media": PlayMediaAction,
    "stop_media": StopMediaAction,
    "read_message": ReadMessageAction,
    "reply_message": ReplyMessageAction,
    "create_reminder": CreateReminderAction,
    "complete_reminder": CompleteReminderAction,
    "suggest_stop": SuggestStopAction,
    "delegate": DelegateAction,
    "show_on_screen": ShowOnScreenAction,
    "set_preference": SetPreferenceAction,
    "stay_silent": StaySilentAction,
    "search_media": SearchMediaAction,
}

_TYPED_ACTION: TypeAdapter[TypedAction] = TypeAdapter(TypedAction)


def parse_action(data: dict[str, Any] | Action) -> TypedAction:
    """Validate one action against its typed model (unknown type or missing parameter -> ``ValidationError``)."""
    if isinstance(data, Action):
        data = data.model_dump(exclude_none=True)
    return _TYPED_ACTION.validate_python(data)


# =====================================================================================================================
# /ws/perception: core <-> P1
# =====================================================================================================================

PerceptionCommandName = Literal["dialog_window", "calibrate", "debug", "enroll"]
_PERCEPTION_COMMANDS: frozenset[str] = frozenset({"dialog_window", "calibrate", "debug", "enroll"})


class PerceptionCommand(ContractModel):
    """Core -> P1. Core sends ``{"type": "command", "cmd": ...}``; ``{"cmd": ...}`` and ``{"type": "<cmd>"}`` parse too.

    * ``dialog_window {open, to, until}``: look for head answers / gestures; ``to`` = seat or ``occupants[].id``,
      ``until`` = ``time.time()`` when the window closes (P1 default: 6 s).
    * ``calibrate {profile, quick}``: gaze-zone calibration; ``quick`` = ~15 s road + mirrors over the saved profile.
    * ``debug {on}``: debug overlay on the MJPEG video.
    * ``enroll {name, camera}``: face enrolment for identity.
    """

    type: Literal["command"] = "command"
    cmd: PerceptionCommandName
    open: bool = False
    to: Literal["driver", "passenger"] | int | None = None
    until: float | None = None
    on: bool = False
    profile: str | None = None
    name: str | None = None
    quick: bool = False
    camera: Literal["driver", "passenger"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_short_forms(cls, data: Any) -> Any:
        if isinstance(data, dict) and "cmd" not in data and data.get("type") in _PERCEPTION_COMMANDS:
            data = {**data, "cmd": data["type"], "type": "command"}
        return data


class PerceptionAck(ContractModel):
    """P1 -> core: the answer to a command. ``status``: ok / error / not_implemented / queued / started / progress /
    done."""

    type: Literal["ack"] = "ack"
    cmd: str
    status: str
    detail: Any = None


class CalibrationPrompt(ContractModel):
    """P1 -> core: one calibration step, so the voice can read the instruction."""

    type: Literal["calibration_prompt"] = "calibration_prompt"
    profile: str | None = None
    step: int | None = None
    steps: int | None = None
    zone: str | None = None
    mode: Literal["owl", "lizard"] | None = None
    text: str | None = None
    remaining_s: float | None = None


PerceptionMessage = PerceptionFrame | PerceptionAck | CalibrationPrompt


def parse_perception_message(data: dict[str, Any]) -> PerceptionMessage:
    """A message from P1: an ack, a calibration prompt, or (no ``type`` key) a PerceptionFrame."""
    kind = data.get("type")
    if kind == "ack":
        return PerceptionAck.model_validate(data)
    if kind == "calibration_prompt":
        return CalibrationPrompt.model_validate(data)
    return PerceptionFrame.model_validate(data)


# =====================================================================================================================
# /ws/ui: core <-> browser (P4's UI and P3's voice)
# =====================================================================================================================

# --- core -> browser -------------------------------------------------------------------------------------------------


class UiState(ContractModel):
    """The state, 10 Hz."""

    type: Literal["state"] = "state"
    state: State = Field(default_factory=State)


class UiEvent(ContractModel):
    """One entry of the event log (and ``visual_cue``)."""

    type: Literal["event"] = "event"
    event: Event


class SpeakSentence(ContractModel):
    id: str
    text: str
    url: str  # /tts/<id>.mp3


class UiSpeak(ContractModel):
    """Say something (built by ``assistant.tts.speak_message``). ``id`` comes back in ``speak_done``."""

    type: Literal["speak"] = "speak"
    id: str
    to: Addressee = "driver"
    is_question: bool = False
    expects: Expects | None = None
    text: str = ""
    clip_url: str | None = None  # a pre-generated clip replaces TTS
    sentences: list[SpeakSentence] = Field(default_factory=list)


class UiSpeakControl(ContractModel):
    """Yield the floor (D4): pause / resume ("...cum ziceam") / stop. A higher priority sends ``stop``."""

    type: Literal["speak_control"] = "speak_control"
    action: Literal["pause", "resume", "stop"]


class UiAlarm(ContractModel):
    """Play an alarm clip now; it stops speech and music. ``id`` comes back in ``alarm_played``."""

    type: Literal["alarm"] = "alarm"
    id: str
    clip_url: str  # /sounds/clips/alarm_<name>.mp3, are_you_ok.mp3, passenger_instructions_*.mp3, ...
    level: SafetyLevel | None = None
    alert: str | None = None


class UiMedia(ContractModel):
    """Music: play / stop / volume."""

    type: Literal["media"] = "media"
    action: Literal["play", "stop", "volume"]
    url: str | None = None  # assistant.music.track_url(track_id): /media/<id>.mp3 or /media/yt/<id>.m4a (D11)
    volume: float | None = None
    track_id: str | None = None
    title: str | None = None
    loop: bool | None = None  # assistant.music.loops(track_id): catalog tracks loop, YouTube results do not


# --- browser -> core -------------------------------------------------------------------------------------------------

#: Known director-panel commands (P4, I2). The list is open: unknown ``cmd`` values are tolerated.
UI_COMMANDS: tuple[str, ...] = (
    "debug",             # on: bool -> forwarded to P1
    "scene",             # value: 1-10
    "start", "pause",
    "time_scale",        # value: 1 / 20
    "speed",             # value: km/h
    "stop_at_next_poi",
    "llm",               # on: bool (C6)
    "declare_occupant",  # value: {profile, role, seat: "rear"}
    "fake_message",      # value: {from, app, text}
    "calibrate",         # value: {profile, quick} -> forwarded to P1
    "enroll",            # value: {name, camera} -> forwarded to P1
    "end_trip",          # the trip report (J2, J3)
    "reset",
)


class UiCommand(ContractModel):
    """A command from the dashboard (director panel, key D, scene jumps)."""

    type: Literal["command"] = "command"
    cmd: str
    on: bool | None = None
    value: Any = None


class UiSpeech(ContractModel):
    """A recognised utterance. Core acts only on ``final`` and ``addressed`` results."""

    type: Literal["speech"] = "speech"
    text: str = ""
    raw: str | None = None
    final: bool = True
    addressed: bool = False  # wake word in the text, or the dialog window was open
    early: Literal["quick", "stable"] | None = None
    wait_ms: float | None = None
    confidence: float | None = None
    ts: float = 0.0


class UiSpeechOnset(ContractModel):
    """Start of the voice (WebAudio), for the verbal reaction time."""

    type: Literal["speech_onset"] = "speech_onset"
    ts: float = 0.0


class UiSpeakDone(ContractModel):
    """The browser finished an utterance. For a question core opens the dialog window."""

    type: Literal["speak_done"] = "speak_done"
    id: str
    is_question: bool = False
    interrupted: bool = False
    ts: float = 0.0


class UiAlarmPlayed(ContractModel):
    """The alarm sound started; ``alarm_ms`` = threshold crossed -> this ``ts``."""

    type: Literal["alarm_played"] = "alarm_played"
    id: str
    ts: float = 0.0


UiToBrowser = Annotated[
    UiState | UiEvent | UiSpeak | UiSpeakControl | UiAlarm | UiMedia, Field(discriminator="type")
]
UiFromBrowser = Annotated[
    UiCommand | UiSpeech | UiSpeechOnset | UiSpeakDone | UiAlarmPlayed, Field(discriminator="type")
]
#: Any message on ``/ws/ui``, in either direction.
UiMessage = Annotated[
    (
        UiState | UiEvent | UiSpeak | UiSpeakControl | UiAlarm | UiMedia
        | UiCommand | UiSpeech | UiSpeechOnset | UiSpeakDone | UiAlarmPlayed
    ),
    Field(discriminator="type"),
]

_UI_FROM_BROWSER: TypeAdapter[UiFromBrowser] = TypeAdapter(UiFromBrowser)
_UI_MESSAGE: TypeAdapter[UiMessage] = TypeAdapter(UiMessage)


def parse_ui_message(data: dict[str, Any]) -> UiMessage:
    """Any ``/ws/ui`` message, by its ``type``."""
    return _UI_MESSAGE.validate_python(data)


def parse_browser_message(data: dict[str, Any]) -> UiFromBrowser:
    """A message the browser sent to core (command, speech, speech_onset, speak_done, alarm_played)."""
    return _UI_FROM_BROWSER.validate_python(data)


# =====================================================================================================================
# /ws/phone: core <-> P3's phone bridge
# =====================================================================================================================


class PhoneMessage(ContractModel):
    """Bridge -> core: a whitelisted notification (SMS / WhatsApp). Becomes a :class:`Message` in the queue."""

    type: Literal["phone_message"] = "phone_message"
    notification_id: str = ""
    app: Literal["sms", "whatsapp"] = "sms"
    from_: str = Field(default="", alias="from")
    text: str = ""
    replyable: bool = False
    ts: float = 0.0


class PhoneCall(ContractModel):
    """Bridge -> core: incoming call (F4, S)."""

    type: Literal["call"] = "call"
    from_: str = Field(default="", alias="from")
    state: str = "ringing"
    ts: float = 0.0


class PhoneStatusMessage(ContractModel):
    """Bridge -> core: connection and battery, periodically. Fills ``state.phone``."""

    type: Literal["phone_status"] = "phone_status"
    connected: bool = False
    battery: int | None = None


class PhoneResult(ContractModel):
    """Bridge -> core: the outcome of a ``send_reply`` / ``send_sms``."""

    type: Literal["phone_result"] = "phone_result"
    request_id: str | None = None
    ok: bool = False
    error: str | None = None


class SendReply(ContractModel):
    """Core -> bridge: reply through the notification's reply action (WhatsApp)."""

    type: Literal["send_reply"] = "send_reply"
    request_id: str
    notification_id: str
    text: str


class SendSms(ContractModel):
    """Core -> bridge: SMS from the driver's phone. ``to`` is a role; the numbers are only in ``.env``."""

    type: Literal["send_sms"] = "send_sms"
    request_id: str
    to: Literal["safe_contact", "emergency"]
    text: str


PhoneEvent = Annotated[PhoneMessage | PhoneCall | PhoneStatusMessage | PhoneResult, Field(discriminator="type")]
PhoneCommand = Annotated[SendReply | SendSms, Field(discriminator="type")]

_PHONE_EVENT: TypeAdapter[PhoneEvent] = TypeAdapter(PhoneEvent)
_PHONE_COMMAND: TypeAdapter[PhoneCommand] = TypeAdapter(PhoneCommand)


def parse_phone_event(data: dict[str, Any]) -> PhoneEvent:
    """A message from the phone bridge."""
    return _PHONE_EVENT.validate_python(data)


def parse_phone_command(data: dict[str, Any]) -> PhoneCommand:
    """A command for the phone bridge."""
    return _PHONE_COMMAND.validate_python(data)


# =====================================================================================================================
# Reports: SOS (C5, F6) and the trusted contact (C10, F8). Texts come from core/config/templates.yaml, never the LLM.
# =====================================================================================================================


class SosReport(ContractModel):
    """Argument of ``integrations.twilio_call.place_sos_call(report)`` and ``contact_app.push_sos(report)``."""

    driver_name: str = ""
    unresponsive_s: float = 0.0
    occupants_n: int = 1
    passenger_state: Literal["awake", "asleep", "absent"] = "absent"
    pos: Position = Field(default_factory=Position)
    maps_url: str = ""
    time_hhmm: str = ""
    ts: float = 0.0
    text: str = ""  # the rendered template, read by Twilio <Say> and sent by SMS


class SafeContactNotice(ContractModel):
    """Argument of ``contact_app.push_safe_contact(info)``: the yellow "{name} pare obosit" notice."""

    contact_name: str = ""
    driver_name: str = ""
    elapsed_min: float = 0.0
    eta_min: float | None = None
    pos: Position = Field(default_factory=Position)
    maps_url: str = ""
    ts: float = 0.0
    text: str = ""  # the rendered template (same text as the SMS)


__all__ = [
    "ACTION_ALLOWED_LEVELS",
    "ACTION_CONFIRM_IF_PASSENGERS",
    "ACTION_MODELS",
    "ACTION_NEEDS_CONFIRMATION",
    "ACTION_TYPES",
    "ALL_EVENT_TYPES",
    "ASSISTANT_INTERNAL_ACTIONS",
    "CAUSE_LABELS",
    "CONTRACT_VERSION",
    "CORE_EVENT_TYPES",
    "EVENT_TYPES",
    "GAZE_ZONES",
    "GESTURES",
    "LLM_VETO_LEVELS",
    "MONITORING_REASONS",
    "NO_CONFIRMATION_PREFERENCES",
    "SAFETY_LEVELS",
    "UI_COMMANDS",
    "AbCounter",
    "Action",
    "ActionType",
    "Addressee",
    "AskAction",
    "Assessment",
    "AssistantStatus",
    "BlindMeters",
    "CalibrationPrompt",
    "CameraPerf",
    "Cause",
    "CompleteReminderAction",
    "ContractModel",
    "CreateReminderAction",
    "DelegateAction",
    "Driver",
    "DriverPerception",
    "Event",
    "Expects",
    "Eyes",
    "Gaze",
    "GazeZone",
    "Head",
    "Integrations",
    "Interaction",
    "Intervention",
    "LastInput",
    "Media",
    "MediaKind",
    "Message",
    "Occupant",
    "Passenger",
    "PerceptionAck",
    "PerceptionCommand",
    "PerceptionFrame",
    "PerceptionMessage",
    "PerceptionPerf",
    "Perf",
    "Phone",
    "PhoneCall",
    "PhoneCommand",
    "PhoneEvent",
    "PhoneMessage",
    "PhoneResult",
    "PhoneStatus",
    "PhoneStatusMessage",
    "PlayMediaAction",
    "Poi",
    "Position",
    "Reaction",
    "ReadMessageAction",
    "Reminder",
    "ReminderTrigger",
    "ReplyMessageAction",
    "SafeContact",
    "SafeContactNotice",
    "Safety",
    "SafetyLevel",
    "Scorecard",
    "SearchMediaAction",
    "SendReply",
    "SendSms",
    "SetPreferenceAction",
    "ShowOnScreenAction",
    "SosReport",
    "SosState",
    "SosStatus",
    "SpeakAction",
    "SpeakSentence",
    "State",
    "StaySilentAction",
    "StopMediaAction",
    "SuggestMediaAction",
    "SuggestStopAction",
    "Trip",
    "TypedAction",
    "UiAlarm",
    "UiAlarmPlayed",
    "UiCommand",
    "UiEvent",
    "UiFromBrowser",
    "UiMedia",
    "UiMessage",
    "UiSpeak",
    "UiSpeakControl",
    "UiSpeakDone",
    "UiSpeech",
    "UiSpeechOnset",
    "UiState",
    "UiToBrowser",
    "parse_action",
    "parse_browser_message",
    "parse_perception_message",
    "parse_phone_command",
    "parse_phone_event",
    "parse_ui_message",
    "to_wire",
]
