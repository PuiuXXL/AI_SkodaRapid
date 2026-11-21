"""Tests for core/safety: eyes closed longer than a blink (C3, C4: the check-in, the warning, the alarm), "Ești bine?"
(C4), the SOS countdown (C5), "Nu te mai văd" (C7), the arbiter (C1) and the yes / no on every channel (E3).
Scenes 8 and 9 of the demo, in fake time."""

from __future__ import annotations

from typing import Any

import pytest
from p2_helpers import ALARM_S, ASK_AFTER, ASK_WINDOW, COUNTDOWN, Rig

from core.safety.answers import parse_gesture, parse_sos_voice, parse_voice
from core.settings import th
from shared import contracts as c

CHECKIN_AFTER = th("safety", "checkin", "after_open_s")
WARN_S = th("safety", "drowsiness", "warn_ms") / 1000.0
ANSWER_WINDOW = th("sos", "answer_window_s")
REASK_WINDOW = th("sos", "reask_clip_s") + ANSWER_WINDOW
CHECKIN_TEXT = "Andrei, ai închis ochii câteva clipe. Facem o pauză?"


def alarm_rig(key: str = "7", **kwargs: Any) -> Rig:
    """Highway (scene 8), eyes closed until the alarm fires."""
    rig = Rig(**kwargs)
    rig.press("1")
    rig.run(2.0)
    rig.press(key)
    rig.run_until(lambda: rig.engine.safety.sos.state == "alarm", limit_s=ALARM_S + 1.0)
    return rig


def closure_rig(seconds: float) -> Rig:
    """Highway, the eyes closed for ``seconds``, then open again."""
    rig = Rig()
    rig.press("1")
    rig.run(2.0)
    rig.press("7")
    rig.run(seconds)
    rig.press("1")
    return rig


def checkins(rig: Rig) -> list[dict[str, Any]]:
    return [s for s in rig.speaks() if s["id"].startswith("drw") and s["is_question"]]


def faces_lost_after(start: float) -> Any:
    """A patch like the real P1 when the head falls: from ``start`` no face, so no eye data."""

    def patch(frame: dict[str, Any], t: float) -> None:
        if t >= start:
            frame["driver"]["eyes"].update(reliable=False, closed_ms=0.0, state="UNKNOWN", ear=None)
            frame["driver"]["head"].update(yaw=None, pitch=None, roll=None)

    return patch


# --- answers ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("Da.", "yes"), ("da, sunt bine", "yes"), ("Sunt bine", "yes"), ("ok", "yes"), ("Da, nu-i nimic", "yes"),
        ("Nu.", "no"), ("nu sunt bine", "no"), ("Nu mă simt bine", "no"), ("ajutor", "no"),
        ("bineînțeles că nu", "no"),  # "bine" inside another word is not a yes
        ("poate", None), ("", None), ("dar", None), ("unde suntem?", None),
    ],
)
def test_voice_answers(text: str, answer: str | None) -> None:
    assert parse_voice(text) == answer


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("Da.", "yes"), ("sunt bine", "yes"), ("Da, nu-i nimic", "yes"),
        ("nu-i nimic", "yes"), ("Nu, sunt bine.", "yes"), ("nu mi-e rău", "yes"), ("n-am nimic", "yes"),
        ("nu-ți face griji", "yes"), ("sunt ok, nu-ți face griji", "yes"),
        ("nu sunt bine", "no"), ("Nu, nu sunt bine.", "no"), ("mi-e rău", "no"), ("ajutor", "no"),
        ("Nu mă simt bine", "no"),
        ("Nu.", "unclear"), ("nu știu", "unclear"),
        ("poate", None), ("", None), ("unde suntem?", None),
    ],
)
def test_sos_voice_answers(text: str, answer: str | None) -> None:
    assert parse_sos_voice(text) == answer


def test_gesture_answers() -> None:
    assert (parse_gesture("Thumb_Up"), parse_gesture("Thumb_Down"), parse_gesture("Open_Palm")) == ("yes", "no", None)


# --- eyes closed longer than a blink, before the alarm (C3, C4) ------------------------------------------------------


