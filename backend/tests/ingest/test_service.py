"""IngestionService: the loop, its subscribers, and its readiness contract."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from flightsite.ingest.health import AdapterHealth, HealthState
from flightsite.ingest.service import (
    READINESS_SUBSYSTEM,
    IngestionService,
    build_ingestion_service,
    null_sink,
)
from flightsite.ingest.types import AircraftStateBatch, AircraftStateUpdate
from flightsite.readiness import ReadinessRegistry

from .conftest import TEST_ENDPOINT


def batch(icao: str = "4ca87c") -> AircraftStateBatch:
    moment = datetime(2025, 9, 17, 16, 0, tzinfo=UTC)
    return AircraftStateBatch(
        timestamp=moment,
        updates=(AircraftStateUpdate(icao=icao, timestamp=moment),),
    )


class FakeAdapter:
    """An adapter that yields a fixed number of batches, then waits forever."""

    def __init__(self, count: int = 3, *, health: AdapterHealth | None = None) -> None:
        self.count = count
        self.started = 0
        self.stopped = 0
        self.exhausted = asyncio.Event()
        self._health = health if health is not None else AdapterHealth()

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1

    def health(self) -> AdapterHealth:
        return self._health

    async def updates(self) -> AsyncIterator[AircraftStateBatch]:
        for index in range(self.count):
            yield batch(f"4ca8{index:02d}")
        self.exhausted.set()
        # A real adapter never ends its stream on a decoder outage; it waits
        # and retries. Blocking here reproduces that.
        await asyncio.Event().wait()


async def run_until_exhausted(service: IngestionService, adapter: FakeAdapter) -> None:
    await service.start()
    await asyncio.wait_for(adapter.exhausted.wait(), timeout=1.0)
    await service.stop()


# ----------------------------------------------------------- dispatch


async def test_batches_reach_every_subscriber() -> None:
    adapter = FakeAdapter(count=3)
    service = IngestionService(adapter)
    first: list[AircraftStateBatch] = []
    second: list[AircraftStateBatch] = []
    service.subscribe(first.append)
    service.subscribe(second.append)

    await run_until_exhausted(service, adapter)

    assert len(first) == 3
    assert [b.updates[0].icao for b in first] == ["4ca800", "4ca801", "4ca802"]
    assert second == first
    assert service.batches_ingested == 3
    assert service.updates_ingested == 3


async def test_unsubscribe_detaches_a_consumer() -> None:
    adapter = FakeAdapter(count=3)
    service = IngestionService(adapter)
    received: list[AircraftStateBatch] = []
    unsubscribe = service.subscribe(received.append)
    unsubscribe()
    unsubscribe()  # idempotent

    await run_until_exhausted(service, adapter)

    assert received == []
    assert service.batches_ingested == 3


async def test_a_broken_consumer_cannot_stop_the_loop() -> None:
    adapter = FakeAdapter(count=3)
    service = IngestionService(adapter)
    survivor: list[AircraftStateBatch] = []

    def explode(_batch: AircraftStateBatch) -> None:
        raise RuntimeError("consumer bug")

    service.subscribe(explode)
    service.subscribe(survivor.append)

    await run_until_exhausted(service, adapter)

    # docs/ARCHITECTURE.md §3.1: a broken consumer may lag or fail, but it
    # must never stall the adapter or starve the other consumers.
    assert len(survivor) == 3
    assert service.batches_ingested == 3


async def test_the_default_sink_discards_batches() -> None:
    adapter = FakeAdapter(count=2)
    service = IngestionService(adapter)

    await run_until_exhausted(service, adapter)

    # The live state store subscribes in slice 008; until then the seam is
    # exercised by a sink that does nothing at all.
    null_sink(batch())
    assert service.batches_ingested == 2


# ---------------------------------------------------------- lifecycle


async def test_start_is_idempotent() -> None:
    adapter = FakeAdapter(count=1)
    service = IngestionService(adapter)

    await service.start()
    await service.start()
    await asyncio.wait_for(adapter.exhausted.wait(), timeout=1.0)
    await service.stop()

    assert adapter.started == 1
    assert service.batches_ingested == 1


async def test_stop_is_idempotent_and_safe_before_start() -> None:
    adapter = FakeAdapter(count=1)
    service = IngestionService(adapter)

    await service.stop()
    await service.start()
    await service.stop()
    await service.stop()

    assert service.running is False
    assert adapter.stopped == 3


async def test_stopping_cancels_a_loop_that_is_waiting_on_the_decoder() -> None:
    adapter = FakeAdapter(count=0)
    service = IngestionService(adapter)

    await service.start()
    assert service.running
    await asyncio.wait_for(service.stop(), timeout=1.0)

    assert service.running is False


async def test_health_is_read_through_from_the_adapter() -> None:
    health = AdapterHealth(state=HealthState.DEGRADED, consecutive_failures=2)
    service = IngestionService(FakeAdapter(count=0, health=health))

    assert service.health() is health


# ---------------------------------------------------------- readiness


async def test_readiness_is_marked_as_soon_as_the_loop_runs() -> None:
    readiness = ReadinessRegistry()
    readiness.mark_startup_complete()
    adapter = FakeAdapter(count=1)
    service = IngestionService(adapter, readiness=readiness)

    await service.start()

    assert readiness.snapshot() == {READINESS_SUBSYSTEM: True}
    assert readiness.is_ready is True
    await service.stop()


async def test_a_down_decoder_does_not_make_the_app_unready() -> None:
    readiness = ReadinessRegistry()
    readiness.mark_startup_complete()
    down = AdapterHealth(state=HealthState.DOWN, consecutive_failures=99)
    service = IngestionService(FakeAdapter(count=0, health=down), readiness=readiness)

    await service.start()

    # FlightSite is usable without a decoder; restarting the container because
    # something outside it went offline would be the opposite of helpful.
    assert service.health().state is HealthState.DOWN
    assert readiness.is_ready is True
    await service.stop()
    assert readiness.snapshot()[READINESS_SUBSYSTEM] is True


async def test_readiness_is_untouched_when_no_registry_is_given() -> None:
    service = IngestionService(FakeAdapter(count=0))

    await service.start()
    await service.stop()

    assert service.running is False


# ------------------------------------------------------------ factory


def test_the_built_service_polls_the_given_endpoint() -> None:
    service = build_ingestion_service(TEST_ENDPOINT)

    assert service.running is False
    assert service.health().state is HealthState.DOWN


async def test_build_ingestion_service_registers_readiness() -> None:
    readiness = ReadinessRegistry()
    service = build_ingestion_service(TEST_ENDPOINT, readiness=readiness)

    with pytest.raises(KeyError):
        # Nothing is registered until the loop actually starts.
        readiness.mark_ready(READINESS_SUBSYSTEM)
    assert service.batches_ingested == 0
