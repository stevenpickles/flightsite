"""The activity feed and the milestone ledger.

Creates the two tables ``docs/DATA_MODEL.md`` §5 gives slice 035 —
``activity_events`` and ``milestones`` — and alters nothing. Nothing existing
referenced them, so the downgrade is a plain drop.

Unlike slice 031's rollups, these rows are **not** derived: an activity event
records that something was noticed at a moment, and a milestone records that
something happened for the first time. Neither can be recomputed from
``sightings`` after the fact without also reconstructing what the receiver knew
at the time, which is why both tables carry real foreign keys to ``aircraft``
and ``sightings`` and why the downgrade genuinely loses history rather than a
cache of it.

Two columns are the whole idempotency design, and both are constraints rather
than conventions:

* ``activity_events.dedupe_key`` is ``UNIQUE``. Every producer derives it from
  stored state — ``first_ever_aircraft:{icao}``, ``range_record:{at_ms}`` —
  so a restart, a catch-up scan or a replayed event recomputes the same string
  and its insert is a no-op. The roadmap's "no duplicates on restart/replay"
  criterion is therefore enforced by SQLite, not by the producer remembering.
  It is nullable because SQLite treats every ``NULL`` as distinct, which keeps
  the column usable by a future genuinely repeatable event; slice 035 fills it
  on every row it writes.
* ``milestones.key`` is the primary key, which makes fire-once free.

``activity_events.type`` deliberately carries **no** ``CHECK``. §5 names the
values in a comment and lists more than this slice emits — alerts and
emergency squawks are phase 6's, ``maintenance_issue`` and ``data_reset`` are
later — and widening a SQLite ``CHECK`` means rebuilding the table. The
vocabulary lives in :class:`flightsite.activity.model.ActivityEventType`
instead. ``severity`` does carry one: that ladder is fixed (``docs/API.md``
§2.8) and shared with the alert tables.

``ix_activity_ts`` is declared **descending** because newest-first is the
feed's only ordering, both for ``GET /api/v1/activity`` and for the panel on
the Live Map. ``ix_activity_type_ts`` covers §3.9's ``type`` filter combined
with the same chronology.

``milestones`` is ``WITHOUT ROWID``: it is reached only by its text key, it
holds tens of rows, and the key is the b-tree. ``activity_events`` is a plain
rowid table — it has an autoincrement surrogate key, two secondary indexes and
a unique index, none of which a ``WITHOUT ROWID`` layout would help.

Revision ID: 0010
Revises: 0009
Created: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from flightsite.db.models import ACTIVITY_SEVERITY_CHECK

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ts_ms", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default=sa.text("'info'")),
        sa.Column("aircraft_id", sa.Integer(), nullable=True),
        sa.Column("sighting_id", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.CheckConstraint(ACTIVITY_SEVERITY_CHECK, name="ck_activity_events_severity"),
        sa.ForeignKeyConstraint(["aircraft_id"], ["aircraft.id"]),
        sa.ForeignKeyConstraint(["sighting_id"], ["sightings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_activity_ts", "activity_events", [sa.text("ts_ms DESC")])
    op.create_index("ix_activity_type_ts", "activity_events", ["type", "ts_ms"])
    op.create_table(
        "milestones",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("achieved_ms", sa.Integer(), nullable=False),
        sa.Column("aircraft_id", sa.Integer(), nullable=True),
        sa.Column("value_num", sa.REAL(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["aircraft_id"], ["aircraft.id"]),
        sa.PrimaryKeyConstraint("key"),
        sqlite_with_rowid=False,
    )


def downgrade() -> None:
    op.drop_table("milestones")
    op.drop_index("ix_activity_type_ts", table_name="activity_events")
    op.drop_index("ix_activity_ts", table_name="activity_events")
    op.drop_table("activity_events")
