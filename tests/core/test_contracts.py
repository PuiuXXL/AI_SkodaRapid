"""Tests for shared/contracts.py (contract v2.0, plan sections 6, 7 and 13)."""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from shared import contracts as c

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = Path(__file__).resolve().parent / "fixtures" / "state_example.json"


def _example() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _lost_or_changed(src: Any, out: Any, path: str = "") -> list[str]:
    """Paths of the source JSON that are missing or different in the serialized output."""
    problems: list[str] = []
    if isinstance(src, dict):
        for key, value in src.items():
            if key not in out:
                problems.append(f"lost {path}.{key}")
            else:
                problems += _lost_or_changed(value, out[key], f"{path}.{key}")
    elif isinstance(src, list):
        if len(src) != len(out):
            problems.append(f"length {path}")
        for i, (a, b) in enumerate(zip(src, out, strict=False)):  # a length change is reported above
            problems += _lost_or_changed(a, b, f"{path}[{i}]")
    elif src != out:
        problems.append(f"changed {path}: {src!r} -> {out!r}")
    return problems


# --- State (section 7) -----------------------------------------------------------------------------------------------


def test_version() -> None:
    assert c.CONTRACT_VERSION == "2.1"


def test_plan_example_validates_and_round_trips() -> None:
    raw = _example()
    state = c.State.model_validate(raw)
    assert state.safety.level == "P3"
    assert state.cause.label == "passenger_showing_phone"
    assert state.messages[0].from_ == "Mihai"
    assert state.interaction.last_input is not None and state.interaction.last_input.from_ == 1
    assert _lost_or_changed(raw, c.to_wire(state)) == []


def test_wire_names_use_aliases() -> None:
    out = c.to_wire(c.State.model_validate(_example()))
    assert out["messages"][0]["from"] == "Mihai" and "from_" not in out["messages"][0]
    assert out["interaction"]["last_input"]["from"] == 1


def test_every_state_and_frame_field_has_a_default() -> None:
    state = c.State.model_validate({})
    assert state.safety.monitoring_ok is True and state.safety.level is None
    assert state.assistant.muted_until is None
    assert state.driver.eyes.microsleep is False and state.driver.head.yaw is None
    assert c.PerceptionFrame.model_validate({}).driver.gaze.zone == "unknown"
    c.to_wire(state)  # serializable as is


def test_unknown_fields_are_kept() -> None:
    state = c.State.model_validate({"future_block": {"x": 1}, "driver": {"eyes": {"new_metric": 3}}})
    out = c.to_wire(state)
    assert out["future_block"] == {"x": 1}
    assert out["driver"]["eyes"]["new_metric"] == 3


def test_list_items_need_their_id() -> None:
    with pytest.raises(ValidationError):
        c.State.model_validate({"messages": [{"app": "sms"}]})
    with pytest.raises(ValidationError):
        c.State.model_validate({"reminders": [{"task": "x"}]})


def test_gaze_zone_vocabulary() -> None:
    assert typing.get_args(c.GazeZone) == c.GAZE_ZONES
    with pytest.raises(ValidationError):
        c.Gaze.model_validate({"zone": "ceiling"})


def test_p3_state_fixture_validates() -> None:
    """The dashboard and the assistant tests use this file too."""
    raw = json.loads((ROOT / "tests" / "assistant" / "fixtures" / "state_example.json").read_text(encoding="utf-8"))
    c.State.model_validate(raw)


def test_p1_nulls_before_the_first_monitoring_result() -> None:
    """P1 sends null for values it does not have yet (perception/frame_builder.py); a frame must never fail on that."""
    frame = c.PerceptionFrame.model_validate(
        {
            "ts": 1.0, "seq": 1,
            "driver": {"face_conf": None, "camera_mode": None, "monitoring_reason": None,
                       "head": {"yaw": None, "pitch": None, "roll": None}, "eyes": {"ear": None, "blink_rate": None},
                       "phone": {"side": None, "usage": None}, "gesture_score": None},
            "passenger": {"present": True, "monitoring_ok": True, "monitoring_warnings": [], "camera_mode": "mono",
                          "face_conf": None},
            "occupants": [{"id": 1, "seat": "driver", "source": "cam_driver", "profile": None,
                           "profile_score": None}],
        }
    )
    assert frame.driver.face_conf is None and frame.passenger.camera_mode == "mono"
    assert not frame.passenger.model_extra  # the passenger monitoring fields are declared


def test_frame_blocks_fit_the_state() -> None:
    """Core copies P1's blocks into State: a PerceptionFrame's driver must be a valid State driver."""
    frame = c.PerceptionFrame.model_validate(
        {
            "ts": 1.0,
            "seq": 7,
            "occupants": [{"id": 1, "seat": "driver", "source": "cam_driver", "profile": None}],
            "driver": {"eyes": {"closed_ms": 1200, "state": "CLOSED"}, "monitoring_reason": "occluded"},
            "perf": {"cameras": {"driver": {"capture_fps": 30, "available": True}}, "stages_ms": {"driver": {}}},
        }
    )
    state = c.State.model_validate({"driver": frame.driver.model_dump(), "perf": frame.perf.model_dump()})
    assert state.driver.eyes.closed_ms == 1200
    assert state.driver.reaction.missed == 0


