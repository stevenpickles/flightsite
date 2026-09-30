"""The last ADS-B emitter category each airframe transmitted.

Slice 086 (issue #229) captures the decoder's emitter category — ``A0``-``D7``,
the category an ADS-B transmitter broadcasts about its own airframe: light,
large, heavy, rotorcraft, glider, UAV and so on. The live picture carries it
per aircraft; this revision keeps the last one each airframe sent, so the
Aircraft page and ``GET /api/v1/aircraft/{icao}`` can say "rotorcraft" about
an airframe that is not overhead right now and that no metadata registry
describes.

One nullable ``TEXT`` column on ``aircraft``, written by the persistence
worker when a sighting has seen a category (the column belongs to the
airframe rather than the sighting because the category describes the
airframe, which is also why a later sighting's value simply replaces it).
``NULL`` is every existing row and every airframe that never transmitted a
category — a Mode S-only aircraft, an MLAT-only one, any aircraft heard only
through a legacy dump1090-fa feed — and it is ``docs/API.md`` §2.7's "unknown",
not a category.

Deliberately no ``CHECK``: SQLite can add a column with one, but the
validation already happens where the value enters FlightSite
(:mod:`flightsite.ingest.readsb` refuses anything that is not ``A0``-``D7``),
and a constraint here would be a third copy of that rule for a column that
nothing but the persistence worker writes. No index either: nothing filters
or sorts on it, and an index would be rewritten on flushes for no reader.

``ADD COLUMN`` and ``DROP COLUMN`` are both in-place on SQLite — no table
rebuild, so none of the foreign-key care
:mod:`flightsite.db.migrations.rebuild` exists for — and both are made
conditional, because SQLite DDL is not transactional (``docs/DEVELOPMENT.md``)
and a revision that failed halfway is re-run from the top.

Revision ID: 0019
Revises: 0018
Created: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from flightsite.db.migrations import rebuild

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "aircraft"
_COLUMN = "emitter_category"


def upgrade() -> None:
    if not rebuild.has_column(op.get_bind(), _TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))


def downgrade() -> None:
    if rebuild.has_column(op.get_bind(), _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
