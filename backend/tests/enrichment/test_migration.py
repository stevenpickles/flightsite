"""Migration 0006: schema shape, linear history, drift, and rollback.

Every assertion reads the database file with stdlib ``sqlite3`` through
:mod:`tests.db.harness`, so "the migration created this" cannot be satisfied by
a model declaration alone.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from flightsite.db import migrate
from flightsite.enrichment.model import RouteCacheStatus
from tests.db.harness import (
    autogenerate_diffs,
    column_types,
    create_sql,
    database_at,
    index_names,
    index_sql,
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0006"
PREVIOUS = "0005"
TABLE = "route_cache"

#: ``docs/DATA_MODEL.md`` §7, column for column.
EXPECTED_COLUMNS = {
    "cache_key": "TEXT",
    "status": "TEXT",
    "origin_ident": "TEXT",
    "destination_ident": "TEXT",
    "payload_json": "TEXT",
    "fetched_ms": "INTEGER",
    "expires_ms": "INTEGER",
}


def test_this_revision_sits_directly_on_the_previous_head() -> None:
    """The linear-history rule of ``docs/DEVELOPMENT.md`` §"Parallel migrations".

    That there is exactly *one* head is asserted globally in
    ``tests/db/test_migrations.py``, not here: later slices add revisions on top
    of this one, and a per-slice test that pinned itself as the head would have
    to be edited by every slice that followed.
    """
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == PREVIOUS


async def test_a_database_at_the_previous_revision_upgrades_cleanly(db_path: Path) -> None:
    """The upgrade path an existing install takes."""
    async with database_at(db_path, PREVIOUS) as database:
        assert await database.current_revision() == PREVIOUS
    assert TABLE not in table_names(db_path)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION

    assert TABLE in table_names(db_path)


async def test_the_schema_at_head_matches_the_models(db_path: Path) -> None:
    """Drift is checked at head, where the models describe the whole schema."""
    async with database_at(db_path) as database:
        assert await autogenerate_diffs(database) == []


async def test_the_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, TABLE) == EXPECTED_COLUMNS
    assert primary_key_columns(db_path, TABLE) == ["cache_key"]
    assert "WITHOUT ROWID" in create_sql(db_path, TABLE).upper()


async def test_only_the_answer_columns_are_nullable(db_path: Path) -> None:
    """A cached row always knows *what* it is and *when* it expires."""
    await upgrade_empty_database(db_path)

    assert not_null_columns(db_path, TABLE) == {
        "cache_key",
        "status",
        "fetched_ms",
        "expires_ms",
    }


async def test_expiry_is_indexed_for_pruning(db_path: Path) -> None:
    """The one query that is not a point lookup."""
    await upgrade_empty_database(db_path)

    assert "ix_route_cache_expiry" in index_names(db_path, TABLE)
    assert "expires_ms" in index_sql(db_path, "ix_route_cache_expiry")


async def test_the_status_check_is_enforced_by_sqlite(db_path: Path) -> None:
    """A vocabulary declared but not enforced is a comment."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO route_cache (cache_key, status, fetched_ms, expires_ms) "
            "VALUES ('X:2026-08-30', 'maybe', 1, 2)"
        )


@pytest.mark.parametrize("status", list(RouteCacheStatus))
async def test_every_vocabulary_value_is_accepted(db_path: Path, status: RouteCacheStatus) -> None:
    """The runtime enum and the SQL ``CHECK`` name the same three values."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO route_cache (cache_key, status, fetched_ms, expires_ms) "
            "VALUES (?, ?, 1, 2)",
            (f"X{status.value}:2026-08-30", status.value),
        )


async def test_the_sighting_route_columns_predate_this_revision(db_path: Path) -> None:
    """0002 created them; this slice fills them, and alters nothing."""
    async with database_at(db_path, PREVIOUS):
        pass

    columns = column_types(db_path, "sightings")

    assert {"origin_ident", "destination_ident", "route_source"} <= set(columns)


async def test_the_revision_rolls_back(db_path: Path) -> None:
    """A migration that cannot be undone is a one-way door."""
    await upgrade_empty_database(db_path)
    assert TABLE in table_names(db_path)

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert TABLE not in table_names(db_path)
