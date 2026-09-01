"""Fixtures for the persistence-worker tests.

Everything here runs on **simulated time**. The rule the suite is proving —
"a sighting closes ten minutes after the aircraft was last heard" — would take
ten real minutes to observe with a wall clock and would flake on a loaded
machine (``docs/TEST_STRATEGY.md`` §3). :class:`SimulatedTime` drives all three
clocks the pipeline reads from one number:

* the live store's **monotonic** clock, which decides stale/removed,
* the worker's **epoch-millisecond** clock, which decides sighting closure,
* the **decoder timestamps** stamped on each observation.

Keeping them in lockstep is what makes an assertion like "advance 601 s and the
sighting is closed with ``ended_ms`` at the last observation" exactly true
rather than approximately true.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.db import Aircraft, Database, Sighting, database_path
from flightsite.db.clock import to_epoch_ms
from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker

#: Fixed wall-clock origin, so every ``started_ms``/``ended_ms`` expectation is
#: an exact number rather than a tolerance.
BASE_TIME = datetime(2026, 8, 30, 22, 0, 0, tzinfo=UTC)
BASE_EPOCH_MS = to_epoch_ms(BASE_TIME)

#: The receiver: Seattle-Tacoma. Distances in these tests are whatever the live
#: store derives from it — the worker does no geometry of its own.
SEATTLE = Position(latitude=47.4502, longitude=-122.3088)

ICAO = "ae1463"
OTHER_ICAO = "a1b2c3"

#: Live-store lifecycle thresholds used throughout, matching the defaults.
STALE_S = 15.0
REMOVE_S = 60.0
#: Sighting closure gap. The product default is 600 s and the tests use it, so
#: what they prove is what ships.
CLOSE_S = 600.0
FLUSH_INTERVAL_S = 30.0


class SimulatedTime:
    """One clock driving monotonic seconds, epoch milliseconds and timestamps."""

    def __init__(self) -> None:
        self.elapsed_s = 0.0

    def advance(self, seconds: float) -> None:
        """Move every derived clock forward together."""
        self.elapsed_s += seconds

    def monotonic(self) -> float:
        """Monotonic seconds, as the live store's lifecycle sweep reads them."""
        return 1_000.0 + self.elapsed_s

    def epoch_ms(self) -> int:
        """UTC epoch milliseconds, as the persistence worker reads them."""
        return BASE_EPOCH_MS + int(self.elapsed_s * 1_000)

    def now(self) -> datetime:
        """The decoder's UTC timestamp for an observation made now."""
        return BASE_TIME + timedelta(seconds=self.elapsed_s)


@pytest.fixture
def clock() -> SimulatedTime:
    """Simulated time, advanced explicitly by each test."""
    return SimulatedTime()


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
def live(clock: SimulatedTime) -> LiveStore:
    """A live store on the default thresholds and a known receiver location."""
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
    """A started persistence worker with its background task suppressed.

    ``tick_interval_s`` is large on purpose: tests call
    :meth:`~flightsite.sightings.PersistenceWorker.process_pending` themselves
    so that every write happens at a known simulated instant, with no
    background task racing the assertions.
    """
    instance = PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        flush_interval_s=FLUSH_INTERVAL_S,
        tick_interval_s=3_600.0,
        clock=clock.epoch_ms,
    )
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()


def make_update(
    icao: str = ICAO, *, at: datetime, position: Position | None = None, **fields: Any
) -> AircraftStateUpdate:
    """One observation, defaulting ``position_source`` from ``position``."""
    source = fields.pop("position_source", "adsb" if position is not None else "none")
    return AircraftStateUpdate(
        icao=icao, timestamp=at, position=position, position_source=source, **fields
    )


def observe(
    live: LiveStore,
    clock: SimulatedTime,
    icao: str = ICAO,
    *,
    position: Position | None = None,
    **fields: Any,
) -> None:
    """Apply one observation of ``icao`` stamped at the current simulated time."""
    update = make_update(icao, at=clock.now(), position=position, **fields)
    live.apply(AircraftStateBatch(timestamp=clock.now(), updates=(update,)))


def observe_many(
    live: LiveStore, clock: SimulatedTime, icaos: Sequence[str], **fields: Any
) -> None:
    """Apply one observation of each of ``icaos`` in a single batch."""
    now = clock.now()
    live.apply(
        AircraftStateBatch(
            timestamp=now, updates=tuple(make_update(icao, at=now, **fields) for icao in icaos)
        )
    )


def north_of(receiver: Position, nm: float) -> Position:
    """A position ``nm`` nautical miles due north of ``receiver``.

    One minute of latitude is one nautical mile, which makes the intended
    distance readable in the test rather than hidden in a coordinate.
    """
    return Position(latitude=receiver.latitude + nm / 60.0, longitude=receiver.longitude)


@asynccontextmanager
async def reading(database: Database) -> AsyncIterator[AsyncSession]:
    """A read-only session for assertions."""
    async with database.read_session() as session:
        yield session


async def sightings_of(database: Database, icao: str = ICAO) -> list[Sighting]:
    """Every sighting row for ``icao``, oldest first."""
    statement = (
        select(Sighting)
        .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
        .where(Aircraft.icao24 == icao)
        .order_by(Sighting.started_ms, Sighting.id)
    )
    async with reading(database) as session:
        return list((await session.scalars(statement)).all())


async def only_sighting(database: Database, icao: str = ICAO) -> Sighting:
    """The single sighting row for ``icao``; fails the test if there is not one."""
    rows = await sightings_of(database, icao)
    assert len(rows) == 1, f"expected exactly one sighting for {icao}, found {len(rows)}"
    return rows[0]


async def aircraft_row(database: Database, icao: str = ICAO) -> Aircraft | None:
    """The ``aircraft`` row for ``icao``, or ``None`` if it has never been seen."""
    async with reading(database) as session:
        row: Aircraft | None = await session.scalar(select(Aircraft).where(Aircraft.icao24 == icao))
        return row


async def existing_aircraft(database: Database, icao: str = ICAO) -> Aircraft:
    """The ``aircraft`` row for ``icao``; fails the test if it is absent."""
    row = await aircraft_row(database, icao)
    assert row is not None, f"no aircraft row for {icao}"
    return row
