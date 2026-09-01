"""Fixtures for the route-enrichment tests.

Three things are injected everywhere here, and all three for the same reason:
the rules under test are measured in minutes and requests, and a suite that
waited for either would take minutes and reach the internet.

* **Time.** :class:`SimulatedTime` drives the live store's monotonic clock, the
  persistence worker's epoch-millisecond clock, the decoder timestamps, *and*
  the enrichment limiter and breaker from one number. So "the circuit stays
  open for five minutes" is proved exactly, in microseconds.
* **The provider.** :class:`FakeProvider` is a scripted
  :class:`~flightsite.enrichment.provider.RouteEnrichmentProvider` that records
  every callsign it was asked about. Tests that want the *real* provider
  exercised give :class:`~flightsite.enrichment.AeroDataBoxProvider` an
  ``httpx.MockTransport`` instead, so the request building and response parsing
  run for real with no socket (``docs/TEST_STRATEGY.md`` §"No external network
  in tests").
* **The service's tasks.** The fixtures build a service that is *not* started,
  and the tests step it with :meth:`~flightsite.enrichment.EnrichmentService.
  consider` and :meth:`~flightsite.enrichment.EnrichmentService.drain_once`.
  Every lookup then happens at a known instant with nothing racing the
  assertions — the same discipline ``tests/sightings`` applies to the
  persistence worker's cycle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from flightsite.db import Aircraft, Database, Sighting, SightingEvent, database_path
from flightsite.db.clock import to_epoch_ms
from flightsite.enrichment import (
    AeroDataBoxProvider,
    EnrichmentService,
    RouteCacheRepository,
    RouteInfo,
    RouteLookup,
    RouteNotFound,
)
from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.live.events import AircraftAppeared
from flightsite.sightings import PersistenceWorker
from tests.conftest import SECRET_SENTINEL

#: Fixed wall-clock origin, so every cache key and ``ts_ms`` is an exact value.
BASE_TIME = datetime(2026, 8, 30, 22, 0, 0, tzinfo=UTC)
BASE_EPOCH_MS = to_epoch_ms(BASE_TIME)

#: The UTC day :data:`BASE_TIME` falls in — the date half of every cache key
#: the fixtures produce.
BASE_DATE = "2026-08-30"

SEATTLE = Position(latitude=47.4502, longitude=-122.3088)

ICAO = "ae1463"
OTHER_ICAO = "a1b2c3"

#: An eligible callsign: three-letter designator plus a flight number.
AIRLINE_CALLSIGN = "DAL1234"
#: What the fixtures' provider answers for it.
ORIGIN = "KATL"
DESTINATION = "KSLC"

STALE_S = 15.0
REMOVE_S = 60.0
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
        """Monotonic seconds, as the limiter and breaker read them."""
        return 1_000.0 + self.elapsed_s

    def epoch_ms(self) -> int:
        """UTC epoch milliseconds, as the worker and the cache read them."""
        return BASE_EPOCH_MS + int(self.elapsed_s * 1_000)

    def now(self) -> datetime:
        """The decoder's UTC timestamp for an observation made now."""
        return BASE_TIME + timedelta(seconds=self.elapsed_s)


class FakeProvider:
    """A scripted route provider that records what it was asked.

    ``answers`` maps a callsign to the result it returns; anything not named
    falls back to ``default``. ``calls`` is every callsign asked about, in
    order — which is how a test proves that a cache hit spent no request, and
    that a disabled install spent none at all.
    """

    def __init__(
        self,
        answers: dict[str, RouteLookup] | None = None,
        *,
        default: RouteLookup | None = None,
        name: str = "aerodatabox",
    ) -> None:
        self.answers = answers or {}
        self.default: RouteLookup = default if default is not None else RouteNotFound()
        self.calls: list[str] = []
        self.closed = False
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def lookup(self, callsign: str) -> RouteLookup:
        self.calls.append(callsign)
        return self.answers.get(callsign, self.default)

    async def aclose(self) -> None:
        self.closed = True


