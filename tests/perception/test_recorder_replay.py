from __future__ import annotations

import gzip
from pathlib import Path

import orjson
import pytest

from perception.recorder import FeatureWriter, ensure_data_dir
from perception.replay import FeatureReplay
from tests.perception.feature_factory import make_frame

META = {
    "schema_version": 1,
    "label": "synthetic",
    "camera": {"name": "driver", "width": 1280, "height": 720, "fps": 30.0},
}


@pytest.mark.parametrize("name", ["features.jsonl", "features.jsonl.gz"])
def test_record_then_replay_is_identical(tmp_path: Path, name: str) -> None:
    frames = [make_frame(i) for i in range(120)]
    path = tmp_path / name
    with FeatureWriter(path, META) as writer:
        for frame in frames:
            writer.write(frame)
    assert writer.count == 120

    replay = FeatureReplay(path)
    assert replay.meta == META
    assert list(replay.frames()) == frames


def test_gzip_is_really_compressed(tmp_path: Path) -> None:
    path = tmp_path / "f.jsonl.gz"
    with FeatureWriter(path, META) as writer:
        writer.write(make_frame(0))
    with gzip.open(path, "rb") as fh:
        assert orjson.loads(fh.readline())["type"] == "meta"


def test_play_keeps_original_timing(tmp_path: Path) -> None:
    path = tmp_path / "f.jsonl"
    with FeatureWriter(path, META) as writer:
        for i in range(31):  # 0 .. 1.0 s at 30 fps
            writer.write(make_frame(i))

    now = [0.0]
    slept: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    replay = FeatureReplay(path)
    frames = list(replay.play(1.0, clock=clock, sleep=sleep))
    assert len(frames) == 31
    assert now[0] == pytest.approx(1.0, abs=1e-6)

    now[0], slept[:] = 0.0, []
    list(replay.play(4.0, clock=clock, sleep=sleep))
    assert now[0] == pytest.approx(0.25, abs=1e-6)

    now[0], slept[:] = 0.0, []
    list(replay.play(0, clock=clock, sleep=sleep))  # as fast as possible
    assert slept == []


def test_summary_counts(tmp_path: Path) -> None:
    path = tmp_path / "f.jsonl"
    with FeatureWriter(path, META) as writer:
        for i in range(60):
            writer.write(make_frame(i))
    summary = FeatureReplay(path).summary()
    assert summary["frames"] == 60
    assert summary["fps"] == pytest.approx(30.0, rel=0.01)
    assert summary["gaze_runs"] == 30  # every 2nd frame (the faceless frame 49 is odd, so no gaze is lost)
    assert summary["phone_runs"] == 10
    assert summary["gesture_runs"] == 20
    assert summary["face_present_pct"] == pytest.approx(100 * 59 / 60, abs=0.1)


def test_replay_requires_meta_line(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_bytes(make_frame(0).to_json() + b"\n")
    with pytest.raises(ValueError, match="meta"):
        FeatureReplay(path)


def test_replay_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FeatureReplay(tmp_path / "nope.jsonl")


def test_data_dir_ignores_itself(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_data_dir(root / "features" / "s1" / "f.jsonl", data_root=root)
    assert (root / ".gitignore").read_text(encoding="utf-8").strip().endswith("*")
    assert "never in the demo" in (root / "README.md").read_text(encoding="utf-8")
    # paths outside the data root are left alone
    other = tmp_path / "elsewhere"
    ensure_data_dir(other / "f.jsonl", data_root=other / "data")
    assert not (other / "data").exists()
