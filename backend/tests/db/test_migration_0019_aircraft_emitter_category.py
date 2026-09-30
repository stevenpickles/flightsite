"""Migration 0019: ``aircraft.emitter_category``.

Slice 086 (issue #229). ``tests/db/test_migrations.py`` already proves the
graph is linear, that head matches the models, and that a fixture database
upgrades; what is left for this revision is what it specifically claims — one
nullable ``TEXT`` column and nothing else, a downgrade that removes exactly
it, a re-run over a half-applied attempt that finishes, and an upgrade *and*
a downgrade over a populated database — the airframes' sightings and their
child rows included — that lose no row and leave every foreign key intact.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

from flightsite.db import migrate
from tests.db.harness import (
    column_types,
    database_at,
    index_names,
    not_null_columns,
    upgrade_empty_database,
)

REVISION = "0019"
PREVIOUS = "0018"

#: Every table a populated install has rows in that hangs off ``aircraft``.
SEEDED_TABLES = (
    "aircraft",
    "sightings",
    "sighting_events",
    "sighting_tracks",
)


async def test_the_upgrade_adds_one_nullable_text_column(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = column_types(db_path, "aircraft")

    assert await upgrade_empty_database(db_path, REVISION) == REVISION

    after = column_types(db_path, "aircraft")
    assert after == {**before, "emitter_category": "TEXT"}
    assert "emitter_category" not in not_null_columns(db_path, "aircraft")


async def test_the_upgrade_adds_no_index(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = index_names(db_path, "aircraft")

    async with database_at(db_path, REVISION):
        pass

    assert index_names(db_path, "aircraft") == before


async def test_the_downgrade_removes_exactly_the_column(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = column_types(db_path, "aircraft")

    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == migrate.head_revision()
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert column_types(db_path, "aircraft") == before


async def test_the_upgrade_resumes_from_a_half_applied_attempt(db_path: Path) -> None:
    """SQLite DDL is not transactional: a failed revision is re-run from the top."""
    async with database_at(db_path, REVISION) as database:
        await database.downgrade_to(PREVIOUS)
        async with database.writer_session() as session:
            await session.execute(text("ALTER TABLE aircraft ADD COLUMN emitter_category TEXT"))

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION

    assert column_types(db_path, "aircraft")["emitter_category"] == "TEXT"


async def test_a_populated_database_upgrades_and_downgrades_without_losing_rows(
    db_path: Path,
) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    _seed(db_path)
    before = _counts(db_path)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION
    assert _counts(db_path) == before
    _assert_intact(db_path)
    with sqlite3.connect(db_path) as connection:
        # Every existing airframe is "unknown", not a category.
        assert connection.execute(
            "SELECT COUNT(*) FROM aircraft WHERE emitter_category IS NOT NULL"
        ).fetchone() == (0,)
        connection.execute("UPDATE aircraft SET emitter_category = 'A3' WHERE id <= 10")

    async with database_at(db_path, REVISION) as database:
        await database.downgrade_to(PREVIOUS)
    assert _counts(db_path) == before
    _assert_intact(db_path)
    assert "emitter_category" not in column_types(db_path, "aircraft")


def _assert_intact(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def _seed(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms) VALUES (?, ?, 1, 2)",
            [(index, f"{index:06x}") for index in range(1, 51)],
        )
        connection.executemany(
            "INSERT INTO sightings (id, aircraft_id, started_ms, ended_ms) VALUES (?, ?, ?, ?)",
            [
                (index, 1 + index % 50, index * 1_000, index * 1_000 + 500)
                for index in range(1, 201)
            ],
        )
        connection.executemany(
            "INSERT INTO sighting_events (sighting_id, ts_ms, type, payload_json) "
            "VALUES (?, ?, 'emergency_start', '{\"squawk\":\"7700\"}')",
            [(index, index * 1_000) for index in range(1, 201)],
        )
        connection.executemany(
            "INSERT INTO sighting_tracks (sighting_id, encoding_version, point_count, "
            "started_ms, points_blob) VALUES (?, 1, 0, 0, x'')",
            [(index,) for index in range(1, 201)],
        )


def _counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in SEEDED_TABLES
        }
