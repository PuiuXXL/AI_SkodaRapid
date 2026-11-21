"""Tests for core/safety: the alarm (C3), "Ești bine?" (C4), the SOS countdown (C5), "Nu te mai văd" (C7), the
arbiter (C1) and the yes / no on every channel (E3). Scenes 8 and 9 of the demo, in fake time."""

from __future__ import annotations

from typing import Any

import pytest
from p2_helpers import Rig

from core.safety.answers import parse_gesture, parse_voice
from core.settings import th
from shared import contracts as c

ASK_AFTER = th("sos", "ask_after_alarm_s")
ASK_WINDOW = th("sos", "ask_clip_s") + th("sos", "answer_window_s")
COUNTDOWN = th("sos", "countdown_s")


def alarm_rig(key: str = "7", **kwargs: Any) -> Rig:
    """Highway (scene 8), eyes closed until the alarm fires."""
    rig = Rig(**kwargs)
    rig.press("1")
    rig.run(2.0)
    rig.press(key)
    rig.run_until(lambda: rig.engine.safety.sos.state == "alarm", limit_s=5)
    return rig


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


def test_gesture_answers() -> None:
    assert (parse_gesture("Thumb_Up"), parse_gesture("Thumb_Down"), parse_gesture("Open_Palm")) == ("yes", "no", None)


# --- alarm (C3) ------------------------------------------------------------------------------------------------------


def test_blinks_and_mirror_glances_never_alarm() -> None:
    rig = Rig()
    rig.press("1")
    rig.run(20.0)
    rig.press("2")
    rig.run(5.0)
    assert not rig.hub.of_type("alarm")
    assert rig.engine.safety.sos.state == "normal" and rig.state.safety.level is None


def test_eyes_closed_alarm_fires_on_the_frame() -> None:
    rig = Rig()
    rig.press("1")
    rig.run(2.0)
    pressed = rig.t
    rig.press("7")
    rig.run_until(lambda: bool(rig.hub.of_type("alarm")), limit_s=5)
    alarm_at = rig.hub.events("alarm")[0]["ts"]
    threshold = th("safety", "microsleep", "closed_ms") / 1000.0
    assert threshold <= alarm_at - pressed <= threshold + 1.0 / 15 + 1e-6  # the first frame over the threshold
    alarm = rig.hub.of_type("alarm")[0]
    assert alarm["clip_url"] == "/sounds/clips/alarm_andrei.mp3" and (alarm["level"], alarm["alert"]) == ("P1",
                                                                                                         "microsleep")
    sent = [m["type"] for m in rig.hub.ui_sent]
    assert sent.index("speak_control") < sent.index("media") < sent.index("alarm")  # sounds stop first
    assert rig.state.safety.level == "P1" and rig.state.safety.llm_allowed is False
    assert rig.hub.events("alarm")[0]["explanation"] == "Ochii închiși 1,0 s la 118 km/h."


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
    rig.run(1.5)
    assert len(rig.hub.of_type("alarm")) == 2  # eyes opened in between: a new closure, a new alarm


# --- "Ești bine?" (C4) -----------------------------------------------------------------------------------------------


def test_are_you_ok_opens_the_dialog_window() -> None:
    rig = alarm_rig()
    rig.run(ASK_AFTER + 0.2)
    question = [s for s in rig.speaks() if s["clip_url"] == "/sounds/clips/are_you_ok.mp3"]
    assert question and question[0]["is_question"] and question[0]["expects"] == "yes_no"
    windows = [m for m in rig.hub.perception_sent if m["cmd"] == "dialog_window"]
    assert windows[-1]["open"] is True and windows[-1]["to"] == "driver"
    assert rig.state.interaction.dialog_window_open is True and rig.state.safety.sos.state == "asking"


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


@pytest.mark.parametrize(("key", "channel"), [("y", "nod"), ("g", "gesture")])
def test_nod_or_thumbs_up_cancels(key: str, channel: str) -> None:
    rig = alarm_rig()
    rig.run(ASK_AFTER + 0.5)
    rig.press("1")
    rig.press(key)
    rig.run(0.3)
    assert rig.state.safety.sos.state == "normal"
    assert rig.hub.events("sos_cancelled")[0]["channel"] == channel


def test_speech_without_wake_word_or_window_is_ignored() -> None:
    rig = alarm_rig()  # alarm sent, the question (and its window) not yet
    rig.say("da", addressed=False)
    assert rig.engine.safety.sos.state == "alarm"
    rig.say("da", addressed=True)
    assert rig.engine.safety.sos.state == "normal"


# --- countdown and SOS (C5, F6) --------------------------------------------------------------------------------------


def test_no_answer_leads_to_passenger_instructions_countdown_and_sos() -> None:
    reports: list[c.SosReport] = []
    rig = alarm_rig("8", sos_channels={"test": lambda report: reports.append(report) or "ok"})
    assert rig.hub.of_type("alarm")[0]["alert"] == "nodding"
    rig.run(ASK_AFTER + ASK_WINDOW + 0.2)
    assert rig.state.safety.sos.state == "countdown" and rig.state.safety.level == "P0"
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


def test_answer_no_starts_the_countdown_at_once() -> None:
    rig = alarm_rig()
    rig.run(ASK_AFTER + 0.5)
    rig.say("Nu.")
    assert rig.engine.safety.sos.state == "countdown"  # at once, not at the end of the window
    rig.run(0.1)
    assert rig.state.safety.sos.state == "countdown" and rig.state.safety.level == "P0"
    assert rig.hub.events("sos_countdown")[0]["data"]["why"] == "answer_no:voice"


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
    rig.run(ASK_AFTER + ASK_WINDOW + 0.5)
    assert not [s for s in rig.speaks() if s["to"] == "passenger"]
    report = rig.engine.safety.sos.build_report(rig.t)
    assert (report.passenger_state, report.occupants_n) == ("absent", 1)
    assert "pasagerul din dreapta e absent" in report.text


def test_director_reset_clears_the_sos() -> None:
    rig = alarm_rig("8")
    rig.run(ASK_AFTER + ASK_WINDOW + 1.0)
    rig.press("1")  # eyes open: with closed eyes the new trip would alarm again at once (safety never stops)
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
