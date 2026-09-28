"""The list pages' ``q`` search is index-driven on slice 050's synthetic history.

Slice 083's acceptance criterion is that ``q`` answers within the analytics
query budget on a three-year dataset. A three-year dataset takes twenty
minutes to generate, so it belongs to ``flightsite-storage-qual`` (whose
query probes include the searches; ``docs/PERFORMANCE.md`` §7). What the
in-suite smoke dataset can prove, and prove independently of how busy the
machine is, is *why* the search stays flat as history grows: every table it
touches is entered through a named index, and neither ``aircraft``,
``aircraft_metadata_resolved`` nor ``sightings`` is ever read row by row
(:mod:`tests.perf.storage.test_indexes`' distinction).

The statements checked are the repositories' own, compiled — not hand-copied
SQL that could drift from what the endpoints issue. Each is planned twice:
cold, and after ``ANALYZE`` (the daily maintenance ``PRAGMA optimize`` can
write ``sqlite_stat1``, and a plan that is only good without statistics is a
plan that changes under a user overnight).

Measured on the row counts of the three-year Scenario A run
(``docs/PERFORMANCE.md`` §7.6.1) before and after rev 0018, on a development
machine: the aircraft search went from ~1 s per query (twice, with the count)
to under 10 ms for a three-character prefix and ~470 ms page-plus-count for a
single letter; a ``/sightings`` prefix matching nothing went from 1.6 s to
2 ms.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.dialects import sqlite

from flightsite.api import history, sightings
from flightsite.api.history import AircraftHistoryRepository
from flightsite.api.sightings import SightingsRepository
from flightsite.db import Database
from flightsite.db.models import Aircraft, Sighting

from .test_indexes import plan, scans_without_an_index

#: ``docs/PERFORMANCE.md``'s ``analytics_query_ms`` budget — what slice 083's
#: acceptance criterion names — applied to the smoke dataset, where it is a
#: generous ceiling rather than a measurement.
QUERY_BUDGET_MS = 500.0

#: A callsign prefix the generator's airline roster (``demo/roster.py``) uses,
#: an address prefix, a single letter (the broadest query there is) and a
#: prefix that matches nothing.
QUERIES = ("dal", "4f", "a", "zz9")


def _sql(statement: Any) -> str:
    """``statement`` as SQLite text with its parameters inlined."""
    return str(statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))


def _aircraft_page(q: str) -> str:
    filtered = history._joined_query().where(
        *history._filters(classification=None, operator_group=None, type_code=None, q=q)
    )
    return _sql(
        filtered.order_by(
            history._direction(history.SORT_COLUMNS["last_seen"], "desc"),
            Aircraft.icao24.asc(),
        ).limit(50)
    )


def _aircraft_count(q: str) -> str:
    filtered = history._joined_query().where(
        *history._filters(classification=None, operator_group=None, type_code=None, q=q)
    )
    return _sql(select(func.count()).select_from(filtered.subquery()))


def _sightings_page(q: str) -> str:
    filtered = sightings._joined_query().where(
        *sightings._filters(
            icao=None, from_ms=None, to_ms=None, interesting=None, open_only=None, q=q
        )
    )
    return _sql(
        filtered.order_by(
            sightings._direction(sightings.SORT_COLUMNS["started_at"], "desc"),
            Sighting.id.asc(),
        ).limit(50)
    )


def _assert_aircraft_search_is_indexed(rendered: str) -> None:
    for index in (
        "sqlite_autoindex_aircraft_1",
        "ix_amr_registration_nocase",
        "ix_amr_type",
        "ix_amr_operator_nocase",
        "ix_sightings_callsign",
        "ix_sightings_aircraft",
    ):
        assert index in rendered, f"the aircraft search no longer reads {index}: {rendered}"
    for table in ("aircraft", "aircraft_metadata_resolved", "sightings"):
        assert not scans_without_an_index(rendered, table), (
            f"the aircraft search reads every {table} row: {rendered}"
        )
    # Aliased tables plan under their alias; none may be a bare scan either.
    assert not any(
        step.strip().startswith("scan ") and "using" not in step for step in rendered.split("|")
    ), f"the aircraft search scans a table: {rendered}"


def _assert_sightings_search_is_indexed(rendered: str) -> None:
    assert "ix_sightings_callsign" in rendered, rendered
    assert "ix_sightings_aircraft" in rendered, rendered
    assert not scans_without_an_index(rendered, "sightings"), (
        f"the sightings search reads every sighting: {rendered}"
    )
    assert "scan sightings using index ix_sightings_started" not in rendered, (
        f"the sightings search walks all history newest-first: {rendered}"
    )


async def _plans_hold(database: Database) -> None:
    for q in QUERIES:
        _assert_aircraft_search_is_indexed(await plan(database, _aircraft_page(q)))
        _assert_aircraft_search_is_indexed(await plan(database, _aircraft_count(q)))
        _assert_sightings_search_is_indexed(await plan(database, _sightings_page(q)))


async def test_the_searches_are_index_driven_without_statistics(database: Database) -> None:
    await _plans_hold(database)


@pytest.mark.parametrize("q", QUERIES)
async def test_the_searches_answer_inside_the_budget(database: Database, q: str) -> None:
    """Through the repositories the endpoints call, page and count together."""
    aircraft = AircraftHistoryRepository(database)
    log = SightingsRepository(database)

    started = time.perf_counter()
    rows, total = await aircraft.list_aircraft(limit=50, offset=0, q=q)
    aircraft_ms = (time.perf_counter() - started) * 1_000.0
    started = time.perf_counter()
    await log.list_sightings(limit=50, offset=0, q=q)
    sightings_ms = (time.perf_counter() - started) * 1_000.0

    print(f"q={q!r}: aircraft {aircraft_ms:.1f} ms ({total} rows), sightings {sightings_ms:.1f} ms")
    assert aircraft_ms < QUERY_BUDGET_MS
    assert sightings_ms < QUERY_BUDGET_MS
    assert len(rows) <= 50


async def test_a_roster_callsign_prefix_finds_real_rows(database: Database) -> None:
    """The dataset exercises the callsign branches rather than planning empty ones."""
    rows, total = await AircraftHistoryRepository(database).list_aircraft(
        limit=50, offset=0, q="DAL"
    )
    logged = await SightingsRepository(database).list_sightings(limit=50, offset=0, q="dal")

    assert total > 0
    assert rows
    assert logged
    assert all(str(row["callsign_last"]).upper().startswith("DAL") for row in logged)


async def test_the_searches_stay_index_driven_after_analyze(database: Database) -> None:
    """Last in the module: it writes ``sqlite_stat1`` into the shared dataset."""
    async with database.writer_session() as session:
        await session.execute(text("ANALYZE"))

    await _plans_hold(database)
