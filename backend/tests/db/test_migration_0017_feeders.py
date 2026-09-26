"""Migration 0017: the two feeder history tables.

Slice 077 (issue #215). ``tests/db/test_migrations.py`` already proves the
graph is linear, that head matches the models, and that a fixture database
upgrades; what is left for this revision is what it specifically claims —
the two tables' keys, columns and ``WITHOUT ROWID`` layout with no secondary
index or ``CHECK``, a downgrade that removes both, a re-run over a
half-applied attempt that finishes, and an upgrade over a populated database
that touches none of its rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

from flightsite.db import migrate
from tests.db.harness import (
    column_types,
    create_sql,
    database_at,
    index_names,
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0017"
PREVIOUS = "0016"

EPISODES = "feeder_episodes"
SAMPLES = "feeder_samples"
NEW_TABLES = (EPISODES, SAMPLES)


async def test_the_upgrade_creates_both_tables(db_path: Path) -> None:
    assert await upgrade_empty_database(db_path, REVISION) == REVISION

    assert set(NEW_TABLES) <= table_names(db_path)


async def test_the_episode_table_shape(db_path: Path) -> None:
    await upgrade_empty_database(db_path, REVISION)

    assert column_types(db_path, EPISODES) == {
        "feeder": "TEXT",
        "started_ms": "INTEGER",
        "ended_ms": "INTEGER",
        "state": "TEXT",
    }
    assert primary_key_columns(db_path, EPISODES) == ["feeder", "started_ms"]
    assert "ended_ms" not in not_null_columns(db_path, EPISODES)


async def test_the_sample_table_shape(db_path: Path) -> None:
    await upgrade_empty_database(db_path, REVISION)

    assert column_types(db_path, SAMPLES) == {
        "feeder": "TEXT",
        "ts_ms": "INTEGER",
        "state": "TEXT",
        "metrics_json": "TEXT",
    }
    assert primary_key_columns(db_path, SAMPLES) == ["feeder", "ts_ms"]


async def test_both_are_without_rowid_with_no_index_or_check(db_path: Path) -> None:
    await upgrade_empty_database(db_path, REVISION)

    for table in NEW_TABLES:
        sql = create_sql(db_path, table).upper()
        assert "WITHOUT ROWID" in sql
        assert "CHECK" not in sql
        assert index_names(db_path, table) == {f"sqlite_autoindex_{table}_1"}


async def test_the_downgrade_drops_both_tables(db_path: Path) -> None:
    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == migrate.head_revision()

        await database.downgrade_to(PREVIOUS)

        assert await database.current_revision() == PREVIOUS

    assert not set(NEW_TABLES) & table_names(db_path)


async def test_the_upgrade_resumes_from_a_half_applied_attempt(db_path: Path) -> None:
    """SQLite DDL is not transactional: a failed revision is re-run from the top."""
    async with database_at(db_path, REVISION) as database:
        await database.downgrade_to(PREVIOUS)
        async with database.writer_session() as session:
            await session.execute(text(_HALF_APPLIED_SQL))

    assert EPISODES in table_names(db_path)
    assert SAMPLES not in table_names(db_path)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION

    assert set(NEW_TABLES) <= table_names(db_path)


async def test_a_populated_database_upgrades_without_touching_its_rows(db_path: Path) -> None:
    """The revision adds empty tables only: existing data is carried untouched."""
    async with database_at(db_path, PREVIOUS):
        pass
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO meta (key, value, updated_ms) VALUES (?, ?, 0)",
            [(f"filler_{index}", "x" * 64) for index in range(2_000)],
        )
    before = _meta_count(db_path)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION

    assert _meta_count(db_path) == before


def _meta_count(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        (count,) = connection.execute("SELECT COUNT(*) FROM meta").fetchone()
    return int(count)


#: The half of revision 0017 an interrupted attempt would have committed.
_HALF_APPLIED_SQL = (
    f"CREATE TABLE {EPISODES} ("
    "feeder TEXT NOT NULL, started_ms INTEGER NOT NULL, ended_ms INTEGER, "
    "state TEXT NOT NULL, PRIMARY KEY (feeder, started_ms)) WITHOUT ROWID"
)
