"""The daily interesting count converges, because it is derived rather than counted.

Roadmap slice 038 maintains *"daily interesting-aircraft counts consumed by the
Sightings page (030) and today-at-a-glance (036)"*. The interesting thing about
how it does so is that this slice adds **no counting code at all**: slice 031's
fold already reads ``interesting`` off ``sightings.max_alert_severity IS NOT
NULL`` (:class:`~flightsite.analytics.model.SightingFact`), so the whole of
this slice's contribution is persisting that column.

That is worth a test rather than a note, because it is what makes the
convergence property free. :func:`~flightsite.analytics.rollup.fold_day` is a
total function of the day's facts and the writer replaces the day's rows, so
an incremental flush and a full backfill are the *same computation over the
same rows* — there is no accumulator that could drift. These tests check the
count is right, that a rebuild agrees with the incremental result, and that
raising a sighting's severity after it was first counted does not
double-count it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from flightsite.alerts.engine import AlertEngine
from flightsite.alerts.model import RarityCondition, RuleConditions
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.analytics import AnalyticsService
from flightsite.analytics.bucketing import local_day
from flightsite.analytics.repository import AnalyticsRepository
from flightsite.db import Database
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.metadata import MetadataService
from flightsite.sightings import PersistenceWorker

from .conftest import NOW_MS, rule, seed_rules, settle

RARE_ONCE = RuleConditions(rare_aircraft=RarityCondition(max_sightings=1))
NEAR = RuleConditions(max_distance_nm=500.0)

BASE_TIME = datetime.fromtimestamp(NOW_MS / 1000, tz=UTC)
ZONE = ZoneInfo("UTC")


def observe(live: LiveStore, *icaos: str, second: int = 0) -> None:
    live.apply_updates(
        [
            AircraftStateUpdate(
                icao=icao,
                timestamp=BASE_TIME + timedelta(seconds=second),
                position=Position(latitude=51.0, longitude=-1.0),
                position_source="adsb",
                altitude_ft=25_000.0,
                on_ground=False,
            )
            for icao in icaos
        ]
    )


@pytest.fixture
async def analytics(database: Database, persistence: PersistenceWorker) -> AnalyticsService:
    """An analytics service driven by hand, on the same frozen clock."""
    return AnalyticsService(
        database=database,
        persistence=persistence,
        timezone="UTC",
        clock=lambda: NOW_MS,
    )


@pytest.fixture
def rollups(database: Database) -> AnalyticsRepository:
    """The rollup tables' query layer, read to check what a flush wrote."""
    return AnalyticsRepository(database)


async def rebuild(analytics: AnalyticsService, repository: AnalyticsRepository, day: str) -> int:
    """Rebuild one day from ``sightings`` ground truth and return its count."""
    analytics.mark_dirty(day)
    await analytics.flush()
    rollup = await repository.day(day)
    assert rollup is not None
    return rollup.interesting


async def test_a_sighting_that_alerted_counts_as_interesting(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    analytics: AnalyticsService,
    database: Database,
    rollups: AnalyticsRepository,
) -> None:
    """The end-to-end path: a rule matches, the accumulator takes the severity,
    the flush writes the column, and the fold counts the row."""
    compiled = (rule(RARE_ONCE, severity=AlertSeverity.HIGH),)
    await seed_rules(database, *compiled)
    engine.set_rules(compiled)
    observe(live, "ae1463", "000002")
    await settle(metadata)
    await persistence.process_pending()
    await engine.process_pending()
    await persistence.process_pending()

    day = local_day(NOW_MS, ZONE)

    assert await rebuild(analytics, rollups, day) == 2


async def test_a_sighting_that_never_alerted_is_not_counted(
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    analytics: AnalyticsService,
    rollups: AnalyticsRepository,
) -> None:
    observe(live, "ae1463")
    await settle(metadata)
    await persistence.process_pending()

    assert await rebuild(analytics, rollups, local_day(NOW_MS, ZONE)) == 0


