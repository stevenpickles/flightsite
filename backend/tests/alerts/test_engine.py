"""The engine: dedupe, severity upgrades, downstream writes, recovery.

Everything here runs against the *real* subsystems — a real live store, a real
metadata cache over a real database, a real watchlist matcher and a real
persistence worker — because the properties being checked are about how those
five agree, and a stand-in for any one of them would be checking the stand-in.
What is hand-driven is only *time*: the engine's cycle and the worker's cycle
are called explicitly, so a scenario says "the sighting is committed here" and
"the second update arrives here" rather than sleeping and hoping.

The dedupe assertions read ``alert_matches`` directly (:func:`stored_matches`)
rather than through the repository. "Once per sighting per rule" is a claim
about what is in the table, and a query layer that filtered would hide exactly
the bug the claim is about.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from flightsite.activity.facts import AlertMatchFact
from flightsite.alerts.engine import AlertEngine, subject_for
from flightsite.alerts.model import (
    ClassificationCondition,
    CompiledRule,
    RarityCondition,
    RuleConditions,
)
from flightsite.alerts.repository import AlertRepository
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.counters import counters
from flightsite.db import Database
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.metadata import MetadataService
from flightsite.sightings import PersistenceWorker
from flightsite.sightings.vocabulary import SightingEventType
from flightsite.watchlists import WatchlistEntryKind, WatchlistService

from .conftest import (
    NOW_MS,
    Clock,
    rule,
    seed_resolved_metadata,
    seed_rules,
    settle,
    stored_matches,
)

RARE_ONCE = RuleConditions(rare_aircraft=RarityCondition(max_sightings=1))
MILITARY = RuleConditions(classification=ClassificationCondition(military=True))
ANY_WATCHLIST = RuleConditions(watchlist_any=True)
NEAR = RuleConditions(max_distance_nm=50.0)

BASE_TIME = datetime.fromtimestamp(NOW_MS / 1000, tz=UTC)


def observe(
    live: LiveStore,
    icao: str = "ae1463",
    *,
    second: int = 0,
    squawk: str | None = None,
    distance_lon: float = -1.0,
) -> None:
    """One decoder observation of ``icao``, as a poll would deliver it."""
    live.apply_updates(
        [
            AircraftStateUpdate(
                icao=icao,
                timestamp=BASE_TIME + timedelta(seconds=second),
                position=Position(latitude=51.0, longitude=distance_lon),
                position_source="adsb",
                altitude_ft=25_000.0,
                squawk=squawk,
                on_ground=False,
            )
        ]
    )


async def commit_sighting(worker: PersistenceWorker) -> None:
    """Run one persistence cycle, so the open sighting has ids to match with."""
    await worker.process_pending()


class Collector:
    """An alert listener that keeps what each cycle published."""

    def __init__(self) -> None:
        self.facts: list[AlertMatchFact] = []

    def __call__(self, matches: Sequence[AlertMatchFact]) -> None:
        self.facts.extend(matches)


class EpochClock:
    """A UTC epoch-millisecond source the test moves by hand."""

    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


async def use(engine: AlertEngine, database: Database, *compiled: CompiledRule) -> None:
    """Put ``compiled`` in force, with the ``alert_rules`` rows their ids name.

    The rows are real because the foreign key is real: ``alert_matches.rule_id``
    references ``alert_rules(id)`` and ADR-0001 enforces it, so a rule the
    engine matches on has to exist before a match can cite it.
    """
    await seed_rules(database, *compiled)
    engine.set_rules(compiled)


@pytest.fixture
def collected(engine: AlertEngine) -> Collector:
    collector = Collector()
    engine.subscribe(collector)
    return collector


# ----------------------------------------------------------------- the subject


async def test_a_subject_is_built_from_memory_alone(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
) -> None:
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)

    built = subject_for(
        "ae1463",
        live=live,
        metadata=metadata.cache,
        watchlists=watchlists.matcher,
        persistence=persistence,
        now_ms=NOW_MS,
    )

    assert built is not None
    assert built.icao == "ae1463"
    assert built.sighting_id is not None
    assert built.aircraft_id is not None
    assert built.metadata_resolved


async def test_a_subject_for_an_aircraft_that_is_not_live_is_none(
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
) -> None:
    assert (
        subject_for(
            "000000",
            live=live,
            metadata=metadata.cache,
            watchlists=watchlists.matcher,
            persistence=persistence,
            now_ms=NOW_MS,
        )
        is None
    )


async def test_a_first_ever_airframe_counts_as_one_sighting_here(
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
) -> None:
    """The count-trails-by-a-cycle note from slice 021, resolved: the cache
    populates on the appear event, the worker opens the sighting on its next
    tick, so the cache's figure is the count *before* this sighting and the
    subject adds it back. ``1`` therefore means "never seen here before" —
    which is what ``max_sightings=1`` is written against."""
    observe(live)
    await settle(metadata)

    built = subject_for(
        "ae1463",
        live=live,
        metadata=metadata.cache,
        watchlists=watchlists.matcher,
        persistence=persistence,
        now_ms=NOW_MS,
    )

    assert built is not None
    assert built.sightings_here == 1


async def test_a_returning_airframe_counts_its_history_plus_this_sighting(
    database: Database,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
) -> None:
    """Rarity against fixture history: three previous sightings on the airframe
    row make this the fourth, which is the number
    ``aircraft.sighting_count`` will hold once the worker commits."""
    async with database.writer_session() as session:
        await session.execute(
            text(
                "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms, sighting_count) "
                "VALUES (1, 'ae1463', :now, :now, 3)"
            ),
            {"now": NOW_MS},
        )
    observe(live)
    await settle(metadata)

    built = subject_for(
        "ae1463",
        live=live,
        metadata=metadata.cache,
        watchlists=watchlists.matcher,
        persistence=persistence,
        now_ms=NOW_MS,
    )

    assert built is not None
    assert built.sightings_here == 4


# --------------------------------------------------------------- firing at all


async def test_a_matching_rule_records_one_match(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    await use(engine, database, rule(RARE_ONCE, rule_id=1, name="First-ever aircraft"))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)

    result = await engine.process_pending()

    assert result.recorded == 1
    assert await stored_matches(database) == [
        (1, None, 1, "high", "Rule: First-ever aircraft"),
    ]


async def test_an_emergency_squawk_records_a_match_with_no_rules_configured(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """Roadmap acceptance criterion: zero user configuration."""
    observe(live, squawk="7700")
    await settle(metadata)
    await commit_sighting(persistence)

    result = await engine.process_pending()

    assert result.recorded == 1
    (row,) = await stored_matches(database)
    assert row[0] is None
    assert row[1] == "emergency_7700"
    assert row[3] == "critical"


async def test_a_match_is_held_until_the_sighting_has_been_committed(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """The first second or so of a new aircraft: the ids do not exist yet, so
    the proposal waits rather than being dropped."""
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)

    held = await engine.process_pending()

    assert held.recorded == 0
    assert held.pending == 1
    assert await stored_matches(database) == []

    await commit_sighting(persistence)
    written = await engine.process_pending()

    assert written.recorded == 1
    assert len(await stored_matches(database)) == 1


async def test_an_unresolved_aircraft_is_re_evaluated_without_new_events(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """Metadata arrives a fraction of a second after the aircraft does, and a
    rule about it must not be decided on the absence. The re-evaluation set is
    what repairs that — and it repairs it *without* rescanning the live set, so
    the second cycle here drains no events at all and still evaluates the one
    aircraft that was owed a second look.

    The first cycle is run with no ``await`` between the observation and it, so
    the metadata cache's own task has genuinely not been scheduled yet — which
    is the real ordering a decoder poll produces, not a contrived one.
    """
    await use(engine, database, rule(RuleConditions(type_code="C17")))
    observe(live)

    first = await engine.process_pending()
    assert first.events == 1
    assert first.recorded == 0

    second = await engine.process_pending()

    assert second.events == 0
    assert second.evaluated == 1


async def test_a_metadata_dependent_rule_fires_once_the_cache_resolves_it(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """The repair, end to end: a type-code rule cannot match before the cache
    has a type, and matches on the next cycle after it does."""
    await seed_resolved_metadata(database, "ae1463", type_code="C17")
    await use(engine, database, rule(RuleConditions(type_code="C17")))
    observe(live)

    assert (await engine.process_pending()).recorded == 0

    await settle(metadata)
    await commit_sighting(persistence)

    assert (await engine.process_pending()).recorded == 1
    assert len(await stored_matches(database)) == 1


async def test_a_rarity_rule_fires_against_fixture_history(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """Roadmap acceptance criterion: *"rarity thresholds correct against fixture
    history"*. Two airframes, identical in every way except what this receiver
    has already recorded of them — one new, one seen four times before — and a
    rule that says "at most twice here"."""
    async with database.writer_session() as session:
        await session.execute(
            text(
                "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms, sighting_count) "
                "VALUES (1, '000002', :now, :now, 4)"
            ),
            {"now": NOW_MS},
        )
    await use(
        engine, database, rule(RuleConditions(rare_aircraft=RarityCondition(max_sightings=2)))
    )
    observe(live, "ae1463")
    observe(live, "000002")
    await settle(metadata)
    await commit_sighting(persistence)

    await engine.process_pending()

    assert engine.interesting("ae1463") is not None
    assert engine.interesting("000002") is None
    assert len(await stored_matches(database)) == 1


async def test_ground_traffic_is_excluded_from_a_rule_but_not_from_an_emergency(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """SPEC §40's "excluded from relevant alerts", end to end — and SPEC §47's
    exception to it, in the same cycle: an aircraft on the ground is not
    interesting because it is rare, but it is interesting because it is
    squawking 7500."""
    await use(engine, database, rule(RARE_ONCE))
    live.apply_updates(
        [
            AircraftStateUpdate(
                icao=icao,
                timestamp=BASE_TIME,
                position=Position(latitude=51.0, longitude=-1.0),
                position_source="adsb",
                on_ground=True,
                squawk=squawk,
            )
            for icao, squawk in (("ae1463", None), ("000002", "7500"))
        ]
    )
    await settle(metadata)
    await commit_sighting(persistence)

    await engine.process_pending()

    assert engine.interesting("ae1463") is None
    interesting = engine.interesting("000002")
    assert interesting is not None
    assert interesting.severity is AlertSeverity.CRITICAL
    assert [row[1] for row in await stored_matches(database)] == ["emergency_7500"]


# ------------------------------------------------------------------- the dedupe


async def test_a_rule_fires_once_per_sighting_however_many_updates_arrive(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """SPEC §48's core guarantee: the aircraft keeps matching on every poll,
    and exactly one row exists."""
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)

    for second in range(1, 6):
        observe(live, second=second)
        await engine.process_pending()

    assert len(await stored_matches(database)) == 1


async def test_the_dedupe_survives_losing_the_engines_memory(
    database: Database,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
    engine: AlertEngine,
) -> None:
    """A restart mid-sighting: a *second* engine with no memory at all, over
    the same open sighting. The persisted key is what stops the second match,
    and it stops it whether or not the new engine adopts the keys."""
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()
    assert len(await stored_matches(database)) == 1

    successor = AlertEngine(
        database=database,
        live=live,
        metadata=metadata.cache,
        watchlists=watchlists.matcher,
        persistence=persistence,
        clock=lambda: NOW_MS,
    )
    successor.attach()
    successor.set_rules([rule(RARE_ONCE)])
    observe(live, second=1)

    result = await successor.process_pending()

    assert result.recorded == 0
    assert len(await stored_matches(database)) == 1


async def test_adopting_the_open_sightings_keys_stops_the_write_being_attempted(
    database: Database,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
    engine: AlertEngine,
) -> None:
    """The same restart, with the boot-time adoption the service performs: the
    successor does not even propose the match, so it pays no failed insert per
    cycle for the rest of the sighting."""
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()

    successor = AlertEngine(
        database=database,
        live=live,
        metadata=metadata.cache,
        watchlists=watchlists.matcher,
        persistence=persistence,
        clock=lambda: NOW_MS,
    )
    successor.attach()
    successor.set_rules([rule(RARE_ONCE)])
    successor.adopt_open_matches(await AlertRepository(database).open_sighting_match_keys())
    observe(live, second=1)

    result = await successor.process_pending()

    assert result.recorded == 0
    assert result.pending == 0


async def test_a_second_sighting_of_the_same_airframe_alerts_again(
    database: Database,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    clock: Clock,
) -> None:
    """ "Once per sighting", not "once per aircraft": SPEC §48's dedupe scope is
    the sighting, so an airframe heard again after its previous sighting closed
    alerts again.

    A distance rule rather than a rarity one, deliberately: rarity would stop
    matching on the second sighting for its own good reasons, which would hide
    the property being tested.

    This test drives both clocks by hand — the live store's monotonic one to
    remove the aircraft, and the worker's epoch one past the closure gap — so
    the whole two-sighting lifecycle happens in microseconds.
    """
    epoch = EpochClock(NOW_MS)
    worker = PersistenceWorker(database=database, live=live, clock=epoch)
    await worker.start()
    engine = AlertEngine(
        database=database,
        live=live,
        metadata=metadata.cache,
        watchlists=watchlists.matcher,
        persistence=worker,
        clock=epoch,
    )
    engine.attach()
    await use(engine, database, rule(NEAR))
    try:
        observe(live)
        await settle(metadata)
        await worker.process_pending()
        await engine.process_pending()
        assert len(await stored_matches(database)) == 1

        # The aircraft leaves the live set, and the closure gap expires.
        clock.value = 1_000.0
        live.sweep()
        await engine.process_pending()
        epoch.value = NOW_MS + 700_000
        closed = await worker.process_pending()
        assert closed.closed == 1

        # ...and is heard again, which opens a second sighting.
        observe(live, second=800)
        await settle(metadata)
        opened = await worker.process_pending()
        assert opened.opened == 1
        await engine.process_pending()
    finally:
        await worker.stop()

    rows = await stored_matches(database)
    assert [row[2] for row in rows] == [1, 2]


async def test_a_second_rule_matching_later_is_a_second_match(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """The dedupe is per *rule*, so another rule is another match — which is
    what makes SPEC §48's documented exception reachable at all."""
    await use(engine, database, rule(RARE_ONCE, rule_id=1, name="First ever"))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()

    await use(
        engine,
        database,
        rule(RARE_ONCE, rule_id=1, name="First ever"),
        rule(NEAR, rule_id=2, name="Close in", severity=AlertSeverity.CRITICAL),
    )
    observe(live, second=1)
    await engine.process_pending()

    assert [row[0] for row in await stored_matches(database)] == [1, 2]


