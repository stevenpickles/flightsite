"""User-defined watchlists.

Creates the two tables ``docs/DATA_MODEL.md`` §4.1 gives slice 037 —
``watchlists`` and ``watchlist_entries`` — per SPEC §42. Nothing existing
referenced them, so the downgrade is a plain drop.

``watchlists`` is a plain rowid table: few rows, always addressed by surrogate
id or by the whole set, never bulk-scanned. ``watchlist_entries`` cascades on
its parent's deletion (``ondelete="CASCADE"``, enforced because ADR-0001 runs
with ``PRAGMA foreign_keys = ON``) — the only cascading foreign key in the
schema, because an entry has no meaning once its watchlist is gone and
deleting a watchlist is meant to delete everything on it in one action.

``value`` is stored pre-normalized (lower-case ``icao24``, upper-case
``registration``/``type_code``/``operator``, the mission-category spelling for
``category`` — see :mod:`flightsite.watchlists.vocabulary`), which is what
lets :mod:`flightsite.watchlists.matcher` build its in-memory index with plain
equality rather than re-normalizing a live aircraft's fields against every
entry on every lookup.

``ix_wentries_kind_value`` mirrors the shape the in-memory match index is
built from — every access is a ``(kind, value)`` prefix — and is the read path
for a future audit query ("every entry naming this aircraft") the table's own
docstring anticipates; the ``UNIQUE`` constraint scopes to one watchlist, so
the same value may appear on two different watchlists for two different
reasons.

MIGRATION NOTE (parallel slices): this revision's local ``down_revision`` is
``0009``, the head in this worktree at the time slice 037 was implemented.
Slice ``036`` independently owns revision ``0010`` in its own worktree; per
``docs/DEVELOPMENT.md``'s "Parallel migrations" rebase rule, the orchestrator
re-parents this file onto ``0010`` at reconcile time (a one-line
``down_revision`` edit) rather than either slice guessing the other's shape in
advance. Nothing in this migration's operations depends on anything ``0010``
creates, so the reparenting is mechanical.

Revision ID: 0011
Revises: 0009
Created: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``docs/DATA_MODEL.md`` §4.1's ``watchlist_entries.kind`` vocabulary,
#: mirroring :data:`flightsite.db.models.WATCHLIST_ENTRY_KIND_CHECK`. Spelled
#: out again here rather than imported: a migration must keep reading
#: correctly however the model file evolves after this revision is written
#: (the same rule every other migration in this directory follows).
_WATCHLIST_ENTRY_KIND_CHECK = (
    "kind IN ('icao24', 'registration', 'type_code', 'operator', 'category')"
)


def upgrade() -> None:
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_watchlists_name"),
    )
    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("watchlist_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(_WATCHLIST_ENTRY_KIND_CHECK, name="ck_watchlist_entries_kind"),
        sa.ForeignKeyConstraint(
            ["watchlist_id"],
            ["watchlists.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "watchlist_id", "kind", "value", name="uq_watchlist_entries_watchlist_kind_value"
        ),
    )
    op.create_index("ix_wentries_kind_value", "watchlist_entries", ["kind", "value"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_wentries_kind_value", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
    op.drop_table("watchlists")
