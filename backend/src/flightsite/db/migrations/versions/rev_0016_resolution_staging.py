"""Scratch tables that take resolution out of the promotion transaction.

Slice 075 (issue #185). A metadata promotion used to resolve and classify
every airframe in the database *inside* the transaction that swapped the new
snapshot in — Python work, one airframe at a time, on the event loop, holding
the process's single writer (ADR-0008) for minutes on the owner's Pi. The
persistence worker and the alert engine could not drain their bounded queues
while it ran, so they overflowed and resynced.

This revision adds the two tables that let the work happen *first*:

* **``aircraft_metadata_resolved_staging``** (``docs/DATA_MODEL.md`` §3.3)
* **``aircraft_classification_staging``** (§3.4)

Each is its live table's column set and nothing else. No foreign key from the
staging resolved rows to ``operator_groups``: those ids name the curated
directory the promotion is *about to install*, so enforcing the reference
while the previous directory is still in place would fail on a group the old
one never had. No secondary indexes and no ``CHECK`` either — nothing queries
these tables, every row is read back exactly once by an ``INSERT ... SELECT``,
and the live tables enforce the vocabulary where the rows come to rest.

Both are scratch in the same sense as ``aircraft_metadata_staging``: emptied
when a build starts, emptied when it promotes, emptied by "Clear Metadata
Cache", and never read by anything but the promotion that filled them. So the
downgrade is a plain drop, and an install that downgrades loses nothing a
metadata update would not rebuild.

Two ``CREATE TABLE``s and no data movement, so this is one of the cheap ones:
milliseconds on any install, whatever its history is worth. Every step is
conditional, because SQLite DDL is not transactional (``docs/DEVELOPMENT.md``,
"SQLite DDL is not transactional") and a revision that failed halfway is
re-run from the top.

Revision ID: 0016
Revises: 0015
Created: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from flightsite.db.migrations import rebuild

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOLVED_STAGING = "aircraft_metadata_resolved_staging"
_CLASSIFICATION_STAGING = "aircraft_classification_staging"

_ZERO = sa.text("0")
_UNKNOWN = sa.text("'unknown'")


def _resolved_columns() -> list[sa.Column[Any]]:
    """``aircraft_metadata_resolved``'s columns, as this revision found them.

    Spelled out rather than imported from :mod:`flightsite.db.models` for the
    reason revision 0014 gives: a migration records what an install ran, so a
    later slice adding a column must not retroactively change what this one
    created.
    """
    return [
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
    ]


def _classification_columns() -> list[sa.Column[Any]]:
    """``aircraft_classification``'s columns, as this revision found them."""
    return [
        sa.Column("icao24", sa.Text(), nullable=False),
        sa.Column("military", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("military_src", sa.Text(), nullable=True),
        sa.Column("military_conf", sa.REAL(), nullable=True),
        sa.Column("government", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("government_src", sa.Text(), nullable=True),
        sa.Column("government_conf", sa.REAL(), nullable=True),
        sa.Column("law_enforcement", sa.Integer(), nullable=False, server_default=_ZERO),
        sa.Column("law_enforcement_src", sa.Text(), nullable=True),
        sa.Column("law_enforcement_conf", sa.REAL(), nullable=True),
        sa.Column("mission_category", sa.Text(), nullable=False, server_default=_UNKNOWN),
        sa.Column("mission_src", sa.Text(), nullable=True),
        sa.Column("mission_conf", sa.REAL(), nullable=True),
        sa.Column("icon_category", sa.Text(), nullable=False, server_default=_UNKNOWN),
        sa.Column("updated_ms", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    if not rebuild.has_table(bind, _RESOLVED_STAGING):
        op.create_table(
            _RESOLVED_STAGING,
            *_resolved_columns(),
            sa.PrimaryKeyConstraint("icao24"),
            sqlite_with_rowid=False,
        )
    if not rebuild.has_table(bind, _CLASSIFICATION_STAGING):
        op.create_table(
            _CLASSIFICATION_STAGING,
            *_classification_columns(),
            sa.PrimaryKeyConstraint("icao24"),
            sqlite_with_rowid=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (_CLASSIFICATION_STAGING, _RESOLVED_STAGING):
        if rebuild.has_table(bind, table):
            op.drop_table(table)