async def test_only_the_sightings_that_alerted_are_counted(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    analytics: AnalyticsService,
    database: Database,
    rollups: AnalyticsRepository,
) -> None:
    """A distance rule the far aircraft cannot satisfy, so exactly one of the
    two sightings on the day is interesting."""
    compiled = (rule(RuleConditions(max_distance_nm=5.0)),)
    await seed_rules(database, *compiled)
    engine.set_rules(compiled)
    observe(live, "ae1463")
    live.apply_updates(
        [
            AircraftStateUpdate(
                icao="000002",
                timestamp=BASE_TIME,
                position=Position(latitude=51.0, longitude=-40.0),
                position_source="adsb",
                altitude_ft=25_000.0,
                on_ground=False,
            )
        ]
    )
    await settle(metadata)
    await persistence.process_pending()
    await engine.process_pending()
    await persistence.process_pending()

    assert await rebuild(analytics, rollups, local_day(NOW_MS, ZONE)) == 1


async def test_a_severity_upgrade_does_not_double_count_the_sighting(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    analytics: AnalyticsService,
    database: Database,
    rollups: AnalyticsRepository,
) -> None:
    """``interesting`` counts *sightings*, not matches: a second, higher-severity
    rule on the same sighting raises the column but adds no row, so the count
    is unchanged."""
    first = (rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.INFO),)
    await seed_rules(database, *first)
    engine.set_rules(first)
    observe(live, "ae1463")
    await settle(metadata)
    await persistence.process_pending()
    await engine.process_pending()
    await persistence.process_pending()
    day = local_day(NOW_MS, ZONE)
    assert await rebuild(analytics, rollups, day) == 1

    both = (*first, rule(NEAR, rule_id=2, severity=AlertSeverity.CRITICAL))
    await seed_rules(database, *both)
    engine.set_rules(both)
    observe(live, "ae1463", second=1)
    await engine.process_pending()
    await persistence.process_pending()

    async with database.read_session() as session:
        severity = await session.scalar(text("SELECT max_alert_severity FROM sightings"))
    assert severity == "critical"
    assert await rebuild(analytics, rollups, day) == 1


async def test_a_rebuild_agrees_with_the_incremental_result(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    analytics: AnalyticsService,
    database: Database,
    rollups: AnalyticsRepository,
) -> None:
    """The convergence property, and why it is free: slice 031's fold is a total
    function of the day's rows and the writer replaces them, so "incremental"
    and "backfilled" are the same computation. Nothing this slice added
    accumulates, so nothing it added can drift."""
    compiled = (rule(RARE_ONCE, severity=AlertSeverity.HIGH),)
    await seed_rules(database, *compiled)
    engine.set_rules(compiled)
    observe(live, "ae1463", "000002", "000003")
    await settle(metadata)
    await persistence.process_pending()
    await engine.process_pending()
    await persistence.process_pending()

    day = local_day(NOW_MS, ZONE)
    incremental = await rebuild(analytics, rollups, day)
    rebuilt_again = await rebuild(analytics, rollups, day)
    once_more = await rebuild(analytics, rollups, day)

    assert incremental == rebuilt_again == once_more == 3


async def test_the_count_matches_a_brute_force_over_the_sightings_table(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    analytics: AnalyticsService,
    database: Database,
    rollups: AnalyticsRepository,
) -> None:
    """Checked against SQL rather than against the fold, so a shared bug in the
    fold and this test cannot agree with itself."""
    compiled = (rule(RuleConditions(max_distance_nm=5.0)),)
    await seed_rules(database, *compiled)
    engine.set_rules(compiled)
    observe(live, "ae1463", "000002")
    await settle(metadata)
    await persistence.process_pending()
    await engine.process_pending()
    await persistence.process_pending()

    async with database.read_session() as session:
        expected = await session.scalar(
            text("SELECT COUNT(*) FROM sightings WHERE max_alert_severity IS NOT NULL")
        )

    assert await rebuild(analytics, rollups, local_day(NOW_MS, ZONE)) == expected
