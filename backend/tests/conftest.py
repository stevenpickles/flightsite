"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from flightsite.config import ConfigStore

SECRET_SENTINEL = "sentinel-aerodatabox-key-9c1f4a"
"""A recognisable fake secret. Secret-leak tests search serialized output,
files and log records for this exact string."""


@pytest.fixture(autouse=True)
def _reset_logging_state() -> Iterator[None]:
    """Restore the root logger's handlers/level after each test.

    ``configure_logging`` mutates the process-wide root logger, so tests that
    call it (directly or via ``create_app``) must not leak handlers or a
    non-default level into unrelated tests.
    """
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    yield

    root_logger.handlers.clear()
    root_logger.handlers.extend(original_handlers)
    root_logger.setLevel(original_level)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give every test a private, empty data directory and a clean environment.

    Configuration reads ``FLIGHTSITE_*`` environment variables, so a stray
    variable in the developer's shell (or one set by an earlier test) would
    otherwise change results. Every ``FLIGHTSITE_*`` variable is removed and
    ``FLIGHTSITE_DATA_DIR`` is pointed at a fresh temporary directory.
    """
    for name in list(os.environ):
        if name.startswith("FLIGHTSITE_"):
            monkeypatch.delenv(name, raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FLIGHTSITE_DATA_DIR", str(data_dir))
    return data_dir


@pytest.fixture
def store(isolated_data_dir: Path) -> ConfigStore:
    """A ``ConfigStore`` bound to the test's isolated data directory."""
    return ConfigStore(isolated_data_dir)
