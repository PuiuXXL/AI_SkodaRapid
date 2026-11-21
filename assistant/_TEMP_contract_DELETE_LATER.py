"""
###############################################################################
#                                                                             #
#   TEMPORARY FILE - DELETE WHEN shared/contracts.py EXISTS                   #
#                                                                             #
#   This is a provisional copy of the JSON contract v2 written by P3 so the   #
#   assistant can be built and tested before P2 publishes the real one.       #
#                                                                             #
#   NOTE FOR P2 (owner of shared/contracts.py):                               #
#   1. Nothing in assistant/ imports this file directly. Everything goes      #
#      through assistant/contract.py, which AUTOMATICALLY uses                #
#      shared/contracts.py as soon as it exists and only falls back here.     #
#   2. When shared/contracts.py is published:                                 #
#        - make sure it defines the names listed in assistant/contract.py     #
#          (__all__), or tell P3 which names differ;                          #
#        - run `pytest tests/assistant` to check compatibility;               #
#        - delete this file.                                                  #
#   3. Feel free to copy any model from here into shared/contracts.py:        #
#      they follow DriveMate-PLAN-FINAL.md section 6 (actions) and section 7  #
#      (state) field by field.                                                #
#                                                                             #
###############################################################################

Provisional Pydantic v2 models of the DriveMate contract, as used by P3.

Contents:

* **State** (plan section 7): the full ~10 Hz state produced by core. Every field
  has a default so partial JSON (test fixtures, early core versions) still parses,
  and unknown fields are kept (``extra="allow"``) so newer core versions never break
  the assistant.
* **Event**: what core passes to ``assistant.client.handle_event(event, state)``.
  The plan does not list event types, so :data:`EVENT_TYPES` is P3's proposal.
* **Action** (plan section 6): the only things the LLM may ask for. Core validates
  them again (plan C, "validate de C") before executing.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

#: Contract version this temporary copy follows (plan section 7: "contractul v2").
CONTRACT_VERSION = "2.1-temp-p3"


class _Model(BaseModel):
    """Base model: tolerant to unknown fields so newer core versions never break P3."""

    model_config = ConfigDict(extra="allow")


# =============================================================================
# State (plan section 7)
# =============================================================================

#: Gaze zones (plan section 7). ``unknown`` never triggers an alert.
GazeZone = Literal[
    "road", "mirror_left", "mirror_right", "mirror_rear", "cluster", "infotainment",
    "lap", "passenger", "rear_seat", "away", "unknown",
]

#: Safety / priority levels (plan section 5). P0 = most critical.
SafetyLevel = Literal["P0", "P1", "P2", "P3", "P4"]


class Poi(_Model):
    """A point of interest on the route (simulator/stops.json, owned by P4)."""

    id: str
    category: str
    dist_km: Optional[float] = None
    name: Optional[str] = None


class Position(_Model):
    """GPS position of the (simulated) car."""

    lat: float = 0.0
    lon: float = 0.0


class Trip(_Model):
    """Simulated trip context (plan B7): speed, road, ETA, stops."""

    speed_kmh: float = 0.0
    road: str = "city"
    elapsed_min: float = 0.0
    pos: Position = Field(default_factory=Position)
    eta_min: Optional[float] = None
    scene: Optional[int] = None
    stopped: bool = False
    at_poi: Optional[Poi] = None
    next_poi: Optional[Poi] = None


class Occupant(_Model):
    """One person in the car. ``source`` says how we know: a camera or declared."""

    id: int
    seat: Literal["driver", "front_right", "rear"]
    source: Literal["cam_driver", "cam_passenger", "declared"] = "declared"
    profile: Optional[str] = None
    role: Literal["adult", "child"] = "adult"


class Eyes(_Model):
    """Driver eye metrics (P1, plan AS2)."""

    ear: Optional[float] = None
    eye_used: Optional[str] = None
    perclos_60s: float = 0.0
    blink_ms: Optional[float] = None
    microsleep: bool = False
    reliable: bool = True


class Head(_Model):
    """Driver head pose and nod/shake answer (P1, plan AS4, AS8)."""

    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    nodding: bool = False
    answer: Optional[Literal["yes", "no"]] = None


class Gaze(_Model):
    """Driver gaze zone and glance statistics (P1, plan AS5, AS6)."""

    zone: GazeZone = "unknown"
    conf: float = 0.0
    source: Optional[str] = None
    off_road_ms: float = 0.0
    vats_60s: int = 0
    entropy_60s: Optional[float] = None


class Phone(_Model):
    """Phone in the driver's hand (P1, plan AS7)."""

    in_use: bool = False
    conf: float = 0.0
    source: Optional[Literal["detector", "lap_pattern"]] = None


