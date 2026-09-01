"""Migration tests for revision 0003 (DATA_MODEL §2.4/§2.5).

Asserted from the outside with stdlib ``sqlite3`` through the shared harness,
so "the migration created this column" cannot be satisfied by the ORM
declaration alone. The single-head and drift checks in
``tests/db/test_migrations.py`` cover this revision automatically; what is here
is the column-by-column contract of the three new tables, the storage decisions
that make the growth model work (``WITHOUT ROWID``, clustered primary keys,
integer enum codes) and the upgrade path from the previous revision.
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
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0003"
PREVIOUS = "0002"

NEW_TABLES = {"sighting_track_checkpoints", "sighting_tracks", "sighting_events"}

EXPECTED_CHECKPOINT_COLUMNS = {
    "sighting_id": "INTEGER",
    "seq": "INTEGER",
    "ts_ms": "INTEGER",
    "lat": "REAL",
    "lon": "REAL",
    "alt_ft": "INTEGER",
    "gs_kt": "REAL",
    "track_deg": "REAL",
    "pos_source": "INTEGER",
}

EXPECTED_TRACK_COLUMNS = {
    "sighting_id": "INTEGER",
    "encoding_version": "INTEGER",
    "point_count": "INTEGER",
    "started_ms": "INTEGER",
    "points_blob": "BLOB",
}

EXPECTED_EVENT_COLUMNS = {
    "id": "INTEGER",
    "sighting_id": "INTEGER",
    "ts_ms": "INTEGER",
    "type": "TEXT",
    "payload_json": "TEXT",
}


async def test_the_migration_creates_all_three_tables(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert table_names(db_path) >= NEW_TABLES


async def test_the_checkpoint_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "sighting_track_checkpoints") == EXPECTED_CHECKPOINT_COLUMNS
    assert not_null_columns(db_path, "sighting_track_checkpoints") == {
        "sighting_id",
        "seq",
        "ts_ms",
        "lat",
        "lon",
        "pos_source",
    }
    assert primary_key_columns(db_path, "sighting_track_checkpoints") == ["sighting_id", "seq"]
    assert foreign_keys(db_path, "sighting_track_checkpoints") == {
        ("sighting_id", "sightings", "id")
    }


async def test_the_checkpoint_table_is_clustered_by_sighting(db_path: Path) -> None:
    # WITHOUT ROWID under (sighting_id, seq) is what makes a sighting's points
    # contiguous, which is both how they are written and the only way they are
    # ever read — and is why no separate index over sighting_id exists.
    await upgrade_empty_database(db_path)

    assert "WITHOUT ROWID" in create_sql(db_path, "sighting_track_checkpoints").upper()


async def test_the_packed_track_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "sighting_tracks") == EXPECTED_TRACK_COLUMNS
    assert not_null_columns(db_path, "sighting_tracks") == {
        "sighting_id",
        "encoding_version",
        "point_count",
        "started_ms",
        "points_blob",
    }
    # One row per sighting: the primary key is the uniqueness guarantee, so a
    # second packed track for the same sighting cannot exist.
    assert primary_key_columns(db_path, "sighting_tracks") == ["sighting_id"]
    assert foreign_keys(db_path, "sighting_tracks") == {("sighting_id", "sightings", "id")}
    assert "WITHOUT ROWID" in create_sql(db_path, "sighting_tracks").upper()


async def test_the_sighting_events_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "sighting_events") == EXPECTED_EVENT_COLUMNS
    assert not_null_columns(db_path, "sighting_events") == {"id", "sighting_id", "ts_ms", "type"}
    assert primary_key_columns(db_path, "sighting_events") == ["id"]
    assert foreign_keys(db_path, "sighting_events") == {("sighting_id", "sightings", "id")}
    assert "ix_sevents_sighting" in index_names(db_path, "sighting_events")


async def test_the_event_vocabulary_is_enforced_by_the_schema(db_path: Path) -> None:
    # The whole vocabulary is constrained from birth, including the values
    # later slices emit: widening a SQLite CHECK means rebuilding the table.
    await upgrade_empty_database(db_path)

    sql = create_sql(db_path, "sighting_events")

    for value in (
        "callsign_change",
        "squawk_change",
        "emergency_start",
        "emergency_end",
        "route_enriched",
        "classification_available",
        "alert_matched",
        "alert_severity_upgraded",
    ):
        assert f"'{value}'" in sql


async def test_a_database_at_the_previous_revision_upgrades_cleanly(db_path: Path) -> None:
    # The upgrade path an existing slice-009 install takes.
    async with database_at(db_path, PREVIOUS) as database:
        assert await database.current_revision() == PREVIOUS
    assert not NEW_TABLES & table_names(db_path)

    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == migrate.head_revision()
        assert await autogenerate_diffs(database) == []

    assert table_names(db_path) >= NEW_TABLES


def test_this_revision_sits_directly_on_the_previous_one() -> None:
    # The linear-head rule of docs/DEVELOPMENT.md §"Parallel migrations": this
    # revision must hang off the head it was written against, not off a branch.
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == PREVIOUS
    # Not "this is the head": later slices legitimately add revisions on top of
    # it (021 added 0004). What must stay true is that this one hangs off the
    # head it was written against and remains on the single linear path — the
    # head itself is asserted by tests/db/test_migrations.py.
    reachable = {revision.revision for revision in migrate.script_directory().walk_revisions()}
    assert REVISION in reachable


async def test_downgrading_removes_the_three_tables(db_path: Path) -> None:
    await upgrade_empty_database(db_path)
    database = Database(db_path)
    try:
        await database.downgrade_to(PREVIOUS)

        remaining = table_names(db_path)
        assert not NEW_TABLES & remaining
        # ...and leaves the tables this revision did not create.
        assert {"aircraft", "sightings", "meta"} <= remaining
    finally:
        await database.dispose()