# ------------------------------------------------------------ severity upgrades


async def test_a_higher_severity_match_raises_the_sightings_severity(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    await use(engine, database, rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.INFO))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    first = await engine.process_pending()

    assert first.upgraded == 1
    assert persistence.max_alert_severity_for("ae1463") == "info"

    await use(
        engine,
        database,
        rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.INFO),
        rule(NEAR, rule_id=2, severity=AlertSeverity.CRITICAL),
    )
    observe(live, second=1)
    second = await engine.process_pending()

    assert second.upgraded == 1
    assert persistence.max_alert_severity_for("ae1463") == "critical"


async def test_a_lower_severity_match_does_not_lower_the_sightings_severity(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """``max_alert_severity`` is a maximum over the sighting: the sighting
    really did reach the higher one."""
    await use(engine, database, rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.CRITICAL))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()

    await use(
        engine,
        database,
        rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.CRITICAL),
        rule(NEAR, rule_id=2, severity=AlertSeverity.INFO),
    )
    observe(live, second=1)
    result = await engine.process_pending()

    assert result.recorded == 1
    assert result.upgraded == 0
    assert persistence.max_alert_severity_for("ae1463") == "critical"


async def test_an_equal_severity_match_is_not_an_upgrade(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """SPEC §48 allows a further notification for a *higher*-priority
    condition; a tie must not read as one."""
    await use(engine, database, rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.HIGH))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()

    await use(
        engine,
        database,
        rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.HIGH),
        rule(NEAR, rule_id=2, severity=AlertSeverity.HIGH),
    )
    observe(live, second=1)
    result = await engine.process_pending()

    assert result.recorded == 1
    assert result.upgraded == 0


