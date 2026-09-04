"""The credit economy: what gets bought, in what order, and how much (#167).

Slice 070's measurements on the owner's receiver are the whole argument for
this file, so they are worth restating: 2,200-2,650 distinct airline callsigns
a day at ~190 lookups an hour, 62 % of a day's callsigns already heard the day
before, 1 % transient contacts, and one restricted business jet (EJM99) retried
nine times in twelve minutes that tripped the circuit breaker twice (#165).
Enrichment was spending AeroDataBox credits faster than the feeder earned them.

Everything here is driven through the real service with an injected clock and a
scripted provider, exactly as ``test_service.py`` does: a budget measured in
days and a confirmation rule measured in calendar days are provable in
microseconds that way, and untestable any other way.
"""

from __future__ import annotations

from typing import Any

import pytest

from flightsite.airports.model import AirportContext, InferredPhase
from flightsite.counters import counters
from flightsite.db import Database
from flightsite.enrichment import (
    EnrichmentEconomy,
    EnrichmentService,
    RouteCacheRepository,
    RouteInfo,
)
from flightsite.enrichment.cache import MS_PER_SECOND, SECONDS_PER_DAY
from flightsite.enrichment.model import RouteCacheStatus, RouteRestricted
from flightsite.enrichment.service import BUDGET_EXHAUSTED_EVENT, ENRICHMENT_FAILURES_COUNTER
from flightsite.ingest import Position
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker
from tests.enrichment.conftest import (
    AIRLINE_CALLSIGN,
    DESTINATION,
    ICAO,
    ORIGIN,
    SEATTLE,
    FakeProvider,
    SimulatedTime,
    build_service,
    feed,
    observe,
    only_sighting,
    pump,
    route_answer,
)

KEY = AIRLINE_CALLSIGN

#: Enough to cross the UTC midnight after :data:`~tests.enrichment.conftest.
#: BASE_TIME` (22:00 UTC) with room to spare.
TO_TOMORROW_S = 3 * 60 * 60

#: A position a few miles from the receiver, and one on the far side of the
#: continent — inside and outside any sane display radius.
NEAR_RECEIVER = Position(latitude=SEATTLE.latitude + 0.05, longitude=SEATTLE.longitude)
FAR_AWAY = Position(latitude=25.79, longitude=-80.29)


def arriving_at(ident: str) -> AirportContext:
    """The airport-context service's latched answer for an aircraft landing."""
    return AirportContext(ident=ident, name=ident, distance_nm=3.0, phase=InferredPhase.ARRIVING)


def departing_from(ident: str) -> AirportContext:
    return AirportContext(ident=ident, name=ident, distance_nm=2.0, phase=InferredPhase.DEPARTING)


class RecordedLogs:
    """A stand-in for the service's module logger.

    Substituted for it rather than captured through structlog: by the time this
    suite reaches here another test has usually built the real application,
    which configures structlog with cached bound loggers — and a cached logger
    is one ``structlog.testing.capture_logs`` cannot intercept. Replacing the
    name is exact, and it is the same seam the service itself uses.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def _record(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    debug = info = warning = error = _record

    def named(self, event: str) -> list[dict[str, Any]]:
        return [fields for name, fields in self.events if name == event]


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> RecordedLogs:
    """Every structured event the enrichment service emitted."""
    recorder = RecordedLogs()
    monkeypatch.setattr("flightsite.enrichment.service.logger", recorder)
    return recorder


class Probes:
    """The two closures the app injects, as a test can drive them.

    Mutable on purpose: an aircraft starts matching an alert rule, or lands
    somewhere unexpected, *while* its lookup is queued, and both probes are
    read at the moment the decision is made rather than at enqueue time.
    """

    def __init__(self) -> None:
        self.alerting: set[str] = set()
        self.contexts: dict[str, AirportContext] = {}
        self.radius_nm: float | None = None

    def is_alerting(self, icao: str) -> bool:
        return icao in self.alerting

    def context_for(self, icao: str) -> AirportContext | None:
        return self.contexts.get(icao)

    def display_radius_nm(self) -> float | None:
        return self.radius_nm


@pytest.fixture
def probes() -> Probes:
    return Probes()


def economy_service(
    *,
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    provider: object,
    clock: SimulatedTime,
    probes: Probes,
    **overrides: Any,
) -> EnrichmentService:
    """A service wired to the probes, as ``create_app`` wires the real one."""
    return build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        alerting=probes.is_alerting,
        airport_context=probes.context_for,
        display_radius_nm=probes.display_radius_nm,
        **overrides,
    )


# ------------------------------------------------------------ restricted (#165)


async def test_a_restricted_flight_is_cached_and_never_asked_about_again(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    database: Database,
) -> None:
    """EJM99's nine retries in twelve minutes, as one request and one row."""
    provider = FakeProvider(default=RouteRestricted())
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)

    for _ in range(9):
        clock.advance(80.0)
        observe(live, clock)
        await worker.process_pending()
        feed(service, live)
        await pump(service)
        await worker.process_pending()

    row = await cache.get(KEY, now_ms=clock.epoch_ms())
    assert provider.calls == [AIRLINE_CALLSIGN]
    assert row is not None
    assert row.status is RouteCacheStatus.RESTRICTED
    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (None, None)


