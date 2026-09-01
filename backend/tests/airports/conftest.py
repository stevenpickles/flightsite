"""Fixtures for the airport-context tests.

Three things are constructed here, and each exists to make an assertion exact
rather than approximate.

* **A tiny, deliberate world.** :data:`FIXTURE_AIRPORTS` is nine airports
  chosen for geometry, not realism: two real fields a known distance apart, a
  pair straddling a grid-cell boundary, a pair straddling the antimeridian, and
  one inside the polar band. Every nearest-airport assertion in the suite is
  against a set small enough to reason about by hand.
* **One clock.** :class:`SimulatedTime` drives the live store's monotonic
  clock, the persistence worker's epoch milliseconds *and* the decoder
  timestamps from one number, so a track that takes four minutes of flying
  takes no wall-clock time at all and every ``ts_ms`` is an exact value. The
  same discipline ``tests/enrichment`` applies.
* **Tracks, not observations.** :func:`fly` applies a whole scripted profile —
  approach, departure, cruise — through the real live store, so the inference
  is driven by the same events production drives it with. Nothing calls the
  gate functions directly except ``test_inference.py``, which tests them as a
  table on purpose.

The service under test is deliberately **not started**: the tests hand it
events with :meth:`~flightsite.airports.service.AirportContextService.consider`
themselves, so nothing happens at an instant the test did not choose.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from flightsite.airports import AirportContextService, AirportRecord, AirportRepository
from flightsite.airports.index import AirportIndex
from flightsite.db import Aircraft, Database, Sighting, database_path
from flightsite.db.clock import to_epoch_ms
from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.live.events import AircraftAppeared, AircraftUpdated
from flightsite.sightings import PersistenceWorker

#: Fixed wall-clock origin, so every ``ts_ms`` in the suite is an exact value.
BASE_TIME = datetime(2026, 8, 30, 22, 0, 0, tzinfo=UTC)
BASE_EPOCH_MS = to_epoch_ms(BASE_TIME)

ICAO = "ae1463"
OTHER_ICAO = "a1b2c3"

STALE_S = 15.0
REMOVE_S = 60.0
CLOSE_S = 600.0
FLUSH_INTERVAL_S = 30.0

#: Nautical miles in a degree of latitude. Used to place an aircraft an exact
#: number of miles from a field, which is what makes the distance-gate
#: assertions statements about the gate rather than about arithmetic.
NM_PER_DEGREE: float = 60.0

# Real coordinates, so a reader can sanity-check the geometry against a chart.
BOEING_FIELD = (47.5300, -122.3018)
SEATTLE_TACOMA = (47.4502, -122.3088)


def airport(
    ident: str,
    lat: float,
    lon: float,
    *,
    name: str | None = None,
    type: str = "medium_airport",
    elevation_ft: int | None = 20,
    iata: str | None = None,
    upstream_id: int | None = None,
) -> AirportRecord:
    """One fixture airport, with a name derived from the ident by default."""
    return AirportRecord(
        ident=ident,
        name=name if name is not None else f"{ident} Field",
        type=type,
        lat=lat,
        lon=lon,
        elevation_ft=elevation_ft,
        iata=iata,
        upstream_id=upstream_id,
    )


#: The fixture world. Nine airports, each present for a reason:
#:
#: ``KBFI``/``KSEA``   two real fields ~5.5 nm apart, for ordinary nearest and
#:                     trend assertions. ``KSEA`` carries a real field
#:                     elevation so the height-above-field gate has something
#:                     to subtract.
#: ``KHIGH``           an airstrip at 9 000 ft, for the same gate at altitude.
#: ``KNOEL``           no elevation at all, the ~16% case.
#: ``CELLA``/``CELLB`` either side of the 47.5° grid-cell boundary.
#: ``EASTX``/``WESTX`` either side of the antimeridian.
#: ``POLAR``           inside the band where longitude cells stop being useful.
FIXTURE_AIRPORTS: tuple[AirportRecord, ...] = (
    airport(
        "KBFI",
        *BOEING_FIELD,
        name="Boeing Field",
        type="large_airport",
        elevation_ft=21,
        iata="BFI",
        upstream_id=3411,
    ),
    airport(
        "KSEA",
        *SEATTLE_TACOMA,
        name="Seattle-Tacoma International",
        type="large_airport",
        elevation_ft=433,
        iata="SEA",
        upstream_id=3577,
    ),
    airport("KHIGH", 39.0000, -106.0000, name="High Mountain", elevation_ft=9_000),
    airport("KNOEL", 30.0000, -90.0000, name="No Elevation", elevation_ft=None),
    airport("CELLA", 47.4999, -120.0000, name="Just Below The Line"),
    airport("CELLB", 47.5001, -120.0000, name="Just Above The Line"),
    airport("EASTX", 0.0000, 179.9500, name="East Of The Seam"),
    airport("WESTX", 0.0000, -179.9500, name="West Of The Seam"),
    airport("POLAR", 87.0000, 20.0000, name="Very Far North"),
)


def north_of(field: tuple[float, float], nm: float) -> Position:
    """A position ``nm`` nautical miles due north of ``field``.

    Due north so the conversion is exactly one minute of arc per mile, with no
    cosine and no rounding to argue about.
    """
    return Position(latitude=field[0] + nm / NM_PER_DEGREE, longitude=field[1])


class SimulatedTime:
    """One clock driving monotonic seconds, epoch milliseconds and timestamps."""

    def __init__(self) -> None:
        self.elapsed_s = 0.0

    def advance(self, seconds: float) -> None:
        """Move every derived clock forward together."""
        self.elapsed_s += seconds

    def monotonic(self) -> float:
        """Monotonic seconds, as the live store reads them."""
        return 1_000.0 + self.elapsed_s

    def epoch_ms(self) -> int:
        """UTC epoch milliseconds, as the persistence worker reads them."""
        return BASE_EPOCH_MS + int(self.elapsed_s * 1_000)

    def now(self) -> datetime:
        """The decoder's UTC timestamp for an observation made now."""
        return BASE_TIME + timedelta(seconds=self.elapsed_s)