class Reaction(_Model):
    """Reaction times on 3 channels vs. the personal baseline (P2, plan B1)."""

    visual_ms: Optional[float] = None
    verbal_ms: Optional[float] = None
    gesture_ms: Optional[float] = None
    baseline_ms: dict[str, float] = Field(default_factory=dict)
    missed: int = 0
    response_rate_10min: Optional[float] = None


class Driver(_Model):
    """Everything perceived about the driver (P1) plus reaction data (P2)."""

    eyes: Eyes = Field(default_factory=Eyes)
    head: Head = Field(default_factory=Head)
    gaze: Gaze = Field(default_factory=Gaze)
    yawn: bool = False
    speaking: bool = False
    phone: Phone = Field(default_factory=Phone)
    gesture: Optional[str] = None
    reaction: Reaction = Field(default_factory=Reaction)


class Passenger(_Model):
    """Front-right passenger, from the passenger camera (P1, plan A-P)."""

    present: bool = False
    awake: bool = True
    eyes_closed_s: float = 0.0
    speaking: bool = False
    holding_phone: bool = False
    gesture: Optional[str] = None
    answer: Optional[Literal["yes", "no"]] = None


class Cause(_Model):
    """Cause of the distraction, fused from both cameras (P2, plan B4)."""

    target: Optional[str] = None
    person_id: Optional[int] = None
    label: Optional[str] = None
    glances_30s: int = 0
    conf: float = 0.0
    sources: list[str] = Field(default_factory=list)


class Assessment(_Model):
    """Scores 0-1 (attention, fatigue F, disengagement D) and risk 0-3 (P2, plan B2, B3)."""

    attention: float = 1.0
    fatigue: float = 0.0
    disengagement: float = 0.0
    risk: int = 0


class Safety(_Model):
    """Safety status (P2, plan C). ``llm_allowed`` is the veto; ``llm_enabled`` the director switch."""

    level: Optional[SafetyLevel] = None
    alert: Optional[str] = None
    llm_allowed: bool = True
    llm_enabled: bool = True
    monitoring_ok: bool = True
    alarm_ms_last: Optional[float] = None


class LastInput(_Model):
    """Last multimodal input (plan E3): who, on which channel, what value."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    from_: Optional[int] = Field(default=None, alias="from")
    channel: Optional[str] = None
    value: Optional[str] = None
    ts: Optional[float] = None


class Interaction(_Model):
    """Dialog status (plan E1, E3): is the assistant speaking, is the dialog window open."""

    state: Optional[str] = None
    addressed_to: Optional[int] = None
    dialog_window_open: bool = False
    last_input: Optional[LastInput] = None


class AssistantStatus(_Model):
    """Silence after a refusal (plan C10, D10). Safety is never affected."""

    muted_until: Optional[float] = None
    mute_reason: Optional[str] = None


class SafeContact(_Model):
    """Trusted contact from the profile (plan C10). The phone number is only in .env."""

    name: Optional[str] = None
    configured: bool = False
    consent: bool = False
    announce: bool = True
    notified_ts: Optional[float] = None
    last_reply_msg_id: Optional[str] = None


class PhoneStatus(_Model):
    """Driver's phone connection over KDE Connect (plan F1)."""

    connected: bool = False
    battery: Optional[int] = None


