"""Migration 0020: ``range_by_bearing_band_daily``.

Slice 087 (issue #230). ``tests/db/test_migrations.py`` already proves the
graph is linear, that head matches the models, and that a fixture database
upgrades; what is left for this revision is what it specifically claims — one
new ``WITHOUT ROWID`` table with the §6.3.1 columns and key and nothing else,
a downgrade that removes exactly it, a re-run over a half-applied attempt that
finishes, and an upgrade *and* a downgrade over a populated database — the
airframes' sightings with their child rows, and the receiver-metric tables the
new one sits beside — that lose no row and leave every foreign key intact.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

from flightsite.db import migrate
from tests.db.harness import (
    autogenerate_diffs,
    column_types,
    create_sql,
    database_at,
    index_names,
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0020"
PREVIOUS = "0019"
TABLE = "range_by_bearing_band_daily"

#: ``docs/DATA_MODEL.md`` §6.3.1, column for column.
COLUMNS = {
    "day": "TEXT",
    "bearing_bucket": "INTEGER",
    "altitude_band": "INTEGER",
    "max_range_nm": "REAL",
    "at_ms": "INTEGER",
    "icao24": "TEXT",
    "sample_count": "INTEGER",
}

#: Every table a populated install has rows in that this revision must not touch.
SEEDED_TABLES = (
    "aircraft",
    "sightings",
    "sighting_events",
    "sighting_tracks",
    "range_by_bearing_daily",
    "receiver_metrics_daily",
)


def test_this_revision_sits_directly_on_the_previous_head() -> None:
    """The linear-history rule of ``docs/DEVELOPMENT.md`` §"Parallel migrations"."""
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == PREVIOUS


async def test_the_upgrade_adds_exactly_one_table(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = table_names(db_path)

    assert await upgrade_empty_database(db_path, REVISION) == REVISION

    assert table_names(db_path) == before | {TABLE}


async def test_the_table_has_the_documented_shape(db_path: Path) -> None:
    await upgrade_empty_database(db_path, REVISION)

    assert column_types(db_path, TABLE) == COLUMNS
    assert primary_key_columns(db_path, TABLE) == ["day", "bearing_bucket", "altitude_band"]
    # Only the attribution may be absent: a cell with no range is no row.
    assert not_null_columns(db_path, TABLE) == set(COLUMNS) - {"icao24"}
    assert "WITHOUT ROWID" in create_sql(db_path, TABLE).upper()
    # Every read is a day range — a prefix of the key — so no secondary index.
    assert {name for name in index_names(db_path, TABLE) if not name.startswith("sqlite_")} == set()


async def test_head_matches_the_models(db_path: Path) -> None:
    async with database_at(db_path, "head") as database:
        assert await autogenerate_diffs(database) == []


async def test_the_downgrade_removes_exactly_the_table(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = table_names(db_path)

    async with database_at(db_path, REVISION) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert table_names(db_path) == before


async def test_the_upgrade_resumes_from_a_half_applied_attempt(db_path: Path) -> None:
    """SQLite DDL is not transactional: a failed revision is re-run from the top."""
    async with database_at(db_path, REVISION) as database:
        await database.downgrade_to(PREVIOUS)
        async with database.writer_session() as session:
            await session.execute(
                text(
                    f"CREATE TABLE {TABLE} (day TEXT NOT NULL, bearing_bucket INTEGER NOT NULL, "
                    "altitude_band INTEGER NOT NULL, max_range_nm REAL NOT NULL, "
                    "at_ms INTEGER NOT NULL, icao24 TEXT, sample_count INTEGER NOT NULL, "
                    "PRIMARY KEY (day, bearing_bucket, altitude_band)) WITHOUT ROWID"
                )
            )

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION

    assert column_types(db_path, TABLE) == COLUMNS


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
        # Nothing is backfilled: banded history starts on upgrade.
        assert connection.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone() == (0,)
        connection.executemany(
            f"INSERT INTO {TABLE} (day, bearing_bucket, altitude_band, max_range_nm, at_ms, "
            "icao24, sample_count) VALUES ('2026-09-30', ?, ?, 100.0, 1, 'abc123', 4)",
            [(bucket, band) for bucket in range(72) for band in range(3)],
        )

    async with database_at(db_path, REVISION) as database:
        await database.downgrade_to(PREVIOUS)
    assert _counts(db_path) == before
    _assert_intact(db_path)
    assert TABLE not in table_names(db_path)


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
        connection.executemany(
            "INSERT INTO range_by_bearing_daily (day, bearing_bucket, max_range_nm, at_ms) "
            "VALUES (?, ?, 120.0, 1)",
            [(f"2026-09-{day:02d}", bucket) for day in range(1, 31) for bucket in range(72)],
        )
        connection.executemany(
            "INSERT INTO receiver_metrics_daily (day, sample_count) VALUES (?, 5760)",
            [(f"2026-09-{day:02d}",) for day in range(1, 31)],
        )


def _counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in SEEDED_TABLES
        }
