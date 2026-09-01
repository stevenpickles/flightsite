"""Receiver metrics beside the persistence worker, under a slowed writer.

The roadmap's constraint for this slice is *"never blocks ingestion"*, and
``docs/ARCHITECTURE.md`` §3.1 states the general form: *"A slow consumer can
lag or drop to a resync; it cannot stall the adapter loop."* Two things have to
be true for that, and both are tested here against a **real** stalled writer
rather than a mocked one:

1. Ingestion — :meth:`~flightsite.live.store.LiveStore.apply`, the call the
   decoder adapter makes on its poll task — stays fast while a metrics
   transaction is stuck on the disk.
2. The sighting worker and the metrics service, sharing the one serialized
   writer, do not deadlock or lose work when they collide. They queue, and
   both batches land.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.service import ReceiverMetricsService
from flightsite.sightings import PersistenceWorker
from tests.receiver_metrics.conftest import SimulatedTime, place

#: Budget for one ingestion batch while the writer is held. Generous by two
#: orders of magnitude against the real cost of applying a batch — the point is
#: that it does not scale with how long the writer is stalled, not the exact
#: number (``docs/ARCHITECTURE.md`` §3.3 owns the real budget).
INGESTION_BUDGET_MS = 50.0


async def test_ingestion_is_unaffected_by_a_stalled_metrics_write(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """The invariant, measured where it matters: on the ingestion call itself."""
    service = ReceiverMetricsService(
        database=database,
        live=live,
        sample_interval_s=15.0,
        flush_interval_s=1.0,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )
    for index in range(50):
        place(live, clock, icao=f"a{index:05d}", bearing_deg=index * 7.0 % 360.0, messages=100)
    clock.advance(15.0)
    await service.sample_once()

    release = asyncio.Event()

    async def hold_the_writer() -> None:
        async with database.writer_session():
            await release.wait()

    holder = asyncio.create_task(hold_the_writer())
    await asyncio.sleep(0)

    # The metrics flush is now queued behind a writer that will not return
    # until this test lets it. Ingestion must not notice.
    flush = asyncio.create_task(service.flush())
    await asyncio.sleep(0)

    elapsed_ms: list[float] = []
    for _ in range(20):
        clock.advance(1.0)
        started = time.perf_counter()
        for index in range(50):
            place(live, clock, icao=f"a{index:05d}", bearing_deg=index * 7.0 % 360.0, messages=200)
        elapsed_ms.append((time.perf_counter() - started) * 1_000.0)
        await asyncio.sleep(0)

    assert not flush.done(), "the metrics flush should still be blocked on the writer"
    worst = max(elapsed_ms)
    assert worst < INGESTION_BUDGET_MS, (
        f"applying observations took {worst:.1f} ms while the writer was held "
        f"(budget {INGESTION_BUDGET_MS:.0f} ms)"
    )

    release.set()
    await holder
    assert await flush is True


async def test_the_metrics_flush_and_the_sighting_worker_both_land(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """Two writers, one lock: they serialize, and neither loses its batch.

    Started concurrently and deliberately colliding. If the metrics service
    opened a writer of its own the two would race for SQLite's file lock; if
    either held the lock across the other's work they would deadlock. Both
    batches landing is the evidence that neither happens.
    """
    worker = PersistenceWorker(
        database=database, live=live, tick_interval_s=3_600.0, clock=clock.epoch_ms
    )
    service = ReceiverMetricsService(
        database=database,
        live=live,
        sample_interval_s=15.0,
        flush_interval_s=1.0,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )
    await worker.start()
    try:
        for index in range(20):
            place(live, clock, icao=f"b{index:05d}", bearing_deg=index * 11.0 % 360.0)
        clock.advance(15.0)
        await service.sample_once()

        cycle, flushed = await asyncio.gather(worker.process_pending(), service.flush())

        assert cycle.failed is False
        assert cycle.opened == 20
        assert flushed is True
        assert await repository.raw_count() == 1
    finally:
        await worker.stop()


async def test_a_metrics_write_failure_does_not_touch_the_sighting_worker(
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separate tables, separate transactions, separate failure modes.

    The reason receiver metrics are not folded into the sighting worker's
    cycle: a bug here must not be able to fail the transaction that records
    what the receiver saw.
    """
    worker = PersistenceWorker(
        database=database, live=live, tick_interval_s=3_600.0, clock=clock.epoch_ms
    )
    service = ReceiverMetricsService(
        database=database,
        live=live,
        sample_interval_s=15.0,
        flush_interval_s=1.0,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )
    await worker.start()
    try:
        place(live, clock, icao="ae1463", bearing_deg=42.0)
        clock.advance(15.0)
        await service.sample_once()

        async def refuse(*args: object, **kwargs: object) -> None:
            raise OSError("disk I/O error")

        with monkeypatch.context() as patched:
            patched.setattr(MetricsRepository, "record", refuse)
            assert await service.flush() is False

        cycle = await worker.process_pending()

        assert cycle.failed is False
        assert cycle.opened == 1
        assert worker.active_count == 1
    finally:
        await worker.stop()


@pytest.mark.perf
async def test_sampling_the_live_set_is_cheap_enough_for_a_busy_receiver(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """A sample walks the whole live set; a busy receiver's is 500 aircraft.

    It runs every fifteen seconds on its own task, so this is nowhere near the
    ingestion budget — but a sample that took a visible fraction of a second on
    a Pi would still be a background task worth noticing.
    """
    service = ReceiverMetricsService(
        database=database,
        live=live,
        sample_interval_s=15.0,
        flush_interval_s=10**9,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )
    for index in range(500):
        place(live, clock, icao=f"c{index:05d}", bearing_deg=index * 0.72, distance_nm=index % 250)
    clock.advance(15.0)
    await service.sample_once()

    clock.advance(15.0)
    started = time.perf_counter()
    await service.sample_once()
    elapsed_ms = (time.perf_counter() - started) * 1_000.0

    assert len(live) == 500
    assert elapsed_ms < INGESTION_BUDGET_MS, f"sampling 500 aircraft took {elapsed_ms:.1f} ms"
