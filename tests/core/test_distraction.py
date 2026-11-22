"""Tests for the distraction escalation (C2: discrete signal -> voice -> alarm) and the A/B counter (B8).
Scenes 2 (mirror, counter) and 3 (phone), in fake time."""

from __future__ import annotations

from typing import Any

from p2_helpers import ALARM_S, ASK_AFTER, ASK_WINDOW, Rig

from core.settings import th

VOICE_AFTER = th("safety", "escalation", "voice_after_ms") / 1000.0
ALARM_AFTER = th("safety", "escalation", "alarm_after_ms") / 1000.0
PHONE_MIN = th("safety", "distraction", "phone_min_ms") / 1000.0


def look_at(zone: str, start: float, conf: float = 0.9) -> Any:
    """A patch: from ``start`` the driver looks at ``zone`` and keeps looking (off_road_ms grows)."""

    def patch(frame: dict[str, Any], t: float) -> None:
        if t >= start:
            gaze = frame["driver"]["gaze"]
            gaze.update(zone=zone, conf=conf, off_road_ms=round((t - start) * 1000.0, 1))

    return patch


def cue_times(rig: Rig) -> list[float]:
    return [e["ts"] for e in rig.hub.events("visual_cue")]


def warnings(rig: Rig) -> list[str]:
    return [s["text"] for s in rig.speaks() if s["id"].startswith("dis")]


# --- scene 2: the mirror and the counter -----------------------------------------------------------------------------


def test_mirror_glance_trips_the_simple_threshold_not_drivemate() -> None:
    rig = Rig(scene=2)
    rig.press("2")
    rig.run(4.0)
    assert not rig.hub.events("visual_cue")
    assert (rig.state.ab.naive_alerts, rig.state.ab.our_alerts) == (1, 0)
    assert rig.hub.events("naive_alert")[0]["data"]["reason"] == "head_pose"


def test_normal_driving_alerts_nobody() -> None:
    rig = Rig(scene=8)
    rig.run(30.0)
    assert (rig.state.ab.naive_alerts, rig.state.ab.our_alerts) == (0, 0)
    assert not rig.hub.events("visual_cue")


# --- scene 3: the phone ----------------------------------------------------------------------------------------------


def test_phone_escalates_cue_voice_alarm() -> None:
    rig = Rig(scene=3)
    rig.run(1.0)
    pressed = rig.t
    rig.press("3")
    rig.run(PHONE_MIN + ALARM_AFTER + 0.5)
    cue = rig.hub.events("visual_cue")[0]
    assert PHONE_MIN <= cue["ts"] - pressed <= PHONE_MIN + 0.2
    assert cue["data"]["alert"] == "phone" and cue["explanation"].endswith("la 50 km/h.")
    assert rig.state.safety.level == "P2" and rig.state.safety.alert == "phone"
    assert rig.state.safety.llm_allowed is False
    assert warnings(rig) == ["Andrei, lasă telefonul, te rog."]
    spoken = next(s for s in rig.speaks() if s["id"].startswith("dis"))
    assert spoken["sentences"] and spoken["clip_url"] is None  # no clip yet: P3's TTS, browser voice as fallback
    voice_at = rig.hub.events("alert")[0]["ts"]
    assert VOICE_AFTER <= voice_at - cue["ts"] <= VOICE_AFTER + 0.15
    alarm = rig.hub.of_type("alarm")[0]
    assert (alarm["level"], alarm["alert"]) == ("P2", "phone")
    assert ALARM_AFTER <= rig.hub.events("alarm")[0]["ts"] - cue["ts"] <= ALARM_AFTER + 0.15
    assert rig.state.ab.our_alerts == 1 and rig.state.ab.naive_alerts >= 1
    rig.press("1")
    rig.run(0.5)
    assert rig.state.safety.level is None and rig.state.safety.llm_allowed is True
    assert rig.hub.events("distraction_end")[0]["data"]["alert"] == "phone"


def test_phone_with_a_waiting_message() -> None:
    rig = Rig(scene=3)
    rig.command("fake_message", {"from": "Mihai", "app": "whatsapp", "text": "Unde ești?"})
    rig.press("3")
    rig.run(PHONE_MIN + VOICE_AFTER + 0.3)
    assert warnings(rig) == ["Andrei, lasă telefonul, ți-l citesc eu."]


def test_no_drivemate_alert_when_parked() -> None:
    rig = Rig(scene=1)  # 0 km/h
    rig.press("3")
    rig.run(6.0)
    assert not rig.hub.events("visual_cue") and rig.state.ab.our_alerts == 0
    assert rig.state.ab.naive_alerts >= 1  # the simple threshold has no context


