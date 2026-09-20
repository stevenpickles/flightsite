"""Migration 0016: the two tables a promotion builds its resolution in.

Slice 075 (issue #185). ``tests/db/test_migrations.py`` already proves the
graph is linear, that head matches the models, and that a fixture database
upgrades; what is left for this revision is what it specifically claims —
that each new table is its live table's column set with **none** of its
constraints or indexes, that the downgrade removes both, and that a re-run
over a half-applied attempt finishes instead of failing on a table it created
the first time round (``docs/DEVELOPMENT.md``, "SQLite DDL is not
transactional").
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from flightsite.db import migrate
from tests.db.harness import (
    column_types,
    create_sql,
    database_at,
    foreign_keys,
    index_names,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0016"
PREVIOUS = "0015"

RESOLVED = "aircraft_metadata_resolved"
RESOLVED_STAGING = "aircraft_metadata_resolved_staging"
CLASSIFICATION = "aircraft_classification"
CLASSIFICATION_STAGING = "aircraft_classification_staging"

NEW_TABLES = (RESOLVED_STAGING, CLASSIFICATION_STAGING)


async def test_the_upgrade_creates_both_scratch_tables(db_path: Path) -> None:
    assert await upgrade_empty_database(db_path) == REVISION

    assert set(NEW_TABLES) <= table_names(db_path)


async def test_each_scratch_table_has_its_live_table_s_columns(db_path: Path) -> None:
    """The swap is an ``INSERT ... SELECT`` pairing them column for column."""
    await upgrade_empty_database(db_path)

    assert column_types(db_path, RESOLVED_STAGING) == column_types(db_path, RESOLVED)
    assert column_types(db_path, CLASSIFICATION_STAGING) == column_types(db_path, CLASSIFICATION)


async def test_each_scratch_table_is_keyed_by_address_without_a_rowid(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    for table in NEW_TABLES:
        assert primary_key_columns(db_path, table) == ["icao24"]
        assert "WITHOUT ROWID" in create_sql(db_path, table).upper()


async def test_the_resolved_scratch_table_references_nothing(db_path: Path) -> None:
    """Its group ids name a curated directory the promotion has not installed yet."""
    await upgrade_empty_database(db_path)

    assert foreign_keys(db_path, RESOLVED) == {("operator_group_id", "operator_groups", "id")}
    assert foreign_keys(db_path, RESOLVED_STAGING) == set()


async def test_neither_scratch_table_carries_an_index_or_a_check(db_path: Path) -> None:
    """Nothing queries them, and every row is read back exactly once.

    The primary key's implicit index is the only one either table may have —
    it is what ``WITHOUT ROWID`` stores the rows in, not a lookup structure
    paid for on the side.
    """
    await upgrade_empty_database(db_path)

    for table in NEW_TABLES:
        assert index_names(db_path, table) == {f"sqlite_autoindex_{table}_1"}
        assert "CHECK" not in create_sql(db_path, table).upper()


async def test_the_downgrade_drops_both_tables(db_path: Path) -> None:
    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == migrate.head_revision()

        await database.downgrade_to(PREVIOUS)

        assert await database.current_revision() == PREVIOUS

    names = table_names(db_path)
    assert not set(NEW_TABLES) & names
    # The tables the scratch ones shadow are untouched by the rollback.
    assert {RESOLVED, CLASSIFICATION} <= names


async def test_the_upgrade_resumes_from_a_half_applied_attempt(db_path: Path) -> None:
    """SQLite DDL is not transactional: a failed revision is re-run from the top.

    Simulated by upgrading, rolling back to 0015, and re-creating just the
    first of the two tables — the state an install would be left in if the
    process died between the revision's two statements.
    """
    async with database_at(db_path, "head") as database:
        await database.downgrade_to(PREVIOUS)
        async with database.writer_session() as session:
            await session.execute(text(_HALF_APPLIED_SQL))

    assert RESOLVED_STAGING in table_names(db_path)
    assert CLASSIFICATION_STAGING not in table_names(db_path)

    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == migrate.head_revision()

    assert set(NEW_TABLES) <= table_names(db_path)


#: The half of revision 0016 an interrupted attempt would have committed.
_HALF_APPLIED_SQL = (
    f"CREATE TABLE {RESOLVED_STAGING} ("
    "icao24 TEXT NOT NULL, registration TEXT, registration_src TEXT, "
    "type_code TEXT, type_code_src TEXT, model TEXT, model_src TEXT, "
    "manufacture_year INTEGER, year_src TEXT, operator_name TEXT, "
    "operator_src TEXT, operator_group_id INTEGER, owner TEXT, owner_src TEXT, "
    "updated_ms INTEGER NOT NULL, PRIMARY KEY (icao24)) WITHOUT ROWID"
)
