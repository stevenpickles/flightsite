"""Migration 0015: the route directory, ``route_cache.source``, and the rebuild.

Same discipline as ``test_migration_economy.py`` next door — every assertion
reads the database file with stdlib ``sqlite3`` through :mod:`tests.db.harness`,
so "the migration did this" cannot be satisfied by a model declaration alone.

The revision does three things of very different weights, and each is checked
on its own: two new tables, one cheap ``ALTER TABLE``, and a rebuild of
``sightings`` that exists only because SQLite cannot widen a ``CHECK`` in place.
The rebuild is the one worth the most scrutiny, because it moves real history:
the tests below care as much about what survived it — rows, indexes, the
partial-index predicate, the foreign key — as about what changed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from flightsite.db import migrate
from flightsite.db.models import ROUTE_SOURCE_CHECK
from flightsite.enrichment.model import ROUTE_SOURCE_AERODATABOX, ROUTE_SOURCE_VRS
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

REVISION = "0015"
PREVIOUS = "0014"

DIRECTORY = "route_directory"
STAGING = "route_directory_staging"
SIGHTINGS = "sightings"

#: ``docs/DATA_MODEL.md`` §7.1 at this revision, column for column.
EXPECTED_DIRECTORY_COLUMNS = {
    "callsign": "TEXT",
    "airline_code": "TEXT",
    "airport_codes": "TEXT",
    "dataset_version": "TEXT",
}

#: Every index ``sightings`` carries, which the rebuild has to put back.
EXPECTED_SIGHTING_INDEXES = {
    "ix_sightings_aircraft",
    "ix_sightings_started",
    "ix_sightings_open",
    "ix_sightings_max_range",
}

_INSERT_AIRCRAFT = (
    "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms) VALUES (1, 'ae1463', 1, 2)"
)
_INSERT_SIGHTING = (
    "INSERT INTO sightings (id, aircraft_id, started_ms, ended_ms, callsign_last, "
    "origin_ident, destination_ident, route_source, max_range_nm) "
    "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)"
)
_INSERT_ROUTE_CACHE = (
    "INSERT INTO route_cache (cache_key, status, origin_ident, destination_ident, "
    "fetched_ms, expires_ms) VALUES (?, ?, ?, ?, 1, 2)"
)


def _seed_history(db_path: Path, *, route_source: str | None = ROUTE_SOURCE_AERODATABOX) -> None:
    """One aircraft and two sightings, as an older install would have left them."""
    with sqlite3.connect(db_path) as connection:
        connection.execute(_INSERT_AIRCRAFT)
        connection.execute(
            _INSERT_SIGHTING, (1, 100, 200, "DAL1234", "KATL", "KSLC", route_source, 42.5)
        )
        connection.execute(_INSERT_SIGHTING, (2, 300, None, "BAW1", None, None, None, None))


def _sightings(db_path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(db_path) as connection:
        return list(
            connection.execute(
                "SELECT id, callsign_last, origin_ident, destination_ident, route_source, "
                "max_range_nm FROM sightings ORDER BY id"
            )
        )


def test_this_revision_sits_directly_on_the_previous_head() -> None:
    """The linear-history rule of ``docs/DEVELOPMENT.md`` §"Parallel migrations"."""
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == PREVIOUS


def test_it_is_the_only_head() -> None:
    """One head, and it is this one — the rule a migration slice must leave true."""
    assert [script.revision for script in migrate.script_directory().get_revisions("heads")] == [
        REVISION
    ]


# ------------------------------------------------------------ the new tables


async def test_the_directory_tables_arrive_with_this_revision(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = table_names(db_path)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION

    assert DIRECTORY not in before
    assert {DIRECTORY, STAGING} <= table_names(db_path)
    assert column_types(db_path, DIRECTORY) == EXPECTED_DIRECTORY_COLUMNS


async def test_the_directory_is_keyed_on_the_callsign_without_a_rowid(
    db_path: Path,
) -> None:
    """Every read is a point lookup by callsign, so the key *is* the table."""
    await upgrade_empty_database(db_path)

    assert primary_key_columns(db_path, DIRECTORY) == ["callsign"]
    assert "WITHOUT ROWID" in create_sql(db_path, DIRECTORY).upper()
    assert primary_key_columns(db_path, STAGING) == ["callsign"]
    assert "WITHOUT ROWID" in create_sql(db_path, STAGING).upper()


async def test_the_route_and_its_version_are_never_null(db_path: Path) -> None:
    """A row without a path is not a route; one without a version is unattributable."""
    await upgrade_empty_database(db_path)

    required = not_null_columns(db_path, DIRECTORY)
    assert {"callsign", "airport_codes", "dataset_version"} <= required
    assert "airline_code" not in required


async def test_staging_carries_no_version_because_it_does_not_know_one_yet(
    db_path: Path,
) -> None:
    """The version belongs to the artifact, and is stamped on at promotion."""
    await upgrade_empty_database(db_path)

    assert "dataset_version" not in column_types(db_path, STAGING)


# -------------------------------------------------------- route_cache.source


async def test_the_cache_learns_who_answered(db_path: Path) -> None:
    async with database_at(db_path, PREVIOUS):
        pass
    before = column_types(db_path, "route_cache")

    async with database_at(db_path, REVISION):
        pass

    assert "source" not in before
    assert column_types(db_path, "route_cache")["source"] == "TEXT"


async def test_a_pre_existing_cache_row_survives_with_no_source(db_path: Path) -> None:
    """Rows this build did not fetch are not retroactively attributed."""
    async with database_at(db_path, PREVIOUS):
        pass
    with sqlite3.connect(db_path) as connection:
        connection.execute(_INSERT_ROUTE_CACHE, ("DAL1234", "ok", "KATL", "KSLC"))

    async with database_at(db_path, REVISION):
        pass

    with sqlite3.connect(db_path) as connection:
        rows = list(connection.execute("SELECT cache_key, source FROM route_cache"))
    assert rows == [("DAL1234", None)]


# ------------------------------------------------------- the sightings rebuild


async def test_the_route_source_vocabulary_admits_vrs_after_this_revision(
    db_path: Path,
) -> None:
    """The whole reason ``sightings`` is rebuilt at all."""
    async with database_at(db_path, PREVIOUS):
        pass
    with sqlite3.connect(db_path) as connection:
        connection.execute(_INSERT_AIRCRAFT)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                _INSERT_SIGHTING, (1, 100, 200, "BAW1", "EGLL", "KJFK", ROUTE_SOURCE_VRS, None)
            )

    async with database_at(db_path, REVISION):
        pass
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            _INSERT_SIGHTING, (1, 100, 200, "BAW1", "EGLL", "KJFK", ROUTE_SOURCE_VRS, None)
        )


async def test_an_unknown_route_source_is_still_refused(db_path: Path) -> None:
    """Widening a vocabulary is not opening it."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(_INSERT_AIRCRAFT)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                _INSERT_SIGHTING, (1, 100, 200, "BAW1", "EGLL", "KJFK", "guessed", None)
            )


