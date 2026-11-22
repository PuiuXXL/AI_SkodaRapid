"""A head that falls and loses the face, and a face lost for long while moving (live test 2026-11-22: the head let
down with the eyes open gave "Nu te mai văd. Monitorizarea e întreruptă." instead of the alarm)."""

from __future__ import annotations

import math
from typing import Any

from p2_helpers import Rig

from core.settings import th

ALARM_S = th("safety", "drowsiness", "alarm_ms") / 1000.0
FACE_LOST_S = 2.0  # P1: perception.yaml monitoring.face_lost_s
LOST_AFTER = th("safety", "monitoring", "lost_after_ms") / 1000.0
ALARM_AFTER = th("safety", "monitoring", "alarm_after_s")


def driver(fall_at: float, lost_at: float, back_at: float = math.inf, drop_deg: float = 25.0,
           reason: str = "face_lost") -> Any:
    """Frames: upright, then the head goes down by ``drop_deg`` (eyes OPEN) until the face is lost at ``lost_at``
    (P1: angles null, eyes unreliable, monitoring_ok false after face_lost_s with ``reason``), back at ``back_at``."""

    def patch(frame: dict[str, Any], t: float) -> None:
        d = frame["driver"]
        if lost_at <= t < back_at:
            d["head"].update(yaw=None, pitch=None, roll=None, nodding=False)
            d["eyes"].update(reliable=False, state="UNKNOWN", closed_ms=0.0, ear=None)
            d["gaze"].update(zone="unknown", conf=0.0, off_road_ms=0.0)
            if t - lost_at >= FACE_LOST_S:
                d.update(monitoring_ok=False, monitoring_reason=reason)
            return
        pitch = 0.0
        if fall_at <= t < lost_at:
            pitch = -drop_deg * (t - fall_at) / (lost_at - fall_at)
        d["head"].update(yaw=0.0, pitch=round(pitch, 1), roll=0.0, nodding=False)
        d["eyes"].update(reliable=True, state="OPEN", closed_ms=0.0, ear=0.28)
        d["gaze"].update(zone="road", conf=0.9, off_road_ms=0.0)

    return patch


def said(rig: Rig) -> list[str]:
    return [s["text"] for s in rig.speaks()]


def test_a_falling_head_that_loses_the_face_is_a_possible_microsleep() -> None:
    rig = Rig(scene=5)  # 118 km/h
    rig.run(1.0)
    start = rig.t
    rig.patch = driver(fall_at=start + 4.0, lost_at=start + 5.0)  # 25 deg down in 1 s, eyes open, face lost
    rig.run(5.0 + ALARM_S + 0.3)
    alarm = rig.hub.of_type("alarm")
    assert alarm and alarm[0]["alert"] == "head_down"
    assert rig.hub.events("head_fall") and rig.engine.safety.sos.trigger == "head_down"
    alarm_at = rig.hub.events("alarm")[0]["ts"]
    assert ALARM_S - 0.2 <= alarm_at - (start + 5.0) <= ALARM_S + 0.2  # 3 s after the last face frame
    assert "Nu te mai văd. Monitorizarea e întreruptă." not in said(rig)  # the alarm, not the announcement


def test_a_head_back_up_in_time_gets_the_break_question_not_the_alarm() -> None:
    rig = Rig(scene=5)
    rig.run(1.0)
    start = rig.t
    rig.patch = driver(fall_at=start + 4.0, lost_at=start + 5.0, back_at=start + 6.5)
    rig.run(10.0)
    assert not rig.hub.of_type("alarm")
    assert rig.hub.events("head_fall") and rig.hub.events("eyes_reopened")
    assert rig.hub.events("drowsy_check")  # "Andrei, ai închis ochii câteva clipe. Facem o pauză?"


def test_a_steady_head_that_turns_away_is_not_a_fall() -> None:
    rig = Rig(scene=5)
    rig.run(1.0)
    start = rig.t
    rig.patch = driver(fall_at=start + 4.0, lost_at=start + 5.0, drop_deg=3.0)  # face lost, head not falling
    rig.run(5.0 + FACE_LOST_S + LOST_AFTER + 0.3)
    assert not rig.hub.events("head_fall") and not rig.hub.of_type("alarm")
    assert "Nu te mai văd. Monitorizarea e întreruptă." in said(rig)


def test_a_face_lost_for_long_while_moving_starts_the_sos() -> None:
    rig = Rig(scene=5)
    rig.run(1.0)
    start = rig.t
    rig.patch = driver(fall_at=start + 4.0, lost_at=start + 5.0, drop_deg=3.0)
    rig.run(5.0 + FACE_LOST_S + LOST_AFTER + ALARM_AFTER + 0.5)
    alarm = rig.hub.of_type("alarm")
    assert alarm and alarm[0]["alert"] == "face_lost"
    assert rig.engine.safety.sos.state in ("alarm", "asking")
    rig.run(30.0)  # still lost: the announcement repeats, the SOS does not start again
    assert rig.engine.safety.sos.trigger in (None, "face_lost")
    assert len([e for e in rig.hub.events("alarm") if e["data"]["alert"] == "face_lost"]) == 1


def test_a_covered_camera_is_only_announced() -> None:
    rig = Rig(scene=5)
    rig.run(1.0)
    start = rig.t
    rig.patch = driver(fall_at=start + 4.0, lost_at=start + 5.0, drop_deg=3.0, reason="occluded")
    rig.run(5.0 + FACE_LOST_S + LOST_AFTER + ALARM_AFTER + 2.0)
    assert not rig.hub.of_type("alarm") and "Nu te mai văd. Monitorizarea e întreruptă." in said(rig)


def test_parked_no_alarm_for_bending_down() -> None:
    rig = Rig(scene=7)  # stopped at the fuel station
    rig.run(1.0)
    start = rig.t
    rig.patch = driver(fall_at=start + 4.0, lost_at=start + 5.0)
    rig.run(5.0 + FACE_LOST_S + LOST_AFTER + ALARM_AFTER + 2.0)
    assert not rig.hub.events("head_fall") and not rig.hub.of_type("alarm")
