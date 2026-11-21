"""AS13 rear-seat glance: face lost right after a growing right turn -> rear_seat for at most max_s."""

from __future__ import annotations

from perception.driver_cam.rear_glance import RearGlance, RearGlanceConfig

FPS = 30.0


def _play(rg: RearGlance, yaws: list[float | None], t0: float = 0.0) -> list[bool]:
    return [rg.update(t0 + i / FPS, y is not None, y) for i, y in enumerate(yaws)]


def test_growing_right_turn_then_face_lost_is_rear_seat_for_at_most_max_s() -> None:
    rg = RearGlance(RearGlanceConfig())
    turn = [-(5.0 + 40.0 * i / 15) for i in range(16)]  # 5 -> 45 deg to the right in 0.5 s (right = negative yaw)
    out = _play(rg, turn + [None] * round(4.0 * FPS))
    lost = out[16:]
    assert all(lost[: round(2.9 * FPS)]) and not any(lost[round(3.1 * FPS) :])


def test_face_lost_without_the_turn_is_not_rear_seat() -> None:
    for yaws in ([0.0] * 20, [-45.0] * 20, [+(5.0 + 40.0 * i / 15) for i in range(16)]):  # straight / held / left
        assert not any(_play(RearGlance(RearGlanceConfig()), [*yaws, *([None] * 30)]))


def test_switch_off_never_reports_rear_seat() -> None:
    turn = [-(5.0 + 40.0 * i / 15) for i in range(16)]
    assert not any(_play(RearGlance(RearGlanceConfig(), enabled=False), turn + [None] * 30))
