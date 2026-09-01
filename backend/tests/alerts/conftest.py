"""Fixtures and builders for the alerts package tests.

The builders here exist so an evaluation test reads as *the case it is about*.
:func:`subject` takes only the fields a case cares about and fills the rest
with values no condition reacts to — an airborne aircraft, no squawk, no
watchlists, a resolved but empty classification — so a test that says
``subject(distance_nm=10.0)`` is genuinely a test about distance and nothing
else. :func:`rule` does the same for the rule side.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Protocol

import pytest
from sqlalchemy import text

from flightsite.alerts import (
    AlertRuleRecord,
    AlertService,
    AlertSeverity,
    CompiledRule,
    RuleConditions,
)
from flightsite.alerts.engine import AlertEngine
from flightsite.alerts.model import AlertSubject
from flightsite.classification.model import Claim, Classification
from flightsite.classification.vocabulary import (
    ClaimSource,
    Confidence,
    EvidenceBasis,
    MissionCategory,
)
from flightsite.db import Database, database_path
from flightsite.ingest import Position
from flightsite.live import GroundState, LiveStore
from flightsite.metadata import MetadataService, SourceRegistry
from flightsite.sightings import PersistenceWorker
from flightsite.watchlists import WatchlistService

#: Frozen clock: every ``matched_ms`` and ``created_ms`` in these tests is this.
NOW_MS = 1_756_600_000_000

#: Event-loop yields before waiting on a task's idle flag. Same reasoning as
#: :data:`tests.metadata.conftest.SETTLE_YIELDS`: publishing is synchronous, so
#: the consumer task has to be scheduled before it can have caught up.
SETTLE_YIELDS = 4


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


# --------------------------------------------------------------- classification


def claimed(**flags: bool) -> Classification:
    """A classification asserting exactly ``flags``, with the claims to justify it.

    :class:`~flightsite.classification.model.Classification` refuses a flag
    without a claim, which is the invariant that makes provenance structural
    (SPEC §39) — so a test that wants "this aircraft is military" has to say
    why, and this is the shortest honest way to.
    """
    claim = Claim(
        source=ClaimSource.MICTRONICS,
        basis=EvidenceBasis.MILITARY_FLAG,
        confidence=Confidence.HIGH,
        detail="test fixture",
    )
    return Classification(
        military=flags.get("military", False),
        military_claim=claim if flags.get("military") else None,
        government=flags.get("government", False),
        government_claim=claim if flags.get("government") else None,
        law_enforcement=flags.get("law_enforcement", False),
        law_enforcement_claim=claim if flags.get("law_enforcement") else None,
    )


def missioned(mission: MissionCategory) -> Classification:
    """A classification whose only assertion is a mission category."""
    return Classification(
        mission=mission,
        mission_claim=Claim(
            source=ClaimSource.HEURISTIC,
            basis=EvidenceBasis.TYPE_CODE,
            confidence=Confidence.MEDIUM,
            detail="test fixture",
        ),
    )


# -------------------------------------------------------------------- builders


def subject(
    *,
    icao: str = "ae1463",
    sighting_id: int | None = 1,
    aircraft_id: int | None = 1,
    squawk: str | None = None,
    distance_nm: float | None = 10.0,
    altitude_ft: float | None = 25_000.0,
    ground_state: GroundState = GroundState.AIRBORNE,
    classification: Classification | None = None,
    type_code: str | None = None,
    model: str | None = None,
    watchlists: Sequence[str] = (),
    sightings_here: int = 5,
    type_aircraft_here: int | None = 50,
    metadata_resolved: bool = True,
    at_ms: int = NOW_MS,
) -> AlertSubject:
    """One evaluation subject, defaulting to an aircraft no condition reacts to.

    The defaults are deliberately *unremarkable*: airborne, ten miles out, at
    cruise, with a common type and no rarity, so any match a test observes came
    from the field it set rather than from a fixture that happened to be
    interesting.
    """
    return AlertSubject(
        icao=icao,
        at_ms=at_ms,
        sighting_id=sighting_id,
        aircraft_id=aircraft_id,
        squawk=squawk,
        distance_nm=distance_nm,
        altitude_ft=altitude_ft,
        ground_state=ground_state,
        classification=classification if classification is not None else Classification(),
        type_code=type_code,
        model=model,
        watchlists=tuple(watchlists),
        sightings_here=sightings_here,
        type_aircraft_here=type_aircraft_here,
        metadata_resolved=metadata_resolved,
    )


def rule(
    conditions: RuleConditions,
    *,
    rule_id: int = 1,
    name: str = "Test rule",
    severity: AlertSeverity = AlertSeverity.HIGH,
    enabled: bool = True,
    watchlist_name: str | None = None,
    template_key: str | None = None,
) -> CompiledRule:
    """A compiled rule, ready to evaluate."""
    return CompiledRule(
        rule=AlertRuleRecord(
            id=rule_id,
            name=name,
            severity=severity,
            conditions=conditions,
            enabled=enabled,
            template_key=template_key,
            created_ms=NOW_MS,
            updated_ms=NOW_MS,
        ),
        watchlist_name=watchlist_name,
    )


# ------------------------------------------------------------- wired subsystems


class ServiceFactory(Protocol):
    """Builds an :class:`~flightsite.alerts.AlertService` for one test's needs."""

    def __call__(
        self, *, template_keys: Sequence[str] = ..., alert_radius_nm: float | None = ...
    ) -> AlertService: ...


