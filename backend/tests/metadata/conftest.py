"""Fixtures for the metadata framework tests."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from flightsite.db import Database, database_path
from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.metadata import (
    MetadataCache,
    MetadataImporter,
    MetadataRepository,
    MetadataService,
    NormalizedAircraftRecord,
    ResolvedMetadata,
    SourceRegistry,
    normalize_record,
)

#: Frozen clock for the importer; every stored ``_ms`` in these tests is this.
IMPORT_MS = 1_756_600_000_000


@pytest.fixture
def db_path(isolated_data_dir: Path) -> Path:
    """Path the application would use for its database in this test's data dir."""
    return database_path(isolated_data_dir)


@pytest.fixture
async def database(db_path: Path) -> AsyncIterator[Database]:
    """A database migrated to head."""
    instance = Database(db_path)
    await instance.upgrade_to("head")
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def repository(database: Database) -> MetadataRepository:
    """A metadata repository over the migrated database."""
    return MetadataRepository(database)


@pytest.fixture
def registry() -> SourceRegistry:
    """An empty source registry."""
    return SourceRegistry()


@pytest.fixture
def importer(
    database: Database, registry: SourceRegistry, isolated_data_dir: Path
) -> MetadataImporter:
    """An importer on a frozen clock, so stored timestamps are assertable."""
    return MetadataImporter(
        database=database,
        registry=registry,
        data_dir=isolated_data_dir,
        clock=lambda: IMPORT_MS,
    )


@pytest.fixture
def live() -> LiveStore:
    """A live store with a hand-driven clock; nothing sweeps unless asked."""
    return LiveStore(clock=lambda: 0.0)


@pytest.fixture
async def service(
    database: Database, live: LiveStore, registry: SourceRegistry, isolated_data_dir: Path
) -> AsyncIterator[MetadataService]:
    """A started metadata service, stopped on teardown."""
    instance = MetadataService(
        database=database,
        live=live,
        data_dir=isolated_data_dir,
        registry=registry,
        clock=lambda: IMPORT_MS,
    )
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()


def record(icao24: str, **fields: object) -> NormalizedAircraftRecord:
    """A normalized record, written the way a provider's transform would."""
    return normalize_record(icao24=icao24, **fields)  # type: ignore[arg-type]


def updates(*icaos: str) -> list[AircraftStateUpdate]:
    """One decoder batch's worth of observations, one per address."""
    now = datetime.fromtimestamp(IMPORT_MS / 1000, tz=UTC)
    return [
        AircraftStateUpdate(
            icao=icao,
            timestamp=now,
            position_source="adsb",
            position=Position(latitude=51.0, longitude=-1.0),
            altitude_ft=30_000.0,
        )
        for icao in icaos
    ]


#: Event-loop yields before a settle waits on the cache's idle flag.
#:
#: Publishing is synchronous: when ``apply`` returns, the events are queued but
#: the population task has not run. One yield is enough for asyncio to schedule
#: it (``put_nowait`` wakes the waiter through ``call_soon``); a few more cost
#: nothing and remove any dependence on that detail. This is bounded and
#: deterministic — deliberately not a sleep, and not a poll on a condition.
SETTLE_YIELDS = 4


async def settle(cache: MetadataCache) -> None:
    """Let the cache's population task catch up with what was just published."""
    for _ in range(SETTLE_YIELDS):
        await asyncio.sleep(0)
    await cache.wait_idle()


def batch(*icaos: str) -> AircraftStateBatch:
    """One decoder poll, in the shape ``LiveStore.apply`` consumes."""
    return AircraftStateBatch(
        timestamp=datetime.fromtimestamp(IMPORT_MS / 1000, tz=UTC),
        updates=tuple(updates(*icaos)),
    )


def appear(store: LiveStore, *icaos: str) -> None:
    """Apply one decoder batch that makes ``icaos`` appear in ``store``."""
    store.apply_updates(updates(*icaos))


async def seed_aircraft(database: Database, counts: Mapping[str, int]) -> None:
    """Insert ``aircraft`` rows with the given lifetime sighting counts.

    Written with raw SQL through the writer session rather than the persistence
    worker: these tests are about what the cache reads, not about how the
    counter got there.
    """
    async with database.writer_session() as session:
        for index, (icao24, count) in enumerate(counts.items(), start=1):
            await session.execute(
                text(
                    "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms, "
                    "sighting_count, total_observed_ms) "
                    "VALUES (:id, :icao24, :first, :last, :count, 0)"
                ),
                {
                    "id": index,
                    "icao24": icao24,
                    "first": IMPORT_MS,
                    "last": IMPORT_MS,
                    "count": count,
                },
            )


async def resolved_rows(
    repository: MetadataRepository, icaos: Sequence[str]
) -> dict[str, ResolvedMetadata]:
    """Resolved rows for ``icaos``, keyed by address, absent where unknown.

    The repository answers metadata and rarity together in one query (that is
    the cache's read path and the reason it is one query); assertions about
    resolution alone read more clearly through this.
    """
    view = await repository.load_live_view(icaos)
    return {icao: metadata for icao, (metadata, _) in view.items() if metadata is not None}


def dump(path: Path, tables: Sequence[str]) -> dict[str, list[tuple[object, ...]]]:
    """Every row of ``tables``, sorted, read with stdlib ``sqlite3``.

    Read from the outside rather than through the ORM: a fault-injection test
    asserting "the previous dataset is untouched" has to compare what is
    actually in the file, not what a session would reconstruct.
    """
    connection = sqlite3.connect(path)
    try:
        return {
            table: sorted(connection.execute(f"SELECT * FROM {table}").fetchall())
            for table in tables
        }
    finally:
        connection.close()


#: The tables a failed import must leave untouched.
DATASET_TABLES: tuple[str, ...] = ("aircraft_metadata", "aircraft_metadata_resolved")