async def test_several_matches_in_one_cycle_reach_the_final_severity_in_one_step(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """Highest first, so one instant produces one ``alert_matched`` event
    rather than a staircase of upgrades."""
    await use(
        engine,
        database,
        rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.INFO),
        rule(NEAR, rule_id=2, severity=AlertSeverity.CRITICAL),
    )
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)

    result = await engine.process_pending()

    assert result.recorded == 2
    assert result.upgraded == 1
    assert persistence.max_alert_severity_for("ae1463") == "critical"


async def test_the_sighting_timeline_records_the_match_and_its_upgrade(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """``docs/DATA_MODEL.md`` §2.5 reserved ``alert_matched`` and
    ``alert_severity_upgraded`` for this slice; this is what writes them."""
    await use(engine, database, rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.INFO))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()
    await commit_sighting(persistence)

    await use(
        engine,
        database,
        rule(RARE_ONCE, rule_id=1, severity=AlertSeverity.INFO),
        rule(NEAR, rule_id=2, severity=AlertSeverity.CRITICAL),
    )
    observe(live, second=1)
    await engine.process_pending()
    await commit_sighting(persistence)

    async with database.read_session() as session:
        rows = await session.execute(text("SELECT type FROM sighting_events ORDER BY id"))
        types = [row[0] for row in rows.all()]

    assert SightingEventType.ALERT_MATCHED.value in types
    assert SightingEventType.ALERT_SEVERITY_UPGRADED.value in types