def test_blinks_and_mirror_glances_never_alarm() -> None:
    rig = Rig()
    rig.press("1")
    rig.run(20.0)
    rig.press("2")
    rig.run(5.0)
    assert not rig.hub.of_type("alarm") and not checkins(rig)
    assert rig.engine.safety.sos.state == "normal" and rig.state.safety.level is None
    assert rig.state.safety.drowsiness.episodes_10min == 0


def test_a_long_blink_is_nothing() -> None:
    rig = closure_rig(0.7)
    rig.run(5.0)
    assert not rig.hub.of_type("alarm") and not checkins(rig) and not rig.hub.events("eyes_reopened")


def test_a_short_closure_gets_the_checkin_one_second_after_the_eyes_open() -> None:
    rig = closure_rig(1.5)
    rig.run(CHECKIN_AFTER - 0.3)
    assert not checkins(rig)
    rig.run(0.5)
    question = checkins(rig)
    assert len(question) == 1 and question[0]["text"] == CHECKIN_TEXT and question[0]["expects"] == "yes_no"
    assert not rig.hub.of_type("alarm") and rig.state.safety.level is None
    reopened = rig.hub.events("eyes_reopened")[0]
    assert reopened["data"]["closed_ms"] == pytest.approx(1500, abs=100)
    assert rig.hub.events("drowsy_check")[0]["data"]["reason"] == "closure"
    window = [m for m in rig.hub.perception_sent if m["cmd"] == "dialog_window"][-1]
    assert window["open"] is True and rig.state.interaction.dialog_window_open is True
    rig.run(0.2)
    assert rig.state.safety.drowsiness.episodes_10min == 1
    assert rig.state.safety.drowsiness.last_episode_ms == pytest.approx(1500, abs=100)


@pytest.mark.parametrize(("answer", "channel"), [("voice", "voice"), ("y", "nod"), ("g", "gesture")])
def test_yes_to_the_checkin_proposes_the_nearest_stop(answer: str, channel: str) -> None:
    rig = closure_rig(1.5)
    rig.run(CHECKIN_AFTER + 0.2)
    if answer == "voice":
        rig.say("da")
    else:
        rig.press(answer)
        rig.run(0.2)
    accepted = rig.hub.events("break_accepted")[0]
    assert accepted["channel"] == channel and accepted["data"]["poi_name"] == "OMV"
    assert rig.speaks()[-1]["text"] == "Bine. Cea mai apropiată oprire e OMV, la 12 km."
    assert rig.state.scorecard.suggestions_accepted == 1
    rig.run(0.2)
    assert rig.state.interaction.dialog_window_open is False


@pytest.mark.parametrize(("answer", "channel"), [("voice", "voice"), ("b", "gesture")])
def test_no_to_the_checkin(answer: str, channel: str) -> None:
    rig = closure_rig(1.5)
    rig.run(CHECKIN_AFTER + 0.2)
    if answer == "voice":
        rig.say("nu")
    else:
        rig.press(answer)
        rig.run(0.2)
    assert rig.hub.events("break_declined")[0]["channel"] == channel
    assert rig.speaks()[-1]["text"] == "Bine. Sunt aici dacă ai nevoie."
    assert rig.state.scorecard.suggestions_rejected == 1


def test_checkin_unanswered_is_logged() -> None:
    rig = closure_rig(1.5)
    rig.run(CHECKIN_AFTER + th("safety", "checkin", "window_s") + 0.5)
    assert rig.hub.events("drowsy_check_unanswered") and not rig.hub.events("break_accepted")


def test_checkin_at_most_once_per_cooldown() -> None:
    rig = closure_rig(1.5)
    rig.run(CHECKIN_AFTER + 0.2)
    rig.say("nu")
    rig.run(60.0)
    rig.press("7")
    rig.run(1.5)
    rig.press("1")
    rig.run(CHECKIN_AFTER + 0.5)
    assert len(checkins(rig)) == 1
    assert rig.hub.events("drowsy_check_skipped")[0]["data"]["reason"] == "cooldown"
    assert rig.state.safety.drowsiness.episodes_10min == 2


