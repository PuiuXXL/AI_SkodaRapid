"""gaze.mode boxes: angular boxes around the driver's median direction (wide road, generous margins)."""

from __future__ import annotations

from perception.config import load_config
from perception.driver_cam.gaze_boxes import BoxClassifier

CENTER = (-6.0, -3.0)  # a camera a bit off-axis: the driver's road direction is not (0, 0)


def classifier() -> BoxClassifier:
    b = load_config().gaze.boxes
    return BoxClassifier(b.zones, margin_deg=b.margin_deg, right_sign=float(b.right_sign),
                         center_window_s=b.center_window_s, center_min_s=b.center_min_s,
                         away_beyond_deg=b.away_beyond_deg)  # fmt: skip


def warmed() -> tuple[BoxClassifier, float]:
    clf, t = classifier(), 0.0
    for _ in range(90):  # 3 s looking at the road
        clf.classify(t, *CENTER)
        t += 1 / 30
    return clf, t


def zone(clf: BoxClassifier, t: float, right: float, up: float) -> str:
    """Zone of a direction given in the driver's terms (right > 0 = towards the passenger, raw yaw < 0)."""
    res = clf.classify(t, CENTER[0] - right, CENTER[1] + up)
    assert res is not None
    return res.zone


def test_no_zone_until_the_road_centre_is_known() -> None:
    assert classifier().classify(0.0, *CENTER) is None


def test_road_is_wide_not_a_point() -> None:
    clf, t = warmed()
    assert clf.center is not None and abs(clf.center[0] - CENTER[0]) < 1e-6
    for right, up in ((0, 0), (15, 0), (-15, 0), (0, 10), (10, -10), (-17, 11)):  # anywhere on the windscreen
        assert zone(clf, t, right, up) == "road"


def test_every_zone_has_its_box() -> None:
    clf, t = warmed()
    expected = {(0, -25): "cluster", (0, -50): "lap", (20, 15): "mirror_rear", (25, -25): "infotainment",
                (-35, 0): "mirror_left", (50, 0): "mirror_right", (55, -25): "passenger"}  # fmt: skip
    for (right, up), name in expected.items():
        assert zone(clf, t, right, up) == name, (right, up)


def test_margin_then_away_then_unknown() -> None:
    clf, t = warmed()
    near = clf.classify(t, CENTER[0] - 0.0, CENTER[1] + 16.0)  # 4 deg above the road box -> still road
    assert near is not None and near.zone == "road" and near.conf < 0.85
    assert zone(clf, t, -95, 0) == "away"  # far to the left, beyond every box
    assert zone(clf, t, 0, 60) == "unknown"  # straight up at the roof: no zone, never an alert
