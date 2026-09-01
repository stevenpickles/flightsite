"""Migration 0007: schema shape, linear history, drift, and rollback.

Every assertion reads the database file with stdlib ``sqlite3`` through
:mod:`tests.db.harness`, so "the migration created this" cannot be satisfied by
a model declaration alone.
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
    index_sql,
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0007"
PREVIOUS = "0006"
TABLE = "airports"

#: ``docs/DATA_MODEL.md`` §3.6, column for column.
EXPECTED_COLUMNS = {
    "id": "INTEGER",
    "ident": "TEXT",
    "iata": "TEXT",
    "name": "TEXT",
    "type": "TEXT",
    "lat": "REAL",
    "lon": "REAL",
    "elevation_ft": "INTEGER",
    "iso_country": "TEXT",
}


def test_this_revision_sits_directly_on_the_previous_head() -> None:
    """The linear-history rule of ``docs/DEVELOPMENT.md`` §"Parallel migrations"."""
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == PREVIOUS


async def test_a_database_at_the_previous_revision_upgrades_cleanly(db_path: Path) -> None:
    """The upgrade path an existing install takes.

    Drift is asserted after upgrading the rest of the way to head rather than
    at this revision: the models describe head, so an intermediate revision is
    *expected* to lack whatever later slices added.
    """
    async with database_at(db_path, PREVIOUS) as database:
        assert await database.current_revision() == PREVIOUS
    assert TABLE not in table_names(db_path)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION
    assert TABLE in table_names(db_path)

    async with database_at(db_path, "head") as database:
        assert await autogenerate_diffs(database) == []


async def test_the_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, TABLE) == EXPECTED_COLUMNS
    assert primary_key_columns(db_path, TABLE) == ["id"]
    # Not WITHOUT ROWID, unlike `route_cache`: the primary key is an integer
    # and SQLite's rowid *is* that key, so there is nothing to save.
    assert "WITHOUT ROWID" not in create_sql(db_path, TABLE).upper()


async def test_only_the_columns_upstream_may_omit_are_nullable(db_path: Path) -> None:
    """An airport always knows what it is called and where it is."""
    await upgrade_empty_database(db_path)

    assert not_null_columns(db_path, TABLE) == {"id", "ident", "name", "type", "lat", "lon"}


async def test_the_ident_is_unique(db_path: Path) -> None:
    """It is the key everything joins on; a duplicate would make one field two."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO airports (id, ident, name, type, lat, lon) "
            "VALUES (1, 'KSEA', 'Seattle-Tacoma', 'large_airport', 47.45, -122.31)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO airports (id, ident, name, type, lat, lon) "
                "VALUES (2, 'KSEA', 'Impostor', 'small_airport', 0.0, 0.0)"
            )


async def test_coordinates_are_indexed_for_the_bounding_box_lookup(db_path: Path) -> None:
    """§3.6: a box on ``(lat, lon)``, refined by great-circle in code."""
    await upgrade_empty_database(db_path)

    assert "ix_airports_lat" in index_names(db_path, TABLE)
    sql = index_sql(db_path, "ix_airports_lat")
    assert "lat" in sql
    assert "lon" in sql


async def test_the_iata_index_is_partial(db_path: Path) -> None:
    """Roughly one row in eight carries a code; the rest cannot answer the lookup."""
    await upgrade_empty_database(db_path)

    assert "ix_airports_iata" in index_names(db_path, TABLE)
    assert "WHERE" in index_sql(db_path, "ix_airports_iata").upper()


async def test_no_rtree_module_is_required(db_path: Path) -> None:
    """§3.6 is explicit that this row count needs none, and SQLite ships none."""
    await upgrade_empty_database(db_path)

    assert "RTREE" not in create_sql(db_path, TABLE).upper()
    assert not any(name.startswith("airports_rtree") for name in table_names(db_path))


async def test_the_sighting_inference_columns_predate_this_revision(db_path: Path) -> None:
    """0002 created them; this slice fills them, and alters nothing."""
    async with database_at(db_path, PREVIOUS):
        pass

    columns = column_types(db_path, "sightings")

    assert {"inferred_airport_ident", "inferred_phase"} <= set(columns)


async def test_the_inferred_phase_check_is_enforced_by_sqlite(db_path: Path) -> None:
    """A vocabulary declared but not enforced is a comment."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms) "
            "VALUES (1, 'ae1463', 1, 2)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO sightings (id, aircraft_id, started_ms, inferred_phase) "
                "VALUES (1, 1, 1, 'landing')"
            )


@pytest.mark.parametrize("phase", ["arriving", "departing"])
async def test_both_vocabulary_values_are_accepted(db_path: Path, phase: str) -> None:
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms) "
            "VALUES (1, 'ae1463', 1, 2)"
        )
        connection.execute(
            "INSERT INTO sightings (id, aircraft_id, started_ms, "
            "inferred_airport_ident, inferred_phase) VALUES (1, 1, 1, 'KBFI', ?)",
            (phase,),
        )


async def test_the_revision_rolls_back(db_path: Path) -> None:
    """A migration that cannot be undone is a one-way door."""
    await upgrade_empty_database(db_path)
    assert TABLE in table_names(db_path)

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert TABLE not in table_names(db_path)