class Message(_Model):
    """A message in the queue (plan F). ``text`` is optional: P2 may keep it out of the state."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    app: Literal["sms", "whatsapp", "contact_app"] = "sms"
    from_: str = Field(default="", alias="from")
    state: Literal["pending", "deferred", "read", "replied"] = "pending"
    deferred_reason: Optional[str] = None
    replyable: bool = False
    ts: Optional[float] = None
    text: Optional[str] = None


class ReminderTrigger(_Model):
    """When a reminder fires (plan K1): at a stop of a given POI category."""

    type: str = "stop_at_category"
    category: Optional[str] = None


class Reminder(_Model):
    """A route reminder (plan K)."""

    id: str
    task: str
    trigger: ReminderTrigger = Field(default_factory=ReminderTrigger)
    state: Literal["proposed", "active", "done"] = "proposed"
    created_ts: Optional[float] = None


class Media(_Model):
    """What is playing (plan D8)."""

    playing: bool = False
    track_id: Optional[str] = None
    title: Optional[str] = None
    volume: Optional[float] = None
    reason: Optional[str] = None
    kid_safe: bool = False
    # P3 addition (YouTube, docs/assistant.md section 6.1): "catalog" or "youtube".
    source: Optional[str] = None


class State(_Model):
    """The full state broadcast by core at ~10 Hz (plan section 7).

    Only the parts the assistant reads are strictly typed; the rest (``intervention``,
    ``ab``, ``blind_m``, ``scorecard``, ``integrations``, ``perf``) is kept as plain
    dictionaries because P3 never interprets them.
    """

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
    call: Optional[dict[str, Any]] = None
    reminders: list[Reminder] = Field(default_factory=list)
    media: Media = Field(default_factory=Media)
    intervention: dict[str, Any] = Field(default_factory=dict)
    ab: dict[str, Any] = Field(default_factory=dict)
    blind_m: dict[str, Any] = Field(default_factory=dict)
    scorecard: dict[str, Any] = Field(default_factory=dict)
    integrations: dict[str, Any] = Field(default_factory=dict)
    perf: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Events (core -> assistant.handle_event). P3 proposal, the plan leaves it open.
# =============================================================================

#: Event types the assistant understands. Unknown types get a generic fallback.
#: ``data`` keys expected for each type are documented in docs/assistant.md.
EVENT_TYPES: tuple[str, ...] = (
    "trip_start",              # scene 1 greeting
    "driver_speech",           # free request addressed to the assistant   data: text
    "passenger_speech",        # free request from the passenger          data: text, person_id
    "cause_detected",          # D2: state.cause.label is set
    "fatigue_high",            # D3/D10: F above threshold
    "disengagement_high",      # D8: D above threshold, context monotonous
    "media_declined",          # D8: the driver refused the music       (handled without LLM: quiz offer)
    "kss_answer",              # D3: the driver answered the KSS question data: value (1-9)
    "message_received",        # F2: allowed by the timing rule           data: msg_id, delivery ("ask"|"read")
    "safe_contact_reply",      # F8: reply of the trusted contact         data: msg_id, delivery
    "message_reply_dictated",  # F3: the driver dictated a reply          data: msg_id, text
    "stop_suggested",          # K3/D3: P2's rule picked a stop           data: poi_id, poi_name, dist_km, task
    "alert_explain",           # D5: explain the last alert               data: explanation
    "driver_refused",          # D10: refusal recognised by core          (handled without LLM)
)


class Event(_Model):
    """One event passed by core to the assistant.

    Attributes:
        type: One of :data:`EVENT_TYPES` (unknown values are tolerated).
        ts: Unix time of the event.
        data: Type-specific payload (see :data:`EVENT_TYPES`).
    """

    type: str
    ts: float = 0.0
    data: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Actions (plan section 6) - the ONLY outputs the LLM may produce
# =============================================================================

#: Allowed action types (plan section 6). Anything else is rejected and logged.
ActionType = Literal[
    "speak", "ask", "suggest_media", "play_media", "stop_media", "read_message",
    "reply_message", "create_reminder", "complete_reminder", "suggest_stop",
    "delegate", "show_on_screen", "set_preference", "stay_silent",
    # P3 addition: internal to the assistant, resolved before handle_event returns (never reaches core).
    "search_media",
]

#: Who an utterance is addressed to.
Addressee = Literal["driver", "passenger", "rear", "all"]


class Action(_Model):
    """One action requested by the assistant (plan section 6).

    A single flat model is used (instead of one class per action) because it maps
    directly to the JSON schema the LLM must follow. Which fields are required for
    each ``type`` is checked in ``assistant/actions.py``:

    ============== ===========================================================
    type           required fields
    ============== ===========================================================
    speak          to, text (<= 15 words to the driver)
    ask            to, question, expects (yes_no | kss | free)
    suggest_media  track_id, reason                       (needs confirmation)
    play_media     track_id                               (volume optional)
    stop_media     -
    read_message   msg_id                                 (P2 timing rule F2)
    reply_message  msg_id, text                           (needs confirmation)
    create_reminder task, trigger{type, category}         (needs confirmation)
    complete_reminder reminder_id                         (needs confirmation)
    suggest_stop   poi_id (one proposed by P2's rule)     (needs confirmation)
    delegate       to_person, task
    show_on_screen text (target = passenger)
    set_preference key, value (within limits)            (needs confirmation)
    stay_silent    reason
    search_media   query, kind (music | podcast)          (P3 internal, see below)
    ============== ===========================================================

    YouTube media (P3 addition, docs/assistant.md section 6.1):
        ``search_media`` is produced by the LLM (or the fallback) and resolved INSIDE
        ``handle_event``: the assistant searches YouTube and replaces it with an ``ask``
        with ``expects="choice"`` and ``options`` (the results). Core never receives it.
        After the driver chooses, ``play_media`` carries ``track_id="yt:<video id>"`` and
        ``title``; core plays ``music.track_url(track_id)`` (``/media/yt/<id>.m4a``).

    Extra P3 fields (not in the plan table, all optional):
        source: ``"LLM"`` or ``"RULE"`` (plan principle 5: every decision shows its source;
            fixed fallback texts are ``"RULE"``).
        clip_id: a pre-generated clip that says exactly ``text`` (core may play it
            instead of calling TTS - zero latency).
        needs_confirmation: filled by ``assistant/actions.py`` from the plan table;
            core must execute the action only after a "yes" (voice, nod or thumbs-up).
        streamed: True when this ``speak`` / ``ask`` was already sent to TTS while the
            LLM was still streaming (core must not say it twice).
    """

    type: ActionType
    to: Optional[Addressee] = None
    text: Optional[str] = None
    question: Optional[str] = None
    expects: Optional[Literal["yes_no", "kss", "free", "choice"]] = None
    track_id: Optional[str] = None
    volume: Optional[float] = None
    reason: Optional[str] = None
    msg_id: Optional[str] = None
    task: Optional[str] = None
    trigger: Optional[ReminderTrigger] = None
    reminder_id: Optional[str] = None
    poi_id: Optional[str] = None
    to_person: Optional[str] = None
    target: Optional[str] = None
    key: Optional[str] = None
    value: Optional[Any] = None
    # --- P3 extras ---
    source: Literal["LLM", "RULE"] = "LLM"
    clip_id: Optional[str] = None
    needs_confirmation: bool = False
    streamed: bool = False
    # --- P3 extras for YouTube media (section 6.1 of docs/assistant.md) ---
    query: Optional[str] = None
    kind: Optional[Literal["music", "podcast"]] = None
    options: Optional[list[dict[str, Any]]] = None
    title: Optional[str] = None
