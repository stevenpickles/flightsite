"""The route enrichment cache.

Creates ``route_cache`` (``docs/DATA_MODEL.md`` §7), the one table slice 026
owns. The sighting columns enrichment *writes* — ``origin_ident``,
``destination_ident``, ``route_source`` — already exist: revision 0002 created
them with the rest of ``sightings``, and their ``route_source`` ``CHECK``
already names ``aerodatabox``. So this revision adds a table and alters
nothing, which is why it needs no backfill and why its downgrade is a plain
drop.

``WITHOUT ROWID`` with the text ``cache_key`` as the primary key: every access
is a point lookup by that key, so the clustered b-tree is both smaller and one
indirection cheaper than a rowid table with a unique index over the same
column.

One index, on ``expires_ms``. It serves the only query that is not a point
lookup — deleting what has expired during maintenance — and nothing indexes
``status``, whose three values over a table of at most a few thousand rows
would be a scan either way.

Revision ID: 0006
Revises: 0005
Created: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from flightsite.db.models import ROUTE_CACHE_STATUS_CHECK

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "route_cache",
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("origin_ident", sa.Text(), nullable=True),
        sa.Column("destination_ident", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("fetched_ms", sa.Integer(), nullable=False),
        sa.Column("expires_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(ROUTE_CACHE_STATUS_CHECK, name="ck_route_cache_status"),
        sa.PrimaryKeyConstraint("cache_key"),
        sqlite_with_rowid=False,
    )
    op.create_index("ix_route_cache_expiry", "route_cache", ["expires_ms"])


def downgrade() -> None:
    op.drop_index("ix_route_cache_expiry", table_name="route_cache")
    op.drop_table("route_cache")
