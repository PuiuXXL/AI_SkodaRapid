"""Structured logging for perception: one JSON object per line.

Usage::

    from perception.log import configure_logging, get_logger

    configure_logging()
    log = get_logger(__name__)
    log.info("camera opened", extra={"fields": {"camera": "driver", "fps": 30}})

Output::

    {"ts":"2026-11-20T23:15:02.123+00:00","level":"INFO","logger":"perception.capture","msg":"camera opened",
     "camera":"driver","fps":30}

``DRIVEMATE_LOG_LEVEL`` (DEBUG, INFO, ...) overrides the level passed to ``configure_logging``.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

import orjson

__all__ = ["LOG_LEVEL_ENV", "JsonFormatter", "configure_logging", "get_logger"]

LOG_LEVEL_ENV = "DRIVEMATE_LOG_LEVEL"
_RESERVED = ("ts", "level", "logger", "msg")


class JsonFormatter(logging.Formatter):
    """Formats a record as a single JSON line; ``extra={"fields": {...}}`` is merged into the object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                payload[f"field_{key}" if key in _RESERVED else str(key)] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return orjson.dumps(payload, default=str, option=orjson.OPT_SERIALIZE_NUMPY).decode()


class _PlainFormatter(logging.Formatter):
    """Human-readable variant for local debugging: ``fields`` appended as key=value."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict) and fields:
            text += " " + " ".join(f"{k}={v}" for k, v in fields.items())
        return text


def configure_logging(level: str | int = "INFO", *, json: bool = True, stream: TextIO | None = None) -> None:
    """Configure the ``perception`` logger tree (idempotent: replaces handlers installed by a previous call)."""
    env_level = os.environ.get(LOG_LEVEL_ENV)
    resolved: str | int = env_level.upper() if env_level else level
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter() if json else _PlainFormatter())
    root = logging.getLogger("perception")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Logger under the ``perception`` tree (``perception.<name>`` unless already prefixed)."""
    if name == "perception" or name.startswith("perception."):
        return logging.getLogger(name)
    return logging.getLogger(f"perception.{name}")
