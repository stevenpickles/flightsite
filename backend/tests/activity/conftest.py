"""Fixtures for the activity tests: a hand-driven clock and a seeded world.

Nothing in this suite sleeps. The service, its debounce and its passes all take
injected clocks and an injected sleeper, so a fortnight of decoder flapping and
a restart drill take no wall-clock time (``docs/TEST_STRATEGY.md`` §3).

Rows are seeded through the shared
:mod:`tests.api.sighting_fixtures` helpers rather than driven through the live
store and the persistence worker, for the reason those helpers give: the
activity producers read ``sightings``/``aircraft``/the resolved metadata
tables, and a bulk insert of exactly the rows the pipeline eventually writes
exercises them at a millisecond per test instead of a second per sighting.

Two tests deliberately go the other way and drive the *real* worker — the
lifecycle-seam and restart-idempotency drills in
:mod:`tests.activity.test_service` — because what they are asserting is that
the seam and the watermark agree with what the worker actually committed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from flightsite.activity import (
    DEFAULT_OFFLINE_DEBOUNCE_S,
    DEFAULT_SCAN_LIMIT,
    ActivityRepository,
    ActivityService,
)
from flightsite.db import Database, LifetimeStat, Sighting, database_path
from flightsite.ingest.health import AdapterHealth, HealthState
from flightsite.sightings import PersistenceWorker

from ..api.aircraft_history_fixtures import SeedAircraft
from ..api.sighting_fixtures import SeedSighting, seed_sightings

#: A Tuesday, mid-morning UTC, far from any DST edge.
BASE_MS = 1_780_000_000_000

MS_PER_SECOND = 1_000
MS_PER_MINUTE = 60 * MS_PER_SECOND


class ManualClock:
    """An epoch-millisecond source the test moves by hand."""

    def __init__(self, now_ms: int = BASE_MS) -> None:
        self.now_ms = now_ms

    def __call__(self) -> int:
        return self.now_ms

    def advance_s(self, seconds: float) -> None:
        """Move forward by an exact number of seconds."""
        self.now_ms += int(seconds * MS_PER_SECOND)


class FakeHealth:
    """A decoder health probe the test sets by hand.

    ``None`` is a first-class value and means *this install has no decoder* —
    a first run, or demo mode — which the feed must stay silent about rather
    than report as an outage.
    """

    def __init__(self, state: HealthState | None = None, error: str | None = None) -> None:
        self.health: AdapterHealth | None = (
            None if state is None else AdapterHealth(state=state, last_error=error)
        )

    def __call__(self) -> AdapterHealth | None:
        return self.health

    def set(self, state: HealthState, *, error: str | None = None) -> None:
        """Report ``state`` from now on."""
        self.health = AdapterHealth(state=state, last_error=error)

    def detach(self) -> None:
        """Report "no decoder configured" from now on."""
        self.health = None


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
def repository(database: Database) -> ActivityRepository:
    """The activity repository over the migrated database."""
    return ActivityRepository(database)


@pytest.fixture
def clock() -> ManualClock:
    """A hand-driven epoch-millisecond clock."""
    return ManualClock()


@pytest.fixture
def health() -> FakeHealth:
    """A decoder health probe reporting nothing until a test sets it."""
    return FakeHealth()


def service_for(
    database: Database,
    *,
    clock: ManualClock,
    health: FakeHealth | None = None,
    persistence: PersistenceWorker | None = None,
    offline_debounce_s: float = DEFAULT_OFFLINE_DEBOUNCE_S,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
) -> ActivityService:
    """An activity service wired to the test's clock, never to a real one.

    ``sleep`` is deliberately not passed: every test drives
    :meth:`~flightsite.activity.ActivityService.flush` directly, so the
    background task's cadence is never what is under test.
    """
    return ActivityService(
        database=database,
        persistence=persistence,
        health=health,
        offline_debounce_s=offline_debounce_s,
        scan_limit=scan_limit,
        clock=clock,
    )


async def seed(
    database: Database,
    aircraft: Sequence[SeedAircraft],
    sightings: Sequence[SeedSighting],
) -> list[int]:
    """Insert airframes and sightings; returns the sighting ids in order."""
    return await seed_sightings(database, aircraft, sightings)


def airframe(
    icao24: str,
    *,
    first_seen_ms: int = BASE_MS,
    type_code: str | None = None,
    military: bool = False,
    registration: str | None = None,
    model: str | None = None,
    operator_name: str | None = None,
) -> SeedAircraft:
    """A seeded airframe with the fields the activity producers actually read."""
    return SeedAircraft(
        icao24=icao24,
        first_seen_ms=first_seen_ms,
        last_seen_ms=first_seen_ms + MS_PER_MINUTE,
        type_code=type_code,
        military=military,
        registration=registration,
        model=model,
        operator_name=operator_name,
    )


def sighting(
    icao24: str,
    *,
    started_ms: int = BASE_MS,
    duration_ms: int | None = None,
) -> SeedSighting:
    """A seeded sighting, closed when ``duration_ms`` is given and open otherwise."""
    if duration_ms is None:
        return SeedSighting(icao24=icao24, started_ms=started_ms)
    return SeedSighting(
        icao24=icao24,
        started_ms=started_ms,
        ended_ms=started_ms + duration_ms,
        duration_ms=duration_ms,
        closure_reason="gap_timeout",
    )


async def set_lifetime(database: Database, values: dict[str, float | str]) -> None:
    """Write ``lifetime_stats`` rows the way slice 033's writer would.

    Numbers land in ``value_num`` and strings in ``value_text``, which is the
    split :mod:`flightsite.receiver_metrics.lifetime` maintains and the one
    :meth:`~flightsite.activity.ActivityRepository.receiver_records` reads. An
    upsert rather than an insert, because a record being *beaten* — the case
    this slice exists to notice — is that writer overwriting a key it already
    set.
    """
    async with database.writer_session() as session:
        for key, value in values.items():
            numeric = isinstance(value, int | float)
            await session.execute(
                sqlite_insert(LifetimeStat)
                .values(
                    key=key,
                    value_num=float(value) if numeric else None,
                    value_text=None if numeric else value,
                    updated_ms=BASE_MS,
                )
                .on_conflict_do_update(
                    index_elements=[LifetimeStat.key],
                    set_={
                        "value_num": float(value) if numeric else None,
                        "value_text": None if numeric else value,
                    },
                )
            )


async def close_sighting(database: Database, sighting_id: int, *, duration_ms: int) -> None:
    """Close an open sighting the way the persistence worker's cycle would.

    Used where a test needs a sighting to end *after* the activity service has
    already taken its baselines — which is the only way to drill the seam that
    reports closes, since a sighting closed before the service started is part
    of the baseline rather than news.
    """
    async with database.writer_session() as session:
        await session.execute(
            update(Sighting)
            .where(Sighting.id == sighting_id)
            .values(
                ended_ms=Sighting.started_ms + duration_ms,
                duration_ms=duration_ms,
                closure_reason="gap_timeout",
            )
        )
