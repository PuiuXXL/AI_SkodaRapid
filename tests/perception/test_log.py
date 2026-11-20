from __future__ import annotations

import io
import json

import pytest

from perception.log import LOG_LEVEL_ENV, configure_logging, get_logger


def test_json_line_with_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
    buf = io.StringIO()
    configure_logging("INFO", stream=buf)
    get_logger("capture").info("camera opened", extra={"fields": {"camera": "driver", "fps": 30, "msg": "x"}})

    lines = buf.getvalue().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["level"] == "INFO"
    assert record["logger"] == "perception.capture"
    assert record["msg"] == "camera opened"
    assert record["camera"] == "driver"
    assert record["fps"] == 30
    assert record["field_msg"] == "x"  # reserved keys are not overwritten
    assert "ts" in record


def test_level_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
    buf = io.StringIO()
    configure_logging("WARNING", stream=buf)
    log = get_logger("perception.eyes")
    log.info("hidden")
    log.warning("shown")
    lines = buf.getvalue().strip().splitlines()
    assert [json.loads(line)["msg"] for line in lines] == ["shown"]


def test_env_overrides_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENV, "debug")
    buf = io.StringIO()
    configure_logging("WARNING", stream=buf)
    get_logger("gaze").debug("visible")
    assert json.loads(buf.getvalue())["msg"] == "visible"


def test_exception_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
    buf = io.StringIO()
    configure_logging(stream=buf)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        get_logger("x").exception("failed")
    record = json.loads(buf.getvalue())
    assert "RuntimeError: boom" in record["exc"]


def test_plain_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
    buf = io.StringIO()
    configure_logging(json=False, stream=buf)
    get_logger("x").info("hello", extra={"fields": {"a": 1}})
    out = buf.getvalue()
    assert "hello" in out and "a=1" in out
