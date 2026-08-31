"""Migration tests for ``aircraft`` and ``sightings`` (DATA_MODEL §2.2/§2.3).

The schema is asserted from the outside, with stdlib ``sqlite3`` through the
shared harness, so that "the migration created this column" cannot be satisfied
by the ORM declaration alone. The drift and single-head checks in
``tests/db/test_migrations.py`` cover this revision automatically; what is here
is the column-by-column contract of the two new tables, including the ones this
slice deliberately leaves unpopulated.
"""

from __future__ import annotations

from pathlib import Path

from flightsite.db import Database, migrate
from tests.db.harness import (
    autogenerate_diffs,
    column_types,
    create_sql,
    database_at,
    foreign_keys,
    index_names,
    index_sql,
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0002"

EXPECTED_AIRCRAFT_COLUMNS = {
    "id": "INTEGER",
    "icao24": "TEXT",
    "first_seen_ms": "INTEGER",
    "last_seen_ms": "INTEGER",
    "sighting_count": "INTEGER",
    "total_observed_ms": "INTEGER",
    "closest_approach_nm": "REAL",
    "closest_approach_ms": "INTEGER",
    "max_range_nm": "REAL",
    "max_range_ms": "INTEGER",
    "lowest_alt_ft": "INTEGER",
    "lowest_alt_ms": "INTEGER",
    "highest_alt_ft": "INTEGER",
    "highest_alt_ms": "INTEGER",
}

EXPECTED_SIGHTING_COLUMNS = {
    "id": "INTEGER",
    "aircraft_id": "INTEGER",
    "started_ms": "INTEGER",
    "ended_ms": "INTEGER",
    "duration_ms": "INTEGER",
    "closure_reason": "TEXT",
    "callsign_first": "TEXT",
    "callsign_last": "TEXT",
    "squawk_last": "TEXT",
    "had_emergency": "INTEGER",
    "origin_ident": "TEXT",
    "destination_ident": "TEXT",
    "route_source": "TEXT",
    "inferred_airport_ident": "TEXT",
    "inferred_phase": "TEXT",
    "any_position": "INTEGER",
    "mlat_used": "INTEGER",
    "ground_seen": "INTEGER",
    "msg_count": "INTEGER",
    "pos_count": "INTEGER",
    "rssi_peak_db": "REAL",
    "rssi_avg_db": "REAL",
    "rssi_min_db": "REAL",
    "pos_time_pct": "REAL",
    "closest_approach_nm": "REAL",
    "max_range_nm": "REAL",
    "lowest_alt_ft": "INTEGER",
    "highest_alt_ft": "INTEGER",
    "max_alert_severity": "TEXT",
}


async def test_the_migration_creates_both_tables(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert {"aircraft", "sightings"} <= table_names(db_path)


async def test_the_aircraft_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "aircraft") == EXPECTED_AIRCRAFT_COLUMNS
    assert not_null_columns(db_path, "aircraft") == {
        "id",
        "icao24",
        "first_seen_ms",
        "last_seen_ms",
        "sighting_count",
        "total_observed_ms",
    }
    assert primary_key_columns(db_path, "aircraft") == ["id"]
    assert "UNIQUE" in create_sql(db_path, "aircraft").upper()


async def test_the_sightings_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "sightings") == EXPECTED_SIGHTING_COLUMNS
    assert not_null_columns(db_path, "sightings") == {
        "id",
        "aircraft_id",
        "started_ms",
        "had_emergency",
        "any_position",
        "mlat_used",
        "ground_seen",
        "msg_count",
        "pos_count",
    }
    assert primary_key_columns(db_path, "sightings") == ["id"]
    assert foreign_keys(db_path, "sightings") == {("aircraft_id", "aircraft", "id")}


async def test_the_closure_reason_vocabulary_is_enforced_by_the_schema(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    sql = create_sql(db_path, "sightings")

    assert "closure_reason IN ('gap_timeout', 'shutdown_recovery', 'data_reset')" in sql


async def test_the_declared_indexes_exist(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert {
        "ix_aircraft_first_seen",
        "ix_aircraft_last_seen",
        "ix_aircraft_sightings",
    } <= index_names(db_path, "aircraft")
    assert {
        "ix_sightings_aircraft",
        "ix_sightings_started",
        "ix_sightings_open",
    } <= index_names(db_path, "sightings")


async def test_the_open_sighting_index_is_partial(db_path: Path) -> None:
    # A full index over `ended_ms` would grow with the whole history; the
    # predicate is what keeps the open set's index the size of the open set.
    await upgrade_empty_database(db_path)

    assert "WHERE ended_ms IS NULL" in index_sql(db_path, "ix_sightings_open")


async def test_a_database_at_the_previous_revision_upgrades_cleanly(db_path: Path) -> None:
    # The upgrade path an existing slice-005 install takes.
    async with database_at(db_path, "0001") as database:
        assert await database.current_revision() == "0001"
    assert "aircraft" not in table_names(db_path)

    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == migrate.head_revision()
        assert await autogenerate_diffs(database) == []

    assert {"aircraft", "sightings"} <= table_names(db_path)


def test_this_revision_sits_directly_on_the_previous_one() -> None:
    # The linear-head rule of docs/DEVELOPMENT.md §"Parallel migrations": this
    # revision must hang off the head it was written against, not off a branch.
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == "0001"
    reachable = {revision.revision for revision in migrate.script_directory().walk_revisions()}
    assert REVISION in reachable


async def test_downgrading_removes_both_tables(db_path: Path) -> None:
    await upgrade_empty_database(db_path)
    database = Database(db_path)
    try:
        await database.downgrade_to("0001")

        remaining = table_names(db_path)
        assert "aircraft" not in remaining
        assert "sightings" not in remaining
        assert "meta" in remaining
    finally:
        await database.dispose()