def test_checkin_is_said_while_the_assistant_is_silenced() -> None:
    rig = Rig()
    rig.press("1")
    rig.run(2.0)
    rig.state.assistant.muted_until = rig.t + 600.0  # after "lasă-mă în pace": a safety rule still speaks
    rig.press("7")
    rig.run(1.5)
    rig.press("1")
    rig.run(CHECKIN_AFTER + 0.3)
    assert len(checkins(rig)) == 1


def test_warning_at_two_seconds_then_the_checkin() -> None:
    rig = Rig()
    rig.press("1")
    rig.run(2.0)
    pressed = rig.t
    rig.press("7")
    rig.run_until(lambda: bool(rig.hub.events("drowsy_warning")), limit_s=3.0)
    warning = rig.hub.events("drowsy_warning")[0]
    assert WARN_S <= warning["ts"] - pressed <= WARN_S + 0.1
    cue = rig.hub.events("visual_cue")[-1]
    assert cue["data"] == {"alert": "eyes_closing", "level": "P2"}
    assert rig.state.safety.level == "P2" and rig.state.safety.llm_allowed is False
    rig.run(0.15)  # the drowsiness block of the state is written on the next tick
    assert rig.state.safety.drowsiness.stage == "warning"
    assert not rig.hub.of_type("alarm")
    rig.press("1")
    rig.run(0.2)
    assert rig.state.safety.level is None and rig.state.safety.drowsiness.stage == "none"
    rig.run(CHECKIN_AFTER)
    assert len(checkins(rig)) == 1


# --- the alarm (C3) --------------------------------------------------------------------------------------------------


def test_eyes_closed_alarm_fires_on_the_frame() -> None:
    rig = Rig()
    rig.press("1")
    rig.run(2.0)
    pressed = rig.t
    rig.press("7")
    rig.run_until(lambda: bool(rig.hub.of_type("alarm")), limit_s=ALARM_S + 1.0)
    alarm_at = rig.hub.events("alarm")[0]["ts"]
    assert ALARM_S <= alarm_at - pressed <= ALARM_S + 1.0 / 15 + 1e-6  # the first frame over the threshold
    alarm = rig.hub.of_type("alarm")[0]
    assert alarm["clip_url"] == "/sounds/clips/alarm_andrei.mp3" and (alarm["level"], alarm["alert"]) == ("P1",
                                                                                                         "microsleep")
    sent = [m["type"] for m in rig.hub.ui_sent]
    assert sent.index("speak_control") < sent.index("media") < sent.index("alarm")  # sounds stop first
    assert rig.state.safety.level == "P1" and rig.state.safety.llm_allowed is False
    assert rig.hub.events("alarm")[0]["explanation"] == "Ochii închiși 3,0 s la 118 km/h."
    rig.run(0.2)
    assert rig.state.safety.drowsiness.stage == "alarm" and rig.state.safety.sos.trigger == "microsleep"


def test_face_lost_inside_a_closure_keeps_counting() -> None:
    """The head falls and leaves the face tracker (the real P1 then sends no eye data): the alarm still comes."""
    rig = Rig()
    rig.press("1")
    rig.run(2.0)
    pressed = rig.t
    rig.press("7")
    rig.patch = faces_lost_after(pressed + 1.2)
    rig.run_until(lambda: bool(rig.hub.of_type("alarm")), limit_s=ALARM_S + 1.0)
    assert ALARM_S <= rig.hub.events("alarm")[0]["ts"] - pressed <= ALARM_S + 0.1
    assert not monitoring_speaks(rig)  # no "Nu te mai văd" before the alarm


def test_a_blink_then_a_lost_face_is_no_closure() -> None:
    rig = Rig()
    rig.press("1")
    rig.run(2.0)
    rig.press("7")
    rig.patch = faces_lost_after(rig.t + 0.3)  # e.g. the head turns away right after a blink
    rig.run(ALARM_S + 2.0)
    assert not rig.hub.of_type("alarm")


