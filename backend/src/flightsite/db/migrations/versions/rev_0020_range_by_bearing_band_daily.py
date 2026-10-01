"""Per-day maximum range per bearing sector and altitude band.

Slice 087 (issue #230) asks how far the receiver hears in every direction *at
each altitude*, because a single range-by-bearing ring cannot tell an
obstruction from an empty sky: a sector that only ever hears aircraft at
8,000 ft reaches less far than one that hears airliners at cruise, and both
look the same on ``range_by_bearing_daily`` (§6.3). This revision adds the
table behind the Receiver page's coverage chart (``docs/DATA_MODEL.md``
§6.3.1):

* **``range_by_bearing_band_daily``** — one row per receiver-local day, 5°
  bearing sector and altitude band (``0`` below 10,000 ft, ``1`` 10,000 to
  25,000 ft, ``2`` above 25,000 ft, by barometric altitude), holding the
  furthest detection, the moment and airframe that set it, and how many
  receiver samples saw anything in that cell that day. Kept indefinitely,
  like ``range_by_bearing_daily``: at most 72 x 3 rows a day.

The shape copies ``range_by_bearing_daily`` on purpose — ``WITHOUT ROWID`` on
the natural key, no secondary index (every read is a day range, a prefix of
the key), no foreign key on ``icao24`` (the row must outlive any aircraft
cleanup) and no ``CHECK`` on the sector or band, whose only writer is
:mod:`flightsite.receiver_metrics.coverage` where an out-of-range value is
unrepresentable.

One ``CREATE TABLE`` and no data movement: milliseconds on any install,
whatever its history. There is nothing to backfill — the table records
altitudes that ``range_by_bearing_daily`` never kept, so history starts on
upgrade, which the Receiver page says. Every step is conditional, because
SQLite DDL is not transactional (``docs/DEVELOPMENT.md``, "SQLite DDL is not
transactional") and a revision that failed halfway is re-run from the top.

Revision ID: 0020
Revises: 0019
Created: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from flightsite.db.migrations import rebuild

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "range_by_bearing_band_daily"


def upgrade() -> None:
    if not rebuild.has_table(op.get_bind(), _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("day", sa.Text(), nullable=False),
            sa.Column("bearing_bucket", sa.Integer(), nullable=False),
            sa.Column("altitude_band", sa.Integer(), nullable=False),
            sa.Column("max_range_nm", sa.REAL(), nullable=False),
            sa.Column("at_ms", sa.Integer(), nullable=False),
            sa.Column("icao24", sa.Text(), nullable=True),
            sa.Column("sample_count", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("day", "bearing_bucket", "altitude_band"),
            sqlite_with_rowid=False,
        )


def downgrade() -> None:
    if rebuild.has_table(op.get_bind(), _TABLE):
        op.drop_table(_TABLE)
