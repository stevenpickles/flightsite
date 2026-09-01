"""Batching and the flush policy: how often an open sighting reaches the disk.

Write-behind persistence is only worth having if it actually batches. At 1 Hz
across a busy sky, a write per update would be tens of thousands of
transactions an hour against an SD card, for a row whose useful content is a
dozen extremes. These tests pin the policy: open, then a rewrite when flight
context changes, then once per flush interval, then close — and one transaction
per cycle, not one per sighting.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.counters import counters
from flightsite.db import Database
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker

from .conftest import (
    CLOSE_S,
    FLUSH_INTERVAL_S,
    REMOVE_S,
    SEATTLE,
    SimulatedTime,
    north_of,
    observe,
    observe_many,
    only_sighting,
)


class CountingDatabase(Database):
    """A database that records how many writer transactions were opened."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.writer_transactions = 0

    @asynccontextmanager
    async def writer_session(self) -> AsyncIterator[AsyncSession]:
        self.writer_transactions += 1
        async with super().writer_session() as session:
            yield session


class FailingOnceDatabase(Database):
    """A database whose next writer transaction fails, then behaves normally."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.fail_next = False

    @asynccontextmanager
    async def writer_session(self) -> AsyncIterator[AsyncSession]:
        if self.fail_next:
            self.fail_next = False
            raise OSError("disk I/O error")
        async with super().writer_session() as session:
            yield session


@pytest.fixture
async def counting_database(db_path: Path) -> AsyncIterator[CountingDatabase]:
    instance = CountingDatabase(db_path)
    try:
        await instance.upgrade_to("head")
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
async def failing_database(db_path: Path) -> AsyncIterator[FailingOnceDatabase]:
    instance = FailingOnceDatabase(db_path)
    try:
        await instance.upgrade_to("head")
        yield instance
    finally:
        await instance.dispose()


def build_worker(database: Database, live: LiveStore, clock: SimulatedTime) -> PersistenceWorker:
    """A worker on the standard timings with its background task suppressed."""
    return PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        flush_interval_s=FLUSH_INTERVAL_S,
        tick_interval_s=3_600.0,
        clock=clock.epoch_ms,
    )


async def test_updates_inside_the_interval_are_not_written(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime
) -> None:
    observe(live, clock)
    assert (await worker.process_pending()).opened == 1

    writes = 0
    for _ in range(20):
        clock.advance(1.0)
        observe(live, clock, position=north_of(SEATTLE, 10.0))
        writes += (await worker.process_pending()).flushed

    assert writes == 0


async def test_running_values_are_written_once_the_interval_elapses(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()

    clock.advance(FLUSH_INTERVAL_S - 1.0)
    observe(live, clock, position=north_of(SEATTLE, 6.0), altitude_ft=5_000.0)
    assert (await worker.process_pending()).flushed == 0
    assert (await only_sighting(database)).highest_alt_ft is None

    clock.advance(1.0)
    assert (await worker.process_pending()).flushed == 1
    assert (await only_sighting(database)).highest_alt_ft == 5_000


async def test_a_flush_resets_the_interval(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime
) -> None:
    observe(live, clock)
    await worker.process_pending()
    clock.advance(FLUSH_INTERVAL_S)
    observe(live, clock, altitude_ft=1_000.0)
    assert (await worker.process_pending()).flushed == 1

    clock.advance(FLUSH_INTERVAL_S - 1.0)
    observe(live, clock, altitude_ft=2_000.0)
    assert (await worker.process_pending()).flushed == 0


async def test_a_clean_sighting_is_never_rewritten(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime
) -> None:
    # An aircraft transmitting nothing new for an hour must not produce an
    # hourly stream of identical UPDATEs.
    observe(live, clock)
    await worker.process_pending()

    for _ in range(10):
        clock.advance(FLUSH_INTERVAL_S * 2)
        assert (await worker.process_pending()).flushed == 0


async def test_a_callsign_change_is_written_without_waiting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, callsign="ASA123")
    await worker.process_pending()

    clock.advance(2.0)
    observe(live, clock, callsign="ASA999")
    assert (await worker.process_pending()).flushed == 1
    assert (await only_sighting(database)).callsign_last == "ASA999"


async def test_a_squawk_change_is_written_without_waiting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, squawk="1200")
    await worker.process_pending()

    clock.advance(2.0)
    observe(live, clock, squawk="7700")
    assert (await worker.process_pending()).flushed == 1
    sighting = await only_sighting(database)
    assert sighting.squawk_last == "7700"
    assert sighting.had_emergency == 1


async def test_one_transaction_covers_the_whole_cycle(
    counting_database: CountingDatabase, live: LiveStore, clock: SimulatedTime
) -> None:
    worker = build_worker(counting_database, live, clock)
    await worker.start()
    try:
        # Establish T0 first: it is a write-once statement of its own, and
        # counting it here would obscure what the cycle itself costs.
        observe(live, clock, "000001")
        await worker.process_pending()
        counting_database.writer_transactions = 0

        observe_many(live, clock, [f"0000{index:02x}" for index in range(2, 42)])
        result = await worker.process_pending()

        assert result.opened == 40
        assert counting_database.writer_transactions == 1
    finally:
        await worker.stop()


async def test_shutdown_flushes_dirty_state(
    counting_database: CountingDatabase, live: LiveStore, clock: SimulatedTime
) -> None:
    worker = build_worker(counting_database, live, clock)
    await worker.start()
    observe(live, clock)
    await worker.process_pending()

    clock.advance(2.0)
    observe(live, clock, position=north_of(SEATTLE, 7.0), altitude_ft=8_800.0)
    await worker.stop()

    # Not waiting out the flush interval on the way down: the sighting is left
    # open (a clean stop is not a gap) but current.
    sighting = await only_sighting(counting_database)
    assert sighting.ended_ms is None
    assert sighting.highest_alt_ft == 8_800


async def test_a_failed_cycle_is_counted_and_retried(
    failing_database: FailingOnceDatabase, live: LiveStore, clock: SimulatedTime
) -> None:
    worker = build_worker(failing_database, live, clock)
    await worker.start()
    try:
        observe(live, clock, position=north_of(SEATTLE, 5.0), altitude_ft=6_000.0)
        failing_database.fail_next = True

        failed = await worker.process_pending()

        assert failed.failed is True
        assert counters.snapshot()[DB_ERRORS_COUNTER] == 1
        assert worker.sighting_for("ae1463") is not None

        # Nothing was lost: the next cycle writes the same batch.
        retried = await worker.process_pending()

        assert retried.opened == 1
        assert (await only_sighting(failing_database)).highest_alt_ft == 6_000
    finally:
        await worker.stop()


async def test_a_failed_cycle_leaves_no_phantom_sighting_id(
    failing_database: FailingOnceDatabase, live: LiveStore, clock: SimulatedTime
) -> None:
    # The insert assigns a primary key before the transaction commits; adopting
    # it eagerly would leave the worker updating a row that was rolled back.
    worker = build_worker(failing_database, live, clock)
    await worker.start()
    try:
        observe(live, clock)
        failing_database.fail_next = True
        await worker.process_pending()

        accumulator = worker.sighting_for("ae1463")
        assert accumulator is not None
        assert accumulator.sighting_id is None
        assert accumulator.aircraft_id is None
    finally:
        await worker.stop()


async def test_closing_a_sighting_does_not_also_flush_it(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime
) -> None:
    observe(live, clock)
    await worker.process_pending()
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()

    clock.advance(CLOSE_S)
    result = await worker.process_pending()

    assert result.closed == 1
    assert result.flushed == 0
    assert result.wrote is True