def test_open_eyes_end_the_closure_even_while_the_nod_is_held() -> None:
    """P1 holds ``nodding`` for 1 s after a nod: eyes reported OPEN still end the closure."""
    rig = Rig()
    rig.press("1")
    rig.run(2.0)
    rig.patch = lambda frame, t: frame["driver"]["head"].update(nodding=True)
    rig.press("7")
    rig.run(2.2)
    rig.press("1")
    rig.run(1.5)
    assert not rig.hub.of_type("alarm")


def test_alarm_latency_from_the_browser() -> None:
    rig = alarm_rig()
    alarm_id = rig.hub.of_type("alarm")[0]["id"]
    detected = rig.hub.events("alarm")[0]["ts"]
    rig.t = detected + 0.12
    rig.browser({"type": "alarm_played", "id": alarm_id, "ts": rig.t})
    rig.run(0.2)
    assert rig.state.safety.alarm_ms_last == pytest.approx(120.0, abs=0.5)
    assert rig.state.perf.alarm_ms_last == pytest.approx(120.0, abs=0.5)
    played = rig.hub.events("alarm_played")[0]
    assert played["data"]["on_target"] is True and played["latency_ms"] == pytest.approx(120.0, abs=0.5)


def test_one_alarm_per_closure() -> None:
    rig = alarm_rig()
    rig.say("da")  # answered, but the eyes stay closed
    rig.run(10.0)
    assert len(rig.hub.of_type("alarm")) == 1
    rig.press("1")
    rig.run(1.0)
    rig.press("7")
    rig.run(ALARM_S + 0.3)
    assert len(rig.hub.of_type("alarm")) == 2  # eyes opened in between: a new closure, a new alarm


# --- "Ești bine?" (C4) -----------------------------------------------------------------------------------------------


def test_the_dialog_window_opens_with_the_alarm() -> None:
    rig = alarm_rig()
    windows = [m for m in rig.hub.perception_sent if m["cmd"] == "dialog_window"]
    assert windows[-1]["open"] is True and windows[-1]["to"] == "driver"
    rig.say("sunt bine", addressed=False)  # no wake word needed: the window is open from the alarm on
    assert rig.engine.safety.sos.state == "normal"


def test_are_you_ok_comes_after_the_alarm_clip() -> None:
    rig = alarm_rig()
    alarm_id = rig.hub.of_type("alarm")[0]["id"]
    rig.run(0.3)
    rig.browser({"type": "alarm_played", "id": alarm_id, "ts": rig.t})  # the browser started it 0.3 s late
    played = rig.t
    rig.run_until(lambda: rig.engine.safety.sos.state == "asking", limit_s=ASK_AFTER + 1.0)
    assert rig.t - played == pytest.approx(ASK_AFTER, abs=0.11)
    question = [s for s in rig.speaks() if s["clip_url"] == "/sounds/clips/are_you_ok.mp3"]
    assert question and question[0]["is_question"] and question[0]["expects"] == "yes_no"
    assert rig.state.interaction.dialog_window_open is True


def test_the_answer_window_starts_when_the_question_ended() -> None:
    rig = alarm_rig("8")
    rig.run_until(lambda: rig.engine.safety.sos.state == "asking", limit_s=ASK_AFTER + 1.0)
    question_id = rig.engine.safety.sos.question_id
    rig.run(3.0)  # the browser was slow: the question ended 3 s later
    rig.browser({"type": "speak_done", "id": question_id, "is_question": True, "ts": rig.t})
    done = rig.t
    rig.run_until(lambda: rig.engine.safety.sos.state == "countdown", limit_s=ANSWER_WINDOW + 1.0)
    assert rig.t - done == pytest.approx(ANSWER_WINDOW, abs=0.11)


def test_spoken_yes_cancels_and_brings_the_llm_back() -> None:
    rig = alarm_rig()
    rig.run(ASK_AFTER + 0.5)
    rig.press("1")
    rig.say("Da, sunt bine.")
    rig.run(0.2)
    assert rig.state.safety.sos.state == "normal" and rig.state.safety.level is None
    assert rig.state.safety.llm_allowed is True and rig.state.interaction.dialog_window_open is False
    assert rig.hub.events("sos_cancelled")[0]["channel"] == "voice"
    assert rig.speaks()[-1]["clip_url"] == "/sounds/clips/confirm_ok.mp3"
    assert rig.hub.perception_sent[-1] == {**rig.hub.perception_sent[-1], "cmd": "dialog_window", "open": False}


