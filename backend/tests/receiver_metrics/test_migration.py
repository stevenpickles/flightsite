"""Migration 0008: schema shape, linear history, drift, and rollback.

Every assertion reads the database file with stdlib ``sqlite3`` through
:mod:`tests.db.harness`, so "the migration created this" cannot be satisfied by
a model declaration alone. Migrations are a SPEC §84 critical-coverage domain
and retention is another, so this file checks the *retention-relevant* shape
too: which tables a prune could ever touch, and which are structurally
permanent.
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
    index_names,
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0008"
PREVIOUS = "0007"

TABLES = (
    "receiver_metrics_raw",
    "receiver_metrics_hourly",
    "receiver_metrics_daily",
    "range_by_bearing_daily",
    "lifetime_stats",
)

#: ``docs/DATA_MODEL.md`` §6.1, column for column.
RAW_COLUMNS = {
    "ts_ms": "INTEGER",
    "messages_per_sec": "REAL",
    "positions_per_sec": "REAL",
    "aircraft_visible": "INTEGER",
    "aircraft_with_pos": "INTEGER",
    "max_range_nm": "REAL",
    "rssi_avg_db": "REAL",
    "rssi_peak_db": "REAL",
}

#: The summary column set §6.2 shares between the hourly and daily tables.
SUMMARY_COLUMNS = {
    "messages_total": "INTEGER",
    "positions_total": "INTEGER",
    "msgs_per_sec_avg": "REAL",
    "msgs_per_sec_max": "REAL",
    "pos_per_sec_avg": "REAL",
    "pos_per_sec_max": "REAL",
    "aircraft_avg": "REAL",
    "aircraft_max": "INTEGER",
    "max_range_nm": "REAL",
    "rssi_avg_db": "REAL",
    "rssi_peak_db": "REAL",
    "sample_count": "INTEGER",
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
        assert await autogenerate_diffs(database) == []

    assert set(TABLES) <= table_names(db_path)


async def test_the_raw_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "receiver_metrics_raw") == RAW_COLUMNS
    assert primary_key_columns(db_path, "receiver_metrics_raw") == ["ts_ms"]


async def test_every_raw_measurement_is_nullable(db_path: Path) -> None:
    """SPEC §60: a metric a decoder does not report is absent, never zero.

    Zero is a measurement. A ``NOT NULL DEFAULT 0`` here would turn "this
    decoder cannot tell us" into "the receiver heard nothing", which is the one
    misreading §60 exists to prevent.
    """
    await upgrade_empty_database(db_path)

    assert not_null_columns(db_path, "receiver_metrics_raw") == {"ts_ms"}


@pytest.mark.parametrize(
    ("table", "key", "key_type"),
    [
        ("receiver_metrics_hourly", "hour_start_ms", "INTEGER"),
        ("receiver_metrics_daily", "day", "TEXT"),
    ],
)
async def test_the_summary_tables_are_one_shape_with_two_keys(
    db_path: Path, table: str, key: str, key_type: str
) -> None:
    """§6.2: *"identical shape keyed by local calendar day"*."""
    await upgrade_empty_database(db_path)

    assert column_types(db_path, table) == {key: key_type, **SUMMARY_COLUMNS}
    assert primary_key_columns(db_path, table) == [key]
    # Only `sample_count` is guaranteed: how many samples a bucket was built
    # from is known even when every metric in it was absent.
    assert not_null_columns(db_path, table) == {key, "sample_count"}


async def test_the_range_by_bearing_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "range_by_bearing_daily") == {
        "day": "TEXT",
        "bearing_bucket": "INTEGER",
        "max_range_nm": "REAL",
        "at_ms": "INTEGER",
        "icao24": "TEXT",
    }
    assert primary_key_columns(db_path, "range_by_bearing_daily") == ["day", "bearing_bucket"]
    # Only who set the record may be unknown; a sector row with no range or no
    # time would be a record of nothing.
    assert not_null_columns(db_path, "range_by_bearing_daily") == {
        "day",
        "bearing_bucket",
        "max_range_nm",
        "at_ms",
    }


async def test_one_row_per_sector_per_day_is_enforced(db_path: Path) -> None:
    """The composite key is what makes the daily polar plot single-valued."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO range_by_bearing_daily (day, bearing_bucket, max_range_nm, at_ms) "
            "VALUES ('2026-09-01', 12, 180.0, 1)"
        )
        # A different sector on the same day is a different row.
        connection.execute(
            "INSERT INTO range_by_bearing_daily (day, bearing_bucket, max_range_nm, at_ms) "
            "VALUES ('2026-09-01', 13, 90.0, 2)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO range_by_bearing_daily (day, bearing_bucket, max_range_nm, at_ms) "
                "VALUES ('2026-09-01', 12, 999.0, 3)"
            )


