"""``GET /api/v1/overhead`` is index-driven on slice 050's synthetic history.

Roadmap slice 090's acceptance criterion is that a ±10 minute window answers
within the analytics query budget on a three-year dataset. A three-year
dataset takes twenty minutes to generate, so the measurement at that scale
belongs to ``flightsite-storage-qual``, whose query probes include this
lookup (``docs/PERFORMANCE.md`` §7). What the in-suite smoke dataset proves,
independently of how busy the machine is, is *why* the lookup stays flat as
history grows: both candidate reads enter ``sightings`` through a named index
over a bounded range — never a walk of the whole table — and the track reads
go by primary key.

The statements planned are the repository's own builders, compiled — not hand-copied
SQL that could drift from what the endpoint issues — cold and after
``ANALYZE``, as :mod:`tests.perf.storage.test_list_search` does and for the
same reason.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects import sqlite

from flightsite.api.overhead import (
    MINUTE_MS,
    OverheadRepository,
    checkpoints_query,
    open_query,
    recent_query,
    tracks_query,
)
from flightsite.db import Database
from flightsite.ingest import Position
from flightsite.perf.storage_qualification.traffic import TRACK_CENTRE

from .test_indexes import plan, scans_without_an_index

#: ``docs/PERFORMANCE.md``'s ``analytics_query_ms`` budget — what slice 090's
#: acceptance criterion names — applied to the smoke dataset, where it is a
#: generous ceiling rather than a measurement.
QUERY_BUDGET_MS = 500.0

#: The centre the generator's packed tracks are drawn around
#: (:data:`~flightsite.perf.storage_qualification.traffic.TRACK_CENTRE`).
RECEIVER = Position(latitude=TRACK_CENTRE[0], longitude=TRACK_CENTRE[1])

WINDOW_MS = 10 * MINUTE_MS


def _sql(statement: Any) -> str:
    """``statement`` as SQLite text with its parameters inlined."""
    return str(statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))


async def _busiest_moment(database: Database) -> int:
    """The start of a sighting from the middle of history: a moment with traffic."""
    async with database.read_session() as session:
        total = int((await session.execute(text("SELECT count(*) FROM sightings"))).scalar_one())
        started = (
            await session.execute(
                text("SELECT started_ms FROM sightings ORDER BY started_ms LIMIT 1 OFFSET :skip"),
                {"skip": total // 2},
            )
        ).scalar_one()
    return int(started)


async def _plans_hold(database: Database) -> None:
    at_ms = await _busiest_moment(database)
    from_ms, to_ms = at_ms - WINDOW_MS, at_ms + WINDOW_MS

    recent = await plan(database, _sql(recent_query(from_ms, to_ms)))
    assert "ix_sightings_started" in recent, recent
    assert "(started_ms>? and started_ms<?)" in recent, (
        f"the candidate read is not a bounded range of ix_sightings_started: {recent}"
    )
    assert not scans_without_an_index(recent, "sightings"), recent

    still_open = await plan(database, _sql(open_query(to_ms)))
    assert "ix_sightings_open" in still_open, still_open
    assert not scans_without_an_index(still_open, "sightings"), still_open

    tracks = await plan(database, _sql(tracks_query([1, 2, 3])))
    assert "search sighting_tracks using primary key" in tracks, tracks

    checkpoints = await plan(database, _sql(checkpoints_query([1, 2, 3], from_ms, to_ms)))
    assert "search sighting_track_checkpoints using primary key" in checkpoints, checkpoints


async def test_the_candidate_reads_are_index_driven_without_statistics(
    database: Database,
) -> None:
    await _plans_hold(database)


async def test_a_ten_minute_window_answers_inside_the_budget(database: Database) -> None:
    """Through the repository the endpoint calls, on a moment with traffic."""
    at_ms = await _busiest_moment(database)
    repository = OverheadRepository(database)

    started = time.perf_counter()
    result = await repository.closest_passes(
        receiver=RECEIVER, from_ms=at_ms - WINDOW_MS, to_ms=at_ms + WINDOW_MS, limit=10
    )
    elapsed_ms = (time.perf_counter() - started) * 1_000.0

    print(
        f"overhead +/-10 min: {elapsed_ms:.1f} ms, {result.candidates} candidates, "
        f"{result.decoded} decoded, {len(result.passes)} results"
    )
    assert elapsed_ms < QUERY_BUDGET_MS
    assert result.candidates > 0
    assert result.passes
    assert not result.truncated
    distances = [item.fix.distance_nm for item in result.passes]
    assert distances == sorted(distances)
    assert all(at_ms - WINDOW_MS <= item.fix.ts_ms <= at_ms + WINDOW_MS for item in result.passes)


async def test_the_candidate_reads_stay_index_driven_after_analyze(database: Database) -> None:
    """Last in the module: it writes ``sqlite_stat1`` into the shared dataset."""
    async with database.writer_session() as session:
        await session.execute(text("ANALYZE"))

    await _plans_hold(database)