# --- Actions (section 6) ---------------------------------------------------------------------------------------------

VALID_ACTIONS: dict[str, dict[str, Any]] = {
    "speak": {"to": "driver", "text": "Ochii pe drum."},
    "ask": {"to": "driver", "question": "Cât de obosit ești, 1-9?", "expects": "kss"},
    "suggest_media": {"track_id": "t07", "reason": "disengagement"},
    "play_media": {"track_id": "t07", "volume": 0.4},
    "stop_media": {},
    "read_message": {"msg_id": "m17"},
    "reply_message": {"msg_id": "m17", "text": "Ajung pe la 18:40."},
    "create_reminder": {"task": "lichid de parbriz", "trigger": {"type": "stop_at_category", "category": "fuel"}},
    "complete_reminder": {"reminder_id": "r1"},
    "suggest_stop": {"poi_id": "omv_km42"},
    "delegate": {"to_person": "maria", "task": "povestește-i tu"},
    "show_on_screen": {"text": "Mesaj de la Mihai"},
    "set_preference": {"key": "voice_volume", "value": 0.6},
    "stay_silent": {"reason": "conversation"},
    "search_media": {"query": "metal energic", "kind": "music"},
}


def test_action_tables_cover_every_type() -> None:
    assert typing.get_args(c.ActionType) == c.ACTION_TYPES
    assert set(c.ACTION_MODELS) == set(c.ACTION_TYPES) == set(c.ACTION_ALLOWED_LEVELS) == set(VALID_ACTIONS)
    assert set(c.ACTION_TYPES) >= c.ACTION_NEEDS_CONFIRMATION
    for levels in c.ACTION_ALLOWED_LEVELS.values():
        assert levels <= set(c.SAFETY_LEVELS)


def test_llm_actions_are_never_allowed_under_the_veto_except_the_harmless_ones() -> None:
    allowed_under_veto = {t for t, levels in c.ACTION_ALLOWED_LEVELS.items() if levels & c.LLM_VETO_LEVELS}
    assert allowed_under_veto == {"stop_media", "complete_reminder", "show_on_screen", "stay_silent"}


@pytest.mark.parametrize("action_type", sorted(VALID_ACTIONS))
def test_each_action_parses_to_its_typed_model(action_type: str) -> None:
    typed = c.parse_action({"type": action_type, **VALID_ACTIONS[action_type]})
    assert isinstance(typed, c.ACTION_MODELS[action_type])
    flat = c.Action.model_validate({"type": action_type, **VALID_ACTIONS[action_type]})
    assert isinstance(flat.typed(), c.ACTION_MODELS[action_type])


@pytest.mark.parametrize(
    "data",
    [
        {"type": "speak"},  # no text
        {"type": "ask", "question": "Bine?"},  # no expects
        {"type": "reply_message", "msg_id": "m1"},  # no text
        {"type": "suggest_stop"},  # no poi_id
        {"type": "stay_silent"},  # no reason
        {"type": "open_window"},  # not in the table
    ],
)
def test_invalid_actions_are_rejected(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        c.parse_action(data)


def test_youtube_media_fields() -> None:
    """D11 (P3): search_media stays inside the assistant; core gets a choice question and a yt: track."""
    assert set(c.ACTION_TYPES) >= c.ASSISTANT_INTERNAL_ACTIONS
    assert c.ACTION_ALLOWED_LEVELS["search_media"] == {"P4"}
    options = [{"track_id": "yt:abc123", "title": "Enter Sandman", "channel": "Metallica", "duration_s": 331}]
    ask = c.parse_action({"type": "ask", "question": "Am găsit: A, B sau C. Care?", "expects": "choice",
                          "options": options})
    assert isinstance(ask, c.AskAction) and ask.options == options
    with pytest.raises(ValidationError, match="options"):
        c.parse_action({"type": "ask", "question": "Care?", "expects": "choice"})
    play = c.Action(type="play_media", track_id="yt:abc123", title="Enter Sandman").typed()
    assert isinstance(play, c.PlayMediaAction) and play.title == "Enter Sandman"
    assert c.State.model_validate({"media": {"playing": True, "source": "youtube"}}).media.source == "youtube"
    media = c.parse_ui_message({"type": "media", "action": "play", "url": "/media/yt/abc123.m4a", "loop": False})
    assert isinstance(media, c.UiMedia) and media.loop is False
    assert "volume" in c.NO_CONFIRMATION_PREFERENCES


def test_flat_action_keeps_p3_extras() -> None:
    action = c.Action(type="speak", to="driver", text="Ok.", source="RULE", clip_id="confirm_ok", streamed=True)
    typed = action.typed()
    assert isinstance(typed, c.SpeakAction)
    assert (typed.source, typed.clip_id, typed.streamed) == ("RULE", "confirm_ok", True)


# --- /ws/perception --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        {"type": "command", "cmd": "debug", "on": True},
        {"cmd": "debug", "on": True},
        {"type": "debug", "on": True},
    ],
)
def test_perception_command_forms(data: dict[str, Any]) -> None:
    cmd = c.PerceptionCommand.model_validate(data)
    assert (cmd.type, cmd.cmd, cmd.on) == ("command", "debug", True)


