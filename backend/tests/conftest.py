"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest


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
