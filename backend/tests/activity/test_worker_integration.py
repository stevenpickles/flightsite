"""The seam end to end: real observations through the real worker into the feed.

Everything else in this suite drives the activity service against seeded rows.
This file drives the *pipeline*: decoder observations into the live store, the
live store into the persistence worker, the worker's committed cycles out
through :meth:`~flightsite.sightings.worker.PersistenceWorker.subscribe_lifecycle`,
and the activity service's pass into ``activity_events`` — on one simulated
clock, so a ten-minute closure gap costs microseconds
(``docs/TEST_STRATEGY.md`` §3).

It exists to catch the class of bug no unit test can: a watermark that
disagrees with the ids the worker actually assigned, a seam that fires before
a row exists, or — the roadmap's own criterion — a *restart* that narrates
something the previous process already narrated. The restart drill here is the
real one: the service is destroyed, a new one is constructed against the same
database, and the aircraft is heard again.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from flightsite.activity import ActivityService
from flightsite.counters import CounterRegistry
from flightsite.db import ActivityEvent, Database
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker

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

#: Long enough that no background tick fires: every cycle and every pass is one
#: the test asked for.
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


def build_activity(
    database: Database, worker: PersistenceWorker, clock: SimulatedTime
) -> ActivityService:
    """An activity service subscribed to the real worker, on the real clock."""
    return ActivityService(
        database=database,
        persistence=worker,
        flush_interval_s=NEVER_S,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )


@pytest.fixture
async def activity(
    database: Database, worker: PersistenceWorker, clock: SimulatedTime
) -> AsyncIterator[ActivityService]:
    service = build_activity(database, worker, clock)
    await service.start()
    try:
        yield service
    finally:
        if service.running:
            await service.stop()


async def recorded_keys(database: Database) -> list[str]:
    """Every dedupe key in the feed — the identity a duplicate would repeat."""
    async with database.read_session() as session:
        return sorted(key for key in await session.scalars(select(ActivityEvent.dedupe_key)) if key)


async def test_an_aircraft_heard_for_the_first_time_reaches_the_feed(
    live: LiveStore,
    worker: PersistenceWorker,
    activity: ActivityService,
    clock: SimulatedTime,
    database: Database,
) -> None:
    """One observation, one committed cycle, one pass, one event.

    The watermark was initialized on an empty database, so the sighting this
    cycle opens is genuinely above it — which is the ordinary path and the one
    that has to work before any drill means anything.
    """
    observe(live, clock, position=north_of(SEATTLE, 42.0))
    await worker.process_pending()

    await activity.flush()

    assert await recorded_keys(database) == [f"first_ever_aircraft:{ICAO}"]


async def test_the_same_airframe_heard_again_is_not_a_first_sighting(
    live: LiveStore,
    worker: PersistenceWorker,
    activity: ActivityService,
    clock: SimulatedTime,
    database: Database,
) -> None:
    """A second sighting of a known airframe opens a real row and announces nothing.

    The row is genuinely new — a new ``sightings`` id above the watermark, so
    the pass does examine it — and the producer's own judgement is what keeps
    it quiet. This is the difference between "not looked at" and "looked at and
    found unremarkable", and only the pipeline can tell them apart.
    """
    observe(live, clock)
    await worker.process_pending()
    await activity.flush()

    # It leaves, its closure gap expires, and it is heard again.
    clock.advance(120.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(CLOSE_S + 1.0)
    await worker.process_pending()
    observe(live, clock)
    await worker.process_pending()

    await activity.flush()

    assert await recorded_keys(database) == [f"first_ever_aircraft:{ICAO}"]


async def test_a_restarted_service_narrates_nothing_the_previous_one_did(
    live: LiveStore,
    worker: PersistenceWorker,
    clock: SimulatedTime,
    database: Database,
) -> None:
    """The roadmap's criterion, drilled through the real pipeline.

    A process hears two airframes and records them; the process ends; a new one
    starts against the same database and hears one of them again. The restart
    writes nothing, because every key it recomputes is one already stored.
    """
    first = build_activity(database, worker, clock)
    await first.start()
    observe_many(live, clock, [ICAO, OTHER_ICAO])
    await worker.process_pending()
    await first.flush()
    before = await recorded_keys(database)
    await first.stop()

    assert before == sorted([f"first_ever_aircraft:{ICAO}", f"first_ever_aircraft:{OTHER_ICAO}"])

    second = build_activity(database, worker, clock)
    await second.start()
    clock.advance(30.0)
    observe(live, clock)
    await worker.process_pending()
    result = await second.flush()
    await second.stop()

    assert result.recorded == 0
    assert await recorded_keys(database) == before


async def test_a_service_that_missed_a_cycle_entirely_catches_up(
    live: LiveStore,
    worker: PersistenceWorker,
    clock: SimulatedTime,
    database: Database,
) -> None:
    """The worker keeps writing while the detector is down; the watermark repairs it.

    This is the failure the lifecycle seam alone could not survive — the
    notification for a cycle committed while nothing was subscribed is simply
    gone — and it is why opens are found by scanning ``sightings`` rather than
    by trusting the seam.
    """
    started = build_activity(database, worker, clock)
    await started.start()
    observe(live, clock)
    await worker.process_pending()
    await started.flush()
    await started.stop()

    # Nothing is listening, and the worker commits another airframe's sighting.
    clock.advance(30.0)
    observe(live, clock, OTHER_ICAO)
    await worker.process_pending()

    resumed = build_activity(database, worker, clock)
    await resumed.start()
    await resumed.flush()
    await resumed.stop()

    assert await recorded_keys(database) == sorted(
        [f"first_ever_aircraft:{ICAO}", f"first_ever_aircraft:{OTHER_ICAO}"]
    )


async def test_a_committed_close_reaches_the_service_through_the_seam(
    live: LiveStore,
    worker: PersistenceWorker,
    activity: ActivityService,
    clock: SimulatedTime,
) -> None:
    """The notification fires after the ids exist, which is what makes it usable.

    The service only stores the ids, so what this asserts is the contract it
    depends on: by the time a listener runs, the sighting it names is a
    committed row a query would find.
    """
    observe_many(live, clock, [ICAO, OTHER_ICAO])
    await worker.process_pending()
    await activity.flush()

    clock.advance(120.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(CLOSE_S + 1.0)
    await worker.process_pending()

    # Both sightings closed in that cycle, and the seam named both of them.
    result = await activity.flush()

    assert result.examined == 2