def test_dialog_window_command() -> None:
    cmd = c.PerceptionCommand(cmd="dialog_window", open=True, to="passenger", until=123.0)
    assert c.to_wire(cmd)["to"] == "passenger"
    with pytest.raises(ValidationError):
        c.PerceptionCommand.model_validate({"cmd": "self_destruct"})


def test_perception_messages_are_told_apart() -> None:
    assert isinstance(c.parse_perception_message({"ts": 1.0, "seq": 1}), c.PerceptionFrame)
    ack = c.parse_perception_message({"type": "ack", "cmd": "debug", "status": "ok", "detail": None})
    assert isinstance(ack, c.PerceptionAck)
    prompt = c.parse_perception_message({"type": "calibration_prompt", "zone": "mirror_left", "mode": "owl"})
    assert isinstance(prompt, c.CalibrationPrompt)


# --- /ws/ui (formats from docs/assistant.md section 4 and the dashboard) -------------------------------------------


@pytest.mark.parametrize(
    ("data", "model"),
    [
        (
            {
                "type": "speak", "id": "u12", "to": "driver", "is_question": True, "expects": "yes_no",
                "text": "Pare monoton. Pun ceva mai energic?", "clip_url": None,
                "sentences": [{"id": "3f2a", "text": "Pare monoton.", "url": "/tts/3f2a.mp3"}],
            },
            c.UiSpeak,
        ),
        ({"type": "speak_control", "action": "pause"}, c.UiSpeakControl),
        ({"type": "alarm", "id": "a7", "clip_url": "/sounds/clips/alarm_andrei.mp3"}, c.UiAlarm),
        ({"type": "media", "action": "play", "url": "/media/t14.mp3", "volume": 0.6}, c.UiMedia),
        ({"type": "state", "state": {"seq": 3}}, c.UiState),
        ({"type": "event", "event": {"type": "visual_cue", "ts": 1.0, "source": "RULE"}}, c.UiEvent),
        ({"type": "command", "cmd": "debug", "on": True}, c.UiCommand),
        (
            {
                "type": "speech", "text": "pune ceva muzică", "raw": "copilot pune ceva muzică", "final": True,
                "addressed": True, "early": "stable", "wait_ms": 800, "confidence": 0.92, "ts": 1763672400.12,
            },
            c.UiSpeech,
        ),
        ({"type": "speech_onset", "ts": 1763672399.87}, c.UiSpeechOnset),
        ({"type": "speak_done", "id": "u12", "is_question": True, "interrupted": False, "ts": 1.0}, c.UiSpeakDone),
        ({"type": "alarm_played", "id": "a7", "ts": 1763672401.05}, c.UiAlarmPlayed),
    ],
)
def test_ui_messages(data: dict[str, Any], model: type) -> None:
    assert isinstance(c.parse_ui_message(data), model)


def test_browser_messages_only_accept_browser_types() -> None:
    assert isinstance(c.parse_browser_message({"type": "speech_onset", "ts": 1.0}), c.UiSpeechOnset)
    with pytest.raises(ValidationError):
        c.parse_browser_message({"type": "alarm", "id": "a1", "clip_url": "/x.mp3"})


# --- /ws/phone (formats from integrations/phone_bridge.py) -----------------------------------------------------------


def test_phone_events() -> None:
    msg = c.parse_phone_event(
        {
            "type": "phone_message", "notification_id": "n1", "app": "whatsapp", "from": "Mihai",
            "text": "Unde ești?", "replyable": True, "ts": 1763672390.0,
        }
    )
    assert isinstance(msg, c.PhoneMessage) and msg.from_ == "Mihai"
    assert isinstance(c.parse_phone_event({"type": "phone_status", "connected": True, "battery": 64}),
                      c.PhoneStatusMessage)
    assert isinstance(c.parse_phone_event({"type": "phone_result", "request_id": "r1", "ok": True, "error": None}),
                      c.PhoneResult)


def test_phone_commands_use_roles_not_numbers() -> None:
    sms = c.parse_phone_command({"type": "send_sms", "request_id": "r2", "to": "safe_contact", "text": "DriveMate: …"})
    assert isinstance(sms, c.SendSms)
    with pytest.raises(ValidationError):
        c.parse_phone_command({"type": "send_sms", "request_id": "r3", "to": "+40700000000", "text": "x"})
    reply = c.parse_phone_command({"type": "send_reply", "request_id": "r1", "notification_id": "n1", "text": "Ok"})
    assert isinstance(reply, c.SendReply)


# --- Reports ---------------------------------------------------------------------------------------------------------


def test_reports_have_defaults() -> None:
    assert c.SosReport().passenger_state == "absent"
    assert c.SafeContactNotice(contact_name="Mihai").contact_name == "Mihai"
