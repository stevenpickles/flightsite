"""Migration 0004: schema shape, linear head, drift, and rollback.

Every assertion here reads the database file with stdlib ``sqlite3`` through
:mod:`tests.db.harness`, so "the migration created this" cannot be satisfied by
a model declaration alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from flightsite.db import Database, migrate
from flightsite.metadata.precedence import RESOLVED_FIELDS, SRC_COLUMNS
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

REVISION = "0004"
PREVIOUS = "0003"

NEW_TABLES = {
    "metadata_sources",
    "aircraft_metadata",
    "aircraft_metadata_staging",
    "aircraft_metadata_resolved",
    "operators",
    "operator_groups",
}


def test_this_revision_sits_directly_on_the_previous_head() -> None:
    """The linear-head rule of ``docs/DEVELOPMENT.md`` §"Parallel migrations"."""
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == PREVIOUS
    assert migrate.heads() == (REVISION,)
    assert migrate.head_revision() == REVISION


async def test_a_database_at_the_previous_revision_upgrades_cleanly(db_path: Path) -> None:
    """The upgrade path an existing install takes."""
    async with database_at(db_path, PREVIOUS) as database:
        assert await database.current_revision() == PREVIOUS
    assert not NEW_TABLES & table_names(db_path)

    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == REVISION
        assert await autogenerate_diffs(database) == []

    assert table_names(db_path) >= NEW_TABLES


async def test_models_and_migration_do_not_drift(database: Database) -> None:
    """``alembic check`` as a test."""
    assert await autogenerate_diffs(database) == []


async def test_metadata_sources_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "metadata_sources") == {
        "source": "TEXT",
        "last_attempt_ms": "INTEGER",
        "last_success_ms": "INTEGER",
        "status": "TEXT",
        "dataset_version": "TEXT",
        "row_count": "INTEGER",
        "last_error": "TEXT",
    }
    assert primary_key_columns(db_path, "metadata_sources") == ["source"]
    assert not_null_columns(db_path, "metadata_sources") == {"source", "status"}
    assert "WITHOUT ROWID" in create_sql(db_path, "metadata_sources").upper()


async def test_aircraft_metadata_is_keyed_by_address_and_source(db_path: Path) -> None:
    """Sources never overwrite each other (``docs/DATA_MODEL.md`` §3.2)."""
    await upgrade_empty_database(db_path)

    assert primary_key_columns(db_path, "aircraft_metadata") == ["icao24", "source"]
    assert foreign_keys(db_path, "aircraft_metadata") == {("source", "metadata_sources", "source")}
    assert "WITHOUT ROWID" in create_sql(db_path, "aircraft_metadata").upper()


async def test_the_staging_table_mirrors_the_live_one_without_its_constraints(
    db_path: Path,
) -> None:
    """Same columns — the promotion is an ``INSERT ... SELECT`` — no FK, no index."""
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "aircraft_metadata_staging") == column_types(
        db_path, "aircraft_metadata"
    )
    assert primary_key_columns(db_path, "aircraft_metadata_staging") == ["icao24", "source"]
    assert foreign_keys(db_path, "aircraft_metadata_staging") == set()


async def test_the_resolved_table_carries_a_source_column_for_every_field(
    db_path: Path,
) -> None:
    """§3.3's per-field provenance, spelled as the data model spells it."""
    await upgrade_empty_database(db_path)

    columns = column_types(db_path, "aircraft_metadata_resolved")

    for name in RESOLVED_FIELDS:
        assert name in columns, name
        assert SRC_COLUMNS[name] in columns, name
    assert columns["manufacture_year"] == "INTEGER"
    assert columns["year_src"] == "TEXT"
    assert primary_key_columns(db_path, "aircraft_metadata_resolved") == ["icao24"]
    assert "WITHOUT ROWID" in create_sql(db_path, "aircraft_metadata_resolved").upper()


async def test_the_resolved_table_carries_the_three_declared_indexes(
    db_path: Path,
) -> None:
    await upgrade_empty_database(db_path)

    assert index_names(db_path, "aircraft_metadata_resolved") >= {
        "ix_amr_registration",
        "ix_amr_type",
        "ix_amr_opgroup",
    }


async def test_the_operator_tables_exist_and_are_empty(db_path: Path) -> None:
    """Created by 021 so the resolved FK is valid; populated by 024 (§3.5)."""
    await upgrade_empty_database(db_path)

    assert {"operators", "operator_groups"} <= table_names(db_path)
    assert foreign_keys(db_path, "operators") == {("group_id", "operator_groups", "id")}
    assert foreign_keys(db_path, "aircraft_metadata_resolved") == {
        ("operator_group_id", "operator_groups", "id")
    }
    assert "sqlite_autoindex_operator_groups_1" in index_names(db_path, "operator_groups")


async def test_the_status_check_constraint_is_enforced(database: Database) -> None:
    """A vocabulary declared but not enforced would not be a vocabulary."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with database.writer_session() as session:
            await session.execute(
                text("INSERT INTO metadata_sources (source, status) VALUES ('x', 'running')")
            )


async def test_the_resolved_foreign_key_is_enforced(database: Database) -> None:
    """ADR-0001 runs with ``foreign_keys=ON``; §3.3 relies on that being real."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with database.writer_session() as session:
            await session.execute(
                text(
                    "INSERT INTO aircraft_metadata_resolved "
                    "(icao24, operator_group_id, updated_ms) VALUES ('a00001', 99, 1)"
                )
            )


async def test_a_metadata_row_needs_its_source_to_exist(database: Database) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with database.writer_session() as session:
            await session.execute(
                text(
                    "INSERT INTO aircraft_metadata (icao24, source, updated_ms) "
                    "VALUES ('a00001', 'nobody', 1)"
                )
            )


async def test_downgrading_removes_every_table_this_revision_added(db_path: Path) -> None:
    """Rollback is supported where practical (SPEC §107)."""
    await upgrade_empty_database(db_path)
    database = Database(db_path)
    try:
        await database.downgrade_to(PREVIOUS)

        assert not NEW_TABLES & table_names(db_path)
        assert await database.current_revision() == PREVIOUS
    finally:
        await database.dispose()