@dataclass(frozen=True, slots=True)
class Sample:
    """One point of a scripted flight profile, relative to a field."""

    #: Range from the field, nautical miles, due north of it.
    range_nm: float
    #: Barometric altitude, feet. ``None`` for an aircraft reporting none.
    altitude_ft: float | None
    vertical_rate_fpm: float | None = None
    on_ground: bool | None = False
    #: Seconds after the previous sample.
    after_s: float = 10.0


def approach_track() -> tuple[Sample, ...]:
    """A textbook arrival: closing on the field, descending, into the gates.

    Starts outside the arrival distance gate at 9 000 ft and finishes on short
    final. A reader should be able to see the aircraft coming down and coming
    closer without doing arithmetic.
    """
    return (
        Sample(range_nm=20.0, altitude_ft=9_000, vertical_rate_fpm=-900),
        Sample(range_nm=14.0, altitude_ft=6_500, vertical_rate_fpm=-900),
        Sample(range_nm=10.0, altitude_ft=4_500, vertical_rate_fpm=-900),
        Sample(range_nm=6.0, altitude_ft=2_800, vertical_rate_fpm=-800),
        Sample(range_nm=3.0, altitude_ft=1_400, vertical_rate_fpm=-700),
        Sample(range_nm=1.2, altitude_ft=600, vertical_rate_fpm=-500),
    )


def departure_track() -> tuple[Sample, ...]:
    """A textbook departure: off the field, climbing, opening."""
    return (
        Sample(range_nm=0.4, altitude_ft=None, vertical_rate_fpm=None, on_ground=True),
        Sample(range_nm=0.9, altitude_ft=400, vertical_rate_fpm=1_800, on_ground=False),
        Sample(range_nm=2.5, altitude_ft=1_500, vertical_rate_fpm=1_800),
        Sample(range_nm=5.0, altitude_ft=3_200, vertical_rate_fpm=1_600),
        Sample(range_nm=8.0, altitude_ft=5_000, vertical_rate_fpm=1_500),
    )


def cruise_track() -> tuple[Sample, ...]:
    """An airliner at FL350 crossing directly over the field."""
    return (
        Sample(range_nm=12.0, altitude_ft=35_000, vertical_rate_fpm=0),
        Sample(range_nm=6.0, altitude_ft=35_000, vertical_rate_fpm=0),
        Sample(range_nm=0.5, altitude_ft=35_000, vertical_rate_fpm=64),
        Sample(range_nm=6.0, altitude_ft=35_000, vertical_rate_fpm=0),
    )


def ambiguous_track() -> tuple[Sample, ...]:
    """Low and near a field, but level: a transit, a circuit, or a helicopter.

    The case the confidence gate exists for. There is a nearest airport and it
    is worth reporting; what the aircraft intends is not readable.
    """
    return (
        Sample(range_nm=5.0, altitude_ft=2_000, vertical_rate_fpm=0),
        Sample(range_nm=4.0, altitude_ft=2_000, vertical_rate_fpm=100),
        Sample(range_nm=3.0, altitude_ft=2_050, vertical_rate_fpm=-64),
        Sample(range_nm=2.2, altitude_ft=2_000, vertical_rate_fpm=0),
    )


def overflight_track() -> tuple[Sample, ...]:
    """Descending *past* a field rather than into it — closing, then opening.

    The observations used for the assertion are the later ones, where the
    aircraft is still descending but the range is growing: exactly the reading
    the trend gate has to refuse.
    """
    return (
        Sample(range_nm=2.0, altitude_ft=5_000, vertical_rate_fpm=-1_200),
        Sample(range_nm=5.0, altitude_ft=4_000, vertical_rate_fpm=-1_200),
        Sample(range_nm=8.0, altitude_ft=3_000, vertical_rate_fpm=-1_200),
        Sample(range_nm=11.0, altitude_ft=2_000, vertical_rate_fpm=-1_200),
    )


