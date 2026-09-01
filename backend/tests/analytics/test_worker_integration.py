"""The seam end to end: real observations through the real worker into rollups.

Everything else in this suite drives the analytics service directly. This file
drives the *pipeline*: decoder observations into the live store, the live store
into the persistence worker, the worker's committed cycles out through
:meth:`~flightsite.sightings.worker.PersistenceWorker.subscribe_lifecycle`, and
the analytics service's flush into the four rollup tables — on one simulated
clock, so a ten-minute closure gap and a midnight crossing both cost
microseconds (``docs/TEST_STRATEGY.md`` §3).

What it is here to catch is the class of bug no unit test can: a seam that
fires at the wrong moment, an id that is not assigned yet when the notification
goes out, or a rollup that disagrees with the ``sightings`` rows the same
process just wrote.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from flightsite.analytics.bucketing import local_day
from flightsite.analytics.repository import AnalyticsRepository
from flightsite.analytics.service import AnalyticsService
from flightsite.counters import CounterRegistry
from flightsite.db import Database, Sighting
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker
from flightsite.sightings.worker import SightingLifecycle

from ..sightings.conftest import (
    CLOSE_S,
    FLUSH_INTERVAL_S,
    ICAO,
    OTHER_ICAO,
    REMOVE_S,
    SEATTLE,
    STALE_S,
    SimulatedTime,
    north_of,
    observe,
    observe_many,
)
from .conftest import NEW_YORK

#: The zone this whole suite buckets in. The pipeline fixtures come from the
#: sightings suite, which stamps its observations in UTC; naming the zone here
#: keeps every day boundary in this file in one place.
ZONE_NAME = NEW_YORK

#: Long enough that no background tick fires: every cycle and every flush is
#: one the test asked for.
NEVER_S = 3_600.0


@pytest.fixture
def clock() -> SimulatedTime:
    """The sightings suite's simulated time: one number driving three clocks."""
    return SimulatedTime()


@pytest.fixture
def live(clock: SimulatedTime) -> LiveStore:
    """A live store on the product defaults and a known receiver location."""
    return LiveStore(
        stale_s=STALE_S,
        remove_s=REMOVE_S,
        receiver_location=SEATTLE,
        clock=clock.monotonic,
    )


@pytest.fixture
async def worker(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> AsyncIterator[PersistenceWorker]:
    """A started persistence worker whose cycles the test drives by hand."""
    instance = PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        flush_interval_s=FLUSH_INTERVAL_S,
        tick_interval_s=NEVER_S,
        clock=clock.epoch_ms,
    )
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()


@pytest.fixture
async def analytics(
    database: Database, worker: PersistenceWorker, clock: SimulatedTime
) -> AsyncIterator[AnalyticsService]:
    """An analytics service subscribed to the real worker, on the real clock."""
    service = AnalyticsService(
        database=database,
        persistence=worker,
        timezone=ZONE_NAME,
        flush_interval_s=NEVER_S,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )
    await service.start()
    try:
        yield service
    finally:
        if service.running:
            await service.stop()


async def _sighting_count(database: Database) -> int:
    async with database.read_session() as session:
        return int(await session.scalar(select(func.count(Sighting.id))) or 0)


async def test_an_opened_sighting_reaches_the_rollup_through_the_seam(
    database: Database,
    live: LiveStore,
    worker: PersistenceWorker,
    analytics: AnalyticsService,
    clock: SimulatedTime,
    repository: AnalyticsRepository,
) -> None:
    zone = ZoneInfo(ZONE_NAME)
    observe(live, clock, position=north_of(SEATTLE, 42.0))
    await worker.process_pending()

    assert analytics.dirty_days == frozenset({local_day(clock.epoch_ms(), zone)})
    await analytics.flush()

    rollup = await repository.day(local_day(clock.epoch_ms(), zone))
    assert rollup is not None
    assert (rollup.sightings, rollup.unique_aircraft, rollup.new_aircraft) == (1, 1, 1)