async def test_the_lifetime_table_matches_the_data_model(db_path: Path) -> None:
    """§6.4: a narrow key/value table, so a new record is a key not a migration."""
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "lifetime_stats") == {
        "key": "TEXT",
        "value_num": "REAL",
        "value_text": "TEXT",
        "updated_ms": "INTEGER",
    }
    assert primary_key_columns(db_path, "lifetime_stats") == ["key"]
    assert not_null_columns(db_path, "lifetime_stats") == {"key", "updated_ms"}


@pytest.mark.parametrize("table", TABLES)
async def test_every_table_is_without_rowid(db_path: Path, table: str) -> None:
    """Each is reached only by its declared key, so the key is the b-tree."""
    await upgrade_empty_database(db_path)

    assert "WITHOUT ROWID" in create_sql(db_path, table).upper()


@pytest.mark.parametrize("table", TABLES)
async def test_no_table_carries_a_secondary_index(db_path: Path, table: str) -> None:
    """§6 declares none: every query these tables serve is a key prefix.

    ``sqlite_autoindex_*`` is excluded because on a ``WITHOUT ROWID`` table
    that entry *is* the table's own clustered b-tree, not a second copy of the
    key. Anything else would be an index this slice added beyond the data
    model, and therefore write amplification §6 did not ask for.
    """
    await upgrade_empty_database(db_path)

    declared = {
        name for name in index_names(db_path, table) if not name.startswith("sqlite_autoindex")
    }

    assert declared == set()


async def test_the_permanent_tables_hold_no_expiry_column(db_path: Path) -> None:
    """ADR-0009: only the high-resolution window is ever pruned.

    The three summary tables and the lifetime records are permanent, and the
    schema is where that is stated: none of them carries a column a retention
    pass could key an expiry off.
    """
    await upgrade_empty_database(db_path)

    for table in ("receiver_metrics_hourly", "receiver_metrics_daily", "lifetime_stats"):
        assert not any(name.startswith("expires") for name in column_types(db_path, table))


async def test_the_revision_rolls_back(db_path: Path) -> None:
    """A migration that cannot be undone is a one-way door."""
    await upgrade_empty_database(db_path)
    assert set(TABLES) <= table_names(db_path)

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert not set(TABLES) & table_names(db_path)


async def test_rows_written_at_this_revision_survive_a_rebuild_to_head(db_path: Path) -> None:
    """A realistic upgrade fixture: real rows in, upgrade, same rows out."""
    await upgrade_empty_database(db_path, REVISION)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO receiver_metrics_raw (ts_ms, messages_per_sec, aircraft_visible) "
            "VALUES (1756600000000, 412.5, 37)"
        )
        connection.execute(
            "INSERT INTO lifetime_stats (key, value_num, updated_ms) "
            "VALUES ('max_range_nm', 243.5, 1756600000000)"
        )

    async with database_at(db_path, "head") as database:
        assert await autogenerate_diffs(database) == []

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT messages_per_sec, aircraft_visible FROM receiver_metrics_raw"
        ).fetchall() == [(412.5, 37)]
        assert connection.execute(
            "SELECT value_num FROM lifetime_stats WHERE key = 'max_range_nm'"
        ).fetchone() == (243.5,)