def route_answer(origin: str | None = ORIGIN, destination: str | None = DESTINATION) -> RouteInfo:
    """The route the fixtures' provider reports for :data:`AIRLINE_CALLSIGN`."""
    return RouteInfo(origin_ident=origin, destination_ident=destination)


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
def cache(database: Database) -> RouteCacheRepository:
    """The ``route_cache`` repository over the migrated database."""
    return RouteCacheRepository(database)


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
    """A started persistence worker whose cycles the test drives itself."""
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


@pytest.fixture
def provider() -> FakeProvider:
    """A provider that answers :data:`AIRLINE_CALLSIGN` with a known route."""
    return FakeProvider({AIRLINE_CALLSIGN: route_answer()})


def build_service(
    *,
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    provider: object,
    clock: SimulatedTime,
    **overrides: Any,
) -> EnrichmentService:
    """An unstarted service wired to the simulated clock.

    Unstarted on purpose: the tests call ``consider``/``drain_once``
    themselves, so nothing happens at an instant the test did not choose.
    """
    return EnrichmentService(
        live=live,
        persistence=worker,
        cache=cache,
        provider=provider,  # type: ignore[arg-type]
        clock=clock.epoch_ms,
        monotonic=clock.monotonic,
        **overrides,
    )


@pytest.fixture
def service(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    provider: FakeProvider,
    clock: SimulatedTime,
) -> EnrichmentService:
    """The service under test, wired to the fake provider."""
    return build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)


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
    callsign: str | None = AIRLINE_CALLSIGN,
    **fields: Any,
) -> None:
    """Apply one observation of ``icao`` stamped at the current simulated time."""
    update = make_update(icao, at=clock.now(), callsign=callsign, **fields)
    live.apply(AircraftStateBatch(timestamp=clock.now(), updates=(update,)))


async def pump(service: EnrichmentService, *, rounds: int = 4) -> None:
    """Drain the service's queue until it stops making progress.

    Bounded rather than "until empty" so a bug that requeues forever fails the
    test instead of hanging it.
    """
    for _ in range(rounds):
        if not await service.drain_once():
            return


def feed(service: EnrichmentService, live: LiveStore) -> None:
    """Offer the service one appear event per aircraft currently live.

    Its reader task does exactly this from the subscription; driving it from
    the test keeps every step at an instant the test chose.
    """
    for record in live.snapshot():
        service.consider(AircraftAppeared(aircraft=record, at=record.last_seen))


def mock_provider(
    handler: Any, *, api_key: str = SECRET_SENTINEL
) -> tuple[AeroDataBoxProvider, httpx.AsyncClient]:
    """A real :class:`AeroDataBoxProvider` over an ``httpx.MockTransport``.

    The provider builds its URL and headers, and the handler sees exactly what
    would have gone to AeroDataBox — which is what lets the secret-leak and
    outbound-data tests assert on the real request rather than a stand-in.
    """
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AeroDataBoxProvider(api_key=SecretStr(api_key), client=client), client


async def sightings_of(database: Database, icao: str = ICAO) -> list[Sighting]:
    """Every sighting row for ``icao``, oldest first."""
    statement = (
        select(Sighting)
        .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
        .where(Aircraft.icao24 == icao)
        .order_by(Sighting.started_ms, Sighting.id)
    )
    async with database.read_session() as session:
        return list((await session.scalars(statement)).all())


async def only_sighting(database: Database, icao: str = ICAO) -> Sighting:
    """The single sighting row for ``icao``; fails the test if there is not one."""
    rows = await sightings_of(database, icao)
    assert len(rows) == 1, f"expected exactly one sighting for {icao}, found {len(rows)}"
    return rows[0]


async def events_of(database: Database, sighting_id: int) -> list[SightingEvent]:
    """Every ``sighting_events`` row of a sighting, oldest first."""
    statement = (
        select(SightingEvent)
        .where(SightingEvent.sighting_id == sighting_id)
        .order_by(SightingEvent.ts_ms, SightingEvent.id)
    )
    async with database.read_session() as session:
        return list((await session.scalars(statement)).all())


def json_response(payload: Sequence[Any], status_code: int = 200) -> httpx.Response:
    """A JSON array response, as the flight endpoint returns one."""
    return httpx.Response(status_code, json=list(payload))
