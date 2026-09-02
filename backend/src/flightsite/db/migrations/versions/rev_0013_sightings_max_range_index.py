"""Index the ``max_range_nm`` sort on ``sightings``.

``docs/API.md`` §3.6 publishes ``sort=max_range_nm``, and until this revision
``sightings`` carried no index on that column: the sort read every matching row
into a temporary B-tree, so its cost grew linearly with a table that is
retained indefinitely (SPEC §65). Slice 050 measured it at **8,033 ms** over
1.64M sightings against 2 ms for the indexed default sort
(``docs/PERFORMANCE.md`` §7.7), which is the whole of that slice's
``history_query_ms`` overrun.

The index is composite on ``(max_range_nm, id)`` rather than on the column
alone because ``id`` is the list endpoint's stable pagination tiebreaker
(:mod:`flightsite.api.sightings`). Both documented directions are served by
the one index: SQLite walks it forward for ``ORDER BY max_range_nm ASC, id
ASC`` and backward for the ``DESC`` default. The descending case still shows
``USE TEMP B-TREE FOR LAST TERM OF ORDER BY`` in its plan -- the tiebreaker is
ascending in both directions, so the reverse walk orders ``id`` the wrong way
and SQLite sorts *within* each group of equal ranges. That is a partial sort
over ties on a REAL column, not a sort of the table: measured over 1M rows the
first page goes from 91.6 ms to 0.1 ms, and a 5,000-row-deep page from 111.2 ms
to 21.1 ms.

Only ``max_range_nm`` is indexed here. ``closest_approach_nm`` is the same
shape of read and was measured just as slow (7,302 ms), but each index on this
table is maintained by the single writer on the sighting INSERT and again on
*every* 30-second flush (``_RUNNING_COLUMNS`` in
:mod:`flightsite.sightings.repository` rewrites both extremes each time), and
the cost compounds: replaying that write shape over a 1M-row table measured
0.256 ms per sighting with no extra index, 0.769 ms with this one, and 1.437 ms
with both. The second index is another ~2.6x the baseline write cost and
another ~21 B/row on disk for a second rarely-chosen sort, so it is deferred to
evidence of use rather than added on symmetry. GitHub issue #115 carries the
numbers; ``docs/PERFORMANCE.md`` §7.7 keeps the remaining finding.

``duration_s`` and the ``interesting`` filter stay unindexed for the same
reason, unchanged by this revision.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_sightings_max_range"


def upgrade() -> None:
    op.create_index(_INDEX_NAME, "sightings", ["max_range_nm", "id"])


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="sightings")
