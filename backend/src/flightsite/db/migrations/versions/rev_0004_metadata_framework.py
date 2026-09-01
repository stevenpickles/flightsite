"""Aircraft metadata: per-source rows, resolved precedence, operators.

Creates the metadata group of ``docs/DATA_MODEL.md`` §3 that slice 021 owns
(§12): ``metadata_sources`` (§3.1), ``aircraft_metadata`` (§3.2) and its
staging counterpart, ``aircraft_metadata_resolved`` (§3.3), and the empty
``operator_groups`` / ``operators`` tables (§3.5).

Creation order is dictated by ``foreign_keys=ON`` (ADR-0001): a referenced
table must exist when the referencing one is created. So ``metadata_sources``
precedes ``aircraft_metadata``, and ``operator_groups`` precedes
``aircraft_metadata_resolved``. That FK is exactly why §3.5 places the operator
tables in *this* migration even though slice 024 supplies their content —
splitting them out would leave the first metadata migration unable to run.

``aircraft_metadata_staging`` carries no foreign key and no index: it is the
scratch landing area an import streams into before promotion, cleared on both
success and failure, so referential checks and index maintenance on every
staged row would be paid for nothing.

Revision ID: 0004
Revises: 0003
Created: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from flightsite.db.models import METADATA_SOURCE_STATUS_CHECK

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _metadata_columns() -> list[sa.Column[Any]]:
    """Column set shared by ``aircraft_metadata`` and its staging table.

    Rebuilt per call: a :class:`sqlalchemy.Column` object belongs to exactly
    one table, so the two tables cannot share instances.
    """
    return [
        sa.Column("icao24", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("registration", sa.Text(), nullable=True),
        sa.Column("type_code", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("manufacture_year", sa.Integer(), nullable=True),
        sa.Column("operator_name", sa.Text(), nullable=True),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("military_flag", sa.Integer(), nullable=True),
        sa.Column("flags_json", sa.Text(), nullable=True),
        sa.Column("updated_ms", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "metadata_sources",
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("last_attempt_ms", sa.Integer(), nullable=True),
        sa.Column("last_success_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'never_run'")),
        sa.Column("dataset_version", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(METADATA_SOURCE_STATUS_CHECK, name="ck_metadata_sources_status"),
        sa.PrimaryKeyConstraint("source"),
        sqlite_with_rowid=False,
    )

    # Curated grouping tables, created empty (§3.5). They come before the
    # resolved table because that table's operator_group_id references them.
    op.create_table(
        "operator_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "operators",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["operator_groups.id"]),
        sa.PrimaryKeyConstraint("name"),
        sqlite_with_rowid=False,
    )

    op.create_table(
        "aircraft_metadata",
        *_metadata_columns(),
        sa.ForeignKeyConstraint(["source"], ["metadata_sources.source"]),
        sa.PrimaryKeyConstraint("icao24", "source"),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "aircraft_metadata_staging",
        *_metadata_columns(),
        sa.PrimaryKeyConstraint("icao24", "source"),
        sqlite_with_rowid=False,
    )

    op.create_table(
        "aircraft_metadata_resolved",
        sa.Column("icao24", sa.Text(), nullable=False),
        sa.Column("registration", sa.Text(), nullable=True),
        sa.Column("registration_src", sa.Text(), nullable=True),
        sa.Column("type_code", sa.Text(), nullable=True),
        sa.Column("type_code_src", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("model_src", sa.Text(), nullable=True),
        sa.Column("manufacture_year", sa.Integer(), nullable=True),
        sa.Column("year_src", sa.Text(), nullable=True),
        sa.Column("operator_name", sa.Text(), nullable=True),
        sa.Column("operator_src", sa.Text(), nullable=True),
        sa.Column("operator_group_id", sa.Integer(), nullable=True),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("owner_src", sa.Text(), nullable=True),
        sa.Column("updated_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["operator_group_id"], ["operator_groups.id"]),
        sa.PrimaryKeyConstraint("icao24"),
        sqlite_with_rowid=False,
    )
    op.create_index("ix_amr_registration", "aircraft_metadata_resolved", ["registration"])
    op.create_index("ix_amr_type", "aircraft_metadata_resolved", ["type_code"])
    op.create_index("ix_amr_opgroup", "aircraft_metadata_resolved", ["operator_group_id"])


def downgrade() -> None:
    op.drop_index("ix_amr_opgroup", table_name="aircraft_metadata_resolved")
    op.drop_index("ix_amr_type", table_name="aircraft_metadata_resolved")
    op.drop_index("ix_amr_registration", table_name="aircraft_metadata_resolved")
    op.drop_table("aircraft_metadata_resolved")
    op.drop_table("aircraft_metadata_staging")
    op.drop_table("aircraft_metadata")
    op.drop_table("operators")
    op.drop_table("operator_groups")
    op.drop_table("metadata_sources")