async def test_a_restricted_answer_leaves_the_breaker_and_the_counter_alone(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
) -> None:
    """The defect itself: an answer about one flight is not provider failure.

    ``failure_threshold=1`` makes the assertion sharp — one counted failure
    would open the circuit, and the circuit stays closed.
    """
    provider = FakeProvider(default=RouteRestricted())
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        failure_threshold=1,
    )

    for index in range(3):
        clock.advance(1.0)
        observe(live, clock, f"a0000{index:x}", callsign=f"EJM9{index}")
        feed(service, live)
        await pump(service)

    assert len(provider.calls) == 3
    assert service.circuit_open is False
    assert counters.snapshot().get(ENRICHMENT_FAILURES_COUNTER, 0) == 0


# --------------------------------------------------------------- the budget


async def test_the_budget_stops_lookups_once_it_is_spent(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """``daily_lookup_budget: 5``: the sixth callsign of the day is not asked."""
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
        economy=EnrichmentEconomy(daily_lookup_budget=5),
    )

    for index in range(8):
        clock.advance(1.0)
        observe(live, clock, f"a0000{index:x}", callsign=f"DAL{index}00")
    feed(service, live)
    for _ in range(12):
        await service.drain_once()

    assert len(provider.calls) == 5
    assert service.budget.limit == 5
    assert service.budget.used_today == 5
    assert service.budget.remaining == 0
    # Queued, not dropped: the bound on the queue is still the queue's own.
    assert service.pending == 3
    assert await service.drain_once() is False


async def test_an_uncapped_install_reports_no_ceiling(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    provider: FakeProvider,
) -> None:
    """``0`` is the default, and ``null`` is not ``0`` remaining."""
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    observe(live, clock)
    feed(service, live)
    await pump(service)

    budget = service.budget
    assert (budget.limit, budget.remaining) == (None, None)
    assert budget.used_today == 1


async def test_the_days_spend_survives_a_restart(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """Counted from ``route_cache``, so a restart is not a fresh allowance."""
    for index in range(3):
        await cache.store_route(
            f"DAL{index}", RouteInfo(ORIGIN, DESTINATION), now_ms=clock.epoch_ms()
        )
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
        economy=EnrichmentEconomy(daily_lookup_budget=3),
    )

    observe(live, clock)
    feed(service, live)
    await pump(service)

    assert provider.calls == []
    assert service.budget.used_today == 3
    assert service.budget.remaining == 0


async def test_the_next_utc_day_buys_again(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """Midnight UTC, on the injected clock rather than on a real one."""
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
        economy=EnrichmentEconomy(daily_lookup_budget=1),
    )
    observe(live, clock, "a00001", callsign="DAL100")
    feed(service, live)
    await pump(service)
    clock.advance(1.0)
    observe(live, clock, "a00002", callsign="DAL200")
    feed(service, live)
    await pump(service)
    assert provider.calls == ["DAL100"]

    clock.advance(TO_TOMORROW_S)
    observe(live, clock, "a00002", callsign="DAL200")
    feed(service, live)
    await pump(service)

    # The callsign yesterday's budget refused is the new day's first purchase.
    assert provider.calls == ["DAL100", "DAL200"]
    assert service.budget.used_today == 1