async def test_the_severity_reaches_the_sightings_row(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """The column the sightings list and the daily rollup read."""
    await use(engine, database, rule(RARE_ONCE, severity=AlertSeverity.HIGH))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()
    await commit_sighting(persistence)

    async with database.read_session() as session:
        stored = await session.scalar(text("SELECT max_alert_severity FROM sightings"))

    assert stored == "high"


# ---------------------------------------------------------- the interesting block


async def test_the_interesting_block_carries_the_highest_severity_and_every_reason(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    await use(
        engine,
        database,
        rule(RARE_ONCE, rule_id=1, name="First ever", severity=AlertSeverity.INFO),
        rule(NEAR, rule_id=2, name="Close in", severity=AlertSeverity.CRITICAL),
    )
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()

    interesting = engine.interesting("ae1463")

    assert interesting is not None
    assert interesting.severity is AlertSeverity.CRITICAL
    assert interesting.reasons == ("Rule: Close in", "Rule: First ever")
    assert interesting.payload() == {
        "severity": "critical",
        "reasons": ["Rule: Close in", "Rule: First ever"],
    }


async def test_an_aircraft_nothing_matches_has_no_interesting_block(
    engine: AlertEngine, live: LiveStore, metadata: MetadataService
) -> None:
    observe(live)
    await settle(metadata)
    await engine.process_pending()

    assert engine.interesting("ae1463") is None


async def test_the_block_clears_when_the_rule_stops_matching(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """``docs/API.md`` §3.3 defines the null block as "no active alert match",
    so an aircraft that has left a distance window reads null again — while
    the record of what happened stays in ``alert_matches``."""
    await use(engine, database, rule(RuleConditions(max_distance_nm=50.0)))
    observe(live, distance_lon=-1.0)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()
    assert engine.interesting("ae1463") is not None

    observe(live, second=1, distance_lon=-40.0)
    await engine.process_pending()

    assert engine.interesting("ae1463") is None
    assert len(await stored_matches(database)) == 1


# ------------------------------------------------------------------- lifecycle


async def test_a_removed_aircraft_is_forgotten(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    clock: Clock,
    database: Database,
) -> None:
    """What bounds this engine's memory to the live set."""
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()
    assert engine.tracked == 1

    clock.value = 1_000.0
    live.sweep()
    await engine.process_pending()

    assert engine.tracked == 0
    assert engine.interesting("ae1463") is None


async def test_an_overflowed_queue_resyncs_from_the_live_snapshot(
    database: Database,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
    clock: Clock,
) -> None:
    """Shed events may have hidden the update that would have matched, so the
    snapshot — not the event history — decides what to evaluate."""
    small = AlertEngine(
        database=database,
        live=live,
        metadata=metadata.cache,
        watchlists=watchlists.matcher,
        persistence=persistence,
        queue_size=1,
        clock=lambda: NOW_MS,
    )
    small.attach()
    await seed_rules(database, *(compiled := (rule(RARE_ONCE),)))
    small.set_rules(compiled)
    observe(live, "000002")
    await settle(metadata)
    await commit_sighting(persistence)
    await small.process_pending()
    assert small.tracked == 1

    # A departure and a burst that overflows the queue, so the shed events hide
    # both the removal and the appearance the snapshot is the only record of.
    clock.value = 1_000.0
    live.sweep()
    for second in range(5):
        observe(live, second=second)
    await settle(metadata)
    await commit_sighting(persistence)

    result = await small.process_pending()

    assert result.resynced
    assert result.recorded == 1
    assert small.tracked == 1


async def test_an_aircraft_that_left_between_the_event_and_the_cycle_is_dropped(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
    clock: Clock,
) -> None:
    """An ordinary outcome, not an error: the sweep removed the aircraft after
    its update was published, so the cycle has an address with no live record.
    It must be forgotten rather than evaluated against nothing."""
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()
    assert engine.tracked == 1

    observe(live, second=1)
    clock.value = 1_000.0
    live.sweep()
    # The removal and the update are both queued; draining them together is the
    # case where the address is named by an event but is no longer live.
    result = await engine.process_pending()

    assert engine.tracked == 0
    assert result.recorded == 0


async def test_a_failed_write_keeps_its_matches_pending_for_the_next_cycle(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Degradation: an alert gets later, and nothing else happens. Ingestion,
    the live picture and the sighting are all untouched, the failure is counted
    as a database error, and the next cycle retries the whole batch."""
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)

    async def failing(self: AlertRepository, matches: object) -> tuple[int | None, ...]:
        raise RuntimeError("the disk is on fire")

    monkeypatch.setattr(AlertRepository, "record_matches", failing)
    failed = await engine.process_pending()

    assert failed.failed
    assert failed.pending == 1
    assert counters.snapshot()[DB_ERRORS_COUNTER] == 1
    assert await stored_matches(database) == []

    monkeypatch.undo()
    observe(live, second=1)
    recovered = await engine.process_pending()

    assert recovered.recorded == 1
    assert len(await stored_matches(database)) == 1


async def test_a_cycle_with_no_events_and_nothing_owed_does_nothing(engine: AlertEngine) -> None:
    result = await engine.process_pending()

    assert (result.events, result.evaluated, result.recorded) == (0, 0, 0)


async def test_an_engine_with_no_subscription_answers_an_empty_cycle(
    database: Database,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
) -> None:
    """Constructing an engine subscribes to nothing, so a cycle before
    :meth:`attach` is a no-op rather than an error."""
    detached = AlertEngine(
        database=database,
        live=live,
        metadata=metadata.cache,
        watchlists=watchlists.matcher,
        persistence=persistence,
    )
    observe(live)

    result = await detached.process_pending()

    assert (result.events, result.evaluated, result.recorded) == (0, 0, 0)


async def test_the_running_loop_evaluates_a_published_observation(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """The engine as the application actually runs it: its own task, woken by
    the live store publishing, with nothing in the test driving a cycle.

    ``wait_idle`` is what makes that assertable without sleeping — the same
    affordance :meth:`flightsite.metadata.cache.MetadataCache.wait_idle`
    provides, and for the same reason.
    """
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)

    await engine.start()
    try:
        observe(live, second=1)
        for _ in range(4):
            await asyncio.sleep(0)
        await engine.wait_idle()
    finally:
        await engine.stop()

    assert len(await stored_matches(database)) == 1
    assert engine.interesting("ae1463") is not None


async def test_start_and_stop_are_idempotent(engine: AlertEngine) -> None:
    await engine.start()
    await engine.start()
    assert engine.running

    await engine.stop()
    await engine.stop()
    assert not engine.running


# -------------------------------------------------------------- the listener


async def test_created_matches_are_published_once(
    engine: AlertEngine,
    collected: Collector,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """Only the rows the transaction *created* are announced: a re-proposed
    match must not produce a second notification."""
    await use(engine, database, rule(RARE_ONCE, rule_id=1, name="First ever"))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()

    for second in range(1, 4):
        observe(live, second=second)
        await engine.process_pending()

    assert len(collected.facts) == 1
    (fact,) = collected.facts
    assert fact.rule_id == 1
    assert fact.rule_name == "First ever"
    assert fact.icao24 == "ae1463"
    assert fact.severity == "high"
    assert fact.reason == "Rule: First ever"
    assert not fact.emergency


async def test_an_emergency_fact_carries_the_squawk_and_no_rule(
    engine: AlertEngine,
    collected: Collector,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
) -> None:
    observe(live, squawk="7500")
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()

    (fact,) = collected.facts

    assert fact.emergency
    assert fact.builtin_key == "emergency_7500"
    assert fact.squawk == "7500"
    assert fact.rule_id is None


async def test_unsubscribing_stops_the_notifications(
    engine: AlertEngine,
    collected: Collector,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    engine.unsubscribe(collected)
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)
    await engine.process_pending()

    assert collected.facts == []


async def test_subscribing_twice_notifies_once(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """A service restarted against a running engine must not end up notified in
    duplicate."""
    collector = Collector()
    engine.subscribe(collector)
    engine.subscribe(collector)
    await use(engine, database, rule(RARE_ONCE))
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)

    await engine.process_pending()

    assert len(collector.facts) == 1


# ------------------------------------------------------------ watchlist input


async def test_a_watchlist_rule_matches_through_the_real_match_index(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    watchlists: WatchlistService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """The watchlist half of the evaluation inputs, through the index slice 037
    actually maintains rather than a hand-built tuple."""
    created = await watchlists.create_watchlist(name="Locals", description=None)
    await watchlists.add_entry(
        created.id, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None
    )
    await use(
        engine, database, rule(RuleConditions(watchlist_id=created.id), watchlist_name="Locals")
    )
    observe(live)
    await settle(metadata)
    await commit_sighting(persistence)

    result = await engine.process_pending()

    assert result.recorded == 1
    assert len(await stored_matches(database)) == 1
