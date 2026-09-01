"""The backfill job: idempotence, repair planning, the watermark, ``type_stats``.

The roadmap gives slice 031 a *"backfill job [that] rebuilds any day's rollups
from sightings ground truth (idempotent full-day replacement); run
automatically at startup for days that are missing/stale (bounded)"*. Each of
those clauses is a test here, and the convergence property the whole design
rests on — that an incremental rebuild and a from-scratch one produce the same
rows — is asserted in :mod:`tests.analytics.test_service` where both paths
actually exist.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from flightsite.analytics.backfill import AnalyticsBackfill
from flightsite.analytics.bucketing import day_bounds_ms, local_day, next_day, shift_days
from flightsite.analytics.repository import META_KEY_ROLLUP_THROUGH_DAY, AnalyticsRepository
from flightsite.db import Database
from flightsite.db.meta import MetaRepository

from ..api.aircraft_history_fixtures import SeedAircraft
from ..api.sighting_fixtures import SeedSighting
from .conftest import (
    BASE_EPOCH_MS,
    KOLKATA,
    MS_PER_HOUR,
    NEW_YORK,
    World,
    brute_force_day,
    seed_random_world,
    seed_world,
    stored_rollup,
)


def backfill(
    repository: AnalyticsRepository, zone: ZoneInfo, *, max_days: int = 3_650
) -> AnalyticsBackfill:
    return AnalyticsBackfill(
        repository=repository,
        meta=MetaRepository(repository.database),
        zone=zone,
        max_days=max_days,
    )


@pytest.fixture
def job(repository: AnalyticsRepository, zone: ZoneInfo) -> AnalyticsBackfill:
    return backfill(repository, zone)


# ------------------------------------------------------------- idempotence


async def test_rebuilding_a_day_twice_writes_the_same_rows(
    database: Database, repository: AnalyticsRepository, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """The property ADR-0009 asks of downsampling, restated for rollups."""
    world = await seed_random_world(database, 11, zone=zone, days=4, sightings=80)
    day = world.days()[1]
    now_ms = day_bounds_ms(world.days()[-1], zone)[1]

    first = await job.rebuild_day(day, now_ms=now_ms)
    stored_once = await stored_rollup(repository, day)
    second = await job.rebuild_day(day, now_ms=now_ms)

    assert first == second
    assert await stored_rollup(repository, day) == stored_once
    assert (await repository.counts())["daily_stats"] == 1


async def test_a_rebuild_replaces_a_breakdown_row_rather_than_accumulating_it(
    database: Database, repository: AnalyticsRepository, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """A type that stops appearing must *leave* the day, not linger."""
    started_ms = day_bounds_ms(local_day(BASE_EPOCH_MS, zone), zone)[0] + 5 * MS_PER_HOUR
    world = await seed_world(
        database,
        zone=zone,
        aircraft=[
            SeedAircraft(
                icao24="a00001",
                first_seen_ms=started_ms,
                last_seen_ms=started_ms,
                type_code="B738",
            )
        ],
        sightings=[SeedSighting(icao24="a00001", started_ms=started_ms)],
    )
    day = world.days()[0]
    now_ms = day_bounds_ms(day, zone)[1]
    await job.rebuild_day(day, now_ms=now_ms)
    assert (await stored_rollup(repository, day)).types.keys() == {"B738"}

    # A metadata correction moves the airframe to a different designator.
    async with database.writer_session() as session:
        await session.execute(
            text("UPDATE aircraft_metadata_resolved SET type_code = 'A320' WHERE icao24 = 'a00001'")
        )

    await job.rebuild_day(day, now_ms=now_ms)

    assert (await stored_rollup(repository, day)).types.keys() == {"A320"}


async def test_a_day_with_no_sightings_still_writes_its_zero_row(
    database: Database, repository: AnalyticsRepository, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """ "Rebuilt and empty" must be distinguishable from "never rebuilt"."""
    await seed_random_world(database, 5, zone=zone, days=2, sightings=20)
    quiet = shift_days(local_day(BASE_EPOCH_MS, zone), 30)

    rollup = await job.rebuild_day(quiet, now_ms=day_bounds_ms(quiet, zone)[1])

    assert rollup.empty is True
    assert await repository.day(quiet) is not None


async def test_a_day_is_closed_only_once_its_local_midnight_has_passed(
    database: Database, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """§6.5's rule, and the reason ``busiest_hour`` is nullable."""
    world = await seed_random_world(database, 5, zone=zone, days=1, sightings=20)
    day = world.days()[0]
    start_ms, end_ms = day_bounds_ms(day, zone)

    assert (await job.rebuild_day(day, now_ms=end_ms - 1)).busiest_hour is None
    assert (await job.rebuild_day(day, now_ms=end_ms)).busiest_hour is not None
    assert (await job.rebuild_day(day, now_ms=start_ms)).busiest_hour is None


