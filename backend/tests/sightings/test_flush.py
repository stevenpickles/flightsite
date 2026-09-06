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


def build_worker(
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
    *,
    flush_interval_s: float = FLUSH_INTERVAL_S,
) -> PersistenceWorker:
    """A worker on the standard timings with its background task suppressed."""
    return PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        flush_interval_s=flush_interval_s,
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


# ------------------------------------------- removals and the flush policy
#
# Issue #138 asked whether a removal needs to force a write. It does not, and
# measuring it turned up why more precisely than the issue put it: an aircraft
# is only removed after `remove_s` of silence, and at the settings FlightSite
# ships that (60 s) is *longer* than the flush interval (30 s) — so a removal
# always arrives at an accumulator the interval already owes a write. The
# forced flush was buying nothing there, and was adding a write on any
# configuration where the interval is the longer of the two. Both cases are
# covered below.

#: A flush interval longer than the removal threshold. The only configuration
#: in which a removal can reach an accumulator that is *not* already due, and
#: therefore the only one in which the old forced flush changed anything.
SLOW_FLUSH_INTERVAL_S = 300.0


@asynccontextmanager
async def slow_flush_worker(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> AsyncIterator[PersistenceWorker]:
    """A started worker whose flush interval outlasts the removal threshold."""
    worker = build_worker(database, live, clock, flush_interval_s=SLOW_FLUSH_INTERVAL_S)
    await worker.start()
    try:
        yield worker
    finally:
        await worker.stop()


async def test_a_removal_alone_does_not_force_a_write(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """The forced flush on removal is gone (issue #138).

    Measured where it is observable: with the interval longer than the removal
    threshold, a removal used to write the row and now leaves it dirty, to be
    written by the interval it was already waiting for.
    """
    async with slow_flush_worker(database, live, clock) as worker:
        observe(live, clock)
        assert (await worker.process_pending()).opened == 1

        clock.advance(1.0)
        observe(live, clock, position=north_of(SEATTLE, 6.0), altitude_ft=5_000.0)
        await worker.process_pending()
        clock.advance(REMOVE_S + 1.0)
        live.sweep()

        assert (await worker.process_pending()).flushed == 0


async def test_a_removed_sighting_still_flushes_on_the_ordinary_interval(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """What replaces the forced flush, and why dropping it is safe: a pending
    accumulator is flushed by the same cadence an active one is
    (``_accumulators`` yields both sets), so the state an unclean stop would
    find is at worst one interval old — exactly the exposure every live
    sighting already carries."""
    async with slow_flush_worker(database, live, clock) as worker:
        observe(live, clock)
        await worker.process_pending()
        clock.advance(1.0)
        observe(live, clock, position=north_of(SEATTLE, 6.0), altitude_ft=5_000.0)
        await worker.process_pending()
        clock.advance(REMOVE_S + 1.0)
        live.sweep()
        await worker.process_pending()

        clock.advance(SLOW_FLUSH_INTERVAL_S)

        assert (await worker.process_pending()).flushed == 1
        assert (await only_sighting(database)).highest_alt_ft == 5_000


async def test_at_the_shipped_settings_a_removal_owes_no_extra_write(
    counting_database: CountingDatabase, live: LiveStore, clock: SimulatedTime
) -> None:
    """The measurement behind the change: at the shipped timings the removal
    cycle's write is the *interval's*, and there is never a second one.

    Five flap cycles — removed, heard again, removed — cost five transactions,
    one per cycle that the 30 s interval had already fallen due in. Under the
    old code the same five cycles paid the same five plus a forced write each.
    """
    assert REMOVE_S >= FLUSH_INTERVAL_S, "the reasoning above assumes this ordering"
    worker = build_worker(counting_database, live, clock)
    await worker.start()
    try:
        observe(live, clock)
        await worker.process_pending()
        counting_database.writer_transactions = 0

        for _ in range(5):
            clock.advance(REMOVE_S + 1.0)
            live.sweep()
            await worker.process_pending()
            clock.advance(1.0)
            observe(live, clock)
            await worker.process_pending()

        assert counting_database.writer_transactions == 5
    finally:
        await worker.stop()


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
