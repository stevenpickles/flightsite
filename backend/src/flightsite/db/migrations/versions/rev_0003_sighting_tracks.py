"""Sighting track storage, packed tracks and sighting events.

Creates the three tables slice 052 owns (``docs/DATA_MODEL.md`` §2.4, §2.5):
``sighting_track_checkpoints`` (the crash-recovery record of an open sighting's
path), ``sighting_tracks`` (one packed row per closed sighting) and
``sighting_events`` (meaningful flight-context changes). The reception-statistic
*columns* on ``sightings`` already exist from revision 0002 — this slice fills
them, so no column is added here.

All three hang off ``sightings(id)``, so this revision must sit on 0002.

Revision ID: 0003
Revises: 0002
Created: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from flightsite.db.models import SIGHTING_EVENT_TYPE_CHECK

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Row per point, integer enum codes, WITHOUT ROWID: this is the highest
    # volume table in the schema while sightings are open, and clustering a
    # sighting's points under (sighting_id, seq) is both how they are written
    # and the only way they are ever read (ADR-0005).
    op.create_table(
        "sighting_track_checkpoints",
        sa.Column("sighting_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ts_ms", sa.Integer(), nullable=False),
        sa.Column("lat", sa.REAL(), nullable=False),
        sa.Column("lon", sa.REAL(), nullable=False),
        sa.Column("alt_ft", sa.Integer(), nullable=True),
        sa.Column("gs_kt", sa.REAL(), nullable=True),
        sa.Column("track_deg", sa.REAL(), nullable=True),
        # Integer code, not TEXT: docs/DATA_MODEL.md §Conventions puts integer
        # enums on the hot high-volume tables. 0=adsb 1=mlat 2=none 3=other.
        sa.Column("pos_source", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["sighting_id"], ["sightings.id"]),
        sa.PrimaryKeyConstraint("sighting_id", "seq"),
        sqlite_with_rowid=False,
    )

    op.create_table(
        "sighting_tracks",
        sa.Column("sighting_id", sa.Integer(), nullable=False),
        sa.Column("encoding_version", sa.Integer(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        # Absolute base for the per-point time deltas inside the blob.
        sa.Column("started_ms", sa.Integer(), nullable=False),
        sa.Column("points_blob", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["sighting_id"], ["sightings.id"]),
        sa.PrimaryKeyConstraint("sighting_id"),
        sqlite_with_rowid=False,
    )

    op.create_table(
        "sighting_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sighting_id", sa.Integer(), nullable=False),
        sa.Column("ts_ms", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.CheckConstraint(SIGHTING_EVENT_TYPE_CHECK, name="ck_sighting_events_type"),
        sa.ForeignKeyConstraint(["sighting_id"], ["sightings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sevents_sighting", "sighting_events", ["sighting_id", "ts_ms"])


def downgrade() -> None:
    op.drop_index("ix_sevents_sighting", table_name="sighting_events")
    op.drop_table("sighting_events")
    op.drop_table("sighting_tracks")
    op.drop_table("sighting_track_checkpoints")
