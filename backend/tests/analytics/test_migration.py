"""Migration 0009: schema shape, linear history, drift, and rollback.

Every assertion reads the database file with stdlib ``sqlite3`` through
:mod:`tests.db.harness`, so "the migration created this" cannot be satisfied by
a model declaration alone. Migrations are a SPEC §84 critical-coverage domain.

The shape checks are ``docs/DATA_MODEL.md`` §6.5 column for column, plus the
two properties the *rollup* design depends on: the composite keys that make a
day's breakdown single-valued, and the nullability of ``busiest_hour`` and
``max_range_nm``, which is what lets an in-progress day and a day with no
positioned traffic be recorded honestly rather than as a zero.
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

REVISION = "0009"
PREVIOUS = "0008"

TABLES = ("daily_stats", "daily_type_stats", "daily_operator_stats", "type_stats")

#: ``docs/DATA_MODEL.md`` §6.5, column for column.
DAILY_STATS_COLUMNS = {
    "day": "TEXT",
    "unique_aircraft": "INTEGER",
    "new_aircraft": "INTEGER",
    "sightings": "INTEGER",
    "interesting": "INTEGER",
    "military": "INTEGER",
    "government": "INTEGER",
    "law_enforcement": "INTEGER",
    "max_range_nm": "REAL",
    "busiest_hour": "INTEGER",
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


async def test_the_daily_stats_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "daily_stats") == DAILY_STATS_COLUMNS
    assert primary_key_columns(db_path, "daily_stats") == ["day"]


async def test_only_the_two_genuinely_unknowable_daily_columns_are_nullable(
    db_path: Path,
) -> None:
    """Counts are always known; a range and a finalized hour are not.

    ``max_range_nm`` is ``NULL`` for a day whose every sighting was Mode S-only
    (SPEC §20) — no position, so no range — and ``busiest_hour`` is ``NULL``
    until the day closes (§6.5's dual-source rule). A ``NOT NULL DEFAULT 0`` on
    either would turn "we cannot say" into "zero nautical miles" and "midnight".
    """
    await upgrade_empty_database(db_path)

    assert not_null_columns(db_path, "daily_stats") == set(DAILY_STATS_COLUMNS) - {
        "max_range_nm",
        "busiest_hour",
    }


@pytest.mark.parametrize(
    ("table", "key", "key_type"),
    [
        ("daily_type_stats", "type_code", "TEXT"),
        ("daily_operator_stats", "operator_group_id", "INTEGER"),
    ],
)
async def test_the_daily_breakdown_tables_are_one_shape_with_two_keys(
    db_path: Path, table: str, key: str, key_type: str
) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, table) == {
        "day": "TEXT",
        key: key_type,
        "sightings": "INTEGER",
        "unique_aircraft": "INTEGER",
    }
    assert primary_key_columns(db_path, table) == ["day", key]
    assert not_null_columns(db_path, table) == {"day", key, "sightings", "unique_aircraft"}


@pytest.mark.parametrize(
    ("table", "key", "value"),
    [
        ("daily_type_stats", "type_code", "'B738'"),
        ("daily_operator_stats", "operator_group_id", "4"),
    ],
)
async def test_one_row_per_key_per_day_is_enforced(
    db_path: Path, table: str, key: str, value: str
) -> None:
    """The composite key is what makes a day's breakdown single-valued."""
    await upgrade_empty_database(db_path)
    columns = f"(day, {key}, sightings, unique_aircraft)"

    with sqlite3.connect(db_path) as connection:
        connection.execute(f"INSERT INTO {table} {columns} VALUES ('2026-06-02', {value}, 3, 2)")
        connection.execute(f"INSERT INTO {table} {columns} VALUES ('2026-06-03', {value}, 1, 1)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"INSERT INTO {table} {columns} VALUES ('2026-06-02', {value}, 9, 9)"
            )


async def test_the_type_stats_table_matches_the_data_model(db_path: Path) -> None:
    """§6.5's since-T0 per-type table: the receiver-relative rarity source."""
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "type_stats") == {
        "type_code": "TEXT",
        "unique_aircraft": "INTEGER",
        "total_sightings": "INTEGER",
        "first_seen_ms": "INTEGER",
        "last_seen_ms": "INTEGER",
    }
    assert primary_key_columns(db_path, "type_stats") == ["type_code"]
    # A type row exists because an airframe of that type was heard, so both
    # moments are known by construction.
    assert not_null_columns(db_path, "type_stats") == {
        "type_code",
        "unique_aircraft",
        "total_sightings",
        "first_seen_ms",
        "last_seen_ms",
    }


@pytest.mark.parametrize("table", TABLES)
async def test_every_table_is_without_rowid(db_path: Path, table: str) -> None:
    """Each is reached only by its declared key, so the key is the b-tree."""
    await upgrade_empty_database(db_path)

    assert "WITHOUT ROWID" in create_sql(db_path, table).upper()


@pytest.mark.parametrize("table", TABLES)
async def test_no_table_carries_a_secondary_index(db_path: Path, table: str) -> None:
    """§6.5 declares none: every query these tables serve is a key prefix.

    The implicit ``sqlite_autoindex_*`` a ``WITHOUT ROWID`` primary key creates
    is not a secondary index — it *is* the table's b-tree — so it is excluded
    rather than asserted away.
    """
    await upgrade_empty_database(db_path)

    declared = {name for name in index_names(db_path, table) if not name.startswith("sqlite_")}
    assert declared == set()


@pytest.mark.parametrize("table", TABLES)
async def test_no_rollup_table_carries_a_foreign_key(db_path: Path, table: str) -> None:
    """Every row here is derived and discardable — see the migration's docstring.

    A foreign key from ``daily_operator_stats`` to ``operator_groups`` would
    make a future operator-group rebuild unable to touch a group any historical
    day references, in exchange for constraining a writer that re-derives the
    whole day from a join that already resolved the group.
    """
    await upgrade_empty_database(db_path)

    assert foreign_keys(db_path, table) == set()


async def test_the_downgrade_drops_exactly_this_slice_s_tables(db_path: Path) -> None:
    """Rolling back loses only a derived view the backfill can rebuild.

    Upgraded to *this* revision rather than to head: later slices add tables of
    their own, and a downgrade from head to 0008 would drop theirs too — which
    would say nothing about what 0009's own downgrade does.
    """
    await upgrade_empty_database(db_path, REVISION)
    before = table_names(db_path)

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert before - table_names(db_path) == set(TABLES)
    assert {"sightings", "aircraft"} <= table_names(db_path)
