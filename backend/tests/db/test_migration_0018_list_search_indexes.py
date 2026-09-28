"""Migration 0018: the ``NOCASE`` prefix-search indexes.

Slice 083 (issue #226). ``tests/db/test_migrations.py`` already proves the
graph is linear, that head matches the models, and that a fixture database
upgrades; what is left for this revision is what it specifically claims —
four indexes, each in ``NOCASE`` collation (which the models cannot state:
SQLite reflection drops an index column's collation, so ``alembic check``
cannot see it and this file is where it is pinned), a downgrade that removes
exactly them, a re-run over a half-applied attempt that finishes, and an
upgrade over a populated database — sightings and their child rows included —
that touches no row and leaves every foreign key intact.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

from flightsite.db import migrate
from tests.db.harness import database_at, index_names, index_sql, upgrade_empty_database

REVISION = "0018"
PREVIOUS = "0017"

#: ``index -> (table, the collated column)``.
NEW_INDEXES = {
    "ix_amr_registration_nocase": ("aircraft_metadata_resolved", "registration"),
    "ix_amr_operator_nocase": ("aircraft_metadata_resolved", "operator_name"),
    "ix_sightings_callsign": ("sightings", "callsign_last"),
    "ix_sightings_callsign_first": ("sightings", "callsign_first"),
}

#: Every table a populated install has rows in that these indexes touch, and
#: the child tables hanging off ``sightings`` by foreign key.
SEEDED_TABLES = (
    "aircraft",
    "aircraft_metadata_resolved",
    "sightings",
    "sighting_events",
    "sighting_tracks",
)


async def test_the_upgrade_creates_the_four_indexes(db_path: Path) -> None:
    assert await upgrade_empty_database(db_path, REVISION) == REVISION

    for name, (table, _) in NEW_INDEXES.items():
        assert name in index_names(db_path, table)


async def test_each_index_is_nocase_on_its_column(db_path: Path) -> None:
    await upgrade_empty_database(db_path, REVISION)

    for name, (_, column) in NEW_INDEXES.items():
        sql = " ".join(index_sql(db_path, name).split()).upper()
        assert f"{column.upper()} COLLATE NOCASE" in sql, sql


async def test_the_callsign_indexes_carry_the_aircraft_id(db_path: Path) -> None:
    """So "which airframes flew this prefix" is answered by the index entries."""
    await upgrade_empty_database(db_path, REVISION)

    with sqlite3.connect(db_path) as connection:
        columns = {
            index: [
                row[2] for row in connection.execute(f"PRAGMA index_info('{index}')").fetchall()
            ]
            for index in ("ix_sightings_callsign", "ix_sightings_callsign_first")
        }

    assert columns == {
        "ix_sightings_callsign": ["callsign_last", "aircraft_id"],
        "ix_sightings_callsign_first": ["callsign_first", "aircraft_id"],
    }


async def test_the_existing_indexes_are_untouched(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = {table: index_names(db_path, table) for table, _ in NEW_INDEXES.values()}

    async with database_at(db_path, REVISION):
        pass

    for table, names in before.items():
        assert names <= index_names(db_path, table)


async def test_the_downgrade_drops_exactly_the_new_indexes(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = {table: index_names(db_path, table) for table, _ in NEW_INDEXES.values()}

    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == migrate.head_revision()
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    for table, names in before.items():
        assert index_names(db_path, table) == names


async def test_the_upgrade_resumes_from_a_half_applied_attempt(db_path: Path) -> None:
    """SQLite DDL is not transactional: a failed revision is re-run from the top."""
    async with database_at(db_path, REVISION) as database:
        await database.downgrade_to(PREVIOUS)
        async with database.writer_session() as session:
            await session.execute(text(_HALF_APPLIED_SQL))

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION

    for name, (table, _) in NEW_INDEXES.items():
        assert name in index_names(db_path, table)


async def test_a_populated_database_upgrades_without_touching_its_rows(db_path: Path) -> None:
    """Index builds only: every row, and every child row's parent, survives."""
    async with database_at(db_path, PREVIOUS):
        pass
    _seed(db_path)
    before = _counts(db_path)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION

    assert _counts(db_path) == before
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        # The new index answers from the rows that were already there.
        found = connection.execute(
            "SELECT count(*) FROM sightings INDEXED BY ix_sightings_callsign "
            "WHERE callsign_last COLLATE NOCASE >= 'baw' "
            "AND callsign_last COLLATE NOCASE < 'baw' || char(1114111)"
        ).fetchone()[0]
    assert found == 100


def _seed(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms) VALUES (?, ?, 1, 2)",
            [(index, f"{index:06x}") for index in range(1, 51)],
        )
        connection.executemany(
            "INSERT INTO aircraft_metadata_resolved (icao24, registration, registration_src, "
            "operator_name, operator_src, updated_ms) VALUES (?, ?, 'faa', ?, 'faa', 1)",
            [(f"{index:06x}", f"N{index}", f"Operator {index}") for index in range(1, 51)],
        )
        connection.executemany(
            "INSERT INTO sightings (id, aircraft_id, started_ms, ended_ms, callsign_last) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (index, 1 + index % 50, index * 1_000, index * 1_000 + 500, f"BAW{index}")
                for index in range(1, 201)
                if index % 2
            ]
            + [
                (index, 1 + index % 50, index * 1_000, index * 1_000 + 500, None)
                for index in range(1, 201)
                if not index % 2
            ],
        )
        connection.executemany(
            "INSERT INTO sighting_events (sighting_id, ts_ms, type, payload_json) "
            "VALUES (?, ?, 'callsign_change', '{}')",
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


#: The first of revision 0018's four steps, as an interrupted attempt leaves it.
_HALF_APPLIED_SQL = (
    "CREATE INDEX ix_amr_registration_nocase "
    "ON aircraft_metadata_resolved (registration COLLATE NOCASE)"
)
