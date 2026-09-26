"""Feeder status history: episodes and samples.

Slice 077 (issue #215). The Feeders page shows, for every network the
receiver feeds, a gap timeline and a few connection statistics over 24 hours,
7 days and 30 days. This revision adds the two tables behind that
(``docs/DATA_MODEL.md`` §6.6):

* **``feeder_episodes``** — one row per span of one committed state
  (``up``/``degraded``/``down``/``unknown``) per feeder, ``ended_ms`` ``NULL``
  while current. Kept 90 days.
* **``feeder_samples``** — one reading per feeder per minute: its state and a
  small JSON object of numeric chart series. Kept 14 days.

Both ``WITHOUT ROWID`` on their natural keys, with no secondary indexes and no
``CHECK``: every read is one feeder's time range, which is exactly the key
order, and the feeder service is the only writer. Feeder names are the
owner's configured slugs, deliberately not a foreign key to anything —
removing an entry from ``config.yaml`` leaves its history to age out.

Two ``CREATE TABLE``s and no data movement: milliseconds on any install,
whatever its history. Every step is conditional, because SQLite DDL is not
transactional (``docs/DEVELOPMENT.md``, "SQLite DDL is not transactional") and
a revision that failed halfway is re-run from the top.

Revision ID: 0017
Revises: 0016
Created: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from flightsite.db.migrations import rebuild

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EPISODES = "feeder_episodes"
_SAMPLES = "feeder_samples"


def upgrade() -> None:
    bind = op.get_bind()
    if not rebuild.has_table(bind, _EPISODES):
        op.create_table(
            _EPISODES,
            sa.Column("feeder", sa.Text(), nullable=False),
            sa.Column("started_ms", sa.Integer(), nullable=False),
            sa.Column("ended_ms", sa.Integer(), nullable=True),
            sa.Column("state", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("feeder", "started_ms"),
            sqlite_with_rowid=False,
        )
    if not rebuild.has_table(bind, _SAMPLES):
        op.create_table(
            _SAMPLES,
            sa.Column("feeder", sa.Text(), nullable=False),
            sa.Column("ts_ms", sa.Integer(), nullable=False),
            sa.Column("state", sa.Text(), nullable=False),
            sa.Column("metrics_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("feeder", "ts_ms"),
            sqlite_with_rowid=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (_SAMPLES, _EPISODES):
        if rebuild.has_table(bind, table):
            op.drop_table(table)