def test_passenger_phone_is_not_a_driver_alert() -> None:
    """G5: the passenger shows a phone; the simple threshold sees a phone, DriveMate knows whose it is."""
    rig = Rig(scene=4)
    rig.press("4")
    rig.run(10.0)
    assert not rig.hub.events("visual_cue") and rig.state.ab.our_alerts == 0
    assert "phone" in [e["data"]["reason"] for e in rig.hub.events("naive_alert")]


# --- long glances ----------------------------------------------------------------------------------------------------


def test_long_glance_threshold_depends_on_speed() -> None:
    fast = Rig(scene=8)  # 118 km/h: off_road_ms_high_speed
    fast.patch = look_at("infotainment", fast.t + 0.5)
    fast.run(0.5 + th("safety", "distraction", "off_road_ms_high_speed") / 1000.0 + 0.2)
    cue = fast.hub.events("visual_cue")[0]
    assert cue["data"]["alert"] == "off_road"
    assert cue["explanation"].startswith("Ai privit spre ecran 1,") and cue["explanation"].endswith("la 118 km/h.")

    city = Rig(scene=2)  # 50 km/h: off_road_ms
    city.patch = look_at("infotainment", city.t + 0.5)
    city.run(0.5 + th("safety", "distraction", "off_road_ms_high_speed") / 1000.0 + 0.2)
    assert not city.hub.events("visual_cue")
    city.run(1.0)
    assert city.hub.events("visual_cue")
    city.patch = None  # back on the road
    city.run(0.5)
    end = city.hub.events("distraction_end")[0]
    assert end["data"]["alert"] == "off_road" and end["latency_ms"] > 0


def test_unknown_zone_or_low_confidence_never_alerts() -> None:
    for patch in (look_at("unknown", 0.0), look_at("infotainment", 0.0, conf=0.3)):
        rig = Rig(scene=8)
        rig.patch = patch
        rig.run(5.0)
        assert not rig.hub.events("visual_cue")


def test_same_warning_is_not_repeated_within_the_cooldown() -> None:
    rig = Rig(scene=3)
    for _ in range(2):  # two phone episodes, close together
        rig.press("3")
        rig.run(PHONE_MIN + VOICE_AFTER + 0.3)
        rig.press("1")
        rig.run(1.0)
    assert len(cue_times(rig)) == 2 and warnings(rig) == ["Andrei, lasă telefonul, te rog."]
    rig.run(th("safety", "escalation", "cooldown_s"))
    rig.press("3")
    rig.run(PHONE_MIN + VOICE_AFTER + 0.3)
    # again within safety.escalation.repeat_window_min: the firmer text (templates escalation_repeat)
    assert warnings(rig) == ["Andrei, lasă telefonul, te rog.",
                             "Andrei, iar telefonul. Lasă-l jos; ce e urgent îți citesc eu."]


def test_quiet_during_the_sos() -> None:
    rig = Rig(scene=8)
    rig.press("8")
    rig.run(ALARM_S + ASK_AFTER + ASK_WINDOW + 0.5)
    assert rig.state.safety.level == "P0"
    rig.patch = lambda frame, t: frame["driver"]["phone"].update(in_use=True, source="detector", conf=0.9)
    rig.run(PHONE_MIN + ALARM_AFTER + 0.5)
    assert not warnings(rig)
    assert all(a["level"] != "P2" for a in rig.hub.of_type("alarm"))
    assert rig.state.safety.level == "P0"


# --- the A/B counter -------------------------------------------------------------------------------------------------


def test_microsleep_counts_on_both_sides() -> None:
    rig = Rig(scene=8)
    rig.press("7")
    rig.run(ALARM_S + 0.5)
    assert (rig.state.ab.naive_alerts, rig.state.ab.our_alerts) == (1, 1)


def test_a_short_closure_is_only_the_simple_thresholds_alarm() -> None:
    """1.5 s with the eyes closed: the simple threshold (1 s) alarms, DriveMate asks about a break instead."""
    rig = Rig(scene=8)
    rig.press("7")
    rig.run(1.5)
    rig.press("1")
    rig.run(2.0)
    assert (rig.state.ab.naive_alerts, rig.state.ab.our_alerts) == (1, 0)


def test_director_reset_clears_the_counter() -> None:
    rig = Rig(scene=2)
    rig.press("2")
    rig.run(4.0)
    assert rig.state.ab.naive_alerts == 1
    rig.command("reset")
    rig.run(0.2)
    assert (rig.state.ab.naive_alerts, rig.state.ab.our_alerts) == (0, 0)