async def test_history_survives_the_rebuild_row_for_row(db_path: Path) -> None:
    """The rebuild moves real history; nothing may be lost or shifted."""
    async with database_at(db_path, PREVIOUS):
        pass
    _seed_history(db_path)

    async with database_at(db_path, REVISION):
        pass

    assert _sightings(db_path) == [
        (1, "DAL1234", "KATL", "KSLC", ROUTE_SOURCE_AERODATABOX, 42.5),
        (2, "BAW1", None, None, None, None),
    ]


async def test_every_index_survives_the_rebuild(db_path: Path) -> None:
    """Including the partial one and its predicate, and the composite sort."""
    await upgrade_empty_database(db_path)

    assert index_names(db_path, SIGHTINGS) >= EXPECTED_SIGHTING_INDEXES
    assert "ended_ms IS NULL" in index_sql(db_path, "ix_sightings_open")
    assert "max_range_nm" in index_sql(db_path, "ix_sightings_max_range")


async def test_the_foreign_key_to_aircraft_survives_the_rebuild(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert ("aircraft_id", "aircraft", "id") in foreign_keys(db_path, SIGHTINGS)


async def test_the_child_tables_still_reference_sightings(db_path: Path) -> None:
    """The drop-and-rename must not leave a dangling reference behind."""
    await upgrade_empty_database(db_path)

    for table in ("sighting_events", "sighting_tracks", "alert_matches"):
        assert ("sighting_id", "sightings", "id") in foreign_keys(db_path, table), table


async def test_the_models_predicate_is_the_one_in_the_file(db_path: Path) -> None:
    """Autogenerate does not compare ``CHECK`` constraints, so this does.

    The migration spells its vocabulary out — it records what an install ran —
    which is only safe while something asserts the newest one still matches the
    constant the application reasons about.
    """
    await upgrade_empty_database(db_path)

    assert ROUTE_SOURCE_CHECK in create_sql(db_path, SIGHTINGS)


async def test_the_schema_at_head_matches_the_models(db_path: Path) -> None:
    """Drift is checked at head, where the models describe the whole schema."""
    async with database_at(db_path) as database:
        assert await autogenerate_diffs(database) == []


# ------------------------------------------------------------------ rollback


async def test_the_revision_rolls_back(db_path: Path) -> None:
    """A migration that cannot be undone is a one-way door."""
    await upgrade_empty_database(db_path)
    _seed_history(db_path)

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert DIRECTORY not in table_names(db_path)
    assert STAGING not in table_names(db_path)
    assert "source" not in column_types(db_path, "route_cache")
    assert index_names(db_path, SIGHTINGS) >= EXPECTED_SIGHTING_INDEXES
    assert _sightings(db_path) == [
        (1, "DAL1234", "KATL", "KSLC", ROUTE_SOURCE_AERODATABOX, 42.5),
        (2, "BAW1", None, None, None, None),
    ]


async def test_rolling_back_clears_a_route_the_older_build_cannot_attribute(
    db_path: Path,
) -> None:
    """The sighting stays; the route goes, because its provenance cannot.

    SPEC §22 wants a source named for every value that is not the decoder's,
    and the build being downgraded to has no word for ``vrs``. Leaving the
    idents behind unattributed would be the one thing worse than clearing them:
    the next observation of that flight re-enriches it from AeroDataBox.
    """
    await upgrade_empty_database(db_path)
    _seed_history(db_path, route_source=ROUTE_SOURCE_VRS)
    with sqlite3.connect(db_path) as connection:
        connection.execute(_INSERT_ROUTE_CACHE, ("BAW1", "ok", "EGLL", "KJFK"))
        connection.execute("UPDATE route_cache SET source = ? WHERE cache_key = 'BAW1'", ("vrs",))
        connection.execute(_INSERT_ROUTE_CACHE, ("DAL1", "ok", "KATL", "KSLC"))

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)

    with sqlite3.connect(db_path) as connection:
        cached = [key for (key,) in connection.execute("SELECT cache_key FROM route_cache")]
    assert cached == ["DAL1"]
    assert _sightings(db_path) == [
        (1, "DAL1234", None, None, None, 42.5),
        (2, "BAW1", None, None, None, None),
    ]