async def test_the_rollup_matches_the_sightings_the_same_process_wrote(
    database: Database,
    live: LiveStore,
    worker: PersistenceWorker,
    analytics: AnalyticsService,
    clock: SimulatedTime,
    repository: AnalyticsRepository,
) -> None:
    """Three airframes, one of them heard twice across a closure gap."""
    zone = ZoneInfo(ZONE_NAME)
    observe_many(live, clock, [ICAO, OTHER_ICAO, "abcdef"])
    await worker.process_pending()

    # The first aircraft leaves and its gap expires: one closed sighting.
    clock.advance(120.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(CLOSE_S + 1.0)
    await worker.process_pending()

    # ...then comes back, which opens a second sighting for the same airframe.
    observe(live, clock, ICAO)
    await worker.process_pending()

    await analytics.flush()
    day = local_day(clock.epoch_ms(), zone)
    rollup = await repository.day(day)

    assert rollup is not None
    assert rollup.sightings == await _sighting_count(database)
    assert (rollup.sightings, rollup.unique_aircraft, rollup.new_aircraft) == (4, 3, 3)


async def test_a_closed_sighting_carries_its_final_range_into_the_day(
    live: LiveStore,
    worker: PersistenceWorker,
    analytics: AnalyticsService,
    clock: SimulatedTime,
    repository: AnalyticsRepository,
) -> None:
    """The range is only final at close; the seam re-dirties the opening day."""
    zone = ZoneInfo(ZONE_NAME)
    observe(live, clock, position=north_of(SEATTLE, 30.0))
    await worker.process_pending()
    await analytics.flush()

    clock.advance(60.0)
    observe(live, clock, position=north_of(SEATTLE, 210.0))
    clock.advance(120.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(CLOSE_S + 1.0)
    await worker.process_pending()
    await analytics.flush()

    rollup = await repository.day(local_day(clock.epoch_ms(), zone))
    assert rollup is not None
    assert rollup.max_range_nm == pytest.approx(210.0, abs=0.5)


async def test_a_worker_with_no_listener_still_commits_its_cycle(
    database: Database, live: LiveStore, worker: PersistenceWorker, clock: SimulatedTime
) -> None:
    """The seam is optional: persistence has no dependency on analytics."""
    observe(live, clock)

    result = await worker.process_pending()

    assert result.opened == 1
    assert await _sighting_count(database) == 1


async def test_a_listener_that_raises_cannot_fail_a_committed_cycle(
    database: Database, live: LiveStore, worker: PersistenceWorker, clock: SimulatedTime
) -> None:
    """The transaction has already committed; an exception could only make the
    worker retry writes that already landed."""

    def explode(_: SightingLifecycle) -> None:
        raise RuntimeError("listener bug")

    worker.subscribe_lifecycle(explode)
    observe(live, clock)

    result = await worker.process_pending()

    assert result.failed is False
    assert result.opened == 1
    assert await _sighting_count(database) == 1


async def test_subscribing_twice_notifies_once_and_unsubscribing_detaches(
    live: LiveStore, worker: PersistenceWorker, clock: SimulatedTime
) -> None:
    seen: list[SightingLifecycle] = []
    worker.subscribe_lifecycle(seen.append)
    worker.subscribe_lifecycle(seen.append)

    observe(live, clock)
    await worker.process_pending()
    assert len(seen) == 1

    worker.unsubscribe_lifecycle(seen.append)
    worker.unsubscribe_lifecycle(seen.append)
    observe(live, clock, OTHER_ICAO)
    await worker.process_pending()

    assert len(seen) == 1


async def test_the_notification_carries_ids_the_database_can_be_queried_with(
    database: Database, live: LiveStore, worker: PersistenceWorker, clock: SimulatedTime
) -> None:
    """Ids are assigned after the commit, so the seam must fire after that."""
    seen: list[SightingLifecycle] = []
    worker.subscribe_lifecycle(seen.append)
    observe(live, clock)

    await worker.process_pending()

    (event,) = seen
    (opened,) = event.opened
    async with database.read_session() as session:
        row = await session.get(Sighting, opened.sighting_id)
    assert row is not None
    assert (row.aircraft_id, row.started_ms) == (opened.aircraft_id, opened.started_ms)


async def test_the_analytics_service_detaches_from_the_worker_when_stopped(
    live: LiveStore, worker: PersistenceWorker, analytics: AnalyticsService, clock: SimulatedTime
) -> None:
    await analytics.stop()

    observe(live, clock)
    await worker.process_pending()

    assert analytics.dirty_days == frozenset()
