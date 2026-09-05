"""Migration 0015 against a database that actually has children (issue #178).

``tests/enrichment/test_migration_directory.py`` covers what revision 0015
*changes*. This module covers what broke in production: the revision rebuilds
``sightings``, five tables reference ``sightings(id)``, and every test that
existed when the revision shipped seeded **no child rows at all**. With the
foreign keys the application's connections enforce, ``DROP TABLE sightings``
is an implicit ``DELETE`` checked row by row against those five children — five
minutes of CPU on a 16,214-sighting install, then
``FOREIGN KEY constraint failed``, then a rollback and six minutes of downtime.

So the fixtures here populate every child, and the assertions are the three
things the failure denied: the upgrade finishes in a bounded time, every child
row is still attached to its sighting afterwards, and ``foreign_key_check``
has nothing to say. Plus the two mechanisms that make it so — the suspended
pragma, and resuming from the wreckage of a failed attempt.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from flightsite.db import migrate
from flightsite.db.migrations import rebuild
from tests.db.harness import create_sql, database_at, index_names, index_sql, table_names

REVISION = "0015"
PREVIOUS = "0014"
SIGHTINGS = "sightings"
STAGING = "sightings_rebuild"

#: Sightings in the populated fixture, and 30,300 child rows around them.
#: Within an order of magnitude of the install that failed (16,214 sightings)
#: rather than of a unit test, because what the shipped revision did was
#: quadratic in this number — and still well under a second to seed, so it runs
#: in the ordinary suite rather than behind a marker.
SIGHTING_COUNT = 3000

#: Rows written per sighting into each child table, in the proportions a real
#: database carries them: one track blob, several track checkpoints, a couple
#: of sighting events, an activity event or two, an occasional alert match.
CHECKPOINTS_PER_SIGHTING = 5
EVENTS_PER_SIGHTING = 2
ACTIVITY_PER_SIGHTING = 2
ALERT_MATCH_EVERY = 10

#: Wall-clock bound for upgrading the populated fixture, and for downgrading
#: it again. **Measured** on a developer SSD: 0.053 s to upgrade and 0.049 s to
#: downgrade this fixture, and 0.101 s / 0.108 s at the failing install's scale
#: (16,214 sightings, 163,761 child rows, an 11 MB file). The bound is three
#: orders of magnitude above that because it is a *regression* gate on a shared
#: CI runner, not a benchmark — the failure it exists to catch ran for five
#: minutes on a database five times this size and then raised.
MIGRATION_BUDGET_S = 30.0

#: Every table that references ``sightings(id)``. The rebuild has to leave all
#: five resolving, and every one of them is seeded before the upgrade runs.
CHILD_TABLES = (
    "sighting_tracks",
    "sighting_track_checkpoints",
    "sighting_events",
    "activity_events",
    "alert_matches",
)


def _seed_children(db_path: Path, count: int = SIGHTING_COUNT) -> dict[str, int]:
    """Fill a 0014 database with sightings and rows in every child table.

    Written with stdlib ``sqlite3`` against the schema revision 0014 left, the
    way an older build would have written it — not through today's models,
    which is the same discipline :mod:`tests.db.harness` applies.

    Returns the row count seeded into each child table.
    """
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms) "
            "VALUES (1, 'ae1463', 1, 2)"
        )
        connection.executemany(
            "INSERT INTO sightings (id, aircraft_id, started_ms, ended_ms, callsign_last, "
            "origin_ident, destination_ident, route_source, max_range_nm, msg_count) "
            "VALUES (?, 1, ?, ?, ?, 'KATL', 'KSLC', 'aerodatabox', ?, ?)",
            [
                (index, index * 1000, index * 1000 + 500, f"DAL{index:04d}", index / 10.0, index)
                for index in range(1, count + 1)
            ],
        )
        connection.executemany(
            "INSERT INTO sighting_tracks (sighting_id, encoding_version, point_count, "
            "started_ms, points_blob) VALUES (?, 1, 4, ?, ?)",
            [(index, index * 1000, b"\x00\x01\x02\x03") for index in range(1, count + 1)],
        )
        connection.executemany(
            "INSERT INTO sighting_track_checkpoints (sighting_id, seq, ts_ms, lat, lon, "
            "alt_ft, gs_kt, track_deg, pos_source) VALUES (?, ?, ?, 51.5, -0.1, 30000, "
            "440.0, 90.0, 0)",
            [
                (index, seq, index * 1000 + seq)
                for index in range(1, count + 1)
                for seq in range(CHECKPOINTS_PER_SIGHTING)
            ],
        )
        connection.executemany(
            "INSERT INTO sighting_events (sighting_id, ts_ms, type) VALUES (?, ?, ?)",
            [
                (index, index * 1000 + seq, "callsign_change" if seq else "route_enriched")
                for index in range(1, count + 1)
                for seq in range(EVENTS_PER_SIGHTING)
            ],
        )
        connection.executemany(
            "INSERT INTO activity_events (ts_ms, type, severity, aircraft_id, sighting_id) "
            "VALUES (?, 'sighting_closed', 'info', 1, ?)",
            [
                (index * 1000 + seq, index)
                for index in range(1, count + 1)
                for seq in range(ACTIVITY_PER_SIGHTING)
            ],
        )
        connection.executemany(
            "INSERT INTO alert_matches (builtin_key, sighting_id, aircraft_id, matched_ms, "
            "severity, reason) VALUES ('emergency', ?, 1, ?, 'high', 'squawk 7700')",
            [
                (index, index * 1000)
                for index in range(1, count + 1)
                if index % ALERT_MATCH_EVERY == 0
            ],
        )
    return _child_counts(db_path)


def _child_counts(db_path: Path) -> dict[str, int]:
    """Row count of every child table."""
    with sqlite3.connect(db_path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in CHILD_TABLES
        }


def _orphans(db_path: Path) -> dict[str, int]:
    """Rows in each child whose ``sighting_id`` no longer names a sighting."""
    with sqlite3.connect(db_path) as connection:
        return {
            table: int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE sighting_id IS NOT NULL "
                    "AND sighting_id NOT IN (SELECT id FROM sightings)"
                ).fetchone()[0]
            )
            for table in CHILD_TABLES
        }


def _foreign_key_violations(db_path: Path) -> list[tuple[object, ...]]:
    """Whatever ``PRAGMA foreign_key_check`` finds across the whole database."""
    with sqlite3.connect(db_path) as connection:
        return list(connection.execute("PRAGMA foreign_key_check"))


def _schema_of(db_path: Path, names: tuple[str, ...]) -> dict[str, str]:
    """The stored SQL of the named tables and indexes, for comparing schemas."""
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE name IN "
            f"({', '.join('?' * len(names))}) ORDER BY name",
            names,
        ).fetchall()
    return {str(name): str(sql) for name, sql in rows}


#: The objects revision 0015 creates or recreates, whose definitions must come
#: out identical whether the upgrade ran clean or resumed from a failed one.
AFFECTED_OBJECTS = (
    "route_directory",
    "route_directory_staging",
    "route_cache",
    SIGHTINGS,
    "ix_sightings_aircraft",
    "ix_sightings_started",
    "ix_sightings_open",
    "ix_sightings_max_range",
)


@pytest.fixture
async def populated_0014(db_path: Path) -> Path:
    """A revision-0014 database with sightings and every child table filled."""
    async with database_at(db_path, PREVIOUS):
        pass
    _seed_children(db_path)
    return db_path


# ------------------------------------------------------- the upgrade with children


@pytest.mark.perf
async def test_the_upgrade_finishes_promptly_on_a_database_with_children(
    populated_0014: Path,
) -> None:
    """The regression gate: the failure this replaces ran for minutes, then raised.

    A bound rather than a benchmark — see :data:`MIGRATION_BUDGET_S`.
    """
    started = time.perf_counter()
    async with database_at(populated_0014, REVISION) as database:
        assert await database.current_revision() == REVISION
    elapsed = time.perf_counter() - started

    assert elapsed < MIGRATION_BUDGET_S, f"upgrade with children took {elapsed:.2f}s"


async def test_every_child_row_survives_the_rebuild(populated_0014: Path) -> None:
    """Not one row of the five children may be deleted, orphaned or renumbered."""
    before = _child_counts(populated_0014)

    async with database_at(populated_0014, REVISION):
        pass

    assert _child_counts(populated_0014) == before
    assert _orphans(populated_0014) == dict.fromkeys(CHILD_TABLES, 0)


async def test_the_upgrade_leaves_no_dangling_reference_anywhere(
    populated_0014: Path,
) -> None:
    """Enforcement is suspended for the rebuild, so this is what replaces it."""
    async with database_at(populated_0014, REVISION):
        pass

    assert _foreign_key_violations(populated_0014) == []


async def test_the_sightings_themselves_survive_the_rebuild(populated_0014: Path) -> None:
    with sqlite3.connect(populated_0014) as connection:
        before = list(
            connection.execute("SELECT id, callsign_last, max_range_nm FROM sightings ORDER BY id")
        )

    async with database_at(populated_0014, REVISION):
        pass

    with sqlite3.connect(populated_0014) as connection:
        after = list(
            connection.execute("SELECT id, callsign_last, max_range_nm FROM sightings ORDER BY id")
        )
    assert len(after) == SIGHTING_COUNT
    assert after == before


# ------------------------------------------------------ the downgrade with children


@pytest.mark.perf
async def test_the_downgrade_is_bounded_and_keeps_the_children(
    populated_0014: Path,
) -> None:
    """Rollback rebuilds the same table, so it needs the same discipline."""
    async with database_at(populated_0014, REVISION):
        pass
    before = _child_counts(populated_0014)

    started = time.perf_counter()
    async with database_at(populated_0014, REVISION) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS
    elapsed = time.perf_counter() - started

    assert elapsed < MIGRATION_BUDGET_S, f"downgrade with children took {elapsed:.2f}s"
    assert _child_counts(populated_0014) == before
    assert _orphans(populated_0014) == dict.fromkeys(CHILD_TABLES, 0)
    assert _foreign_key_violations(populated_0014) == []


# ----------------------------------------------------------------- the pragma itself


async def test_the_rebuild_runs_with_foreign_keys_off_and_restores_them(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim the original revision made without ever checking it.

    ``PRAGMA foreign_keys`` is read back on the migration's *own* connection —
    once while the rebuild is finished but not yet unwound, which is when
    :func:`flightsite.db.migrations.rebuild.check_foreign_keys` runs, and once
    after each attempt to change it, which is what proves enforcement came
    back rather than merely being asked to.
    """
    during: list[bool] = []
    after_each_change: list[bool] = []
    original_check = rebuild.check_foreign_keys
    original_set = rebuild.set_foreign_keys

    def check_spy(bind: sa.Connection, table: str) -> None:
        during.append(rebuild.foreign_keys_enabled(bind))
        original_check(bind, table)

    def set_spy(bind: sa.Connection, *, enabled: bool) -> None:
        original_set(bind, enabled=enabled)
        after_each_change.append(rebuild.foreign_keys_enabled(bind))

    monkeypatch.setattr(rebuild, "check_foreign_keys", check_spy)
    monkeypatch.setattr(rebuild, "set_foreign_keys", set_spy)

    async with database_at(db_path, PREVIOUS):
        pass
    _seed_children(db_path, count=10)
    async with database_at(db_path, REVISION):
        pass

    assert during == [False], "the rebuild did not run with foreign keys suspended"
    assert after_each_change == [False, True], "enforcement was not restored afterwards"


