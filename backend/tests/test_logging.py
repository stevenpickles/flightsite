"""Tests for structured JSON logging configuration."""

from __future__ import annotations

import io
import json
import logging
import logging.handlers
from pathlib import Path

import pytest
import structlog

from flightsite.app import create_app
from flightsite.diagnostics.errors import ErrorRing, ErrorRingHandler
from flightsite.logging import configure_logging, install_error_capture


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


def test_the_file_handler_rotates(tmp_path: Path) -> None:
    """SPEC §68 asks for *rotating* local logs, not an unbounded file."""
    configure_logging(log_dir=tmp_path, file_logging_enabled=True)

    root_logger = logging.getLogger()
    (handler,) = [
        h for h in root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert handler.maxBytes > 0
    assert handler.backupCount > 0

    handler.maxBytes = 512
    logger = structlog.get_logger("flightsite.test")
    for index in range(200):
        logger.info("rotate_me", index=index, filler="x" * 100)
    handler.flush()

    assert (tmp_path / "flightsite.log.1").exists()


class TestErrorCaptureInstallation:
    """``install_error_capture`` — the diagnostics ring's feed (SPEC §67)."""

    def test_installing_attaches_a_handler_that_captures_warnings(self) -> None:
        ring = ErrorRing()
        install_error_capture(ring)

        logging.getLogger("flightsite.db.example").warning("db_write_failed")

        assert [entry.event for entry in ring.recent("database")] == ["db_write_failed"]

    def test_installing_twice_leaves_one_handler(self) -> None:
        """The test suite builds many apps in one process; handlers must not stack."""
        ring = ErrorRing()
        install_error_capture(ring)
        install_error_capture(ring)

        root_logger = logging.getLogger()
        handlers = [h for h in root_logger.handlers if isinstance(h, ErrorRingHandler)]
        assert len(handlers) == 1

        logging.getLogger("flightsite.db.example").warning("once")
        assert ring.total() == 1

    def test_the_secrets_provider_is_consulted_per_record(self) -> None:
        """A key rotated through the Settings UI takes effect without a restart."""
        ring = ErrorRing()
        current: list[str] = []
        install_error_capture(ring, lambda: tuple(current))

        logging.getLogger("flightsite.db.example").warning("before rotation: hunter2")
        current.append("hunter2")
        logging.getLogger("flightsite.db.example").warning("after rotation: hunter2")

        events = [entry.event for entry in ring.recent("database")]
        assert "hunter2" not in events[0]
        assert "hunter2" in events[1]


def test_create_app_enables_file_logging_in_the_data_dir(isolated_data_dir: Path) -> None:
    """SPEC §68's rotating local logs, finalized: on by default, beside the data.

    An appliance the user is not expected to SSH into needs a log history that
    outlives the container's stdout buffer, and putting it under the data
    directory is what keeps it inside the tree backup already covers.
    """
    create_app(isolated_data_dir)

    root_logger = logging.getLogger()
    file_handlers = [
        h for h in root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename).parent == isolated_data_dir / "logs"


def test_file_logging_can_be_turned_off_in_config(isolated_data_dir: Path) -> None:
    (isolated_data_dir / "config.yaml").write_text("log_file_enabled: false\n", encoding="utf-8")
    create_app(isolated_data_dir)

    root_logger = logging.getLogger()
    assert not [
        h for h in root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
