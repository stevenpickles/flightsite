"""Fixtures for the watchlists package tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from flightsite.db import Database, database_path
from flightsite.watchlists import WatchlistRepository, WatchlistService

#: Frozen clock: every stored ``created_ms`` in these tests is this.
CREATED_MS = 1_756_600_000_000


@pytest.fixture
def db_path(isolated_data_dir: Path) -> Path:
    """Path the application would use for its database in this test's data dir."""
    return database_path(isolated_data_dir)


@pytest.fixture
async def database(db_path: Path) -> AsyncIterator[Database]:
    """A database migrated to head."""
    instance = Database(db_path)
    await instance.upgrade_to("head")
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def repository(database: Database) -> WatchlistRepository:
    """A watchlist repository over the migrated database."""
    return WatchlistRepository(database)


@pytest.fixture
def service(database: Database) -> WatchlistService:
    """A watchlist service on a frozen clock, so stored timestamps are assertable."""
    return WatchlistService(database=database, clock=lambda: CREATED_MS)