async def test_the_exhausted_budget_is_logged_once_a_day(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
    logs: RecordedLogs,
) -> None:
    """One line per day, not one per refused callsign.

    The refusal repeats for every eligible callsign until midnight, so a line
    per refusal would be a log flood describing a single decision.
    """
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
        economy=EnrichmentEconomy(daily_lookup_budget=1),
    )

    for index in range(5):
        clock.advance(1.0)
        observe(live, clock, f"a0000{index:x}", callsign=f"DAL{index}00")
        feed(service, live)
        await pump(service)

    exhausted = logs.named(BUDGET_EXHAUSTED_EVENT)
    assert len(exhausted) == 1
    assert exhausted[0]["limit"] == 1
    assert exhausted[0]["used_today"] == 1


async def test_the_next_day_may_report_an_exhausted_budget_again(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
    logs: RecordedLogs,
) -> None:
    """Once *per day*: a second day of the same refusal is worth saying."""
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
        economy=EnrichmentEconomy(daily_lookup_budget=1),
    )

    for day in range(2):
        for index in range(3):
            clock.advance(1.0)
            observe(live, clock, f"a{day}000{index:x}", callsign=f"DAL{day}{index}0")
            feed(service, live)
            await pump(service)
        clock.advance(TO_TOMORROW_S)

    assert len(logs.named(BUDGET_EXHAUSTED_EVENT)) == 2


async def test_a_cached_answer_costs_nothing_against_the_budget(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """The budget bounds *requests*; the cache is what makes it go far."""
    await cache.store_route(KEY, RouteInfo(ORIGIN, DESTINATION), now_ms=clock.epoch_ms())
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
        economy=EnrichmentEconomy(daily_lookup_budget=1),
    )

    observe(live, clock)
    await worker.process_pending()
    feed(service, live)
    await pump(service)

    assert provider.calls == []
    assert worker.route_for(ICAO) is not None


# ------------------------------------------------------------- the priority


