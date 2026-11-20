from __future__ import annotations

from pathlib import Path

from perception.labels import Interval, KeyLabeler, LabelWriter, align, load_labels, to_intervals

ZONES = ["road", "mirror_left", "mirror_right", "mirror_rear", "cluster", "infotainment", "lap", "passenger"]


def _session(tmp_path: Path) -> tuple[KeyLabeler, LabelWriter]:
    writer = LabelWriter(tmp_path / "labels.jsonl", {"session": "t", "zones": ZONES})
    return KeyLabeler(writer, ZONES), writer


def test_keys_produce_events_and_round_trip(tmp_path: Path) -> None:
    labeler, writer = _session(tmp_path)
    assert labeler.on_key("b", 1.00) == "blink"
    assert labeler.on_key("c", 2.00) == "eyes_closed start"
    assert labeler.on_key("c", 3.50) == "eyes_closed end"
    assert labeler.on_key("z", 4.00) is not None
    assert labeler.on_key("2", 4.10) == "zone = mirror_left"
    assert labeler.on_key("s", 5.00) == "speaking start"
    assert labeler.on_key("x", 5.50) is None  # unknown key ignored
    labeler.finish(6.00)
    writer.close()

    meta, events = load_labels(tmp_path / "labels.jsonl")
    assert meta["zones"] == ZONES
    assert events == labeler.events
    assert [(e.label, e.kind) for e in events] == [
        ("blink", "instant"),
        ("eyes_closed", "start"),
        ("eyes_closed", "end"),
        ("zone", "state"),
        ("speaking", "start"),
        ("speaking", "end"),
        ("zone", "state"),
    ]


def test_held_key_auto_repeat_is_ignored() -> None:
    """Replays the real session log: holding 'c' produced start/end flips 40-50 ms apart."""
    labeler = KeyLabeler(None, ZONES)
    assert labeler.on_key("c", 34.30) == "eyes_closed start"
    for t in (34.84, 34.89, 34.93, 34.96, 35.11):  # OS auto-repeat while the key is held
        assert labeler.on_key("c", t) is None
    assert labeler.active == {"eyes_closed"}
    assert labeler.on_key("c", 36.50) == "eyes_closed end"  # released, pressed again later
    assert labeler.on_key("b", 36.60) == "blink"  # other keys are not affected
    assert labeler.on_key("b", 36.70) is None  # but a held 'b' does not spam blinks


def test_zone_key_needs_a_digit_in_time() -> None:
    labeler = KeyLabeler(None, ZONES)
    labeler.on_key("z", 1.0)
    assert labeler.on_key("3", 3.0) is None  # too late (> 1.5 s): digit ignored
    assert labeler.zone is None
    labeler.on_key("z", 4.0)
    assert labeler.on_key("b", 4.2) == "blink"  # a non-digit cancels the zone and acts normally
    labeler.on_key("z", 5.0)
    assert labeler.on_key("9", 5.1) is None  # only 8 zones
    labeler.on_key("z", 6.0)
    assert labeler.on_key("1", 6.1) == "zone = road"
    labeler.on_key("z", 7.0)
    assert labeler.on_key("0", 7.1) == "zone cleared"
    assert labeler.zone is None


def test_intervals_from_events() -> None:
    labeler = KeyLabeler(None, ZONES)
    labeler.on_key("b", 1.0)
    labeler.on_key("c", 2.0)
    labeler.on_key("c", 3.5)
    labeler.on_key("z", 4.0)
    labeler.on_key("7", 4.1)
    labeler.on_key("z", 5.0)
    labeler.on_key("1", 5.2)
    labeler.on_key("y", 6.0)  # never closed
    intervals = to_intervals(labeler.events, t_end=8.0)
    assert intervals == [
        Interval("blink", 1.0, 1.0),
        Interval("eyes_closed", 2.0, 3.5),
        Interval("zone", 4.1, 5.2, "lap"),
        Interval("zone", 5.2, 8.0, "road"),
        Interval("yawn", 6.0, 8.0),
    ]
    assert Interval("yawn", 6.0, 8.0) not in to_intervals(labeler.events)  # no t_end: open intervals dropped


def test_alignment_to_frame_times() -> None:
    times = [i / 30 for i in range(300)]  # 10 s at 30 fps
    aligned = dict(
        (iv.label, rng) for iv, rng in align([Interval("blink", 1.01, 1.01), Interval("eyes_closed", 2.0, 3.5)], times)
    )
    assert aligned["blink"] == range(30, 31)  # nearest frame to 1.01 s is t=1.000
    closed = aligned["eyes_closed"]
    assert times[closed.start] >= 2.0 and times[closed.start - 1] < 2.0
    assert times[closed.stop - 1] <= 3.5 and times[closed.stop] > 3.5
    assert len(closed) == 46  # frames 60 .. 105


def test_alignment_with_session_clock_from_frames() -> None:
    """Labels and frames share the session clock: an event pressed at a frame's t lands on that frame."""
    times = [0.0, 0.034, 0.067, 0.101, 0.134]
    ((_, rng),) = align([Interval("blink", 0.067, 0.067)], times)
    assert list(rng) == [2]
    ((_, empty),) = align([Interval("yawn", 0.2, 0.3)], times)
    assert len(empty) == 0