def test_a_reassuring_no_cancels_too() -> None:
    rig = alarm_rig()
    rig.run(ASK_AFTER + 0.5)
    rig.say("nu-i nimic, sunt bine")
    assert rig.engine.safety.sos.state == "normal"


@pytest.mark.parametrize(("key", "channel"), [("y", "nod"), ("g", "gesture")])
def test_nod_or_thumbs_up_cancels(key: str, channel: str) -> None:
    rig = alarm_rig()
    rig.run(ASK_AFTER + 0.5)
    rig.press("1")
    rig.press(key)
    rig.run(0.3)
    assert rig.state.safety.sos.state == "normal"
    assert rig.hub.events("sos_cancelled")[0]["channel"] == channel


def test_a_head_shake_is_ignored() -> None:
    rig = alarm_rig("8")
    rig.run(ASK_AFTER + 0.5)
    rig.press("n")
    rig.run(0.5)
    assert rig.engine.safety.sos.state == "asking"


def test_a_clear_no_starts_the_countdown_at_once() -> None:
    rig = alarm_rig()
    rig.run(ASK_AFTER + 0.5)
    rig.say("Nu sunt bine.")
    assert rig.engine.safety.sos.state == "countdown"  # at once, not at the end of the window
    rig.run(0.1)
    assert rig.state.safety.sos.state == "countdown" and rig.state.safety.level == "P0"
    assert rig.hub.events("sos_countdown")[0]["data"]["why"] == "answer_no:voice"


def test_thumbs_down_starts_the_countdown() -> None:
    rig = alarm_rig()
    rig.run(ASK_AFTER + 0.5)
    rig.press("b")
    rig.run(0.2)
    assert rig.hub.events("sos_countdown")[0]["data"]["why"] == "answer_no:gesture"


def test_a_bare_no_asks_again() -> None:
    rig = alarm_rig("8")
    rig.run(ASK_AFTER + 0.5)
    rig.say("Nu.")
    assert rig.engine.safety.sos.state == "asking" and rig.engine.safety.sos.reasked
    reask = rig.hub.events("sos_reask")[0]
    assert reask["data"]["why"] == "unclear:voice" and reask["text"] == "Andrei, mă auzi? Spune da sau dă din cap."
    rig.say("nu")  # unclear again: no third question, the window goes on
    assert len(rig.hub.events("sos_reask")) == 1 and rig.engine.safety.sos.state == "asking"
    rig.run(REASK_WINDOW + 0.2)
    assert rig.engine.safety.sos.state == "countdown"


def test_open_eyes_without_an_answer_ask_once_more() -> None:
    rig = alarm_rig()
    rig.press("1")  # awake, eyes open, but says nothing
    rig.run(ASK_AFTER + ASK_WINDOW + 0.2)
    assert rig.engine.safety.sos.state == "asking"
    assert rig.hub.events("sos_reask")[0]["data"]["why"] == "eyes_open_no_answer"
    assert rig.speaks()[-1]["text"] == "Andrei, mă auzi? Spune da sau dă din cap."
    rig.run(REASK_WINDOW + 0.2)
    assert rig.engine.safety.sos.state == "countdown"
    assert rig.hub.events("sos_countdown")[0]["data"]["why"] == "no_answer"


def test_after_the_sos_is_cancelled_a_break_is_proposed() -> None:
    rig = alarm_rig()
    rig.run(ASK_AFTER + 0.5)
    rig.press("1")
    rig.say("da")
    rig.run(th("safety", "checkin", "after_sos_s") + 0.3)
    question = checkins(rig)
    assert len(question) == 1 and question[0]["text"] == "Andrei, facem o pauză?"
    assert rig.hub.events("drowsy_check")[0]["data"]["reason"] == "after_sos"


