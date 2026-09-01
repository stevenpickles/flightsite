"""The incremental maintainer: the seam, day rollover, convergence, restarts.

The three properties slice 031 is judged on that only exist once the service is
running:

* **Convergence.** Rollups maintained incrementally as sightings arrive equal
  the rollups a from-scratch backfill produces — and both equal brute force.
* **Restart mid-day continuity.** A process that stops halfway through a day
  and starts again finishes with the same rows as one that never stopped.
* **Day rollover.** ``busiest_hour`` is written when — and only when — the day
  closes, and the watermark advances with it.

Everything here runs on a hand-driven clock and calls
:meth:`~flightsite.analytics.service.AnalyticsService.flush` explicitly, so a
midnight crossing costs no wall-clock time and no test depends on a background
task having been scheduled (``docs/TEST_STRATEGY.md`` §3).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from flightsite.analytics.backfill import AnalyticsBackfill, BackfillResult
from flightsite.analytics.bucketing import day_bounds_ms, local_day, shift_days
from flightsite.analytics.repository import AnalyticsRepository
from flightsite.analytics.service import AnalyticsService
from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.sightings.worker import SightingLifecycle, SightingRef

from .conftest import (
    KOLKATA,
    MS_PER_HOUR,
    NEW_YORK,
    ManualClock,
    World,
    brute_force_day,
    random_world,
    seed_random_world,
    seed_world,
    stored_rollup,
)

#: Long enough that no background flush ever fires during a test: every pass is
#: one the test asked for.
NEVER_S = 3_600.0


def build_service(
    database: Database,
    clock: ManualClock,
    *,
    timezone: str = NEW_YORK,
    counters: CounterRegistry | None = None,
) -> AnalyticsService:
    """A service with no persistence worker and no background cadence."""
    return AnalyticsService(
        database=database,
        persistence=None,
        timezone=timezone,
        flush_interval_s=NEVER_S,
        clock=clock,
        counters=counters if counters is not None else CounterRegistry(),
    )


@pytest.fixture
async def service(database: Database, clock: ManualClock) -> AsyncIterator[AnalyticsService]:
    instance = build_service(database, clock)
    try:
        yield instance
    finally:
        if instance.running:
            await instance.stop()


def _ref(prefix: str, index: int, started_ms: int, *, ended: bool) -> SightingRef:
    return SightingRef(
        icao=f"{prefix}{index:04x}",
        aircraft_id=index,
        sighting_id=index,
        started_ms=started_ms,
        ended_ms=started_ms + 1 if ended else None,
    )


def lifecycle(
    at_ms: int, *, opened: tuple[int, ...] = (), closed: tuple[int, ...] = ()
) -> SightingLifecycle:
    """A lifecycle notification naming sightings by their start instant."""
    return SightingLifecycle(
        at_ms=at_ms,
        opened=tuple(
            _ref("a0", index, ms, ended=False) for index, ms in enumerate(opened, start=1)
        ),
        closed=tuple(_ref("b0", index, ms, ended=True) for index, ms in enumerate(closed, start=1)),
    )


# ------------------------------------------------------------------ the seam


async def test_a_committed_cycle_marks_the_day_its_sightings_started_in(
    service: AnalyticsService, zone: ZoneInfo, clock: ManualClock
) -> None:
    yesterday = shift_days(local_day(clock.now_ms, zone), -1)
    started_ms = day_bounds_ms(yesterday, zone)[0] + 3 * MS_PER_HOUR

    service.record_lifecycle(lifecycle(clock.now_ms, opened=(started_ms,)))

    assert service.dirty_days == frozenset({yesterday})


async def test_a_close_re_dirties_the_day_the_sighting_opened_on(
    service: AnalyticsService, zone: ZoneInfo, clock: ManualClock
) -> None:
    """An aircraft overhead across midnight still belongs to the day it arrived."""
    yesterday = shift_days(local_day(clock.now_ms, zone), -1)
    started_ms = day_bounds_ms(yesterday, zone)[1] - 600_000

    service.record_lifecycle(lifecycle(clock.now_ms, closed=(started_ms,)))

    assert service.dirty_days == frozenset({yesterday})


async def test_an_empty_cycle_dirties_nothing(
    service: AnalyticsService, clock: ManualClock
) -> None:
    service.record_lifecycle(lifecycle(clock.now_ms))

    assert service.dirty_days == frozenset()


# --------------------------------------------------------------- the flushes


async def test_a_flush_with_nothing_dirty_writes_nothing(
    database: Database, service: AnalyticsService, repository: AnalyticsRepository
) -> None:
    await seed_random_world(database, 4, zone=ZoneInfo(NEW_YORK), days=2, sightings=20)

    result = await service.flush()

    assert result.days == ()
    assert (await repository.counts())["daily_stats"] == 0


async def test_a_flush_rebuilds_the_dirty_day_and_today(
    database: Database,
    service: AnalyticsService,
    repository: AnalyticsRepository,
    clock: ManualClock,
    zone: ZoneInfo,
) -> None:
    """Today rides along: a sighting closing after midnight dirties yesterday
    while today's row is the one a client is looking at."""
    world = await seed_random_world(database, 4, zone=zone, days=3, sightings=40)
    clock.set_local(world.days()[-1], 12, zone)
    service.mark_dirty(world.days()[0])

    result = await service.flush()

    assert set(result.days) == {world.days()[0], world.days()[-1]}
    assert await stored_rollup(repository, world.days()[0]) == brute_force_day(
        world, world.days()[0], closed=True
    )


