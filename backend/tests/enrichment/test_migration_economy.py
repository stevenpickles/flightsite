"""Migration 0014: learned-schedule columns, the ``restricted`` status, rollback.

Same discipline as ``test_migration.py`` next door — every assertion reads the
database file with stdlib ``sqlite3`` through :mod:`tests.db.harness`, so "the
migration did this" cannot be satisfied by a model declaration alone. This
revision also *rebuilds* ``route_cache`` rather than altering it, so the tests
below care as much about what survived the rebuild as about what changed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from flightsite.db import migrate
from flightsite.db.models import ROUTE_CACHE_STATUS_CHECK
from flightsite.enrichment.cache import LEARNED_CONFIRMATIONS
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
    upgrade_empty_database,
)

REVISION = "0014"
PREVIOUS = "0013"
TABLE = "route_cache"

#: ``docs/DATA_MODEL.md`` §7 at this revision, column for column.
EXPECTED_COLUMNS = {
    "cache_key": "TEXT",
    "status": "TEXT",
    "origin_ident": "TEXT",
    "destination_ident": "TEXT",
    "payload_json": "TEXT",
    "fetched_ms": "INTEGER",
    "expires_ms": "INTEGER",
    "confirmations": "INTEGER",
    "first_fetched_ms": "INTEGER",
}

_INSERT = (
    "INSERT INTO route_cache (cache_key, status, origin_ident, destination_ident, "
    "fetched_ms, expires_ms) VALUES (?, ?, ?, ?, ?, ?)"
)


def _rows(db_path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(db_path) as connection:
        return list(
            connection.execute(
                "SELECT cache_key, status, origin_ident, confirmations, first_fetched_ms "
                "FROM route_cache ORDER BY cache_key"
            )
        )


def test_this_revision_sits_directly_on_the_previous_head() -> None:
    """The linear-history rule of ``docs/DEVELOPMENT.md`` §"Parallel migrations"."""
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == PREVIOUS


def test_this_revision_is_still_on_the_one_linear_history() -> None:
    """One head, and this revision is reachable from it.

    It *was* the head; slice 071's revision 0015 sits on top of it now. What
    the linear-history rule actually asks of a landed migration is that the
    graph stays single-headed and that this revision is still on the path to
    it — the newest revision's own test asserts that it is the head.
    """
    heads = [script.revision for script in migrate.script_directory().get_revisions("heads")]
    walked = {script.revision for script in migrate.script_directory().walk_revisions()}

    assert len(heads) == 1
    assert REVISION in walked


async def test_the_learned_columns_arrive_with_this_revision(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = column_types(db_path, TABLE)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION

    assert "confirmations" not in before
    assert column_types(db_path, TABLE) == EXPECTED_COLUMNS


async def test_the_rebuilt_table_keeps_its_shape(db_path: Path) -> None:
    """``WITHOUT ROWID``, the text primary key and the expiry index all survive."""
    await upgrade_empty_database(db_path)

    assert primary_key_columns(db_path, TABLE) == ["cache_key"]
    assert "WITHOUT ROWID" in create_sql(db_path, TABLE).upper()
    assert "ix_route_cache_expiry" in index_names(db_path, TABLE)
    assert "expires_ms" in index_sql(db_path, "ix_route_cache_expiry")


async def test_the_confirmation_count_is_never_null(db_path: Path) -> None:
    """Zero confirmations is a number; ``NULL`` would be a third state."""
    await upgrade_empty_database(db_path)

    assert "confirmations" in not_null_columns(db_path, TABLE)
    assert "first_fetched_ms" not in not_null_columns(db_path, TABLE)


async def test_existing_rows_survive_the_rebuild_with_no_confirmations(db_path: Path) -> None:
    """An upgrade must not throw away a cache the install already paid for."""
    async with database_at(db_path, PREVIOUS):
        pass
    with sqlite3.connect(db_path) as connection:
        connection.execute(_INSERT, ("DAL1234:2026-09-03", "ok", "KATL", "KSLC", 1, 2))

    async with database_at(db_path, REVISION):
        pass

    assert _rows(db_path) == [("DAL1234:2026-09-03", "ok", "KATL", 0, None)]


async def test_the_schema_at_head_matches_the_models(db_path: Path) -> None:
    """Drift is checked at head, where the models describe the whole schema."""
    async with database_at(db_path) as database:
        assert await autogenerate_diffs(database) == []


async def test_a_restricted_row_is_accepted_only_after_this_revision(db_path: Path) -> None:
    """The ``CHECK`` is what makes ``restricted`` a vocabulary rather than a note."""
    async with database_at(db_path, PREVIOUS):
        pass
    with sqlite3.connect(db_path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(_INSERT, ("EJM99", "restricted", None, None, 1, 2))

    async with database_at(db_path, REVISION):
        pass
    with sqlite3.connect(db_path) as connection:
        connection.execute(_INSERT, ("EJM99", "restricted", None, None, 1, 2))


async def test_an_unknown_status_is_still_refused(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(_INSERT, ("DAL1", "maybe", None, None, 1, 2))


async def test_the_confirmation_column_holds_what_the_cache_writes(db_path: Path) -> None:
    """The learned threshold is a value in this column, not a separate flag."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(_INSERT, ("DAL1", "ok", "KATL", "KSLC", 1, 2))
        connection.execute(
            "UPDATE route_cache SET confirmations = ?, first_fetched_ms = ? WHERE cache_key = ?",
            (LEARNED_CONFIRMATIONS, 1, "DAL1"),
        )

    assert _rows(db_path) == [("DAL1", "ok", "KATL", LEARNED_CONFIRMATIONS, 1)]


async def test_the_revision_rolls_back(db_path: Path) -> None:
    """A migration that cannot be undone is a one-way door.

    The rollback drops the two columns and restores the older vocabulary, so a
    ``restricted`` row cannot survive it — it is deleted rather than left to
    break the constraint, and the callsign is simply looked up again.
    """
    await upgrade_empty_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(_INSERT, ("DAL1", "ok", "KATL", "KSLC", 1, 2))
        connection.execute(_INSERT, ("EJM99", "restricted", None, None, 1, 2))

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    columns = column_types(db_path, TABLE)
    with sqlite3.connect(db_path) as connection:
        remaining = list(connection.execute("SELECT cache_key FROM route_cache"))

    assert "confirmations" not in columns
    assert "first_fetched_ms" not in columns
    assert remaining == [("DAL1",)]
    assert "WITHOUT ROWID" in create_sql(db_path, TABLE).upper()
    assert "ix_route_cache_expiry" in index_names(db_path, TABLE)


async def test_the_models_predicate_is_the_one_in_the_file(db_path: Path) -> None:
    """Autogenerate does not compare ``CHECK`` constraints, so this does.

    The migrations spell their vocabularies out (each records what an install
    ran), which is only safe while something asserts that the newest one still
    matches the constant the application reasons about.
    """
    await upgrade_empty_database(db_path)

    assert ROUTE_CACHE_STATUS_CHECK in create_sql(db_path, TABLE)


async def test_the_runtime_vocabulary_and_the_constraint_agree(db_path: Path) -> None:
    """Every member of the enum is a value SQLite will store at head."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        for status in RouteCacheStatus:
            connection.execute(_INSERT, (f"X{status.value}", status.value, None, None, 1, 2))
