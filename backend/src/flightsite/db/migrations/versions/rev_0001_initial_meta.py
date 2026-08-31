"""Initial schema: the meta key/value table.

Creates the ``meta`` table from ``docs/DATA_MODEL.md`` §2.1 — the application's
key/value state, holding T0 (``t0_ms``) among other app-level keys. The domain
tables arrive with their own slices (§12 landing map).

Revision ID: 0001
Revises:
Created: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meta",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
        # A few rows always fetched by their text key: the clustered b-tree is
        # smaller and one lookup cheaper than rowid indirection.
        sqlite_with_rowid=False,
    )


def downgrade() -> None:
    op.drop_table("meta")