def test_the_pragma_is_restored_even_though_it_had_to_leave_a_transaction(
    db_path: Path,
) -> None:
    """Suspending enforcement inside an open transaction is silently a no-op.

    This is the empirical fact the fix turns on, and it is asserted directly
    rather than inferred: a plain ``PRAGMA foreign_keys=OFF`` issued after a
    DML statement — which is where a multi-revision Alembic run arrives, its
    ``UPDATE alembic_version`` having opened a transaction pysqlite holds open
    — leaves enforcement *on*. Going through
    :func:`flightsite.db.migrations.rebuild.rebuilding` ends that transaction
    first, and restores enforcement on the way out.
    """
    engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO parent (id) VALUES (1)")
        driver = connection.connection.driver_connection
        assert isinstance(driver, sqlite3.Connection)
        assert driver.in_transaction is True

        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        ignored_inside_a_transaction = rebuild.foreign_keys_enabled(connection)

        connection.exec_driver_sql("INSERT INTO parent (id) VALUES (2)")
        with rebuild.rebuilding(connection, "parent"):
            suspended = rebuild.foreign_keys_enabled(connection)
        restored = rebuild.foreign_keys_enabled(connection)
    engine.dispose()

    assert ignored_inside_a_transaction is True
    assert suspended is False
    assert restored is True


