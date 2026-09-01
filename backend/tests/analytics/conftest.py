"""Fixtures for the analytics tests, and the brute force they are checked against.

Three things are built here, and each exists to make an assertion exact rather
than approximate.

* **A hand-driven clock.** Nothing in this suite sleeps: the service, the
  backfill and the day-rollover logic all take an injected epoch-millisecond
  source, so a fortnight of rollups and a midnight crossing take no wall-clock
  time (``docs/TEST_STRATEGY.md`` §3).
* **Randomized worlds.** :func:`random_world` generates airframes and sightings
  scattered across a run of receiver-local days, with metadata, operator groups
  and classification present on some and absent on others — which is what makes
  the LEFT JOINs in the repository load-bearing rather than decorative.
* **An independent brute force.** :func:`brute_force_day` recomputes a day's
  rollup from the fixture's own Python objects, in a different shape from
  :func:`~flightsite.analytics.rollup.fold_day` — grouping with
  ``collections.Counter`` and comparing calendar dates directly rather than
  folding a single pass. It is the *reference*, and it is deliberately not a
  refactor of the implementation: a shared bug would otherwise agree with
  itself.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from flightsite.analytics.bucketing import day_bounds_ms, local_day, local_hour
from flightsite.analytics.model import DayRollup, GroupCount
from flightsite.analytics.repository import AnalyticsRepository
from flightsite.db import DailyOperatorStats, DailyTypeStats, Database, database_path
from flightsite.db.clock import to_epoch_ms

from ..api.aircraft_history_fixtures import SeedAircraft, seed_operator_groups
from ..api.sighting_fixtures import SeedSighting, seed_sightings

#: The default receiver zone for these tests: a DST zone, so a suite that is
#: *not* about DST still runs against boundaries that are not UTC midnight.
NEW_YORK = "America/New_York"

#: A zone whose offset is not a whole number of hours (+05:30) and which never
#: observes DST. Day boundaries there land at 18:30 UTC, which is the case a
#: "divide by 86,400,000" bucketing would get wrong every single day.
KOLKATA = "Asia/Kolkata"

#: A Tuesday, mid-morning UTC, far from any DST edge, so a test that is not
#: about day boundaries cannot accidentally be about one.
BASE_TIME = datetime(2026, 6, 2, 14, 0, 0, tzinfo=UTC)
BASE_EPOCH_MS = to_epoch_ms(BASE_TIME)

MS_PER_HOUR = 3_600_000
MS_PER_DAY = 24 * MS_PER_HOUR

TYPE_CODES = ("B738", "A320", "C172", "EC35", "B77W", None)
OPERATOR_SLUGS = ("alpha", "beta", "gamma", None)
OPERATOR_GROUPS = (("alpha", "Alpha Airlines"), ("beta", "Beta Cargo"), ("gamma", "Gamma Jets"))


class ManualClock:
    """An epoch-millisecond source the test moves by hand."""

    def __init__(self, now_ms: int = BASE_EPOCH_MS) -> None:
        self.now_ms = now_ms

    def __call__(self) -> int:
        return self.now_ms

    def advance_ms(self, milliseconds: int) -> None:
        """Move forward by an exact number of milliseconds."""
        self.now_ms += milliseconds

    def set_local(self, day: str, hour: int, zone: ZoneInfo) -> None:
        """Jump to a named receiver-local hour of a named local day."""
        self.now_ms = day_bounds_ms(day, zone)[0] + hour * MS_PER_HOUR


@dataclass(frozen=True, slots=True)
class World:
    """A seeded fixture: the rows in the database, kept as Python objects too."""

    aircraft: tuple[SeedAircraft, ...]
    sightings: tuple[SeedSighting, ...]
    group_ids: dict[str, int]
    zone: ZoneInfo

    def days(self) -> list[str]:
        """Every receiver-local day some sighting started on, in order."""
        return sorted({local_day(row.started_ms, self.zone) for row in self.sightings})

    def by_icao(self) -> dict[str, SeedAircraft]:
        return {row.icao24: row for row in self.aircraft}


# --------------------------------------------------------------- brute force


def brute_force_day(world: World, day: str, *, closed: bool) -> DayRollup:
    """Recompute one day's rollup from the fixture objects, independently.

    Deliberately a different shape from the implementation: it selects the
    day's sightings by comparing calendar dates rather than by a millisecond
    range, and it tallies with :class:`collections.Counter` and
    :class:`collections.defaultdict` rather than in one fold. Two
    implementations that share no structure agreeing on randomized input is
    evidence; one implementation checked against a copy of itself is not.
    """
    zone = world.zone
    airframes = world.by_icao()
    todays = [row for row in world.sightings if local_day(row.started_ms, zone) == day]
    if not todays:
        return DayRollup(day=day)

    hours = Counter(local_hour(row.started_ms, zone) for row in todays)
    seen: set[str] = {row.icao24 for row in todays}
    fresh = {icao for icao in seen if local_day(airframes[icao].first_seen_ms, zone) == day}

    per_type: defaultdict[str, list[str]] = defaultdict(list)
    per_operator: defaultdict[int, list[str]] = defaultdict(list)
    for row in todays:
        airframe = airframes[row.icao24]
        if airframe.type_code is not None:
            per_type[airframe.type_code].append(row.icao24)
        if airframe.operator_group_slug is not None:
            per_operator[world.group_ids[airframe.operator_group_slug]].append(row.icao24)

    ranges = [row.max_range_nm for row in todays if row.max_range_nm is not None]
    busiest = min(hour for hour, count in hours.items() if count == max(hours.values()))
    return DayRollup(
        day=day,
        unique_aircraft=len(seen),
        new_aircraft=len(fresh),
        sightings=len(todays),
        interesting=sum(1 for row in todays if row.max_alert_severity is not None),
        military=sum(1 for row in todays if airframes[row.icao24].military),
        government=sum(1 for row in todays if airframes[row.icao24].government),
        law_enforcement=sum(1 for row in todays if airframes[row.icao24].law_enforcement),
        max_range_nm=max(ranges) if ranges else None,
        busiest_hour=busiest if closed else None,
        types={
            code: GroupCount(sightings=len(icaos), unique_aircraft=len(set(icaos)))
            for code, icaos in sorted(per_type.items())
        },
        operators={
            group: GroupCount(sightings=len(icaos), unique_aircraft=len(set(icaos)))
            for group, icaos in sorted(per_operator.items())
        },
    )


async def stored_rollup(repository: AnalyticsRepository, day: str) -> DayRollup:
    """Read one day back out of the four tables as a :class:`DayRollup`.

    The comparison target for the brute force: reads the parent row and both
    breakdown tables, so a test that asserts equality is asserting about
    everything the day actually wrote.
    """
    row = await repository.day(day)
    if row is None:
        return DayRollup(day=day)
    async with repository.database.read_session() as session:
        types = (
            await session.execute(
                select(
                    DailyTypeStats.type_code,
                    DailyTypeStats.sightings,
                    DailyTypeStats.unique_aircraft,
                ).where(DailyTypeStats.day == day)
            )
        ).all()
        operators = (
            await session.execute(
                select(
                    DailyOperatorStats.operator_group_id,
                    DailyOperatorStats.sightings,
                    DailyOperatorStats.unique_aircraft,
                ).where(DailyOperatorStats.day == day)
            )
        ).all()
    return DayRollup(
        day=row.day,
        unique_aircraft=row.unique_aircraft,
        new_aircraft=row.new_aircraft,
        sightings=row.sightings,
        interesting=row.interesting,
        military=row.military,
        government=row.government,
        law_enforcement=row.law_enforcement,
        max_range_nm=row.max_range_nm,
        busiest_hour=row.busiest_hour,
        types={
            str(code): GroupCount(sightings=int(count), unique_aircraft=int(unique))
            for code, count, unique in sorted(types)
        },
        operators={
            int(group): GroupCount(sightings=int(count), unique_aircraft=int(unique))
            for group, count, unique in sorted(operators)
        },
    )


# ------------------------------------------------------------ world building


def random_world(
    seed: int,
    *,
    zone: ZoneInfo,
    first_day: str,
    days: int = 5,
    airframes: int = 24,
    sightings: int = 90,
) -> tuple[tuple[SeedAircraft, ...], tuple[SeedSighting, ...]]:
    """Generate airframes and sightings scattered across ``days`` local days.

    Sightings are placed by picking a day and an offset *inside that local
    day's real bounds*, so a 23- or 25-hour DST day gets exactly as much room
    as it actually had — which is what makes a randomized fixture a DST fixture
    in a DST zone.
    """
    rng = random.Random(seed)
    day_list = [
        (datetime.fromisoformat(first_day).date() + timedelta(days=offset)).isoformat()
        for offset in range(days)
    ]
    bounds = [day_bounds_ms(day, zone) for day in day_list]

    placements: list[tuple[str, int]] = []
    for _ in range(sightings):
        icao = f"a0{rng.randrange(airframes):04x}"
        start_ms, end_ms = bounds[rng.randrange(len(bounds))]
        placements.append((icao, rng.randrange(start_ms, end_ms)))
    placements.sort(key=lambda item: item[1])

    first_seen: dict[str, int] = {}
    last_seen: dict[str, int] = {}
    counts: Counter[str] = Counter()
    sighting_rows: list[SeedSighting] = []
    for icao, started_ms in placements:
        first_seen.setdefault(icao, started_ms)
        last_seen[icao] = started_ms
        counts[icao] += 1
        sighting_rows.append(
            SeedSighting(
                icao24=icao,
                started_ms=started_ms,
                ended_ms=started_ms + rng.randrange(60_000, 900_000),
                max_range_nm=None if rng.random() < 0.15 else round(rng.uniform(1.0, 240.0), 3),
                max_alert_severity="interesting" if rng.random() < 0.2 else None,
            )
        )

    aircraft_rows = [
        _airframe(rng, icao, first_seen[icao], last_seen[icao], counts[icao])
        for icao in sorted(first_seen)
    ]
    return tuple(aircraft_rows), tuple(sighting_rows)


def _airframe(
    rng: random.Random, icao: str, first_seen_ms: int, last_seen_ms: int, count: int
) -> SeedAircraft:
    """One airframe, with metadata and classification present only sometimes.

    An airframe with no resolved metadata and no classification row is the
    ordinary case on a fresh install — the metadata import has not run, or no
    source has heard of the address — and it is exactly the case the
    repository's LEFT JOINs exist for.
    """
    type_code = TYPE_CODES[rng.randrange(len(TYPE_CODES))]
    slug = OPERATOR_SLUGS[rng.randrange(len(OPERATOR_SLUGS))]
    military = rng.random() < 0.12
    government = rng.random() < 0.08
    law = rng.random() < 0.06
    mission = "military" if military else "unknown"
    return SeedAircraft(
        icao24=icao,
        first_seen_ms=first_seen_ms,
        last_seen_ms=last_seen_ms,
        sighting_count=count,
        max_range_nm=round(rng.uniform(10.0, 250.0), 3),
        registration=None if type_code is None else f"N{icao[-4:].upper()}",
        type_code=type_code,
        model=None if type_code is None else f"Model {type_code}",
        operator_name=None if slug is None else slug.title(),
        operator_group_slug=slug,
        military=military,
        government=government,
        law_enforcement=law,
        mission_category=mission,
    )


async def seed_world(
    database: Database,
    *,
    zone: ZoneInfo,
    aircraft: Sequence[SeedAircraft],
    sightings: Sequence[SeedSighting],
) -> World:
    """Insert a world's rows and return the fixture object describing them."""
    group_ids = await seed_operator_groups(database, list(OPERATOR_GROUPS))
    await seed_sightings(database, list(aircraft), list(sightings), group_ids=group_ids)
    return World(
        aircraft=tuple(aircraft),
        sightings=tuple(sightings),
        group_ids=group_ids,
        zone=zone,
    )


async def seed_random_world(
    database: Database, seed: int, *, zone: ZoneInfo, **kwargs: int
) -> World:
    """:func:`random_world` seeded straight into a database."""
    first_day = str(kwargs.pop("first_day", local_day(BASE_EPOCH_MS, zone)))
    aircraft, sightings = random_world(seed, zone=zone, first_day=first_day, **kwargs)
    return await seed_world(database, zone=zone, aircraft=aircraft, sightings=sightings)


def days_of(days: Iterable[str]) -> list[str]:
    """Sorted, de-duplicated day list — a readability helper for assertions."""
    return sorted(set(days))


# ----------------------------------------------------------------- fixtures


@pytest.fixture
def zone() -> ZoneInfo:
    """The receiver's timezone for a test that does not name its own."""
    return ZoneInfo(NEW_YORK)


@pytest.fixture
def clock() -> ManualClock:
    """A hand-driven epoch-millisecond clock."""
    return ManualClock()


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
def repository(database: Database) -> AnalyticsRepository:
    """The rollup repository over the migrated database."""
    return AnalyticsRepository(database)