# --- countdown and SOS (C5, F6) --------------------------------------------------------------------------------------


def test_no_answer_leads_to_passenger_instructions_countdown_and_sos() -> None:
    reports: list[c.SosReport] = []
    rig = alarm_rig("8", sos_channels={"test": lambda report: reports.append(report) or "ok"})
    assert rig.hub.of_type("alarm")[0]["alert"] == "nodding"
    rig.run(ASK_AFTER + ASK_WINDOW + 0.2)
    assert rig.state.safety.sos.state == "countdown" and rig.state.safety.level == "P0"
    assert not rig.hub.events("sos_reask")  # the eyes never opened
    instructions = rig.speaks()[-1]
    assert instructions["to"] == "passenger"
    assert instructions["clip_url"] == "/sounds/clips/passenger_instructions_maria_andrei.mp3"
    assert instructions["text"].startswith("Maria, Andrei nu răspunde.")
    assert COUNTDOWN - 1.0 < rig.state.safety.sos.countdown_s <= COUNTDOWN  # counting down, shown in the state
    alarms_before = len(rig.hub.of_type("alarm"))
    rig.run(COUNTDOWN + 0.3)
    assert len(rig.hub.of_type("alarm")) > alarms_before  # re-alarm after the instructions
    assert rig.state.safety.sos.state == "sos_sent" and rig.state.safety.alert == "sos_sent"
    assert len(reports) == 1
    report = reports[0]
    assert (report.driver_name, report.passenger_state, report.occupants_n) == ("Andrei", "awake", 2)
    seconds_left = int(report.unresponsive_s)
    assert ASK_AFTER + ASK_WINDOW + COUNTDOWN - 1 <= seconds_left <= ASK_AFTER + ASK_WINDOW + COUNTDOWN + 1
    assert report.text.startswith(f"Alertă automată DriveMate. Andrei nu răspunde de {seconds_left} secunde.")
    assert "google.com/maps?q=" in report.maps_url and report.time_hhmm
    assert rig.hub.events("sos_sent")[0]["data"]["channels"] == {"test": "ok"}


def test_the_realarm_never_cuts_the_passenger_instructions() -> None:
    rig = alarm_rig("8")
    rig.run(ASK_AFTER + ASK_WINDOW + 0.2)
    instructions_id = rig.engine.safety.sos.instructions_id
    started = rig.hub.events("sos_countdown")[0]["ts"]
    alarms_before = len(rig.hub.of_type("alarm"))
    rig.run(7.0)  # the clip is 7.2 s long
    assert len(rig.hub.of_type("alarm")) == alarms_before
    rig.t = started + 7.2
    rig.browser({"type": "speak_done", "id": instructions_id, "is_question": False, "ts": rig.t})
    rig.run(th("sos", "instructions_pause_s") + 0.15)
    assert len(rig.hub.of_type("alarm")) == alarms_before + 1


def test_default_channels_say_what_is_not_wired_yet() -> None:
    rig = alarm_rig("8")
    rig.run(ASK_AFTER + ASK_WINDOW + COUNTDOWN + 0.5)
    assert rig.hub.events("sos_sent")[0]["data"]["channels"] == {
        "contact_page": "not_connected", "call": "not_connected", "sms": "not_connected"}


def test_a_broken_channel_does_not_stop_the_others() -> None:
    def broken(_: c.SosReport) -> str:
        raise RuntimeError("no network")

    rig = alarm_rig("8", sos_channels={"broken": broken, "ok": lambda _: "ok"})
    rig.run(ASK_AFTER + ASK_WINDOW + COUNTDOWN + 0.5)
    assert rig.hub.events("sos_sent")[0]["data"]["channels"] == {"broken": "error: RuntimeError", "ok": "ok"}


def test_yes_during_the_countdown_still_cancels() -> None:
    rig = alarm_rig("8")
    rig.run(ASK_AFTER + ASK_WINDOW + 2.0)
    rig.press("1")
    rig.press("g")
    rig.run(0.3)
    assert rig.state.safety.sos.state == "normal" and rig.state.safety.level is None
    assert not rig.hub.events("sos_sent")


