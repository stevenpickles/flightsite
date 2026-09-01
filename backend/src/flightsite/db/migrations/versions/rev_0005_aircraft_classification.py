"""Computed aircraft classification with per-claim provenance.

Creates ``aircraft_classification`` (``docs/DATA_MODEL.md`` §3.4), the one
table slice 024 owns. The curated ``operators`` / ``operator_groups`` tables
this slice fills already exist: §3.5 put them in revision 0004 because
``aircraft_metadata_resolved.operator_group_id`` references them and ADR-0001
runs with ``foreign_keys=ON``. So this revision adds a table and touches
nothing that has data in it, which is why it needs no backfill and why its
downgrade is a plain drop.

``WITHOUT ROWID`` with ``icao24`` as the primary key, matching the resolved
table beside it: every read is by address, and the two are rebuilt together in
one transaction.

Three of the four indexes are **partial**. ``military``, ``government`` and
``law_enforcement`` are overwhelmingly ``0`` — a few thousand military
airframes in a database of half a million — so an index over the whole column
would be mostly a list of rows nobody will ever ask for. ``WHERE flag = 1``
indexes the answer the query actually wants and costs a fraction of the space
on a Pi's SD card. ``mission_category`` gets an ordinary index: its values are
spread across twelve categories, none of them rare enough for a partial index
to help.

Revision ID: 0005
Revises: 0004
Created: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from flightsite.db.models import MISSION_CATEGORY_CHECK

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aircraft_classification",
        sa.Column("icao24", sa.Text(), nullable=False),
        sa.Column("military", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("military_src", sa.Text(), nullable=True),
        sa.Column("military_conf", sa.REAL(), nullable=True),
        sa.Column("government", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("government_src", sa.Text(), nullable=True),
        sa.Column("government_conf", sa.REAL(), nullable=True),
        sa.Column("law_enforcement", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("law_enforcement_src", sa.Text(), nullable=True),
        sa.Column("law_enforcement_conf", sa.REAL(), nullable=True),
        sa.Column(
            "mission_category",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column("mission_src", sa.Text(), nullable=True),
        sa.Column("mission_conf", sa.REAL(), nullable=True),
        sa.Column(
            "icon_category",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column("updated_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(MISSION_CATEGORY_CHECK, name="ck_aircraft_classification_mission"),
        sa.PrimaryKeyConstraint("icao24"),
        sqlite_with_rowid=False,
    )
    op.create_index(
        "ix_class_mil",
        "aircraft_classification",
        ["military"],
        sqlite_where=sa.text("military = 1"),
    )
    op.create_index(
        "ix_class_gov",
        "aircraft_classification",
        ["government"],
        sqlite_where=sa.text("government = 1"),
    )
    op.create_index(
        "ix_class_law",
        "aircraft_classification",
        ["law_enforcement"],
        sqlite_where=sa.text("law_enforcement = 1"),
    )
    op.create_index("ix_class_mission", "aircraft_classification", ["mission_category"])


def downgrade() -> None:
    op.drop_index("ix_class_mission", table_name="aircraft_classification")
    op.drop_index("ix_class_law", table_name="aircraft_classification")
    op.drop_index("ix_class_gov", table_name="aircraft_classification")
    op.drop_index("ix_class_mil", table_name="aircraft_classification")
    op.drop_table("aircraft_classification")
