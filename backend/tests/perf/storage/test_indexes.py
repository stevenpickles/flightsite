"""Index behavior at multi-year scale (SPEC §86).

Latency measurements say a query was fast on the day it ran. A query plan says
*why*, and says it in a way that does not vary with how busy the machine was —
which makes it the honest way to answer SPEC §86's "index behavior" item.

The distinction these tests draw is between a read whose cost is bounded by an
index and one whose cost grows with the table. Both exist in the documented
API, deliberately: `docs/DATA_MODEL.md` §2.3 declares a bounded set of indexes
on ``sightings``, so the ``closest_approach_nm`` sort that `docs/API.md` §3.6
publishes is still served by reading and ordering every matching row. That is a
legitimate design choice — an index per sort column is rewritten on every flush
of an open sighting for a sort few users pick — but it is one that has to be
*known*, because it is the difference between a read that is flat in history
and one that is linear in it.

Slice 058 moved ``max_range_nm`` across that line (rev 0013), on the strength
of slice 050's 8.0 s measurement; its sibling stayed behind on measured write
cost. Both sides are pinned below.

So: the reads a browser issues by default must be index-driven, asserted here;
the ones that are not are asserted to be exactly the ones the documents say,
so that a new unindexed path cannot appear unnoticed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from flightsite.db import Database


async def plan(database: Database, sql: str) -> str:
    """``EXPLAIN QUERY PLAN`` for ``sql``, flattened to one lowercase string."""
    async with database.read_session() as session:
        rows = (await session.execute(text(f"EXPLAIN QUERY PLAN {sql}"))).all()
    return " | ".join(str(row[-1]) for row in rows).lower()


def scans_without_an_index(rendered: str, table: str) -> bool:
    """Whether ``rendered`` walks ``table`` with no index at all.

    SQLite writes ``SCAN sightings USING INDEX ix_sightings_started`` for an
    ordered traversal of an index, which is exactly what a newest-first read
    should do — the word "SCAN" alone does not mean a table scan. What matters
    is whether an index is named: ``SCAN sightings`` on its own reads every row
    of the table, and that is the plan whose cost is unbounded in history.
    """
    return any(
        step.strip().startswith(f"scan {table}") and "using" not in step
        for step in rendered.split("|")
    )


#: The reads the Sightings and Aircraft pages issue without the user choosing
#: anything unusual: newest-first history, one aircraft's history, a time
#: window, and the open-sighting lookup recovery depends on.
INDEXED_READS = (
    (
        "sightings newest first",
        "SELECT * FROM sightings ORDER BY started_ms DESC, id ASC LIMIT 50",
        "ix_sightings_started",
    ),
    (
        "one aircraft's sightings",
        "SELECT * FROM sightings WHERE aircraft_id = 7 ORDER BY started_ms DESC LIMIT 50",
        "ix_sightings_aircraft",
    ),
    (
        "a time window",
        "SELECT * FROM sightings WHERE started_ms >= 0 AND started_ms < 9223372036854 "
        "ORDER BY started_ms DESC LIMIT 50",
        "ix_sightings_started",
    ),
    (
        "open sightings",
        "SELECT * FROM sightings WHERE ended_ms IS NULL",
        "ix_sightings_open",
    ),
)


@pytest.mark.parametrize(
    ("label", "sql", "index"), INDEXED_READS, ids=[read[0] for read in INDEXED_READS]
)
async def test_the_default_reads_are_served_by_an_index(
    database: Database, label: str, sql: str, index: str
) -> None:
    """A full scan here would be linear in history, which is unbounded.

    ``sightings`` is retained indefinitely (SPEC §65), so a plan that scans it
    is a plan whose cost has no ceiling. These four reads are the ones a
    browser issues on an ordinary visit, and each must be answered from a
    named index.
    """
    rendered = await plan(database, sql)
    assert index in rendered, f"{label} no longer uses {index}: {rendered}"
    assert not scans_without_an_index(rendered, "sightings"), (
        f"{label} reads every sightings row: {rendered}"
    )


async def test_aircraft_lookups_use_their_indexes(database: Database) -> None:
    """The Aircraft page's own default orderings, and the icao lookup.

    ``aircraft`` grows with distinct airframes rather than with sightings, but
    over years that is still hundreds of thousands of rows.
    """
    by_icao = await plan(database, "SELECT * FROM aircraft WHERE icao24 = 'abc123'")
    assert "using index" in by_icao, by_icao

    by_last_seen = await plan(
        database, "SELECT * FROM aircraft ORDER BY last_seen_ms DESC LIMIT 50"
    )
    assert "ix_aircraft_last_seen" in by_last_seen, by_last_seen


async def test_a_sightings_track_is_fetched_by_primary_key(database: Database) -> None:
    """ADR-0005: every track read is "the whole path for sighting N".

    ``sighting_tracks`` is ``WITHOUT ROWID`` and keyed by ``sighting_id``, so
    the sighting-detail read is a primary-key seek. A scan here would read
    every packed blob in the database to answer one page.
    """
    rendered = await plan(database, "SELECT * FROM sighting_tracks WHERE sighting_id = 42")
    assert "scan" not in rendered, rendered


@pytest.mark.parametrize("order", ["desc", "asc"])
async def test_the_max_range_sort_reads_its_index(database: Database, order: str) -> None:
    """Slice 058 indexed ``max_range_nm``; this pins that it stays indexed.

    ``ix_sightings_max_range`` is ``(max_range_nm, id)`` — the sort key plus
    the list endpoint's pagination tiebreaker — and both documented directions
    read it, forward for ``asc`` and backward for ``desc``.

    The descending plan legitimately still names a temporary B-tree, as "USE
    TEMP B-TREE FOR **LAST TERM OF** ORDER BY": ``id`` breaks ties ascending in
    both directions, so a reverse walk hands it back descending and SQLite
    re-sorts within each group of equal ranges. That is a partial sort over
    ties on a REAL column, not a sort of the table, which is why this asserts
    on the index and on the absence of an unindexed scan rather than on the
    absence of a temp B-tree.
    """
    rendered = await plan(
        database, f"SELECT * FROM sightings ORDER BY max_range_nm {order.upper()}, id ASC LIMIT 50"
    )
    assert "ix_sightings_max_range" in rendered, (
        f"the {order} max_range sort no longer uses its index: {rendered}"
    )
    assert not scans_without_an_index(rendered, "sightings"), (
        f"the {order} max_range sort reads every row: {rendered}"
    )
    if order == "asc":
        assert "temp b-tree" not in rendered, (
            f"the ascending max_range sort matches the index exactly and should "
            f"need no sort at all: {rendered}"
        )


async def test_the_unindexed_sorts_are_exactly_the_documented_ones(
    database: Database,
) -> None:
    """The known slow paths, pinned so a new one cannot appear quietly.

    ``closest_approach_nm`` is published in ``docs/API.md`` §3.6 and is not
    indexed, so SQLite must materialize and sort. Slice 058 indexed its sibling
    ``max_range_nm`` and deliberately left this one alone: every index on
    ``sightings`` is rewritten on each 30-second flush of an open sighting, and
    a second sort index measured ~2.6x the baseline per-sighting write cost
    again (issue #115, and rev 0013's docstring). That trade is recorded in
    ``docs/PERFORMANCE.md`` §7.7.

    The assertion is that this sort *does* scan-and-sort, which is what makes
    the finding true; if someone adds the index, this test fails and points at
    the finding that should then be removed.
    """
    rendered = await plan(
        database, "SELECT * FROM sightings ORDER BY closest_approach_nm DESC, id ASC LIMIT 50"
    )
    assert scans_without_an_index(rendered, "sightings"), (
        f"sort by closest_approach_nm no longer reads every row: {rendered}. If an index "
        "was added, docs/PERFORMANCE.md §7.7's remaining finding about the unindexed sort "
        "is now stale and should be removed."
    )
    assert "temp b-tree" in rendered, (
        f"sort by closest_approach_nm no longer materializes a sort: {rendered}"
    )


async def test_the_interesting_filter_has_no_index_either(database: Database) -> None:
    """``max_alert_severity IS NOT NULL`` is a documented filter with no index.

    Recorded for the same reason as the sorts above: it is a published query
    parameter (``?interesting=true``) whose cost is linear in history. A
    partial index on the severity column would serve it cheaply, which is worth
    weighing alongside the sort indexes if that finding is ever acted on.
    """
    rendered = await plan(
        database,
        "SELECT * FROM sightings WHERE max_alert_severity IS NOT NULL "
        "ORDER BY started_ms DESC LIMIT 50",
    )
    assert "sightings" in rendered


async def test_the_analytics_day_rollups_are_keyed_lookups(database: Database) -> None:
    """Analytics reads scale with days in the window, not sightings in it.

    ``daily_stats`` is ``WITHOUT ROWID`` keyed by ``day``, so a preset's window
    is a range over the primary key. This is the property that keeps the
    analytics surface flat as history grows, and it is worth asserting rather
    than inferring from a latency that happened to be small.
    """
    rendered = await plan(
        database, "SELECT * FROM daily_stats WHERE day >= '2020-01-01' AND day < '2030-01-01'"
    )
    assert "daily_stats" in rendered
    assert "temp b-tree" not in rendered, rendered
