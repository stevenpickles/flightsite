"""Aircraft and sightings: the identity and observation-period tables.

Creates ``aircraft`` (``docs/DATA_MODEL.md`` §2.2) and ``sightings`` (§2.3) —
the persistent half of the aircraft / sighting / flight-context split of
ADR-0004. Track storage, reception statistics and sighting events are slice
052's tables and are not created here; the reception-statistic *columns* on
``sightings`` are, so that row's shape does not change again when 052 lands.

Revision ID: 0002
Revises: 0001
Created: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from flightsite.db.models import (
    ALERT_SEVERITY_CHECK,
    CLOSURE_REASON_CHECK,
    INFERRED_PHASE_CHECK,
    ROUTE_SOURCE_CHECK,
)

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ZERO = sa.text("0")


def upgrade() -> None:
    op.create_table(
        "aircraft",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("icao24", sa.Text(), nullable=False),
        sa.Column("first_seen_ms", sa.Integer(), nullable=False),
        sa.Column("last_seen_ms", sa.Integer(), nullable=False),
        sa.Column("sighting_count", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("total_observed_ms", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("closest_approach_nm", sa.REAL(), nullable=True),
        sa.Column("closest_approach_ms", sa.Integer(), nullable=True),
        sa.Column("max_range_nm", sa.REAL(), nullable=True),
        sa.Column("max_range_ms", sa.Integer(), nullable=True),
        sa.Column("lowest_alt_ft", sa.Integer(), nullable=True),
        sa.Column("lowest_alt_ms", sa.Integer(), nullable=True),
        sa.Column("highest_alt_ft", sa.Integer(), nullable=True),
        sa.Column("highest_alt_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("icao24"),
    )
    op.create_index("ix_aircraft_first_seen", "aircraft", ["first_seen_ms"])
    op.create_index("ix_aircraft_last_seen", "aircraft", ["last_seen_ms"])
    op.create_index("ix_aircraft_sightings", "aircraft", ["sighting_count"])

    op.create_table(
        "sightings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("aircraft_id", sa.Integer(), nullable=False),
        sa.Column("started_ms", sa.Integer(), nullable=False),
        sa.Column("ended_ms", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("closure_reason", sa.Text(), nullable=True),
        # Flight context: temporary properties of the flight, never of the
        # airframe (SPEC §17).
        sa.Column("callsign_first", sa.Text(), nullable=True),
        sa.Column("callsign_last", sa.Text(), nullable=True),
        sa.Column("squawk_last", sa.Text(), nullable=True),
        sa.Column("had_emergency", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("origin_ident", sa.Text(), nullable=True),
        sa.Column("destination_ident", sa.Text(), nullable=True),
        sa.Column("route_source", sa.Text(), nullable=True),
        sa.Column("inferred_airport_ident", sa.Text(), nullable=True),
        sa.Column("inferred_phase", sa.Text(), nullable=True),
        # Position character.
        sa.Column("any_position", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("mlat_used", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("ground_seen", sa.Integer(), nullable=False, server_default=_ZERO),
        # Reception statistics (SPEC §51): columns now, values in slice 052.
        sa.Column("msg_count", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("pos_count", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("rssi_peak_db", sa.REAL(), nullable=True),
        sa.Column("rssi_avg_db", sa.REAL(), nullable=True),
        sa.Column("rssi_min_db", sa.REAL(), nullable=True),
        sa.Column("pos_time_pct", sa.REAL(), nullable=True),
        # Per-sighting extremes (SPEC §57), feeding the lifetime records.
        sa.Column("closest_approach_nm", sa.REAL(), nullable=True),
        sa.Column("max_range_nm", sa.REAL(), nullable=True),
        sa.Column("lowest_alt_ft", sa.Integer(), nullable=True),
        sa.Column("highest_alt_ft", sa.Integer(), nullable=True),
        sa.Column("max_alert_severity", sa.Text(), nullable=True),
        sa.CheckConstraint(CLOSURE_REASON_CHECK, name="ck_sightings_closure_reason"),
        sa.CheckConstraint(ROUTE_SOURCE_CHECK, name="ck_sightings_route_source"),
        sa.CheckConstraint(INFERRED_PHASE_CHECK, name="ck_sightings_inferred_phase"),
        sa.CheckConstraint(ALERT_SEVERITY_CHECK, name="ck_sightings_max_alert_severity"),
        sa.ForeignKeyConstraint(["aircraft_id"], ["aircraft.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sightings_aircraft", "sightings", ["aircraft_id", "started_ms"])
    op.create_index("ix_sightings_started", "sightings", ["started_ms"])
    # Partial index over the open set only: it stays tiny however long the
    # history grows, which is what keeps startup recovery and the
    # "no new sighting before close" check cheap.
    op.create_index(
        "ix_sightings_open",
        "sightings",
        ["ended_ms"],
        sqlite_where=sa.text("ended_ms IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sightings_open", table_name="sightings")
    op.drop_index("ix_sightings_started", table_name="sightings")
    op.drop_index("ix_sightings_aircraft", table_name="sightings")
    op.drop_table("sightings")
    op.drop_index("ix_aircraft_sightings", table_name="aircraft")
    op.drop_index("ix_aircraft_last_seen", table_name="aircraft")
    op.drop_index("ix_aircraft_first_seen", table_name="aircraft")
    op.drop_table("aircraft")