class Clock:
    """A monotonic clock the test drives by hand."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def clock() -> Clock:
    return Clock()


#: The receiver position these tests measure distances from. Present because a
#: distance condition cannot hold for an aircraft FlightSite cannot place, so a
#: store with no receiver location would silently make every distance rule
#: untestable rather than failing loudly.
RECEIVER = Position(latitude=51.0, longitude=-1.0)


@pytest.fixture
def live(clock: Clock) -> LiveStore:
    """A live store with a hand-driven clock and generous lifecycle thresholds."""
    return LiveStore(clock=clock, stale_s=100.0, remove_s=200.0, receiver_location=RECEIVER)


@pytest.fixture
async def persistence(database: Database, live: LiveStore) -> AsyncIterator[PersistenceWorker]:
    """A persistence worker driven by hand: no task, one cycle per call.

    ``tick_interval_s`` is irrelevant because :meth:`start` is never called —
    the tests call :meth:`~flightsite.sightings.worker.PersistenceWorker.
    process_pending` directly, which is what lets a sighting be committed at an
    exact point in a scenario rather than "about a second later".
    """
    worker = PersistenceWorker(database=database, live=live, clock=lambda: NOW_MS)
    await worker.start()
    try:
        yield worker
    finally:
        await worker.stop()


@pytest.fixture
async def watchlists(database: Database) -> WatchlistService:
    """A started watchlist service on a frozen clock."""
    service = WatchlistService(database=database, clock=lambda: NOW_MS)
    await service.start()
    return service


@pytest.fixture
async def metadata(
    database: Database, live: LiveStore, watchlists: WatchlistService, isolated_data_dir: Path
) -> AsyncIterator[MetadataService]:
    """A started metadata service wired to the watchlist matcher, as the app wires it."""
    service = MetadataService(
        database=database,
        live=live,
        data_dir=isolated_data_dir,
        registry=SourceRegistry(),
        on_resolved=watchlists.matcher.on_resolved,
        clock=lambda: NOW_MS,
    )
    await service.start()
    try:
        yield service
    finally:
        await service.stop()


@pytest.fixture
def engine(
    database: Database,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
) -> AlertEngine:
    """An alert engine over the real subsystems, driven by hand.

    :meth:`~flightsite.alerts.engine.AlertEngine.start` is deliberately *not*
    called: the tests call
    :meth:`~flightsite.alerts.engine.AlertEngine.process_pending` so each cycle
    happens at an exact point in a scenario, and
    :meth:`~flightsite.alerts.engine.AlertEngine.attach` takes the subscription
    without the racing background loop.
    """
    instance = AlertEngine(
        database=database,
        live=live,
        metadata=metadata.cache,
        watchlists=watchlists.matcher,
        persistence=persistence,
        clock=lambda: NOW_MS,
    )
    instance.attach()
    return instance


@pytest.fixture
def make_service(
    database: Database,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
) -> ServiceFactory:
    """Build an alert service over the real subsystems, choosing its templates."""

    def build(
        *, template_keys: Sequence[str] = (), alert_radius_nm: float | None = None
    ) -> AlertService:
        return AlertService(
            database=database,
            live=live,
            metadata=metadata.cache,
            watchlists=watchlists,
            persistence=persistence,
            template_keys=template_keys,
            alert_radius=(lambda: alert_radius_nm),
            clock=lambda: NOW_MS,
        )

    return build


async def seed_resolved_metadata(
    database: Database,
    icao24: str,
    *,
    type_code: str | None = None,
    model: str | None = None,
    registration: str | None = None,
) -> None:
    """Insert one ``aircraft_metadata_resolved`` row the cache will read.

    Written with raw SQL rather than by running an import: these tests are
    about what the alert engine does with a resolved view, not about how the
    precedence rules produced one — slice 021's own tests own that.
    """
    async with database.writer_session() as session:
        await session.execute(
            text(
                "INSERT INTO aircraft_metadata_resolved "
                "(icao24, registration, registration_src, type_code, type_code_src, "
                "model, model_src, updated_ms) "
                "VALUES (:icao24, :registration, 'mictronics', :type_code, 'mictronics', "
                ":model, 'mictronics', :now)"
            ),
            {
                "icao24": icao24,
                "registration": registration,
                "type_code": type_code,
                "model": model,
                "now": NOW_MS,
            },
        )


async def seed_rules(database: Database, *compiled: CompiledRule) -> None:
    """Insert the ``alert_rules`` rows the compiled rules' ids name.

    ``alert_matches.rule_id`` is a real foreign key and ADR-0001 enforces it,
    so a rule the engine evaluates must exist as a row before a match can cite
    it. Engine tests build their rules in memory (that is the point — the
    evaluator is pure), so this is what makes the ids they chose citable.

    ``ON CONFLICT DO NOTHING`` so a test can re-seed the same rule after adding
    another one, which is what "a second rule matches later" scenarios do.
    """
    if not compiled:
        return
    async with database.writer_session() as session:
        for entry in compiled:
            record = entry.rule
            await session.execute(
                text(
                    "INSERT INTO alert_rules "
                    "(id, name, severity, enabled, conditions_json, created_ms, updated_ms) "
                    "VALUES (:id, :name, :severity, 1, :conditions, :now, :now) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "id": record.id,
                    "name": record.name,
                    "severity": record.severity.value,
                    "conditions": record.conditions.to_json(),
                    "now": NOW_MS,
                },
            )


async def settle(service: MetadataService) -> None:
    """Let the metadata cache catch up with what was just published."""
    for _ in range(SETTLE_YIELDS):
        await asyncio.sleep(0)
    await service.cache.wait_idle()


async def stored_matches(database: Database) -> list[tuple[object, ...]]:
    """Every ``alert_matches`` row, by id: rule, built-in, sighting, severity.

    Read as a list of tuples rather than through the repository so a dedupe
    assertion is about what is *in the table*, not about what a query layer
    chose to return.
    """
    async with database.read_session() as session:
        rows = await session.execute(
            text(
                "SELECT rule_id, builtin_key, sighting_id, severity, reason "
                "FROM alert_matches ORDER BY id"
            )
        )
        return [tuple(row) for row in rows.all()]