def test_no_passenger_means_no_instructions() -> None:
    rig = Rig()
    rig.press("p")  # passenger out
    rig.press("8")
    rig.run(ALARM_S + ASK_AFTER + ASK_WINDOW + 0.5)
    assert rig.state.safety.sos.state == "countdown"
    assert not [s for s in rig.speaks() if s["to"] == "passenger"]
    report = rig.engine.safety.sos.build_report(rig.t)
    assert (report.passenger_state, report.occupants_n) == ("absent", 1)
    assert "pasagerul din dreapta e absent" in report.text


def test_director_reset_clears_the_sos() -> None:
    rig = alarm_rig("8")
    rig.run(ASK_AFTER + ASK_WINDOW + 1.0)
    rig.press("1")  # eyes open: with closed eyes the new trip would alarm again (safety never stops)
    rig.command("reset")
    rig.run(0.2)
    assert rig.state.safety.sos.state == "normal" and rig.state.safety.level is None


# --- "Nu te mai văd" (C7) --------------------------------------------------------------------------------------------


def monitoring_speaks(rig: Rig) -> list[dict[str, Any]]:
    return [s for s in rig.speaks() if s["clip_url"] == "/sounds/clips/monitoring_lost.mp3"]


def test_covered_camera_is_announced_repeated_and_restored() -> None:
    rig = Rig()
    rig.press("1")
    rig.run(1.0)
    rig.press("9")
    rig.run(th("safety", "monitoring", "lost_after_ms") / 1000.0 + 0.2)
    assert len(monitoring_speaks(rig)) == 1
    event = rig.hub.events("monitoring_lost")[0]
    assert event["explanation"] == "Camera nu te mai vede: camera e acoperită."
    assert rig.state.safety.level == "P2" and rig.state.safety.llm_allowed is False
    rig.run(th("safety", "monitoring", "repeat_s") + 0.3)
    assert len(monitoring_speaks(rig)) == 2 and len(rig.hub.events("monitoring_lost")) == 1
    rig.press("1")
    rig.run(0.3)
    assert rig.hub.events("monitoring_restored") and rig.state.safety.level is None


def test_no_announcement_before_the_camera_ever_saw_the_driver() -> None:
    rig = Rig()
    for _ in range(50):
        rig.engine.tick(rig.t)
        rig.t += 0.1
    assert not monitoring_speaks(rig) and rig.state.safety.monitoring_ok is False


def test_lost_perception_is_announced_too() -> None:
    rig = Rig()
    rig.press("1")
    rig.run(1.0)
    for _ in range(25):  # P1 stops sending: frames get stale
        rig.t += 0.1
        rig.engine.tick(rig.t)
    assert monitoring_speaks(rig)
    assert rig.hub.events("monitoring_lost")[0]["data"]["reason"] == "camera_unavailable"


def test_monitoring_does_not_talk_over_the_sos() -> None:
    rig = alarm_rig("8")
    rig.run(ASK_AFTER + ASK_WINDOW + 0.5)
    rig.press("9")
    rig.run(2.0)
    assert not monitoring_speaks(rig)
    assert rig.state.safety.level == "P0"


# --- arbiter (C1) ----------------------------------------------------------------------------------------------------


def test_arbiter_interrupts_only_when_the_level_rises() -> None:
    rig = Rig()
    arbiter = rig.engine.safety.arbiter
    arbiter.raise_alert("a", "P2", "phone", rig.t)
    arbiter.raise_alert("b", "P1", "microsleep", rig.t)
    arbiter.raise_alert("c", "P2", "monitoring_lost", rig.t)  # lower than the active P1: no interruption
    assert arbiter.interruptions == 2
    assert (rig.state.safety.level, rig.state.safety.alert) == ("P1", "microsleep")
    arbiter.clear("b")
    assert rig.state.safety.level == "P2" and rig.state.safety.llm_allowed is False
    arbiter.clear("a")
    arbiter.clear("c")
    assert rig.state.safety.level is None and rig.state.safety.llm_allowed is True
