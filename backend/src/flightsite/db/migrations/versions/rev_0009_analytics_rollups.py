"""The analytics rollup tables.

Creates the four tables ``docs/DATA_MODEL.md`` §6.5 gives slice 031 —
``daily_stats``, ``daily_type_stats``, ``daily_operator_stats`` and
``type_stats`` — and alters nothing. Nothing existing referenced them, so the
downgrade is a plain drop, and an install that downgrades loses only a
derived view of ``sightings`` that the backfill job rebuilds from ground truth
(:mod:`flightsite.analytics.backfill`).

Every row here is *derived*. That is the whole shape of this migration and the
reason it carries no foreign keys, no ``CHECK`` constraints and no defaults
that a writer relies on: ``sightings`` and ``aircraft`` remain the only truth,
these tables are a materialization of one fold over them, and any row can be
discarded and recomputed. A foreign key from ``daily_operator_stats`` to
``operator_groups`` was considered and rejected for the same reason the
receiver-metric tables carry none: the writer re-derives the whole day inside
one transaction from a join that already resolved the group, so the constraint
could only fail a write that is correct by construction, and it would make a
future operator-group rebuild (slice 024's own concern) unable to touch a
group any historical day references.

All four are ``WITHOUT ROWID``. Every access is a prefix of the declared key:
a point lookup on a day, an ordered range over a contiguous run of days (which
is what every ``docs/API.md`` §3.7 preset resolves to), or a point lookup on a
type designator. A rowid table would add an indirection plus a second copy of
the key for nothing, and the day-keyed tables would lose the clustering that
makes a 30-day window a contiguous b-tree read.

No secondary indexes, because §6.5 declares none and none is needed. The one
non-key query in the package — "the rarest types" — sorts ``type_stats`` by
``unique_aircraft``, and that table has one row per type designator ever
resolved (hundreds), so an index on it would cost more to maintain than the
sort it saves.

``daily_stats.day``, ``daily_type_stats.day`` and ``daily_operator_stats.day``
hold a receiver-*local* ``YYYY-MM-DD`` (``docs/DATA_MODEL.md`` §10) while
``type_stats``' two moments are UTC epoch milliseconds; the column types say
so — ``TEXT`` for the local calendar, ``INTEGER`` ending in ``_ms`` for
instants.

Revision ID: 0009
Revises: 0008
Created: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_stats",
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("unique_aircraft", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("new_aircraft", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sightings", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("interesting", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("military", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("government", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("law_enforcement", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_range_nm", sa.REAL(), nullable=True),
        sa.Column("busiest_hour", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("day"),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "daily_type_stats",
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("type_code", sa.Text(), nullable=False),
        sa.Column("sightings", sa.Integer(), nullable=False),
        sa.Column("unique_aircraft", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("day", "type_code"),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "daily_operator_stats",
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("operator_group_id", sa.Integer(), nullable=False),
        sa.Column("sightings", sa.Integer(), nullable=False),
        sa.Column("unique_aircraft", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("day", "operator_group_id"),
        sqlite_with_rowid=False,
    )
    op.create_table(
        "type_stats",
        sa.Column("type_code", sa.Text(), nullable=False),
        sa.Column("unique_aircraft", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_sightings", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_seen_ms", sa.Integer(), nullable=False),
        sa.Column("last_seen_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("type_code"),
        sqlite_with_rowid=False,
    )


def downgrade() -> None:
    op.drop_table("type_stats")
    op.drop_table("daily_operator_stats")
    op.drop_table("daily_type_stats")
    op.drop_table("daily_stats")
