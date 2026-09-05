"""The offline route directory, and a second value in the route vocabulary.

Slice 071 makes the Virtual Radar Server standing-data routes the *primary*
source of origin and destination (SPEC §28 as amended 2026-09-05, ADR-0016).
Three schema changes carry that:

* **``route_directory`` and ``route_directory_staging``**
  (``docs/DATA_MODEL.md`` §7.1). One row per airline callsign upstream knows a
  route for — 619,770 in the measured snapshot — plus the staging table the
  import promotes from. The dataset is of the aircraft-snapshot magnitude
  rather than the airport one (138 MB held as Python objects), so it stages in
  a table and is promoted with one ``INSERT … SELECT``, exactly as
  ``aircraft_metadata_staging`` is.
* **``route_cache.source``.** A cached route now remembers *which* source
  answered, so a hit is attributed without asking again. Added with a plain
  ``ALTER TABLE`` — the column carries no ``CHECK`` and takes part in no index,
  which is what keeps this one cheap and reversible with ``DROP COLUMN``.
* **``sightings.route_source`` admits ``vrs``.**

Why ``sightings`` is rebuilt
----------------------------

``ck_sightings_route_source`` reads ``route_source IN ('aerodatabox')``, and
SQLite cannot alter a ``CHECK`` in place — the lesson revision 0014 spelled out
for ``route_cache``. The same remedy is the only one available here, and it is
materially more expensive: ``sightings`` is the second-largest table in the
database (1.64M rows at the three-year Scenario A mark measured in slice 050)
and carries four indexes, all of which are rebuilt with it.

**Measured**, on a seeded database at revision 0014: 200,000 sightings (a 24 MB
file) upgrade in **1.02 s** and downgrade in **1.51 s** on a developer SSD, so
the three-year Scenario A database is on the order of ten seconds there and
correspondingly longer on a Pi's SD card. A one-time cost, paid once, at the
upgrade that introduces the second route source. (That figure was taken with
the child tables *empty*, which is the mistake the next section is about; the
populated measurement is the one in
``tests/db/test_migration_0015_children.py``.)

The alternatives were to write a source the vocabulary forbids, to drop the
constraint entirely — the same rebuild for less safety — or to edit the schema
in place through ``PRAGMA writable_schema``, which is O(1) and is not a thing to
do to a user's primary history table unattended.

The copy is ``INSERT … SELECT`` over every column, in the order below, and the
new shape is spelled out here rather than imported from
:mod:`flightsite.db.models` for revision 0014's reason: a migration records
what an install ran, so a later slice adding a column must not retroactively
change what this one created. (Revision 0002 does import its predicates, which
is why a *fresh* database already carries the widened one by the time this
revision runs. The rebuild is then a rebuild of an empty table, and the end
state is identical either way.)

Foreign keys, and what this revision got wrong (issue #178)
-----------------------------------------------------------

This file originally claimed that "``PRAGMA foreign_keys`` is off during
migrations, so the drop-and-rename does not cascade". That was false, and it
took down a v0.6.0 upgrade. ``migrations/env.py`` builds its engine with
:func:`flightsite.db.engine.create_sqlite_engine`, whose connect listener sets
``PRAGMA foreign_keys=ON``; the app path migrates on the writer connection,
which has the same pragma. Under enforcement, ``DROP TABLE sightings`` is an
implicit ``DELETE`` of every row, each checked against the five ``NO ACTION``
children — two of which (``activity_events``,
``sighting_track_checkpoints``) have no index on ``sighting_id``. On a
16,214-sighting install that was five minutes of full scans ending in
``FOREIGN KEY constraint failed``, with the site down until a rollback. The
"200,000 sightings in 1.02 s" measured above was taken on a seed whose child
tables were empty, which is why neither the cost nor the failure showed.

So the rebuild now runs inside the ``rebuilding`` context manager of
:mod:`flightsite.db.migrations.rebuild`: enforcement is suspended (verified by
reading the pragma back, because the
pragma is silently a no-op inside a transaction), the references are checked
with ``PRAGMA foreign_key_check`` after the rename, and enforcement is restored
in a ``finally``.

**Measured again, this time with children**: at the failing install's scale —
16,214 sightings and 163,761 rows across the five children, an 11 MB file — the
upgrade takes **0.10 s** and the downgrade **0.11 s** on a developer SSD, next
to the five minutes and a failure the shipped version produced.
``tests/db/test_migration_0015_children.py`` holds that measurement as a bound.

Resumability
------------

Alembic treats SQLite as non-transactional DDL, so the statements before a
failure stay committed while ``alembic_version`` still says 0014 — the exact
half-migrated state the failed release left behind, and the state a restarting
container re-enters this function with. Every step below is therefore
conditional on its own prior completion: the directory tables, the
``route_cache.source`` column, the four indexes and the staging table.

Revision ID: 0015
Revises: 0014
Created: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from flightsite.db.migrations import rebuild

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIGHTINGS = "sightings"
_SIGHTINGS_REBUILD = "sightings_rebuild"

#: The vocabulary this revision installs on ``sightings.route_source``, and the
#: one it restores on the way down. Spelled out rather than imported — see the
#: module docstring.
_ROUTE_SOURCE_CHECK = "route_source IN ('aerodatabox', 'vrs')"
_PREVIOUS_ROUTE_SOURCE_CHECK = "route_source IN ('aerodatabox')"

#: The other three predicates ``sightings`` carries, unchanged by this
#: revision and repeated here because the rebuild has to recreate them.
_CLOSURE_REASON_CHECK = "closure_reason IN ('gap_timeout', 'shutdown_recovery', 'data_reset')"
_INFERRED_PHASE_CHECK = "inferred_phase IN ('arriving', 'departing')"
_ALERT_SEVERITY_CHECK = "max_alert_severity IN ('info', 'interesting', 'high', 'critical')"

_ZERO = sa.text("0")

#: Every ``sightings`` column, in declaration order. The copy names them
#: explicitly rather than using ``SELECT *`` so a mismatch fails loudly here
#: instead of silently shifting values one column to the left.
_SIGHTINGS_COLUMNS: tuple[str, ...] = (
    "id",
    "aircraft_id",
    "started_ms",
    "ended_ms",
    "duration_ms",
    "closure_reason",
    "callsign_first",
    "callsign_last",
    "squawk_last",
    "had_emergency",
    "origin_ident",
    "destination_ident",
    "route_source",
    "inferred_airport_ident",
    "inferred_phase",
    "any_position",
    "mlat_used",
    "ground_seen",
    "msg_count",
    "pos_count",
    "rssi_peak_db",
    "rssi_avg_db",
    "rssi_min_db",
    "pos_time_pct",
    "closest_approach_nm",
    "max_range_nm",
    "lowest_alt_ft",
    "highest_alt_ft",
    "max_alert_severity",
)

#: ``sightings``' indexes, recreated after the rebuild. ``ix_sightings_open``
#: is partial and ``ix_sightings_max_range`` composite; both are recreated with
#: the definitions revisions 0002 and 0013 gave them.
_SIGHTINGS_INDEXES: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("ix_sightings_aircraft", ("aircraft_id", "started_ms"), None),
    ("ix_sightings_started", ("started_ms",), None),
    ("ix_sightings_open", ("ended_ms",), "ended_ms IS NULL"),
    ("ix_sightings_max_range", ("max_range_nm", "id"), None),
)


def _create_sightings(name: str, *, route_source_check: str) -> None:
    """Create one shape of ``sightings`` under ``name``."""
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("aircraft_id", sa.Integer(), nullable=False),
        sa.Column("started_ms", sa.Integer(), nullable=False),
        sa.Column("ended_ms", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("closure_reason", sa.Text(), nullable=True),
        sa.Column("callsign_first", sa.Text(), nullable=True),
        sa.Column("callsign_last", sa.Text(), nullable=True),
        sa.Column("squawk_last", sa.Text(), nullable=True),
        sa.Column("had_emergency", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("origin_ident", sa.Text(), nullable=True),
        sa.Column("destination_ident", sa.Text(), nullable=True),
        sa.Column("route_source", sa.Text(), nullable=True),
        sa.Column("inferred_airport_ident", sa.Text(), nullable=True),
        sa.Column("inferred_phase", sa.Text(), nullable=True),
        sa.Column("any_position", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("mlat_used", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("ground_seen", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("msg_count", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("pos_count", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("rssi_peak_db", sa.REAL(), nullable=True),
        sa.Column("rssi_avg_db", sa.REAL(), nullable=True),
        sa.Column("rssi_min_db", sa.REAL(), nullable=True),
        sa.Column("pos_time_pct", sa.REAL(), nullable=True),
        sa.Column("closest_approach_nm", sa.REAL(), nullable=True),
        sa.Column("max_range_nm", sa.REAL(), nullable=True),
        sa.Column("lowest_alt_ft", sa.Integer(), nullable=True),
        sa.Column("highest_alt_ft", sa.Integer(), nullable=True),
        sa.Column("max_alert_severity", sa.Text(), nullable=True),
        sa.CheckConstraint(_CLOSURE_REASON_CHECK, name="ck_sightings_closure_reason"),
        sa.CheckConstraint(route_source_check, name="ck_sightings_route_source"),
        sa.CheckConstraint(_INFERRED_PHASE_CHECK, name="ck_sightings_inferred_phase"),
        sa.CheckConstraint(_ALERT_SEVERITY_CHECK, name="ck_sightings_max_alert_severity"),
        sa.ForeignKeyConstraint(["aircraft_id"], ["aircraft.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def _rebuild_sightings(*, route_source_check: str) -> None:
    """Rebuild ``sightings`` into the requested shape, keeping every row.

    Foreign keys are suspended for the duration and checked afterwards — see
    the module docstring and issue #178 — and every step is conditional, so a
    re-run over a half-finished attempt continues rather than failing.
    """
    bind = op.get_bind()
    with rebuild.rebuilding(bind, _SIGHTINGS):
        for name, _columns, _where in _SIGHTINGS_INDEXES:
            if rebuild.has_index(bind, name):
                op.drop_index(name, table_name=_SIGHTINGS)
        _create_sightings(_SIGHTINGS_REBUILD, route_source_check=route_source_check)
        carried = ", ".join(_SIGHTINGS_COLUMNS)
        op.execute(
            f"INSERT INTO {_SIGHTINGS_REBUILD} ({carried}) SELECT {carried} FROM {_SIGHTINGS}"
        )
        rebuild.assert_copied(bind, _SIGHTINGS, _SIGHTINGS_REBUILD)
        op.drop_table(_SIGHTINGS)
        op.rename_table(_SIGHTINGS_REBUILD, _SIGHTINGS)
        for name, columns, where in _SIGHTINGS_INDEXES:
            kwargs: dict[str, Any] = {} if where is None else {"sqlite_where": sa.text(where)}
            op.create_index(name, _SIGHTINGS, list(columns), **kwargs)


def _create_directory_tables() -> None:
    """``route_directory`` and its staging table (``docs/DATA_MODEL.md`` §7.1)."""
    bind = op.get_bind()
    if not rebuild.has_table(bind, "route_directory"):
        op.create_table(
            "route_directory",
            sa.Column("callsign", sa.Text(), nullable=False),
            sa.Column("airline_code", sa.Text(), nullable=True),
            sa.Column("airport_codes", sa.Text(), nullable=False),
            sa.Column("dataset_version", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("callsign"),
            sqlite_with_rowid=False,
        )
    if not rebuild.has_table(bind, "route_directory_staging"):
        op.create_table(
            "route_directory_staging",
            sa.Column("callsign", sa.Text(), nullable=False),
            sa.Column("airline_code", sa.Text(), nullable=True),
            sa.Column("airport_codes", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("callsign"),
            sqlite_with_rowid=False,
        )


def _reconcile_interrupted_attempt() -> None:
    """Put the database back on one of this revision's two footings.

    A previous attempt can have been interrupted anywhere. The only step that
    leaves an object behind is the staging table, and what it means depends on
    whether ``sightings`` is still there — see
    :func:`flightsite.db.migrations.rebuild.reconcile_staging_table`. Doing
    this first means everything after it sees a database with a ``sightings``
    table in one shape or the other, and nothing else out of place.
    """
    rebuild.reconcile_staging_table(op.get_bind(), _SIGHTINGS, _SIGHTINGS_REBUILD)


def upgrade() -> None:
    _reconcile_interrupted_attempt()
    _create_directory_tables()
    if not rebuild.has_column(op.get_bind(), "route_cache", "source"):
        op.add_column("route_cache", sa.Column("source", sa.Text(), nullable=True))
    _rebuild_sightings(route_source_check=_ROUTE_SOURCE_CHECK)


def downgrade() -> None:
    _reconcile_interrupted_attempt()
    # A `vrs` route cannot exist under the older CHECK. The sighting itself is
    # history and is never deleted, but the route on it came from a source the
    # build being downgraded to cannot name — and SPEC §22 wants a provenance
    # for every value that is not the decoder's — so the whole route is cleared
    # rather than left unattributed. The next observation of that flight
    # re-enriches it from AeroDataBox.
    op.execute(
        "UPDATE sightings SET origin_ident = NULL, destination_ident = NULL, "
        "route_source = NULL WHERE route_source = 'vrs'"
    )
    _rebuild_sightings(route_source_check=_PREVIOUS_ROUTE_SOURCE_CHECK)
    # Same reasoning one table over, and the same remedy revision 0014 applied
    # to a `restricted` row: a cache entry the older build would misattribute
    # to AeroDataBox costs one lookup to replace, so it goes.
    bind = op.get_bind()
    if rebuild.has_column(bind, "route_cache", "source"):
        op.execute("DELETE FROM route_cache WHERE source = 'vrs'")
        op.drop_column("route_cache", "source")
    for table in ("route_directory_staging", "route_directory"):
        if rebuild.has_table(bind, table):
            op.drop_table(table)