def test_a_dangling_reference_is_raised_rather_than_committed(db_path: Path) -> None:
    """The check is the substitute for the enforcement, so it has to bite."""
    engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent (id))"
        )
        connection.exec_driver_sql("INSERT INTO parent (id) VALUES (1)")
        connection.exec_driver_sql("INSERT INTO child (id, parent_id) VALUES (1, 1)")

        with pytest.raises(rebuild.DanglingForeignKeys), rebuild.rebuilding(connection, "parent"):
            connection.exec_driver_sql("DELETE FROM parent")

        assert rebuild.foreign_keys_enabled(connection) is True
    engine.dispose()


def test_the_children_of_a_table_are_discovered_from_the_schema(db_path: Path) -> None:
    """So a later slice's new child table is checked without anyone adding it."""
    engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE later (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent (id))"
        )
        connection.exec_driver_sql("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        found = rebuild.child_tables(connection, "parent")
    engine.dispose()

    assert found == ("later",)


# --------------------------------------------------------- resuming a failed attempt


def _replay_failed_attempt(db_path: Path, *, past_the_drop: bool = False) -> None:
    """Leave the database in the state a failed 0015 attempt leaves it in.

    Replayed through Alembic's own operations against the revision module
    itself, rather than hand-written SQL, so the objects a resumed upgrade
    finds are byte-for-byte the ones the failed attempt created.

    By default this is fermi's state, where ``DROP TABLE sightings`` was the
    statement that raised: directory tables present, ``route_cache.source``
    added, all four ``sightings`` indexes dropped, an empty
    ``sightings_rebuild`` left behind (its ``INSERT … SELECT`` rolled back with
    the failing statement), and ``alembic_version`` still naming 0014.

    With ``past_the_drop`` it is the narrower window a crash — a power cut, a
    container kill — can land in instead: the copy done and ``sightings``
    dropped, with the history sitting in ``sightings_rebuild`` and five child
    tables referencing a table that no longer exists.
    """
    module = migrate.script_directory().get_revision(REVISION).module
    engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        context = MigrationContext.configure(connection, opts={"render_as_batch": True})
        with Operations.context(context) as operations:
            module._create_directory_tables()
            operations.add_column("route_cache", sa.Column("source", sa.Text(), nullable=True))
            for name, _columns, _where in module._SIGHTINGS_INDEXES:
                operations.drop_index(name, table_name=SIGHTINGS)
            module._create_sightings(STAGING, route_source_check=module._ROUTE_SOURCE_CHECK)
            if past_the_drop:
                carried = ", ".join(module._SIGHTINGS_COLUMNS)
                operations.execute(
                    f"INSERT INTO {STAGING} ({carried}) SELECT {carried} FROM {SIGHTINGS}"
                )
                operations.drop_table(SIGHTINGS)
        connection.commit()
    engine.dispose()


async def test_the_partial_state_of_a_failed_attempt_is_resumable(
    populated_0014: Path,
) -> None:
    """A restarting container re-runs 0015 over the wreckage of the last try."""
    before = _child_counts(populated_0014)
    _replay_failed_attempt(populated_0014)
    assert STAGING in table_names(populated_0014)

    async with database_at(populated_0014, REVISION) as database:
        assert await database.current_revision() == REVISION

    assert _child_counts(populated_0014) == before
    assert _orphans(populated_0014) == dict.fromkeys(CHILD_TABLES, 0)
    assert _foreign_key_violations(populated_0014) == []
    assert index_names(populated_0014, SIGHTINGS) >= {
        "ix_sightings_aircraft",
        "ix_sightings_started",
        "ix_sightings_open",
        "ix_sightings_max_range",
    }
    assert "ended_ms IS NULL" in index_sql(populated_0014, "ix_sightings_open")
    assert STAGING not in table_names(populated_0014)


async def test_a_resumed_upgrade_lands_on_the_same_schema_as_a_clean_one(
    db_path: Path, tmp_path: Path
) -> None:
    """Same end state, object for object — otherwise "resumable" is a wish."""
    clean = tmp_path / "clean.sqlite3"
    async with database_at(clean, PREVIOUS):
        pass
    _seed_children(clean, count=20)
    async with database_at(clean, REVISION):
        pass

    async with database_at(db_path, PREVIOUS):
        pass
    _seed_children(db_path, count=20)
    _replay_failed_attempt(db_path)
    async with database_at(db_path, REVISION):
        pass

    resumed = _schema_of(db_path, AFFECTED_OBJECTS)
    assert set(resumed) == set(AFFECTED_OBJECTS), "an object is missing, not merely different"
    assert resumed == _schema_of(clean, AFFECTED_OBJECTS)
    assert "vrs" in create_sql(db_path, SIGHTINGS)


async def test_an_interrupted_rename_keeps_the_history_it_was_carrying(
    populated_0014: Path,
) -> None:
    """The one partial state where the staging table *is* the data.

    A crash between ``DROP TABLE sightings`` and the rename leaves the rows in
    ``sightings_rebuild`` and no ``sightings`` at all. Dropping the staging
    table on the next attempt — the obvious reading of "clear anything left
    behind" — would delete the history instead of migrating it.
    """
    before = _child_counts(populated_0014)
    _replay_failed_attempt(populated_0014, past_the_drop=True)
    assert SIGHTINGS not in table_names(populated_0014)

    async with database_at(populated_0014, REVISION) as database:
        assert await database.current_revision() == REVISION

    with sqlite3.connect(populated_0014) as connection:
        surviving = int(connection.execute("SELECT COUNT(*) FROM sightings").fetchone()[0])
    assert surviving == SIGHTING_COUNT
    assert STAGING not in table_names(populated_0014)
    assert _child_counts(populated_0014) == before
    assert _orphans(populated_0014) == dict.fromkeys(CHILD_TABLES, 0)
    assert _foreign_key_violations(populated_0014) == []
