"""Ingest regression test driven by a committed capture/replay fixture.

Roadmap slice 012 acceptance: *"at least one ingest regression test consumes
a captured fixture."* ``tests/fixtures/regression_sample.fsrec.gz`` was
generated once (with :func:`flightsite.devtools.fixture.write_fixture`) from
this same package's own ``readsb_aircraft.json`` and
``dump1090fa_aircraft.json`` documents, normalized through
:func:`flightsite.ingest.readsb.parse_document` — so this test pins the
ingestion pipeline's behaviour against a fixed, version-controlled recording
instead of a live decoder, exactly as ``docs/DEVELOPMENT.md`` recommends.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from flightsite.devtools.fixture import read_fixture
from flightsite.devtools.replay import ReplayAdapter
from flightsite.ingest.health import HealthState
from flightsite.ingest.service import IngestionService
from flightsite.ingest.types import AircraftStateBatch

FIXTURE = Path(__file__).parent.parent / "fixtures" / "regression_sample.fsrec.gz"

#: The fixture's own record count: how many batches a full replay ends with.
EXPECTED_BATCH_COUNT = read_fixture(FIXTURE).header.batch_count


async def run_ingestion_to_completion(
    service: IngestionService, *, expected_batches: int = EXPECTED_BATCH_COUNT
) -> None:
    """Drive ``service`` through a full, as-fast-as-possible replay, then stop it.

    A fixture replayed with ``speed=None`` never awaits real time, so once the
    expected number of batches has been dispatched the adapter has already run
    itself past end-of-fixture (health down included) before control returns
    to the event loop — there is no separate moment to wait for. A temporary
    consumer signals that point via an :class:`asyncio.Event`, bounded by a
    real timeout so a regression here fails the test instead of hanging it.
    """
    finished = asyncio.Event()

    def on_batch(_batch: AircraftStateBatch) -> None:
        if service.batches_ingested >= expected_batches:
            finished.set()

    unsubscribe = service.subscribe(on_batch)
    try:
        await service.start()
        await asyncio.wait_for(finished.wait(), timeout=2.0)
    finally:
        unsubscribe()
    await service.stop()


async def test_replaying_the_committed_fixture_reproduces_its_recorded_batches() -> None:
    adapter = ReplayAdapter.from_path(FIXTURE, speed=None)
    received: list[AircraftStateBatch] = []
    service = IngestionService(adapter, consumers=(received.append,))

    await run_ingestion_to_completion(service)

    assert service.batches_ingested == 2
    assert service.updates_ingested == 11
    assert [len(batch) for batch in received] == [6, 5]

    icaos = {update.icao for batch in received for update in batch}
    assert icaos == {
        "4ca87c",
        "406a3d",
        "3c6444",
        "4008f6",
        "a7c3f1",
        "ac82ec",
        "a0f1b4",
        "ab34d9",
        "ad4e21",
        "a2b9c7",
        "a91d05",
    }
    # The readsb batch's synthetic ~-prefixed entry is dropped by the
    # normalization boundary, not by replay: it never becomes an update, but
    # it is still counted, exactly as a live decoder poll would report it.
    assert received[0].skipped_non_icao == 1


async def test_two_replays_of_the_same_fixture_are_identical() -> None:
    first_adapter = ReplayAdapter.from_path(FIXTURE, speed=None)
    second_adapter = ReplayAdapter.from_path(FIXTURE, speed=None)
    first: list[AircraftStateBatch] = []
    second: list[AircraftStateBatch] = []

    await run_ingestion_to_completion(IngestionService(first_adapter, consumers=(first.append,)))
    await run_ingestion_to_completion(IngestionService(second_adapter, consumers=(second.append,)))

    assert first == second


async def test_replay_health_goes_down_at_fixture_eof() -> None:
    adapter = ReplayAdapter.from_path(FIXTURE, speed=None)
    service = IngestionService(adapter)

    await run_ingestion_to_completion(service)

    assert service.health().state is HealthState.DOWN
