"""Migration 0005: schema shape, linear head, drift, and rollback.

Every assertion reads the database file with stdlib ``sqlite3`` through
:mod:`tests.db.harness`, so "the migration created this" cannot be satisfied by
a model declaration alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from flightsite.classification.vocabulary import MissionCategory
from flightsite.db import Database, migrate
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

REVISION = "0005"
PREVIOUS = "0004"
TABLE = "aircraft_classification"

#: ``docs/DATA_MODEL.md`` §3.4, column for column.
EXPECTED_COLUMNS = {
    "icao24": "TEXT",
    "military": "INTEGER",
    "military_src": "TEXT",
    "military_conf": "REAL",
    "government": "INTEGER",
    "government_src": "TEXT",
    "government_conf": "REAL",
    "law_enforcement": "INTEGER",
    "law_enforcement_src": "TEXT",
    "law_enforcement_conf": "REAL",
    "mission_category": "TEXT",
    "mission_src": "TEXT",
    "mission_conf": "REAL",
    "icon_category": "TEXT",
    "updated_ms": "INTEGER",
}

EXPECTED_INDEXES = {"ix_class_mil", "ix_class_gov", "ix_class_law", "ix_class_mission"}


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
    assert TABLE not in table_names(db_path)

    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == REVISION
        assert await autogenerate_diffs(database) == []

    assert TABLE in table_names(db_path)


async def test_the_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, TABLE) == EXPECTED_COLUMNS
    assert primary_key_columns(db_path, TABLE) == ["icao24"]
    assert "WITHOUT ROWID" in create_sql(db_path, TABLE).upper()


async def test_the_flags_and_the_categories_are_not_nullable(db_path: Path) -> None:
    """A missing answer is ``0``/``unknown``, never ``NULL``: §3.4 has defaults."""
    await upgrade_empty_database(db_path)

    assert not_null_columns(db_path, TABLE) >= {
        "icao24",
        "military",
        "government",
        "law_enforcement",
        "mission_category",
        "icon_category",
        "updated_ms",
    }


async def test_a_row_may_be_inserted_with_nothing_but_an_address(db_path: Path) -> None:
    """The defaults are real: §3.4 gives every answer column one."""
    async with database_at(db_path, "head") as database:
        async with database.writer_session() as session:
            await session.execute(
                text("INSERT INTO aircraft_classification (icao24, updated_ms) VALUES ('ab', 1)")
            )
        async with database.read_session() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT military, government, law_enforcement, mission_category, "
                        "icon_category FROM aircraft_classification"
                    )
                )
            ).one()

    assert tuple(row) == (0, 0, 0, "unknown", "unknown")


async def test_the_mission_check_names_every_spec_category(db_path: Path) -> None:
    await upgrade_empty_database(db_path)
    sql = create_sql(db_path, TABLE)

    assert "ck_aircraft_classification_mission" in sql
    for category in MissionCategory:
        assert f"'{category.value}'" in sql


async def test_the_mission_check_refuses_a_category_outside_the_spec(db_path: Path) -> None:
    """SPEC §39's list is closed, and the column enforces it."""
    async with database_at(db_path, "head") as database:
        with pytest.raises(Exception, match="CHECK constraint failed"):
            async with database.writer_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO aircraft_classification "
                        "(icao24, mission_category, updated_ms) VALUES ('ab', 'spy_plane', 1)"
                    )
                )


async def test_the_icon_category_takes_its_own_vocabulary(db_path: Path) -> None:
    """§3.4 gives it no CHECK: the icon set grows independently of SPEC §39."""
    async with (
        database_at(db_path, "head") as database,
        database.writer_session() as session,
    ):
        await session.execute(
            text(
                "INSERT INTO aircraft_classification "
                "(icao24, icon_category, updated_ms) VALUES ('ab', 'military_transport', 1)"
            )
        )


async def test_the_flag_indexes_are_partial(db_path: Path) -> None:
    """Military airframes are a fraction of a metadata database (§3.4)."""
    await upgrade_empty_database(db_path)

    # SQLite adds its own primary-key index to a WITHOUT ROWID table.
    assert index_names(db_path, TABLE) >= EXPECTED_INDEXES
    for name, column in (
        ("ix_class_mil", "military"),
        ("ix_class_gov", "government"),
        ("ix_class_law", "law_enforcement"),
    ):
        assert f"WHERE {column} = 1" in index_sql(db_path, name)
    assert "WHERE" not in index_sql(db_path, "ix_class_mission")


async def test_downgrade_removes_the_table_and_leaves_0004_intact(db_path: Path) -> None:
    """Rollback is supported where practical (SPEC §107)."""
    database = Database(db_path)
    try:
        await database.upgrade_to("head")
        assert TABLE in table_names(db_path)

        await database.downgrade_to(PREVIOUS)

        assert await database.current_revision() == PREVIOUS
    finally:
        await database.dispose()

    assert TABLE not in table_names(db_path)
    assert "aircraft_metadata_resolved" in table_names(db_path)