# --------------------------------------------------------------- fixtures


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
def repository(database: Database) -> AirportRepository:
    """The ``airports`` repository over the migrated database."""
    return AirportRepository(database)


@pytest.fixture
def index() -> AirportIndex:
    """An index over the whole fixture world."""
    return AirportIndex(FIXTURE_AIRPORTS)


@pytest.fixture
def live(clock: SimulatedTime) -> LiveStore:
    """A live store on the default thresholds and a receiver at Boeing Field."""
    return LiveStore(
        stale_s=STALE_S,
        remove_s=REMOVE_S,
        receiver_location=Position(latitude=BOEING_FIELD[0], longitude=BOEING_FIELD[1]),
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
async def service(
    live: LiveStore,
    worker: PersistenceWorker,
    repository: AirportRepository,
) -> AirportContextService:
    """An unstarted service holding the fixture world in its index.

    Unstarted on purpose: the tests call ``consider`` themselves, so every
    inference happens at an instant the test chose, with nothing racing the
    assertions.
    """
    instance = AirportContextService(live=live, persistence=worker, repository=repository)
    await seed_index(repository, instance, FIXTURE_AIRPORTS)
    return instance


async def seed_index(
    repository: AirportRepository,
    service: AirportContextService,
    airports: Iterable[AirportRecord],
) -> None:
    """Put ``airports`` in the table and rebuild the service's index from it.

    The production path, not a shortcut past it: nine rows cost a millisecond,
    and every test in the suite then reasons about an index that was actually
    built the way the running application builds one.
    """
    records = list(airports)
    await repository.replace_all(
        records, source="airports", at_ms=BASE_EPOCH_MS, dataset_version="fixture"
    )
    await service.reload()


# --------------------------------------------------------------- driving


def observe(
    live: LiveStore,
    clock: SimulatedTime,
    *,
    icao: str = ICAO,
    position: Position | None = None,
    **fields: Any,
) -> None:
    """Apply one observation of ``icao`` stamped at the current simulated time."""
    source = fields.pop("position_source", "adsb" if position is not None else "none")
    update = AircraftStateUpdate(
        icao=icao,
        timestamp=clock.now(),
        position=position,
        position_source=source,
        **fields,
    )
    live.apply(AircraftStateBatch(timestamp=clock.now(), updates=(update,)))


def feed(service: AirportContextService, live: LiveStore, *, icao: str = ICAO) -> None:
    """Offer the service the current live record for ``icao`` as an event.

    Its reader task does exactly this from the subscription; driving it from
    the test keeps every step at an instant the test chose.
    """
    record = live.get(icao)
    assert record is not None, f"{icao} is not live"
    service.consider(AircraftUpdated(aircraft=record, at=record.last_seen))


def appear(service: AirportContextService, live: LiveStore, *, icao: str = ICAO) -> None:
    """The same, as an ``AircraftAppeared``."""
    record = live.get(icao)
    assert record is not None, f"{icao} is not live"
    service.consider(AircraftAppeared(aircraft=record, at=record.last_seen))


async def fly(
    service: AirportContextService,
    live: LiveStore,
    clock: SimulatedTime,
    track: Sequence[Sample],
    *,
    field: tuple[float, float] = BOEING_FIELD,
    icao: str = ICAO,
    callsign: str | None = "N12345",
    worker: PersistenceWorker | None = None,
) -> None:
    """Drive a whole scripted profile through the live store into the service.

    Each sample advances the clock, applies one observation and hands the
    resulting live record to the service — the same sequence a decoder poll
    produces in production, at instants the test controls.

    ``worker`` is given only by the tests that assert on the sighting row. Its
    cycle runs *before* the service sees the observation, because that is the
    real order: the persistence worker opens the sighting from the same live
    event, and an inference has nowhere to land until it has.
    """
    for sample in track:
        clock.advance(sample.after_s)
        observe(
            live,
            clock,
            icao=icao,
            position=north_of(field, sample.range_nm),
            callsign=callsign,
            altitude_ft=sample.altitude_ft,
            vertical_rate_fpm=sample.vertical_rate_fpm,
            on_ground=sample.on_ground,
        )
        if worker is not None:
            await worker.process_pending()
        feed(service, live, icao=icao)


async def only_sighting(database: Database, icao: str = ICAO) -> Sighting:
    """The single sighting row for ``icao``; fails the test if there is not one."""
    statement = (
        select(Sighting)
        .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
        .where(Aircraft.icao24 == icao)
        .order_by(Sighting.started_ms, Sighting.id)
    )
    async with database.read_session() as session:
        rows = list((await session.scalars(statement)).all())
    assert len(rows) == 1, f"expected exactly one sighting for {icao}, found {len(rows)}"
    return rows[0]
