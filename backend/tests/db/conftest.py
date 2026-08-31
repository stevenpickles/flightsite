"""Fixtures for the persistence tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from flightsite.db import Database, MetaRepository, database_path


@pytest.fixture
def db_path(isolated_data_dir: Path) -> Path:
    """Path the application would use for its database in this test's data dir."""
    return database_path(isolated_data_dir)


@pytest.fixture
async def database(db_path: Path) -> AsyncIterator[Database]:
    """An un-migrated database (no schema yet)."""
    instance = Database(db_path)
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
async def migrated_database(database: Database) -> Database:
    """A database upgraded to head."""
    await database.upgrade_to("head")
    return database


@pytest.fixture
def meta(migrated_database: Database) -> MetaRepository:
    """A ``meta`` repository over the migrated database."""
    return MetaRepository(migrated_database)
