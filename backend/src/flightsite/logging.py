"""Structured JSON logging configuration.

Configures both ``structlog`` and stdlib ``logging`` so that every log record
— whether emitted through a ``structlog`` logger or a stdlib one (e.g. from
uvicorn or third-party libraries) — is rendered as a single JSON line with an
ISO-8601 UTC timestamp. The log level is configurable via the
``FLIGHTSITE_LOG_LEVEL`` environment variable (default ``INFO``).

A rotating-file handler scaffold is included but disabled by default.

:func:`flightsite.app.create_app` passes ``settings.log_level``, which the
settings model has already resolved through the config.yaml / secrets.yaml /
environment layering — so ``FLIGHTSITE_LOG_LEVEL`` still outranks
``config.yaml``. The environment fallback below keeps this module usable on
its own, before any settings object exists.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

import structlog

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_FILENAME = "flightsite.log"
DEFAULT_MAX_BYTES = 10_000_000
DEFAULT_BACKUP_COUNT = 5


def _resolve_level(level: str | None) -> int:
    name = (level or os.environ.get("FLIGHTSITE_LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()
    resolved = logging.getLevelName(name)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    return resolved


def configure_logging(
    *,
    level: str | None = None,
    log_dir: str | Path | None = None,
    file_logging_enabled: bool = False,
) -> None:
    """Configure structlog + stdlib logging for structured JSON output.

    Args:
        level: log level name (e.g. "DEBUG"). Defaults to the
            ``FLIGHTSITE_LOG_LEVEL`` environment variable, then "INFO".
        log_dir: directory for the rotating file handler scaffold. Defaults to
            the ``FLIGHTSITE_LOG_DIR`` environment variable, then "logs".
            Only used when ``file_logging_enabled`` is True.
        file_logging_enabled: enables the rotating file handler in addition to
            the stream handler. Disabled by default.
    """
    resolved_level = _resolve_level(level)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(resolved_level)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    if file_logging_enabled:
        resolved_log_dir = Path(log_dir or os.environ.get("FLIGHTSITE_LOG_DIR") or DEFAULT_LOG_DIR)
        resolved_log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            resolved_log_dir / DEFAULT_LOG_FILENAME,
            maxBytes=DEFAULT_MAX_BYTES,
            backupCount=DEFAULT_BACKUP_COUNT,
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
