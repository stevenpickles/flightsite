"""The receiver-metric tables.

Creates the five tables ``docs/DATA_MODEL.md`` §6.1 to §6.4 gives slice 033 —
``receiver_metrics_raw``, ``receiver_metrics_hourly``,
``receiver_metrics_daily``, ``range_by_bearing_daily`` and ``lifetime_stats``
— and alters nothing. Nothing existing referenced them, so the downgrade is a
plain drop.

The three-tier shape is ADR-0009's: a rolling high-resolution window that is
pruned, and hourly/daily summaries plus lifetime records that never are. The
schema is what encodes the difference. ``receiver_metrics_raw`` is the only
table here a maintenance pass ever deletes from; the other four have no
expiry, which is why none of them carries a retention column.

All five are ``WITHOUT ROWID``. Every one of them is accessed exclusively by
its declared key — a timestamp range on ``ts_ms``, a point lookup on an hour,
a day, a ``(day, sector)`` pair or a statistic name — so the clustered b-tree
*is* the access path and a rowid table would add an indirection plus a second
copy of the key for nothing. For the raw table it also means the prune deletes
a contiguous head of the b-tree rather than scattered leaves.

No secondary indexes, because ``docs/DATA_MODEL.md`` §6 declares none and none
is needed: every query these tables serve is a prefix of a primary key. And no
``CHECK`` on ``bearing_bucket`` either — §6.3 states the ``0..71`` range as a
comment on the column rather than as a constraint, and the only writer is
:func:`flightsite.receiver_metrics.model.bearing_bucket`, whose modulo makes
an out-of-range bucket unrepresentable.

``receiver_metrics_daily.day`` and ``range_by_bearing_daily.day`` hold a
receiver-*local* ``YYYY-MM-DD`` (``docs/DATA_MODEL.md`` §10) while everything
else here is UTC epoch milliseconds; the column types say so — ``TEXT`` for
the local calendar, ``INTEGER`` ending in ``_ms`` for instants.

Revision ID: 0008
Revises: 0007
Created: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _summary_columns() -> list[sa.Column[Any]]:
    """The summary column set §6.2 shares between the hourly and daily tables.

    Built fresh per call: a :class:`sqlalchemy.Column` binds to the table it is
    given to, so one list cannot be handed to two ``create_table`` calls.
    """
    return [
        sa.Column("messages_total", sa.Integer(), nullable=True),
        sa.Column("positions_total", sa.Integer(), nullable=True),
        sa.Column("msgs_per_sec_avg", sa.REAL(), nullable=True),
        sa.Column("msgs_per_sec_max", sa.REAL(), nullable=True),
        sa.Column("pos_per_sec_avg", sa.REAL(), nullable=True),
        sa.Column("pos_per_sec_max", sa.REAL(), nullable=True),
        sa.Column("aircraft_avg", sa.REAL(), nullable=True),
        sa.Column("aircraft_max", sa.Integer(), nullable=True),
        sa.Column("max_range_nm", sa.REAL(), nullable=True),
        sa.Column("rssi_avg_db", sa.REAL(), nullable=True),
        sa.Column("rssi_peak_db", sa.REAL(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "receiver_metrics_raw",
        sa.Column("ts_ms", sa.Integer(), nullable=False),
        sa.Column("messages_per_sec", sa.REAL(), nullable=True),
        sa.Column("positions_per_sec", sa.REAL(), nullable=True),
        sa.Column("aircraft_visible", sa.Integer(), nullable=True),
        sa.Column("aircraft_with_pos", sa.Integer(), nullable=True),
        sa.Column("max_range_nm", sa.REAL(), nullable=True),
        sa.Column("rssi_avg_db", sa.REAL(), nullable=True),
        sa.Column("rssi_peak_db", sa.REAL(), nullable=True),
        sa.PrimaryKeyConstraint("ts_ms"),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "receiver_metrics_hourly",
        sa.Column("hour_start_ms", sa.Integer(), nullable=False),
        *_summary_columns(),
        sa.PrimaryKeyConstraint("hour_start_ms"),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "receiver_metrics_daily",
        sa.Column("day", sa.Text(), nullable=False),
        *_summary_columns(),
        sa.PrimaryKeyConstraint("day"),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "range_by_bearing_daily",
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("bearing_bucket", sa.Integer(), nullable=False),
        sa.Column("max_range_nm", sa.REAL(), nullable=False),
        sa.Column("at_ms", sa.Integer(), nullable=False),
        sa.Column("icao24", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("day", "bearing_bucket"),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "lifetime_stats",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value_num", sa.REAL(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("updated_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
        sqlite_with_rowid=False,
    )


def downgrade() -> None:
    op.drop_table("lifetime_stats")
    op.drop_table("range_by_bearing_daily")
    op.drop_table("receiver_metrics_daily")
    op.drop_table("receiver_metrics_hourly")
    op.drop_table("receiver_metrics_raw")