async def test_a_failed_flush_keeps_the_days_dirty_and_counts_the_error(
    database: Database, clock: ManualClock, zone: ZoneInfo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is marked clean that was not written."""

    async def boom(*_: object, **__: object) -> BackfillResult:
        raise OSError("disk gone")

    counters = CounterRegistry()
    service = build_service(database, clock, counters=counters)
    world = await seed_random_world(database, 4, zone=zone, days=2, sightings=20)
    service.mark_dirty(world.days()[0])
    monkeypatch.setattr(AnalyticsBackfill, "rebuild_days", boom)

    result = await service.flush()

    assert result.failed is True
    assert world.days()[0] in service.dirty_days
    assert counters.snapshot()[DB_ERRORS_COUNTER] == 1


# ------------------------------------------------------------- day rollover


async def test_crossing_local_midnight_finalizes_the_day_that_ended(
    database: Database,
    service: AnalyticsService,
    repository: AnalyticsRepository,
    clock: ManualClock,
    zone: ZoneInfo,
) -> None:
    world = await seed_random_world(database, 9, zone=zone, days=2, sightings=40)
    yesterday, today = world.days()
    clock.set_local(yesterday, 20, zone)
    await service.start()
    assert (await stored_rollup(repository, yesterday)).busiest_hour is None

    clock.set_local(today, 1, zone)
    result = await service.flush()

    assert result.day_closed is True
    assert (await stored_rollup(repository, yesterday)) == brute_force_day(
        world, yesterday, closed=True
    )
    assert await service.backfill.watermark() == yesterday


async def test_a_process_asleep_for_several_days_finalizes_every_one_of_them(
    database: Database,
    service: AnalyticsService,
    repository: AnalyticsRepository,
    clock: ManualClock,
    zone: ZoneInfo,
) -> None:
    """A suspended Pi wakes up owing more than one busiest hour."""
    world = await seed_random_world(database, 9, zone=zone, days=5, sightings=100)
    clock.set_local(world.days()[0], 20, zone)
    await service.start()

    clock.set_local(world.days()[-1], 4, zone)
    result = await service.flush()

    assert result.day_closed is True
    for day in world.days()[:-1]:
        assert (await stored_rollup(repository, day)).busiest_hour is not None
    assert await service.backfill.watermark() == world.days()[-2]


async def test_a_clock_jumping_years_forward_does_not_rebuild_years_in_one_pass(
    database: Database, service: AnalyticsService, clock: ManualClock, zone: ZoneInfo
) -> None:
    """The cap bites, and the watermark is deliberately left where it was."""
    world = await seed_random_world(database, 9, zone=zone, days=2, sightings=20)
    clock.set_local(world.days()[0], 20, zone)
    await service.start()
    before = await service.backfill.watermark()

    clock.set_local(shift_days(world.days()[-1], 400), 4, zone)
    result = await service.flush()

    assert 0 < result.rebuilt <= 33
    assert await service.backfill.watermark() == before


# -------------------------------------------------------------- convergence


@pytest.mark.parametrize("zone_name", [NEW_YORK, KOLKATA])
@pytest.mark.parametrize("seed", [13, 91])
async def test_incremental_maintenance_converges_with_a_from_scratch_backfill(
    database: Database, clock: ManualClock, zone_name: str, seed: int
) -> None:
    """The convergence property, driven sighting by sighting.

    The world is replayed in order: each sighting is announced through the seam
    exactly as a committed worker cycle would, with a flush after each one — so
    every day is rebuilt many times, from an ever-growing set of sightings, in
    the order they actually happened. The result is compared against a single
    from-scratch rebuild of the same database *and* against brute force.
    """
    zone = ZoneInfo(zone_name)
    aircraft, sightings = random_world(
        seed, zone=zone, first_day="2026-03-06", days=4, sightings=70
    )
    world = await seed_world(database, zone=zone, aircraft=aircraft, sightings=sightings)
    service = build_service(database, clock, timezone=zone_name)
    repository = AnalyticsRepository(database)

    for row in sorted(world.sightings, key=lambda item: item.started_ms):
        clock.now_ms = row.started_ms
        service.record_lifecycle(lifecycle(clock.now_ms, opened=(row.started_ms,)))
        await service.flush()

    clock.set_local(shift_days(world.days()[-1], 1), 6, zone)
    await service.flush()
    incremental = {day: await stored_rollup(repository, day) for day in world.days()}

    await service.backfill.rebuild_days(world.days(), now_ms=clock.now_ms)
    rebuilt = {day: await stored_rollup(repository, day) for day in world.days()}

    assert incremental == rebuilt
    for day in world.days():
        assert incremental[day] == brute_force_day(world, day, closed=True)


async def test_a_restart_mid_day_leaves_the_same_rows_as_never_stopping(
    database: Database, clock: ManualClock, zone: ZoneInfo
) -> None:
    """Restart continuity: the day is rebuilt from ground truth, not resumed."""
    world = await seed_random_world(database, 55, zone=zone, days=3, sightings=60)
    today = world.days()[-1]
    clock.set_local(today, 13, zone)
    repository = AnalyticsRepository(database)

    first = build_service(database, clock)
    await first.start()
    first.mark_dirty(today)
    await first.flush()
    await first.stop()

    before_restart = {day: await stored_rollup(repository, day) for day in world.days()}

    second = build_service(database, clock)
    await second.start()
    await second.flush()
    await second.stop()

    after_restart = {day: await stored_rollup(repository, day) for day in world.days()}
    assert after_restart == before_restart
    for day in world.days():
        assert after_restart[day] == brute_force_day(world, day, closed=day != today)


# --------------------------------------------------------------- lifecycle


async def test_start_repairs_before_anything_can_read_a_rollup_row(
    database: Database, repository: AnalyticsRepository, clock: ManualClock, zone: ZoneInfo
) -> None:
    world = await seed_random_world(database, 66, zone=zone, days=3, sightings=50)
    clock.set_local(world.days()[-1], 9, zone)
    service = build_service(database, clock)

    await service.start()

    assert service.startup_repair.rebuilt == len(world.days())
    assert (await repository.counts())["daily_stats"] == len(world.days())
    await service.stop()


async def test_start_is_idempotent_and_stop_flushes_what_is_dirty(
    database: Database, repository: AnalyticsRepository, clock: ManualClock, zone: ZoneInfo
) -> None:
    world = await seed_random_world(database, 66, zone=zone, days=2, sightings=30)
    clock.set_local(world.days()[-1], 9, zone)
    service = build_service(database, clock)
    await service.start()
    await service.start()
    assert service.running is True

    service.mark_dirty(world.days()[0])
    await service.stop()

    assert service.running is False
    assert service.dirty_days == frozenset()
    assert await stored_rollup(repository, world.days()[0]) == brute_force_day(
        world, world.days()[0], closed=True
    )


async def test_a_failed_startup_repair_degrades_to_a_stale_rollup_not_a_failed_boot(
    database: Database, clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repair that cannot run leaves rollups stale; the process still serves."""

    async def boom(*_: object, **__: object) -> BackfillResult:
        raise OSError("disk gone")

    counters = CounterRegistry()
    service = build_service(database, clock, counters=counters)
    monkeypatch.setattr(AnalyticsBackfill, "run_startup_repair", boom)

    await service.start()

    assert service.running is True
    assert service.startup_repair.rebuilt == 0
    assert counters.snapshot()[DB_ERRORS_COUNTER] == 1
    await service.stop()


async def test_the_background_task_runs_a_pass_on_its_own_cadence(
    database: Database, repository: AnalyticsRepository, clock: ManualClock, zone: ZoneInfo
) -> None:
    """The loop is real, not just a method tests call.

    Its sleep is replaced with one that yields to the loop, so the cadence is
    driven by the test rather than by wall-clock time.
    """
    world = await seed_random_world(database, 66, zone=zone, days=2, sightings=30)
    clock.set_local(world.days()[-1], 9, zone)
    ticks = asyncio.Event()

    async def sleep(_: float) -> None:
        ticks.set()
        await asyncio.sleep(0)

    service = AnalyticsService(
        database=database,
        persistence=None,
        timezone=NEW_YORK,
        clock=clock,
        sleep=sleep,
        counters=CounterRegistry(),
    )
    await service.start()
    service.mark_dirty(world.days()[0])
    await ticks.wait()
    await asyncio.sleep(0)
    await service.stop()

    assert await repository.day(world.days()[0]) is not None


def test_the_service_refuses_a_nonsense_cadence(database: Database) -> None:
    with pytest.raises(ValueError, match="flush_interval_s"):
        AnalyticsService(database=database, flush_interval_s=0.0)


def test_a_world_fixture_with_no_sightings_names_no_days(zone: ZoneInfo) -> None:
    assert World(aircraft=(), sightings=(), group_ids={}, zone=zone).by_icao() == {}


async def test_a_type_resolved_after_the_sighting_reaches_type_stats_on_the_next_pass(
    database: Database, repository: AnalyticsRepository, clock: ManualClock, zone: ZoneInfo
) -> None:
    """The ordinary case: a metadata import lands hours after the airframe did.

    ``type_stats`` is maintained on *type resolution*, not on the sighting, so
    a designator that only became known between two passes must appear without
    waiting for the day to close.
    """
    world = await seed_random_world(database, 88, zone=zone, days=1, sightings=10)
    service = build_service(database, clock)
    clock.set_local(world.days()[0], 20, zone)
    await service.start()
    async with database.writer_session() as session:
        await session.execute(text("DELETE FROM aircraft_metadata_resolved"))
    service.mark_dirty(world.days()[0])
    await service.flush()
    assert await repository.type_stats() == ()

    async with database.writer_session() as session:
        await session.execute(
            text(
                "INSERT INTO aircraft_metadata_resolved (icao24, type_code, updated_ms) "
                "SELECT icao24, 'B738', 1 FROM aircraft"
            )
        )
    service.mark_dirty(world.days()[0])
    await service.flush()

    assert [row.type_code for row in await repository.type_stats()] == ["B738"]
    await service.stop()


async def test_stopping_a_service_that_never_started_is_a_no_op(
    database: Database, clock: ManualClock
) -> None:
    """Shutdown runs on every path, including one where startup never got there."""
    service = build_service(database, clock)

    await service.stop()

    assert service.running is False
    assert service.dirty_days == frozenset()
