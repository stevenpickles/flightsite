"""Migration 0010: schema shape, linear history, drift, and rollback.

Every assertion reads the database file with stdlib ``sqlite3`` through
:mod:`tests.db.harness`, so "the migration created this" cannot be satisfied by
a model declaration alone. Migrations are a SPEC §84 critical-coverage domain.

The shape checks are ``docs/DATA_MODEL.md`` §5 column for column, plus the two
properties the whole slice stands on: ``dedupe_key`` being genuinely ``UNIQUE``
in SQLite (not merely declared in Python), and ``milestones.key`` being a
primary key that refuses a second claim. Those two constraints *are* the
exactly-once guarantee, so they are asserted by provoking the errors rather
than by reading a schema string.
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
    index_sql,
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0010"
PREVIOUS = "0009"

TABLES = ("activity_events", "milestones")

#: ``docs/DATA_MODEL.md`` §5, column for column.
ACTIVITY_COLUMNS = {
    "id": "INTEGER",
    "ts_ms": "INTEGER",
    "type": "TEXT",
    "severity": "TEXT",
    "aircraft_id": "INTEGER",
    "sighting_id": "INTEGER",
    "payload_json": "TEXT",
    "dedupe_key": "TEXT",
}

MILESTONE_COLUMNS = {
    "key": "TEXT",
    "achieved_ms": "INTEGER",
    "aircraft_id": "INTEGER",
    "value_num": "REAL",
    "payload_json": "TEXT",
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


async def test_the_activity_events_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "activity_events") == ACTIVITY_COLUMNS
    assert primary_key_columns(db_path, "activity_events") == ["id"]


async def test_only_the_genuinely_optional_activity_columns_are_nullable(db_path: Path) -> None:
    """An event always has a moment, a type and a severity; the rest may be absent.

    ``aircraft_id`` and ``sighting_id`` are null for a receiver-wide event —
    a decoder outage is about no aircraft at all. ``payload_json`` is null for
    an event with nothing to render beyond its type. ``dedupe_key`` is nullable
    because SQLite treats every ``NULL`` as distinct, which is the shape a
    future genuinely repeatable event would need; every producer in this slice
    fills it.
    """
    await upgrade_empty_database(db_path)

    assert not_null_columns(db_path, "activity_events") == {"id", "ts_ms", "type", "severity"}


async def test_the_severity_ladder_is_constrained_but_the_type_vocabulary_is_not(
    db_path: Path,
) -> None:
    """§2.8's ladder is fixed; §5's event list is a comment, and stays open.

    The asymmetry is the point. Widening a SQLite ``CHECK`` means rebuilding
    the table, and ``activity_events.type`` has to grow — phase 6 adds alert
    and emergency events, later slices add maintenance and reset ones. The
    severity ladder does not grow, is shared with ``alert_rules`` and
    ``alert_matches``, and so is worth enforcing.
    """
    await upgrade_empty_database(db_path)
    columns = "(ts_ms, type, severity)"

    with sqlite3.connect(db_path) as connection:
        # A type nothing has invented yet is accepted, which is what lets a
        # later slice add a producer without a migration.
        connection.execute(f"INSERT INTO activity_events {columns} VALUES (1, 'not_yet', 'info')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"INSERT INTO activity_events {columns} VALUES (1, 'milestone', 'urgent')"
            )


async def test_severity_defaults_to_info(db_path: Path) -> None:
    """§5's ``DEFAULT 'info'``: an event nobody graded is ordinary news."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO activity_events (ts_ms, type) VALUES (1, 'milestone')")
        (severity,) = connection.execute("SELECT severity FROM activity_events").fetchone()

    assert severity == "info"


async def test_a_repeated_dedupe_key_is_refused_by_the_database(db_path: Path) -> None:
    """The restart/replay guarantee, enforced by SQLite rather than by a producer.

    This is the roadmap's *"no duplicates on restart/replay"* at its lowest
    level: whatever a producer concludes, and however many times a pass
    re-derives it, the second row with the same key cannot exist.
    """
    await upgrade_empty_database(db_path)
    columns = "(ts_ms, type, severity, dedupe_key)"

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"INSERT INTO activity_events {columns} "
            "VALUES (1, 'first_ever_aircraft', 'info', 'first_ever_aircraft:ae1463')"
        )
        # A *different* address is a different event, and is accepted.
        connection.execute(
            f"INSERT INTO activity_events {columns} "
            "VALUES (2, 'first_ever_aircraft', 'info', 'first_ever_aircraft:a9c2f0')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                f"INSERT INTO activity_events {columns} "
                "VALUES (9, 'first_ever_aircraft', 'info', 'first_ever_aircraft:ae1463')"
            )


