"""Backpressure: a stalled writer must cost persistence, never ingestion.

This is the acceptance criterion the roadmap states for slice 009 — *"ingestion
throughput unaffected by artificially slowed writer; hot path performs zero
synchronous DB reads/writes"* — and the invariant ADR-0008 exists to hold. The
measurement is direct: stall the writer, then time
:meth:`~flightsite.live.store.LiveStore.apply` while it is stalled.

The second half of the file covers what happens once the bounded queue actually
overflows. Shedding is acceptable and stalling is not, but a gap must never be
delivered as continuity: the worker resyncs from the live snapshot, opens the
sightings it missed, and arms closure for the removals it missed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.counters import LIVE_EVENTS_DROPPED, counters
from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker

from .conftest import (
    CLOSE_S,
    REMOVE_S,
    SimulatedTime,
    aircraft_row,
    observe,
    observe_many,
    sightings_of,
)

#: How long each writer transaction is held open in the stall test. Long
#: against an event-loop hop, short against a test run.
STALL_S = 0.05

#: Batches timed in each phase of the stall comparison.
SAMPLES = 40

#: How much slower applying a batch may be while the writer is stalled than
#: while nothing is persisting at all. Ingestion touches no database on either
#: side, so the honest answer is "not at all"; the allowance absorbs scheduler
#: noise on a loaded machine, and the stall it is compared against is orders of
#: magnitude larger than the allowance.
STALLED_SLOWDOWN_ALLOWANCE = 4.0

#: Floor under that ratio, so a baseline measured in microseconds cannot make
#: the comparison hypersensitive.
MINIMUM_ALLOWANCE_S = 0.005

#: The absolute ceiling ``docs/ARCHITECTURE.md`` §3.3 gives applying a batch:
#: an apply approaching the polling interval turns the live picture into a
#: backlog, stalled writer or not.
APPLY_BUDGET_S = 0.1

FLEET = tuple(f"a0{index:04x}" for index in range(100))


async def median_apply_time(live: LiveStore, clock: SimulatedTime) -> float:
    """Median seconds to apply one :data:`FLEET`-sized batch.

    The median rather than the maximum, for the reason ``tests/live/test_perf``
    gives: this must fail on a regression in the code, not on a garbage
    collection landing inside one of the samples.
    """
    samples: list[float] = []
    for _ in range(SAMPLES):
        clock.advance(1.0)
        started = time.perf_counter()
        observe_many(live, clock, FLEET)
        samples.append(time.perf_counter() - started)
        # Hand the loop over between batches so anything else that wants to run
        # — the stalled worker, in the second phase — actually does.
        await asyncio.sleep(0)
    samples.sort()
    return samples[len(samples) // 2]


class StallingDatabase(Database):
    """A database whose every writer transaction takes :data:`STALL_S`."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.stalls = 0

    @asynccontextmanager
    async def writer_session(self) -> AsyncIterator[AsyncSession]:
        async with super().writer_session() as session:
            self.stalls += 1
            await asyncio.sleep(STALL_S)
            yield session


@pytest.fixture
async def stalling_database(db_path: Path) -> AsyncIterator[StallingDatabase]:
    instance = StallingDatabase(db_path)
    try:
        await instance.upgrade_to("head")
        yield instance
    finally:
        await instance.dispose()


@pytest.mark.perf
async def test_ingestion_is_unaffected_by_a_stalled_writer(
    stalling_database: StallingDatabase, live: LiveStore, clock: SimulatedTime
) -> None:
    worker = PersistenceWorker(
        database=stalling_database,
        live=live,
        close_s=CLOSE_S,
        tick_interval_s=0.001,
        clock=clock.epoch_ms,
    )
    # Baseline first, with nothing consuming and nothing writing: this is what
    # applying a batch costs when the database is not in the picture at all.
    observe_many(live, clock, FLEET)
    baseline_s = await median_apply_time(live, clock)

    await worker.start()
    try:
        stalled_s = await median_apply_time(live, clock)

        assert stalling_database.stalls > 0, "the writer never stalled; the test proved nothing"
        allowance_s = max(baseline_s * STALLED_SLOWDOWN_ALLOWANCE, MINIMUM_ALLOWANCE_S)
        assert stalled_s <= allowance_s, (
            f"applying a batch cost {stalled_s * 1_000:.2f} ms with the writer stalled "
            f"for {STALL_S * 1_000:.0f} ms per transaction, against a "
            f"{baseline_s * 1_000:.2f} ms baseline"
        )
        assert stalled_s <= APPLY_BUDGET_S
        assert len(live) == len(FLEET)
    finally:
        await worker.stop()