async def test_an_alerting_aircraft_is_asked_about_first(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """The acceptance criterion: one alert match among ten ordinary callsigns."""
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    for index in range(10):
        clock.advance(1.0)
        observe(live, clock, f"a0000{index:x}", callsign=f"DAL{index}00")
    clock.advance(1.0)
    observe(live, clock, "b00001", callsign="AAL9999")
    probes.alerting.add("b00001")
    feed(service, live)

    await service.drain_once()

    assert provider.calls == ["AAL9999"]


async def test_an_aircraft_inside_the_display_radius_outranks_the_rest(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """What the map is showing beats what it is not."""
    provider = FakeProvider(default=route_answer())
    probes.radius_nm = 50.0
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    observe(live, clock, "a00001", callsign="DAL100", position=FAR_AWAY)
    clock.advance(1.0)
    observe(live, clock, "a00002", callsign="DAL200")
    clock.advance(1.0)
    observe(live, clock, "a00003", callsign="DAL300", position=NEAR_RECEIVER)
    feed(service, live)

    await service.drain_once()

    assert provider.calls == ["DAL300"]


async def test_a_refresh_of_a_known_route_goes_last(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """Something correct is already on file for a refresh; nothing is for a miss."""
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
        economy=EnrichmentEconomy(route_ttl_days=1),
    )
    observe(live, clock, "a00001", callsign="DAL100")
    feed(service, live)
    await pump(service)
    assert provider.calls == ["DAL100"]

    # A day later the answer has expired, so DAL100 queues as a refresh — and
    # a callsign nobody has an answer for queues behind it, and goes first.
    clock.advance(SECONDS_PER_DAY + 60.0)
    observe(live, clock, "a00001", callsign="DAL100")
    clock.advance(1.0)
    observe(live, clock, "a00002", callsign="DAL200")
    feed(service, live)
    await service.drain_once()

    assert provider.calls == ["DAL100", "DAL200"]


async def test_within_a_priority_the_queue_is_still_first_in_first_out(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """Priority reorders tiers; it does not shuffle the aircraft in one."""
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    for index in range(3):
        clock.advance(1.0)
        observe(live, clock, f"a0000{index:x}", callsign=f"DAL{index}00")
    feed(service, live)

    for _ in range(3):
        await service.drain_once()

    assert provider.calls == ["DAL000", "DAL100", "DAL200"]


# ------------------------------------------------------ consistency (the latch)


async def test_a_landing_somewhere_else_invalidates_the_cached_route(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """The aircraft disproves the row, and the next observation re-buys it."""
    await cache.store_route(KEY, RouteInfo(ORIGIN, DESTINATION), now_ms=clock.epoch_ms())
    provider = FakeProvider({AIRLINE_CALLSIGN: RouteInfo("KSEA", "KPDX")})
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    probes.contexts[ICAO] = arriving_at("KPDX")

    observe(live, clock)
    feed(service, live)
    await pump(service)
    await worker.process_pending()

    assert provider.calls == [AIRLINE_CALLSIGN]
    row = await cache.get(KEY, now_ms=clock.epoch_ms())
    assert row is not None
    assert (row.origin_ident, row.destination_ident) == ("KSEA", "KPDX")


async def test_a_departure_from_the_cached_origin_invalidates_nothing(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """The check must be cheap *and* quiet, or it is just a second lookup."""
    await cache.store_route(KEY, RouteInfo(ORIGIN, DESTINATION), now_ms=clock.epoch_ms())
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    probes.contexts[ICAO] = departing_from(ORIGIN)

    observe(live, clock)
    feed(service, live)
    await pump(service)

    assert provider.calls == []


async def test_a_contradicted_route_is_re_bought_once_and_not_in_a_loop(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """A provider that keeps saying the same thing must not be asked forever.

    The invalidation fires once per callsign per process. Without that bound a
    route the aircraft permanently disagrees with — an IATA code against an
    ICAO-identified field, say — would be a request per observation, which is
    the shape of the retry storm this slice exists to stop.
    """
    await cache.store_route(KEY, RouteInfo(ORIGIN, DESTINATION), now_ms=clock.epoch_ms())
    provider = FakeProvider({AIRLINE_CALLSIGN: RouteInfo(ORIGIN, DESTINATION)})
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    probes.contexts[ICAO] = arriving_at("KPDX")

    for _ in range(5):
        clock.advance(1.0)
        observe(live, clock)
        feed(service, live)
        await pump(service)

    assert provider.calls == [AIRLINE_CALLSIGN]


async def test_an_answer_already_in_memory_is_invalidated_too(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """The memory gate sits in front of the table, so it checks as well."""
    provider = FakeProvider({AIRLINE_CALLSIGN: RouteInfo(ORIGIN, DESTINATION)})
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    observe(live, clock)
    await worker.process_pending()
    feed(service, live)
    await pump(service)
    assert provider.calls == [AIRLINE_CALLSIGN]

    provider.answers[AIRLINE_CALLSIGN] = RouteInfo("KSEA", "KPDX")
    probes.contexts[ICAO] = arriving_at("KPDX")
    clock.advance(1.0)
    observe(live, clock)
    feed(service, live)
    await pump(service)
    await worker.process_pending()

    assert provider.calls == [AIRLINE_CALLSIGN, AIRLINE_CALLSIGN]
    route = worker.route_for(ICAO)
    assert route is not None
    assert (route.origin_ident, route.destination_ident) == ("KSEA", "KPDX")


# ------------------------------------------------------------- learned rows


async def test_a_confirmed_route_is_frozen_and_counted(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
    database: Database,
) -> None:
    """Three days of the same answer, through the service that buys them."""
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
        economy=EnrichmentEconomy(route_ttl_days=1),
    )

    for _ in range(4):
        observe(live, clock)
        feed(service, live)
        await pump(service)
        clock.advance(SECONDS_PER_DAY + 60.0)

    row = await cache.get(KEY, now_ms=clock.epoch_ms())
    assert len(provider.calls) == 4
    assert row is not None
    assert row.confirmations == 3
    assert row.learned is True
    # Thirty days out, not one: the row has earned its freeze.
    assert row.expires_ms - row.fetched_ms == 30 * SECONDS_PER_DAY * MS_PER_SECOND
    assert service.cache_stats.learned == 1
    assert await cache.count_learned() == 1


async def test_cache_hits_and_misses_are_counted_for_diagnostics(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    provider = FakeProvider(default=route_answer())
    service = economy_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        probes=probes,
    )

    for _ in range(3):
        clock.advance(1.0)
        observe(live, clock)
        feed(service, live)
        await pump(service)

    stats = service.cache_stats
    assert stats.misses == 1
    assert stats.hits == 2