async def test_null_dedupe_keys_do_not_collide(db_path: Path) -> None:
    """SQLite treats each ``NULL`` as distinct — which is why the column is nullable."""
    await upgrade_empty_database(db_path)
    columns = "(ts_ms, type, severity, dedupe_key)"

    with sqlite3.connect(db_path) as connection:
        connection.execute(f"INSERT INTO activity_events {columns} VALUES (1, 'x', 'info', NULL)")
        connection.execute(f"INSERT INTO activity_events {columns} VALUES (2, 'x', 'info', NULL)")
        (count,) = connection.execute("SELECT COUNT(*) FROM activity_events").fetchone()

    assert count == 2


async def test_the_feed_indexes_are_the_ones_the_data_model_declares(db_path: Path) -> None:
    """§5's two indexes, and the descending one is genuinely descending.

    Newest-first is the feed's only ordering — for ``GET /api/v1/activity`` and
    for the Live Map panel alike — so the chronological index is created
    ``DESC``. SQLite's index reflection cannot report a sort direction, which
    is why the model declares a plain column index and this test reads the
    stored ``CREATE INDEX`` statement instead.
    """
    await upgrade_empty_database(db_path)

    declared = {name for name in index_names(db_path, "activity_events") if "autoindex" not in name}
    assert declared == {"ix_activity_ts", "ix_activity_type_ts"}
    assert "DESC" in index_sql(db_path, "ix_activity_ts").upper()
    assert "(type, ts_ms)" in index_sql(db_path, "ix_activity_type_ts")


async def test_activity_events_reference_the_rows_they_describe(db_path: Path) -> None:
    """Real foreign keys, unlike the derived rollup tables of slice 031.

    An activity event is not a materialization of anything: it records that
    something was noticed. The link to the airframe and the sighting is what a
    feed row opens, so it is a constraint rather than a convention.
    """
    await upgrade_empty_database(db_path)

    assert foreign_keys(db_path, "activity_events") == {
        ("aircraft_id", "aircraft", "id"),
        ("sighting_id", "sightings", "id"),
    }


async def test_the_milestones_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "milestones") == MILESTONE_COLUMNS
    assert primary_key_columns(db_path, "milestones") == ["key"]
    assert not_null_columns(db_path, "milestones") == {"key", "achieved_ms"}
    assert foreign_keys(db_path, "milestones") == {("aircraft_id", "aircraft", "id")}


async def test_a_milestone_can_only_be_claimed_once(db_path: Path) -> None:
    """The primary key *is* SPEC §54's fire-once rule."""
    await upgrade_empty_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO milestones (key, achieved_ms) VALUES ('first_military', 1)")
        connection.execute(
            "INSERT INTO milestones (key, achieved_ms) VALUES ('unique_aircraft_1000', 2)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO milestones (key, achieved_ms) VALUES ('first_military', 9)"
            )


async def test_milestones_is_without_rowid_and_activity_events_is_not(db_path: Path) -> None:
    """Each layout matches how its table is actually reached.

    ``milestones`` holds tens of rows and every access is a point lookup on its
    text key, so the key is the b-tree. ``activity_events`` has an
    autoincrement surrogate key and three indexes over it, none of which a
    ``WITHOUT ROWID`` layout would help.
    """
    await upgrade_empty_database(db_path)

    assert "WITHOUT ROWID" in create_sql(db_path, "milestones").upper()
    assert "WITHOUT ROWID" not in create_sql(db_path, "activity_events").upper()


async def test_the_downgrade_drops_exactly_this_slice_s_tables(db_path: Path) -> None:
    """Rolling back loses real history — which is why it is a drop, not a rebuild.

    Unlike slice 031's rollups there is no backfill that could recreate these
    rows: an activity event records that something was noticed at a moment, and
    that is not derivable from ``sightings`` after the fact.
    """
    await upgrade_empty_database(db_path, REVISION)
    before = table_names(db_path)

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert before - table_names(db_path) == set(TABLES)
    assert {"sightings", "aircraft"} <= table_names(db_path)
