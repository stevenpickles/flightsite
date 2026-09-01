"""Migration 0011: schema shape, linear history, drift, cascade, and rollback.

Every assertion reads the database file with stdlib ``sqlite3`` through
:mod:`tests.db.harness`, so "the migration created this" cannot be satisfied by
a model declaration alone.

MIGRATION NOTE: this revision's ``down_revision`` is ``0009`` in this
worktree — the head at the time slice 037 was implemented, per the note in
``rev_0011_watchlists.py`` and ``docs/DEVELOPMENT.md``'s "Parallel migrations"
rebase rule. ``test_this_revision_sits_directly_on_the_previous_head`` pins
that fact so a local run stays green; the orchestrator updates both the
migration file and this constant together when it re-parents the revision
onto ``0010`` at reconcile time.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from flightsite.db import migrate
from tests.db.harness import (
    autogenerate_diffs,
    column_types,
    create_sql,
    database_at,
    foreign_keys,
    index_names,
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0011"
PREVIOUS = "0010"

TABLES = ("watchlists", "watchlist_entries")

#: ``docs/DATA_MODEL.md`` §4.1, column for column.
WATCHLISTS_COLUMNS = {
    "id": "INTEGER",
    "name": "TEXT",
    "description": "TEXT",
    "created_ms": "INTEGER",
}

WATCHLIST_ENTRIES_COLUMNS = {
    "id": "INTEGER",
    "watchlist_id": "INTEGER",
    "kind": "TEXT",
    "value": "TEXT",
    "note": "TEXT",
    "created_ms": "INTEGER",
}


def test_this_revision_sits_directly_on_the_previous_head() -> None:
    """The linear-history rule of ``docs/DEVELOPMENT.md`` §"Parallel migrations"."""
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == PREVIOUS


async def test_a_database_at_the_previous_revision_upgrades_cleanly(db_path: Path) -> None:
    """The upgrade path an existing install takes."""
    async with database_at(db_path, PREVIOUS) as database:
        assert await database.current_revision() == PREVIOUS
    assert not set(TABLES) & table_names(db_path)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION
    assert set(TABLES) <= table_names(db_path)

    async with database_at(db_path, "head") as database:
        assert await autogenerate_diffs(database) == []


async def test_the_watchlists_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "watchlists") == WATCHLISTS_COLUMNS
    assert primary_key_columns(db_path, "watchlists") == ["id"]
    assert not_null_columns(db_path, "watchlists") == {"id", "name", "created_ms"}


async def test_watchlist_names_are_unique(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO watchlists (id, name, created_ms) VALUES (1, 'Police', 0)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO watchlists (id, name, created_ms) VALUES (2, 'Police', 0)"
            )


async def test_the_watchlist_entries_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "watchlist_entries") == WATCHLIST_ENTRIES_COLUMNS
    assert primary_key_columns(db_path, "watchlist_entries") == ["id"]
    assert not_null_columns(db_path, "watchlist_entries") == {
        "id",
        "watchlist_id",
        "kind",
        "value",
        "created_ms",
    }


async def test_watchlist_entries_has_the_kind_and_the_kind_value_indexes(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    declared = {
        name for name in index_names(db_path, "watchlist_entries") if not name.startswith("sqlite_")
    }
    assert declared == {"ix_wentries_kind_value"}


async def test_watchlist_entries_enforces_one_value_per_kind_per_watchlist(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("INSERT INTO watchlists (id, name, created_ms) VALUES (1, 'W', 0)")
        columns = "(watchlist_id, kind, value, created_ms)"
        connection.execute(
            f"INSERT INTO watchlist_entries {columns} VALUES (1, 'icao24', 'ae1463', 0)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"INSERT INTO watchlist_entries {columns} VALUES (1, 'icao24', 'ae1463', 0)"
            )


async def test_watchlist_entries_rejects_an_unrecognized_kind(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO watchlists (id, name, created_ms) VALUES (1, 'W', 0)")
        columns = "(watchlist_id, kind, value, created_ms)"
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"INSERT INTO watchlist_entries {columns} VALUES (1, 'not_a_kind', 'x', 0)"
            )


async def test_watchlist_entries_foreign_key_targets_watchlists(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert foreign_keys(db_path, "watchlist_entries") == {("watchlist_id", "watchlists", "id")}


async def test_deleting_a_watchlist_cascades_to_its_entries(db_path: Path) -> None:
    """ADR-0001 runs with ``PRAGMA foreign_keys = ON``, which is what makes
    SQLite actually enforce ``ON DELETE CASCADE`` rather than merely declare it."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("INSERT INTO watchlists (id, name, created_ms) VALUES (1, 'W', 0)")
        connection.execute(
            "INSERT INTO watchlist_entries (watchlist_id, kind, value, created_ms) "
            "VALUES (1, 'icao24', 'ae1463', 0)"
        )
        connection.commit()

        connection.execute("DELETE FROM watchlists WHERE id = 1")
        connection.commit()

        remaining = connection.execute("SELECT COUNT(*) FROM watchlist_entries").fetchone()[0]
    assert remaining == 0


@pytest.mark.parametrize("table", TABLES)
async def test_every_table_is_a_plain_rowid_table(db_path: Path, table: str) -> None:
    """Unlike the analytics rollups, these are addressed by surrogate id and
    edited through CRUD — the same shape as ``aircraft``/``sightings``, not
    the ``WITHOUT ROWID`` derived-view shape."""
    await upgrade_empty_database(db_path)

    assert "WITHOUT ROWID" not in create_sql(db_path, table).upper()


async def test_models_and_migrations_do_not_drift_at_head(db_path: Path) -> None:
    async with database_at(db_path, "head") as database:
        assert await autogenerate_diffs(database) == []


async def test_the_downgrade_drops_exactly_this_slice_s_tables(db_path: Path) -> None:
    """Upgraded to *this* revision rather than to head: later slices add tables
    of their own (0012's alert tables are the first), and a downgrade from head
    to 0010 would drop theirs too — which would say nothing about what 0011's
    own downgrade does."""
    await upgrade_empty_database(db_path, REVISION)
    before = table_names(db_path)

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert before - table_names(db_path) == set(TABLES)
    assert {"sightings", "aircraft"} <= table_names(db_path)
