"""One receiver-local day, hour by hour (slice 097).

``AnalyticsQueries.hourly`` is what gives the Analytics page's day-granular
cards something to draw when the window is a single day. Every test here names
its day and its "now" outright rather than deriving them from the wall clock:
the endpoint is a function of the clock, and a test that inherits the time of
day it happens to run at is one that fails at 05:40 UTC (issue #221).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from flightsite.analytics.bucketing import day_bounds_ms
from flightsite.analytics.queries import AnalyticsQueries
from flightsite.db import Database, ReceiverMetricHourly

from ..api.aircraft_history_fixtures import SeedAircraft
from ..api.sighting_fixtures import SeedSighting, seed_sightings
from .conftest import MS_PER_HOUR, NEW_YORK

#: An ordinary 24-hour day in New York (EDT, UTC-4).
DAY = "2026-06-10"
#: The 25-hour day the clocks go back, and the 23-hour day they go forward.
FALL_BACK = "2026-11-01"
SPRING_FORWARD = "2026-03-08"

MINUTE = 60_000


def _start(day: str, zone: ZoneInfo) -> int:
    return day_bounds_ms(day, zone)[0]


def _aircraft(icao24: str, at_ms: int) -> SeedAircraft:
    return SeedAircraft(icao24=icao24, first_seen_ms=at_ms, last_seen_ms=at_ms)


async def test_a_day_is_twenty_four_buckets_labelled_by_local_hour(
    database: Database, zone: ZoneInfo
) -> None:
    queries = AnalyticsQueries(database, timezone=NEW_YORK)
    start = _start(DAY, zone)

    rows = await queries.hourly(DAY, now_ms=start + 48 * MS_PER_HOUR)

    assert [row.hour for row in rows] == list(range(24))
    assert [row.hour_start_ms for row in rows] == [start + h * MS_PER_HOUR for h in range(24)]
    # A day with no traffic that has fully elapsed: zeros are measurements.
    assert all(row.sightings == 0 and row.unique_aircraft == 0 for row in rows)
    # No hourly metrics rows were ever written: "not recorded", never zero.
    assert all(
        row.messages is None and row.positions is None and row.max_range_nm is None for row in rows
    )


async def test_sightings_count_in_the_hour_they_start_and_sum_to_the_day(
    database: Database, zone: ZoneInfo
) -> None:
    queries = AnalyticsQueries(database, timezone=NEW_YORK)
    start = _start(DAY, zone)
    nine = start + 9 * MS_PER_HOUR
    await seed_sightings(
        database,
        [_aircraft("a00001", nine), _aircraft("a00002", nine)],
        [
            SeedSighting("a00001", nine + 5 * MINUTE, ended_ms=nine + 20 * MINUTE),
            SeedSighting("a00002", nine + 30 * MINUTE, ended_ms=nine + 40 * MINUTE),
            SeedSighting("a00001", nine + 50 * MINUTE, ended_ms=nine + 55 * MINUTE),
            SeedSighting(
                "a00002", start + 14 * MS_PER_HOUR, ended_ms=start + 14 * MS_PER_HOUR + MINUTE
            ),
        ],
    )

    rows = await queries.hourly(DAY, now_ms=start + 48 * MS_PER_HOUR)

    assert rows[9].sightings == 3
    assert rows[9].unique_aircraft == 2  # two airframes, one of them twice
    assert rows[14].sightings == 1
    assert sum(row.sightings or 0 for row in rows) == 4


async def test_an_aircraft_is_heard_in_every_hour_its_sighting_overlaps(
    database: Database, zone: ZoneInfo
) -> None:
    """Started at 09:50, ended at 11:10: one sighting, heard in three hours."""
    queries = AnalyticsQueries(database, timezone=NEW_YORK)
    start = _start(DAY, zone)
    began = start + 9 * MS_PER_HOUR + 50 * MINUTE
    await seed_sightings(
        database,
        [_aircraft("a00001", began)],
        [SeedSighting("a00001", began, ended_ms=start + 11 * MS_PER_HOUR + 10 * MINUTE)],
    )

    rows = await queries.hourly(DAY, now_ms=start + 48 * MS_PER_HOUR)

    assert [row.sightings for row in rows[9:12]] == [1, 0, 0]
    assert [row.unique_aircraft for row in rows[8:13]] == [0, 1, 1, 1, 0]


async def test_a_sighting_begun_the_evening_before_is_heard_but_not_counted_again(
    database: Database, zone: ZoneInfo
) -> None:
    queries = AnalyticsQueries(database, timezone=NEW_YORK)
    start = _start(DAY, zone)
    began = start - 10 * MINUTE
    await seed_sightings(
        database,
        [_aircraft("a00001", began)],
        [SeedSighting("a00001", began, ended_ms=start + 5 * MINUTE)],
    )

    rows = await queries.hourly(DAY, now_ms=start + 48 * MS_PER_HOUR)

    assert rows[0].sightings == 0  # it started yesterday, and counts there
    assert rows[0].unique_aircraft == 1
    assert rows[1].unique_aircraft == 0


async def test_an_open_sighting_is_heard_up_to_now_and_future_hours_are_null(
    database: Database, zone: ZoneInfo
) -> None:
    queries = AnalyticsQueries(database, timezone=NEW_YORK)
    start = _start(DAY, zone)
    began = start + 9 * MS_PER_HOUR + 10 * MINUTE
    now_ms = start + 10 * MS_PER_HOUR + 30 * MINUTE
    await seed_sightings(
        database,
        [_aircraft("a00001", began)],
        [SeedSighting("a00001", began, ended_ms=None)],
    )

    rows = await queries.hourly(DAY, now_ms=now_ms)

    assert len(rows) == 24  # the whole day is laid out, not just the past
    assert [row.unique_aircraft for row in rows[8:11]] == [0, 1, 1]
    assert rows[10].sightings == 0  # the hour in progress has begun: a real zero
    # Hours that have not begun are "not measured", never zero.
    assert all(row.sightings is None and row.unique_aircraft is None for row in rows[11:])


async def test_receiver_figures_come_from_the_hourly_metrics_rows(
    database: Database, zone: ZoneInfo
) -> None:
    queries = AnalyticsQueries(database, timezone=NEW_YORK)
    start = _start(DAY, zone)
    async with database.writer_session() as session:
        session.add_all(
            [
                ReceiverMetricHourly(
                    hour_start_ms=start + 7 * MS_PER_HOUR,
                    messages_total=120_000,
                    positions_total=9_000,
                    max_range_nm=212.4,
                    sample_count=60,
                ),
                # A row with counters and no range: a null is carried, not a zero.
                ReceiverMetricHourly(
                    hour_start_ms=start + 8 * MS_PER_HOUR,
                    messages_total=80_000,
                    positions_total=None,
                    max_range_nm=None,
                    sample_count=60,
                ),
                # The day before and the day after must not leak in.
                ReceiverMetricHourly(
                    hour_start_ms=start - MS_PER_HOUR, messages_total=1, sample_count=1
                ),
                ReceiverMetricHourly(
                    hour_start_ms=start + 24 * MS_PER_HOUR, messages_total=1, sample_count=1
                ),
            ]
        )

    rows = await queries.hourly(DAY, now_ms=start + 48 * MS_PER_HOUR)

    assert (rows[7].messages, rows[7].positions, rows[7].max_range_nm) == (120_000, 9_000, 212.4)
    assert (rows[8].messages, rows[8].positions, rows[8].max_range_nm) == (80_000, None, None)
    assert rows[6].messages is None
    assert sum(row.messages or 0 for row in rows) == 200_000


async def test_a_fall_back_day_has_twenty_five_buckets_and_names_the_repeated_hour_twice(
    database: Database, zone: ZoneInfo
) -> None:
    queries = AnalyticsQueries(database, timezone=NEW_YORK)

    rows = await queries.hourly(FALL_BACK, now_ms=_start(FALL_BACK, zone) + 72 * MS_PER_HOUR)

    assert len(rows) == 25
    assert [row.hour for row in rows[:4]] == [0, 1, 1, 2]
    assert rows[-1].hour == 23


async def test_a_spring_forward_day_has_twenty_three_buckets_and_skips_an_hour(
    database: Database, zone: ZoneInfo
) -> None:
    queries = AnalyticsQueries(database, timezone=NEW_YORK)

    rows = await queries.hourly(
        SPRING_FORWARD, now_ms=_start(SPRING_FORWARD, zone) + 72 * MS_PER_HOUR
    )

    assert len(rows) == 23
    assert [row.hour for row in rows[:4]] == [0, 1, 3, 4]


async def test_a_half_hour_zone_attributes_each_utc_bucket_to_the_day_it_begins_in(
    database: Database,
) -> None:
    """India is UTC+5:30, so no UTC hour begins at local midnight. The bucket
    straddling the start of the day belongs to the day before; the day's
    buckets begin at 00:30 local and the last one runs past midnight."""
    kolkata = ZoneInfo("Asia/Kolkata")
    queries = AnalyticsQueries(database, timezone="Asia/Kolkata")
    start, end = day_bounds_ms(DAY, kolkata)

    rows = await queries.hourly(DAY, now_ms=end + 48 * MS_PER_HOUR)

    assert len(rows) == 24
    assert rows[0].hour_start_ms == start + 30 * MINUTE
    assert all(start <= row.hour_start_ms < end for row in rows)
    assert [row.hour for row in rows] == list(range(24))