async def test_a_stalled_writer_never_loses_the_live_picture(
    stalling_database: StallingDatabase, live: LiveStore, clock: SimulatedTime
) -> None:
    # Persistence may lag arbitrarily; the live store is authoritative for
    # "now" and answers from memory throughout (ARCHITECTURE §3.1).
    worker = PersistenceWorker(
        database=stalling_database,
        live=live,
        close_s=CLOSE_S,
        tick_interval_s=0.001,
        clock=clock.epoch_ms,
    )
    await worker.start()
    try:
        observe_many(live, clock, FLEET)
        counts = live.counts()

        assert counts.total == len(FLEET)
        assert live.get(FLEET[0]) is not None
    finally:
        await worker.stop()


async def test_an_overflowing_queue_resyncs_from_the_snapshot(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    # A queue of four against a hundred aircraft: the worker sees the tail and
    # is told, by the overflow flag, that it missed the rest.
    worker = PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        tick_interval_s=3_600.0,
        queue_size=4,
        clock=clock.epoch_ms,
    )
    await worker.start()
    try:
        observe_many(live, clock, FLEET)

        result = await worker.process_pending()

        assert result.resynced is True
        assert result.opened == len(FLEET)
        assert worker.active_count == len(FLEET)
        for icao in (FLEET[0], FLEET[50], FLEET[-1]):
            assert await aircraft_row(database, icao) is not None
    finally:
        await worker.stop()


async def test_the_overflow_episode_is_acknowledged_and_counted(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    worker = PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        tick_interval_s=3_600.0,
        queue_size=4,
        clock=clock.epoch_ms,
    )
    await worker.start()
    try:
        observe_many(live, clock, FLEET)
        await worker.process_pending()

        assert counters.snapshot()[LIVE_EVENTS_DROPPED] > 0

        # The episode is over: a following quiet cycle is an ordinary one.
        clock.advance(1.0)
        observe(live, clock, FLEET[0])
        assert (await worker.process_pending()).resynced is False
    finally:
        await worker.stop()


async def test_a_shed_removal_still_starts_the_closure_gap(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    # The worst thing an overflow could do is leave a sighting open forever
    # because its removal event was the one that got shed. The resync notices
    # the aircraft is no longer in the live set and arms the gap.
    watched, crowd = FLEET[0], FLEET[1:8]
    worker = PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        tick_interval_s=3_600.0,
        queue_size=4,
        clock=clock.epoch_ms,
    )
    await worker.start()
    try:
        observe(live, clock, watched)
        observe_many(live, clock, crowd)
        await worker.process_pending()
        assert worker.active_count == 1 + len(crowd)

        # The watched aircraft goes silent and is removed; the crowd keeps
        # transmitting hard enough to push that removal out of the queue.
        clock.advance(REMOVE_S + 1.0)
        live.sweep()
        for _ in range(4):
            clock.advance(1.0)
            observe_many(live, clock, crowd)

        result = await worker.process_pending()

        assert result.resynced is True
        assert worker.sighting_for(watched) is not None
        assert worker.pending_count == 1
        assert worker.active_count == len(crowd)

        clock.advance(CLOSE_S)
        await worker.process_pending()
        closed = (await sightings_of(database, watched))[0]
        assert closed.ended_ms is not None
    finally:
        await worker.stop()


async def test_a_resync_does_not_duplicate_existing_sightings(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    worker = PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        tick_interval_s=3_600.0,
        queue_size=4,
        clock=clock.epoch_ms,
    )
    await worker.start()
    try:
        observe(live, clock, FLEET[0])
        await worker.process_pending()
        for _ in range(20):
            clock.advance(1.0)
            observe_many(live, clock, FLEET[:10])

        assert (await worker.process_pending()).resynced is True

        assert len(await sightings_of(database, FLEET[0])) == 1
    finally:
        await worker.stop()
