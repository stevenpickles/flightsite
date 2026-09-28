"""Case-insensitive prefix indexes for the list pages' ``q`` search.

Slice 083 (issue #226) adds ``q`` to ``GET /api/v1/aircraft`` and
``GET /api/v1/sightings``: a case-insensitive prefix over the identifiers a
person remembers (:mod:`flightsite.api.search`). A case-insensitive prefix is
a range under ``COLLATE NOCASE``, and SQLite can only read that range from an
index built in the same collation. Three columns needed one:

* **``ix_amr_registration_nocase``** and **``ix_amr_operator_nocase``** on
  ``aircraft_metadata_resolved`` — neither column is case-normalized on
  import (``type_code`` is, so the existing ``ix_amr_type`` serves it).
* **``ix_sightings_callsign``** on ``sightings (callsign_last COLLATE NOCASE,
  aircraft_id)`` — serving both ``/sightings``' callsign prefix and the
  Aircraft page's "most recent callsign", with ``aircraft_id`` included so the
  latter reads "which airframes flew this prefix" from the index alone.

Measured without them, over slice 050's three-year Scenario A row counts
(120,640 airframes, 94,195 resolved rows, 1.64M sightings) on a development
machine: the Aircraft page's ``q`` cost about a second per query, twice
(``total`` counts the same filter), and a ``/sightings`` callsign prefix that
matched nothing walked the whole table newest-first — 1.6 s. With them the
same reads take under 10 ms for a typical three-character query, and ~470 ms
(Aircraft page plus count) or ~400 ms (``/sightings``) for the broadest one
possible — a single letter, matching a third of every airframe.

Write cost, stated rather than assumed:

* ``sightings`` — one index entry per sighting INSERT. Unlike the extremes
  rev 0013 declined to index, ``callsign_last`` is not rewritten on every
  30-second flush: the ORM leaves an unchanged attribute out of the UPDATE,
  so the entry moves only when the callsign actually changes.
* ``aircraft_metadata_resolved`` — replaced wholesale by a metadata promotion
  (:mod:`flightsite.metadata.repository`), so both indexes are rebuilt inside
  that swap. Replaying a 900k-row swap in memory measured 1.5 s without them
  and 3.4 s with them. That is time the single writer is held, which slice 075
  worked to bound; a couple of seconds on an import that runs at most daily
  was judged worth a search that does not scan the metadata table on every
  keystroke.

Building the indexes is a one-off sort of existing rows — about a second for
all three at the sizes above. Every step is conditional, because SQLite DDL
is not transactional (``docs/DEVELOPMENT.md``, "SQLite DDL is not
transactional") and a revision that failed halfway is re-run from the top.

Revision ID: 0018
Revises: 0017
Created: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from flightsite.db.migrations import rebuild

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``(index, table, indexed expressions)``, in creation order.
_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ix_amr_registration_nocase",
        "aircraft_metadata_resolved",
        ("registration COLLATE NOCASE",),
    ),
    (
        "ix_amr_operator_nocase",
        "aircraft_metadata_resolved",
        ("operator_name COLLATE NOCASE",),
    ),
    (
        "ix_sightings_callsign",
        "sightings",
        ("callsign_last COLLATE NOCASE", "aircraft_id"),
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, table, expressions in _INDEXES:
        if not rebuild.has_index(bind, name):
            op.create_index(name, table, [sa.text(expression) for expression in expressions])


def downgrade() -> None:
    bind = op.get_bind()
    for name, table, _ in reversed(_INDEXES):
        if rebuild.has_index(bind, name):
            op.drop_index(name, table_name=table)
