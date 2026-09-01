"""Fixtures for the maintenance tests: a hand-driven clock and fabricated stats.

Two things make this suite deterministic. Cadence is driven by an injected
epoch clock and an injected sleeper, exactly as ``docs/TEST_STRATEGY.md`` §3
requires of every lifecycle timing — no test here waits on wall-clock time. And
the ``VACUUM`` guard is driven by *fabricated*
:class:`~flightsite.maintenance.model.DatabaseStats`, because the conditions it
guards against (a four-gigabyte database that is 30% freelist, a card with no
room left on it) cannot be produced on a test machine and should not be
approximated by one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from flightsite.counters import CounterRegistry
from flightsite.db import Database, database_path
from flightsite.enrichment.cache import RouteCacheRepository
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.maintenance.model import DatabaseStats
from flightsite.maintenance.service import StatsProbe

#: Fixed epoch origin, so every assertion about a job's ``started_ms`` is exact.
BASE_MS = 1_772_000_000_000

#: Wall-clock origin for the synthetic observations the contention tests apply.
BASE_TIME = datetime(2026, 8, 30, 22, 0, 0, tzinfo=UTC)

#: Receiver location for the live store: Seattle-Tacoma, as elsewhere.
SEATTLE = Position(latitude=47.4502, longitude=-122.3088)

#: The page size the stats fixtures assume, matching SQLite's default.
PAGE_SIZE = 4096


class ManualClock:
    """An epoch-millisecond clock a test drives by hand."""

    def __init__(self, start_ms: int = BASE_MS) -> None:
        self.now_ms = start_ms

    def __call__(self) -> int:
        return self.now_ms

    def advance_ms(self, milliseconds: int) -> int:
        """Move time forward and return the new reading."""
        self.now_ms += milliseconds
        return self.now_ms

    def advance_hours(self, hours: float) -> int:
        """Move time forward by ``hours``."""
        return self.advance_ms(int(hours * 60 * 60 * 1_000))

    def advance_days(self, days: float) -> int:
        """Move time forward by ``days``."""
        return self.advance_hours(days * 24)


def make_stats(
    *,
    db_bytes: int = 8 * 1024 * 1024,
    reclaimable_ratio: float = 0.0,
    wal_bytes: int = 0,
    free_bytes: int | None = None,
) -> DatabaseStats:
    """Fabricate statistics from the three numbers the policy actually reads.

    Expressed in the vocabulary of the guard — a size, a fraction of dead
    space, a log size — rather than in pages, so a test reads as the condition
    it is describing. ``free_bytes`` defaults to ten times the database, which
    is comfortably above any free-space floor.
    """
    page_count = max(db_bytes // PAGE_SIZE, 0)
    return DatabaseStats(
        page_count=page_count,
        page_size=PAGE_SIZE,
        freelist_count=int(page_count * reclaimable_ratio),
        file_bytes=db_bytes + wal_bytes,
        wal_bytes=wal_bytes,
        free_bytes=free_bytes if free_bytes is not None else db_bytes * 10,
    )


def fixed_stats(stats: DatabaseStats) -> StatsProbe:
    """A :data:`~flightsite.maintenance.service.StatsProbe` answering ``stats``."""

    async def probe() -> DatabaseStats:
        return stats

    return probe


def observations(count: int, *, offset_s: float = 0.0) -> list[AircraftStateUpdate]:
    """``count`` distinct aircraft observed at one instant.

    Enough of a batch to be worth timing: the contention tests measure how long
    :meth:`~flightsite.live.store.LiveStore.apply_updates` takes while
    maintenance is running, so the batch has to do real work.
    """
    timestamp = BASE_TIME + timedelta(seconds=offset_s)
    return [
        AircraftStateUpdate(
            icao=f"a{index:05x}",
            timestamp=timestamp,
            position_source="adsb",
            position=Position(
                latitude=47.0 + (index % 100) * 0.01, longitude=-122.0 + (index % 100) * 0.01
            ),
            altitude_ft=10_000 + index,
            ground_speed_kt=400.0,
        )
        for index in range(count)
    ]


@pytest.fixture
def clock() -> ManualClock:
    """A hand-driven UTC epoch-millisecond clock."""
    return ManualClock()


@pytest.fixture
def counters() -> CounterRegistry:
    """A private counter registry — the module-level one is process-global."""
    return CounterRegistry()


@pytest.fixture
def db_path(isolated_data_dir: Path) -> Path:
    """Path the application would use for its database in this test's data dir."""
    return database_path(isolated_data_dir)


@pytest.fixture
async def database(db_path: Path) -> AsyncIterator[Database]:
    """A database migrated to head."""
    instance = Database(db_path)
    try:
        await instance.upgrade_to("head")
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def route_cache(database: Database) -> RouteCacheRepository:
    """The enrichment cache repository over the migrated database."""
    return RouteCacheRepository(database)


@pytest.fixture
def live() -> LiveStore:
    """A live store whose sweep never fires unless a test asks for one."""
    return LiveStore(clock=lambda: 0.0, receiver_location=SEATTLE)
