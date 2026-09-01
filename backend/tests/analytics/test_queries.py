"""The read layer's edges: empty windows, empty results, degenerate limits.

The endpoint tests in :mod:`tests.analytics.test_api` cover what these queries
*answer*; this file covers what they do when there is nothing to answer with.
Every case here is a real request a client can make — a range that resolves to
no days, a window before the receiver existed, a preset over a database with no
metadata at all — and the contract for all of them is ``docs/API.md`` §2.7's:
an empty collection, never a guess and never an error.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from flightsite.activity import ActivityBatch, ActivityEventType, NewActivityEvent
from flightsite.activity import ActivityRepository as FeedRepository
from flightsite.analytics.bucketing import Window, day_bounds_ms, local_day, shift_days
from flightsite.analytics.model import DayRollup
from flightsite.analytics.queries import AnalyticsQueries
from flightsite.analytics.repository import AnalyticsRepository
from flightsite.analytics.rollup import fold_day
from flightsite.db import Database

from .conftest import BASE_EPOCH_MS, NEW_YORK, seed_random_world


@pytest.fixture
def queries(database: Database) -> AnalyticsQueries:
    return AnalyticsQueries(database, timezone=NEW_YORK)


def window(zone: ZoneInfo, first_day: str, last_day: str) -> Window:
    """A window over an explicit day range, for the degenerate cases."""
    return Window(
        start_ms=day_bounds_ms(first_day, zone)[0],
        end_ms=day_bounds_ms(last_day, zone)[1],
        first_day=first_day,
        last_day=last_day,
    )


def backwards(zone: ZoneInfo, day: str) -> Window:
    """A window whose day range names no days at all."""
    return Window(
        start_ms=day_bounds_ms(day, zone)[0],
        end_ms=day_bounds_ms(day, zone)[1],
        first_day=day,
        last_day=shift_days(day, -1),
    )


# ------------------------------------------------------------- empty ranges


async def test_a_window_naming_no_days_returns_no_series(
    queries: AnalyticsQueries, zone: ZoneInfo
) -> None:
    assert await queries.daily(backwards(zone, local_day(BASE_EPOCH_MS, zone))) == ()


async def test_a_window_naming_no_days_returns_no_rankings(
    queries: AnalyticsQueries, zone: ZoneInfo
) -> None:
    empty = backwards(zone, local_day(BASE_EPOCH_MS, zone))

    assert await queries.top_types(empty) == ()
    assert await queries.top_operators(empty) == ()


async def test_an_empty_window_counts_nothing_and_ranks_nothing(
    database: Database, queries: AnalyticsQueries, zone: ZoneInfo
) -> None:
    """An install with no T0 resolves ``preset=t0`` to a zero-width window."""
    await seed_random_world(database, 2, zone=zone, days=2, sightings=20)
    day = local_day(BASE_EPOCH_MS, zone)
    zero_width = Window(
        start_ms=day_bounds_ms(day, zone)[0],
        end_ms=day_bounds_ms(day, zone)[0],
        first_day=day,
        last_day=day,
    )

    assert await queries.unique_aircraft(zero_width) == 0
    assert await queries.top_aircraft(zero_width) == ()
    assert (await queries.rarity(zero_width)).never_seen_before == 0
    assert (await queries.summary(zero_width)).busiest_hour is None


async def test_a_window_before_the_receiver_existed_finds_nothing(
    database: Database, queries: AnalyticsQueries, zone: ZoneInfo
) -> None:
    world = await seed_random_world(database, 2, zone=zone, days=2, sightings=20)
    long_before = shift_days(world.days()[0], -400)

    quiet = window(zone, long_before, shift_days(long_before, 2))

    assert await queries.top_aircraft(quiet) == ()
    assert await queries.top_types(quiet) == ()
    assert await queries.top_operators(quiet) == ()
    assert (await queries.summary(quiet)).sightings == 0


# --------------------------------------------------------- degenerate limits


@pytest.mark.parametrize("whole_history", [False, True])
async def test_a_zero_limit_ranking_is_empty_rather_than_unbounded(
    database: Database, queries: AnalyticsQueries, zone: ZoneInfo, whole_history: bool
) -> None:
    """The API caps ``limit`` at 1; the query layer must not assume it did."""
    world = await seed_random_world(database, 2, zone=zone, days=2, sightings=20)
    span = window(zone, world.days()[0], world.days()[-1])
    asked = Window(
        start_ms=span.start_ms,
        end_ms=span.end_ms,
        first_day=span.first_day,
        last_day=span.last_day,
        whole_history=whole_history,
    )

    assert await queries.top_aircraft(asked, limit=0) == ()
    assert await queries.top_types(asked, limit=0) == ()
    assert await queries.top_operators(asked, limit=0) == ()


# ------------------------------------------------------- the maintenance side


async def test_the_repository_reports_a_day_it_has_never_written_as_absent(
    repository: AnalyticsRepository,
) -> None:
    assert await repository.day("2026-06-02") is None
    assert await repository.stored_days() == set()


async def test_replacing_several_days_writes_each_of_them(
    repository: AnalyticsRepository,
) -> None:
    """One transaction each, so a long catch-up releases the writer lock."""
    rollups = [DayRollup(day="2026-06-01", sightings=3), DayRollup(day="2026-06-02", sightings=5)]

    await repository.replace_days(rollups)

    assert await repository.stored_days() == {"2026-06-01", "2026-06-02"}
    stored = await repository.day("2026-06-02")
    assert stored is not None and stored.sightings == 5


async def test_the_span_of_a_database_with_no_sightings_is_unknown(
    repository: AnalyticsRepository,
) -> None:
    assert await repository.sighting_span_ms() is None


# ---------------------------------------------------------- the ranked paths


async def test_the_windowed_ranking_counts_the_window_not_the_lifetime(
    database: Database, queries: AnalyticsQueries, zone: ZoneInfo
) -> None:
    """The bounded-window form: ``GROUP BY aircraft_id`` over the range.

    Exercised directly rather than only through the API so the *query* is what
    is under test, with no window resolution or serialization in between.
    """
    world = await seed_random_world(database, 3, zone=zone, days=3, sightings=60)
    span = window(zone, world.days()[0], world.days()[-1])
    partial = window(zone, world.days()[-1], world.days()[-1])

    whole = await queries.top_aircraft(span, limit=5)
    last_day = await queries.top_aircraft(partial, limit=5)

    assert len(whole) == 5
    assert whole[0].sightings >= whole[-1].sightings
    assert sum(row.sightings for row in last_day) <= sum(row.sightings for row in whole)
    assert all(row.icao24 for row in last_day)


async def test_the_windowed_group_rankings_report_days_seen_and_true_distincts(
    database: Database, repository: AnalyticsRepository, queries: AnalyticsQueries, zone: ZoneInfo
) -> None:
    """``sightings`` sums the rollup rows; ``unique_aircraft`` is counted exactly."""
    world = await seed_random_world(database, 3, zone=zone, days=3, sightings=60)
    for day in world.days():
        start_ms, end_ms = day_bounds_ms(day, zone)
        await repository.replace_day(
            fold_day(day, await repository.facts_between(start_ms, end_ms), zone=zone, closed=True)
        )
    span = window(zone, world.days()[0], world.days()[-1])

    types = await queries.top_types(span, limit=5)
    operators = await queries.top_operators(span, limit=5)

    assert types
    assert operators
    for row in (*types, *operators):
        assert 1 <= row.days_seen <= len(world.days())
        assert 0 < row.unique_aircraft <= row.sightings
    assert all(row.label is not None for row in operators)


# ----------------------------------------------------- new_milestones (036)

#: A 23-hour local day in ``NEW_YORK`` — see ``tests.analytics.test_bucketing``.
SPRING_FORWARD = "2026-03-08"


async def test_new_milestones_is_zero_over_an_empty_window(
    queries: AnalyticsQueries, zone: ZoneInfo
) -> None:
    assert await queries.new_milestones(backwards(zone, local_day(BASE_EPOCH_MS, zone))) == 0


async def test_new_milestones_counts_only_the_milestone_and_record_types(
    database: Database, queries: AnalyticsQueries, zone: ZoneInfo
) -> None:
    """§59's "new milestones/records" excludes routine operational events."""
    day = local_day(BASE_EPOCH_MS, zone)
    inside_ms = day_bounds_ms(day, zone)[0] + 1
    await FeedRepository(database).record(
        ActivityBatch(
            events=(
                NewActivityEvent(
                    type=ActivityEventType.MILESTONE,
                    ts_ms=inside_ms,
                    dedupe_key="unique_aircraft_100",
                ),
                NewActivityEvent(
                    type=ActivityEventType.RANGE_RECORD,
                    ts_ms=inside_ms,
                    dedupe_key="range_record:100.000",
                ),
                NewActivityEvent(
                    type=ActivityEventType.RECEIVER_OFFLINE,
                    ts_ms=inside_ms,
                    dedupe_key="receiver_offline:1",
                ),
            )
        )
    )
    span = window(zone, day, day)

    assert await queries.new_milestones(span) == 2


async def test_new_milestones_respects_the_spring_forward_days_true_bounds(
    database: Database, queries: AnalyticsQueries, zone: ZoneInfo
) -> None:
    """A milestone struck just inside the 23-hour DST day counts; one struck
    the instant it ends belongs to the next local day, not this one.
    """
    _, end_ms = day_bounds_ms(SPRING_FORWARD, zone)
    just_inside = end_ms - 1
    just_outside = end_ms
    await FeedRepository(database).record(
        ActivityBatch(
            events=(
                NewActivityEvent(
                    type=ActivityEventType.MILESTONE,
                    ts_ms=just_inside,
                    dedupe_key="unique_aircraft_100",
                ),
                NewActivityEvent(
                    type=ActivityEventType.MILESTONE,
                    ts_ms=just_outside,
                    dedupe_key="unique_aircraft_500",
                ),
            )
        )
    )
    span = window(zone, SPRING_FORWARD, SPRING_FORWARD)

    assert await queries.new_milestones(span) == 1
