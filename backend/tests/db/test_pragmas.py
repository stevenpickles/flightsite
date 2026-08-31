"""Connection-pragma verification (roadmap slice 005 acceptance criterion).

Every pragma is asserted by *querying it back* on a live session, not by
inspecting the code that sets it — pragmas are per connection, so the only
meaningful check is what a connection handed to application code actually has.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from flightsite.db import BUSY_TIMEOUT_MS, DB_FILENAME, Database, database_path, sqlite_url
from flightsite.db.engine import READ_POOL_SIZE

# PRAGMA synchronous returns an integer code; NORMAL is 1.
SYNCHRONOUS_NORMAL = 1


async def _pragma(database: Database, name: str, *, writer: bool) -> object:
    manager = database.writer_session() if writer else database.read_session()
    async with manager as session:
        return (await session.execute(text(f"PRAGMA {name}"))).scalar()


@pytest.mark.parametrize("writer", [True, False], ids=["writer", "reader"])
async def test_journal_mode_is_wal(migrated_database: Database, writer: bool) -> None:
    assert await _pragma(migrated_database, "journal_mode", writer=writer) == "wal"


@pytest.mark.parametrize("writer", [True, False], ids=["writer", "reader"])
async def test_synchronous_is_normal(migrated_database: Database, writer: bool) -> None:
    assert await _pragma(migrated_database, "synchronous", writer=writer) == SYNCHRONOUS_NORMAL


@pytest.mark.parametrize("writer", [True, False], ids=["writer", "reader"])
async def test_foreign_keys_are_enforced(migrated_database: Database, writer: bool) -> None:
    """SQLite defaults foreign_keys to OFF; ADR-0001 requires it ON."""
    assert await _pragma(migrated_database, "foreign_keys", writer=writer) == 1


@pytest.mark.parametrize("writer", [True, False], ids=["writer", "reader"])
async def test_busy_timeout_is_configured(migrated_database: Database, writer: bool) -> None:
    assert await _pragma(migrated_database, "busy_timeout", writer=writer) == BUSY_TIMEOUT_MS


async def test_wal_sidecar_files_are_created_next_to_the_database(
    migrated_database: Database,
) -> None:
    """WAL keeps -wal/-shm beside the database, inside the same data directory."""
    async with migrated_database.writer_session() as session:
        await session.execute(text("SELECT 1"))
        wal = migrated_database.path.with_name(migrated_database.path.name + "-wal")
        assert wal.exists()


async def test_read_sessions_are_query_only(migrated_database: Database) -> None:
    """A write on a read session must fail rather than become a second writer."""
    assert await _pragma(migrated_database, "query_only", writer=False) == 1

    with pytest.raises(OperationalError, match="readonly database"):
        async with migrated_database.read_session() as session:
            await session.execute(text("INSERT INTO meta VALUES ('k', 'v', 1)"))


async def test_writer_sessions_are_not_query_only(migrated_database: Database) -> None:
    assert await _pragma(migrated_database, "query_only", writer=True) == 0


def test_database_lives_in_the_data_directory_under_the_documented_name(tmp_path: Path) -> None:
    assert database_path(tmp_path) == tmp_path / DB_FILENAME
    assert DB_FILENAME == "flightsite.sqlite3"


def test_sqlite_url_is_a_valid_async_url_on_this_platform(tmp_path: Path) -> None:
    """``as_posix`` keeps a Windows drive path usable inside the URL."""
    url = sqlite_url(database_path(tmp_path))
    assert url.startswith("sqlite+aiosqlite:///")
    assert "\\" not in url


def test_read_pool_is_bounded() -> None:
    """Reads are short; an unbounded pool would just leak file handles."""
    assert 1 <= READ_POOL_SIZE <= 16