# --------------------------------------------------------- startup planning


async def test_an_install_with_no_sightings_plans_nothing(
    job: AnalyticsBackfill,
) -> None:
    """A fresh install has no history to repair and no day worth a zero row."""
    result = await job.run_startup_repair(now_ms=BASE_EPOCH_MS)

    assert result.days == ()
    assert result.through_day is None


async def test_the_first_repair_builds_the_whole_history(
    database: Database, repository: AnalyticsRepository, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """The upgrade path: the rollup tables exist but have never been written."""
    world = await seed_random_world(database, 21, zone=zone, days=5, sightings=100)
    now_ms = day_bounds_ms(world.days()[-1], zone)[0] + 12 * MS_PER_HOUR

    result = await job.run_startup_repair(now_ms=now_ms)

    assert result.days == tuple(world.days())
    assert result.sightings == len(world.sightings)
    for day in world.days():
        closed = day != world.days()[-1]
        assert await stored_rollup(repository, day) == brute_force_day(world, day, closed=closed)


async def test_the_repair_advances_the_watermark_to_the_last_closed_day(
    database: Database, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """Today is still accumulating, so claiming it complete would be a lie."""
    world = await seed_random_world(database, 21, zone=zone, days=5, sightings=100)
    today = world.days()[-1]
    now_ms = day_bounds_ms(today, zone)[0] + 12 * MS_PER_HOUR

    result = await job.run_startup_repair(now_ms=now_ms)

    assert result.through_day == world.days()[-2]
    assert await job.watermark() == world.days()[-2]


async def test_a_later_repair_rebuilds_only_from_the_watermark(
    database: Database, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """The ordinary restart: today and yesterday, not five years of history."""
    world = await seed_random_world(database, 21, zone=zone, days=5, sightings=100)
    today = world.days()[-1]
    now_ms = day_bounds_ms(today, zone)[0] + 12 * MS_PER_HOUR
    await job.run_startup_repair(now_ms=now_ms)

    result = await job.run_startup_repair(now_ms=now_ms)

    assert result.days == (world.days()[-2], today)


async def test_a_watermark_ahead_of_today_still_repairs_yesterday_and_today(
    database: Database, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """A clock that moved backwards, or a changed timezone. Never rebuild less."""
    world = await seed_random_world(database, 21, zone=zone, days=3, sightings=40)
    today = world.days()[-1]
    await job.set_watermark(shift_days(today, 30))

    planned = await job.plan_startup_repair(now_ms=day_bounds_ms(today, zone)[0])

    assert planned == [shift_days(today, -1), today]


async def test_an_unreadable_watermark_costs_a_slower_boot_not_a_failed_one(
    database: Database, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """The watermark optimizes a rebuild that is always correct without it."""
    world = await seed_random_world(database, 21, zone=zone, days=3, sightings=40)
    await MetaRepository(database).set(META_KEY_ROLLUP_THROUGH_DAY, "not-a-date")

    assert await job.watermark() is None
    planned = await job.plan_startup_repair(now_ms=day_bounds_ms(world.days()[-1], zone)[1] - 1)
    assert planned == world.days()


async def test_the_repair_pass_is_bounded_and_resumes_on_the_next_boot(
    database: Database, repository: AnalyticsRepository, zone: ZoneInfo
) -> None:
    """A long history is rebuilt oldest-first across boots, never in one scan."""
    world = await seed_random_world(database, 33, zone=zone, days=6, sightings=60)
    job = backfill(repository, zone, max_days=2)
    now_ms = day_bounds_ms(world.days()[-1], zone)[0] + 12 * MS_PER_HOUR

    first = await job.run_startup_repair(now_ms=now_ms)
    second = await job.run_startup_repair(now_ms=now_ms)

    assert first.days == tuple(world.days()[:2])
    assert first.truncated is True
    assert second.days == tuple(world.days()[2:4])
    assert await job.watermark() == world.days()[3]


async def test_a_missing_day_inside_the_watermarked_range_is_still_repaired_by_a_full_rebuild(
    database: Database, repository: AnalyticsRepository, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """Deleting the watermark is the documented "rebuild everything" lever."""
    world = await seed_random_world(database, 21, zone=zone, days=4, sightings=60)
    now_ms = day_bounds_ms(world.days()[-1], zone)[1]
    await job.run_startup_repair(now_ms=now_ms)
    async with database.writer_session() as session:
        await session.execute(
            text("DELETE FROM daily_stats WHERE day = :day"),
            {"day": world.days()[0]},
        )
    await MetaRepository(database).delete(META_KEY_ROLLUP_THROUGH_DAY)

    await job.run_startup_repair(now_ms=now_ms)

    assert await stored_rollup(repository, world.days()[0]) == brute_force_day(
        world, world.days()[0], closed=True
    )


# ------------------------------------------------------------- type_stats


async def test_type_stats_are_receiver_relative_totals_since_t0(
    database: Database, repository: AnalyticsRepository, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """One row per designator this receiver has actually heard (§6.5)."""
    world = await seed_random_world(database, 21, zone=zone, days=4, sightings=80)
    await job.refresh_type_stats()

    stats = {row.type_code: row for row in await repository.type_stats()}

    expected: dict[str, list[SeedAircraft]] = {}
    for airframe in world.aircraft:
        if airframe.type_code is not None:
            expected.setdefault(airframe.type_code, []).append(airframe)
    assert stats.keys() == expected.keys()
    for code, airframes in expected.items():
        assert stats[code].unique_aircraft == len(airframes)
        assert stats[code].total_sightings == sum(row.sighting_count for row in airframes)
        assert stats[code].first_seen_ms == min(row.first_seen_ms for row in airframes)
        assert stats[code].last_seen_ms == max(row.last_seen_ms for row in airframes)


async def test_a_type_that_leaves_the_fleet_leaves_the_table(
    database: Database, repository: AnalyticsRepository, job: AnalyticsBackfill
) -> None:
    """A whole-table replacement, so a stale designator cannot linger forever."""
    await seed_world(
        database,
        zone=ZoneInfo(NEW_YORK),
        aircraft=[
            SeedAircraft(
                icao24="a00001",
                first_seen_ms=BASE_EPOCH_MS,
                last_seen_ms=BASE_EPOCH_MS,
                type_code="B738",
            )
        ],
        sightings=[SeedSighting(icao24="a00001", started_ms=BASE_EPOCH_MS)],
    )
    assert await job.refresh_type_stats() == 1

    async with database.writer_session() as session:
        await session.execute(
            text("UPDATE aircraft_metadata_resolved SET type_code = NULL WHERE icao24 = 'a00001'")
        )

    assert await job.refresh_type_stats() == 0
    assert await repository.type_stats() == ()


async def test_the_startup_repair_refreshes_type_stats_even_with_nothing_to_rebuild(
    database: Database, repository: AnalyticsRepository, job: AnalyticsBackfill, zone: ZoneInfo
) -> None:
    """A metadata import that landed while the process was down must show up."""
    world = await seed_random_world(database, 21, zone=zone, days=2, sightings=30)
    await job.run_startup_repair(now_ms=day_bounds_ms(world.days()[-1], zone)[1] - 1)

    assert len(await repository.type_stats()) > 0


# --------------------------------------------------------- across the zones


@pytest.mark.parametrize("zone_name", [NEW_YORK, KOLKATA])
async def test_a_full_repair_reproduces_brute_force_in_both_zones(
    database: Database, repository: AnalyticsRepository, zone_name: str
) -> None:
    zone = ZoneInfo(zone_name)
    world = await seed_random_world(
        database, 77, zone=zone, first_day="2026-03-06", days=6, sightings=140
    )
    job = backfill(repository, zone)
    now_ms = day_bounds_ms(world.days()[-1], zone)[1]

    await job.run_startup_repair(now_ms=now_ms)

    for day in world.days():
        assert await stored_rollup(repository, day) == brute_force_day(world, day, closed=True)


def test_the_backfill_refuses_a_nonsense_bound(
    repository: AnalyticsRepository, zone: ZoneInfo
) -> None:
    with pytest.raises(ValueError, match="max_days"):
        backfill(repository, zone, max_days=0)


async def test_the_watermark_round_trips_through_meta(
    job: AnalyticsBackfill, database: Database
) -> None:
    await job.set_watermark("2026-06-02")

    assert await job.watermark() == "2026-06-02"
    assert await MetaRepository(database).get(META_KEY_ROLLUP_THROUGH_DAY) == "2026-06-02"
    assert next_day(await job.watermark() or "") == "2026-06-03"


def test_the_world_helper_reports_the_days_it_actually_placed(zone: ZoneInfo) -> None:
    """Guard on the fixture itself: a silent empty world would pass everything."""
    world = World(aircraft=(), sightings=(), group_ids={}, zone=zone)

    assert world.days() == []
