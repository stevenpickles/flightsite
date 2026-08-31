"""Tests for structured JSON logging configuration."""

from __future__ import annotations

import io
import json
import logging
import logging.handlers
from pathlib import Path

import pytest
import structlog

from flightsite.logging import configure_logging


def _capture_output(*, level: str = "INFO") -> str:
    configure_logging(level=level)
    stream = io.StringIO()
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.stream = stream  # type: ignore[attr-defined]

    logger = structlog.get_logger("flightsite.test")
    logger.info("test_event", foo="bar")

    for handler in root_logger.handlers:
        handler.flush()
    return stream.getvalue()


def test_log_output_is_json_with_expected_fields() -> None:
    output = _capture_output(level="INFO")
    line = output.strip().splitlines()[-1]

    payload = json.loads(line)

    assert payload["event"] == "test_event"
    assert payload["foo"] == "bar"
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_log_timestamp_is_iso_utc() -> None:
    output = _capture_output(level="INFO")
    line = output.strip().splitlines()[-1]

    payload = json.loads(line)
    timestamp = payload["timestamp"]

    assert timestamp.endswith("Z") or "+00:00" in timestamp


def test_default_level_is_info_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLIGHTSITE_LOG_LEVEL", raising=False)

    configure_logging()

    assert logging.getLogger().level == logging.INFO


def test_log_level_respects_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLIGHTSITE_LOG_LEVEL", "WARNING")

    configure_logging()

    assert logging.getLogger().level == logging.WARNING


def test_log_level_explicit_argument_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLIGHTSITE_LOG_LEVEL", "WARNING")

    configure_logging(level="ERROR")

    assert logging.getLogger().level == logging.ERROR


def test_messages_below_configured_level_are_suppressed() -> None:
    configure_logging(level="WARNING")
    stream = io.StringIO()
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.stream = stream  # type: ignore[attr-defined]

    logger = structlog.get_logger("flightsite.test")
    logger.info("should_not_appear")
    for handler in root_logger.handlers:
        handler.flush()

    assert stream.getvalue() == ""


def test_file_logging_disabled_by_default(tmp_path: Path) -> None:
    configure_logging(log_dir=tmp_path)

    root_logger = logging.getLogger()
    file_handlers = [
        h for h in root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handlers == []
    assert not (tmp_path / "flightsite.log").exists()


def test_file_logging_enabled_writes_json_to_rotating_file(tmp_path: Path) -> None:
    configure_logging(log_dir=tmp_path, file_logging_enabled=True)

    root_logger = logging.getLogger()
    file_handlers = [
        h for h in root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1

    logger = structlog.get_logger("flightsite.test")
    logger.info("file_event")
    for handler in file_handlers:
        handler.flush()

    log_file = tmp_path / "flightsite.log"
    assert log_file.exists()
    payload = json.loads(log_file.read_text().strip().splitlines()[-1])
    assert payload["event"] == "file_event"
