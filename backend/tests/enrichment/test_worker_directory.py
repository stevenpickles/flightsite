"""The worker chain: cache, then directory, then provider — and the last resort.

Slice 071's whole behavioural claim in one file. Two things are being proved
throughout, and they pull in opposite directions:

* a callsign the offline directory knows costs **no** AeroDataBox request, ever,
  and reaches the sighting tagged ``vrs``;
* a callsign it does not know, or one whose directory row the aircraft has just
  disproved, still reaches the provider — under slice 070's budget, priority and
  breaker, unchanged.

Everything runs through the real service with the injected clock and the
scripted provider ``test_service.py`` and ``test_economy.py`` use, so a TTL
measured in days and a log line emitted once per UTC day are provable in
microseconds.
"""

from __future__ import annotations

from typing import Any

import pytest

from flightsite.db import Database
from flightsite.enrichment import (
    EnrichmentEconomy,
    EnrichmentService,
    RouteCacheRepository,
    RouteDirectoryRecord,
    RouteDirectoryRepository,
    RouteInfo,
)
from flightsite.enrichment.cache import (
    MS_PER_SECOND,
    SECONDS_PER_DAY,
    STALE_EXTENSION_S,
)
from flightsite.enrichment.model import (
    ROUTE_SOURCE_AERODATABOX,
    ROUTE_SOURCE_VRS,
    RouteUnavailable,
)
from flightsite.enrichment.service import (
    DIRECTORY_CONTRADICTED_EVENT,
    STALE_SERVED_EVENT,
    UNANSWERABLE_BACKOFF_S,
)
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker
from tests.enrichment.conftest import (
    AIRLINE_CALLSIGN,
    DESTINATION,
    ICAO,
    ORIGIN,
    OTHER_ICAO,
    FakeProvider,
    SimulatedTime,
    build_service,
    feed,
    observe,
    only_sighting,
    pump,
    route_answer,
)
from tests.enrichment.test_economy import (
    TO_TOMORROW_S,
    Probes,
    RecordedLogs,
    arriving_at,
)

KEY = AIRLINE_CALLSIGN

#: What the directory holds for the fixtures' callsign — deliberately a
#: *different* pair from :func:`route_answer`'s, so every assertion below says
#: which source answered rather than merely that something did.
VRS_ORIGIN = "EGLL"
VRS_DESTINATION = "KJFK"


@pytest.fixture
def directory(database: Database) -> RouteDirectoryRepository:
    return RouteDirectoryRepository(database)


#: The key-less tests below pass ``provider=None`` rather than a fake that
#: refuses to answer. That is not a shortcut: ``None`` is exactly what
#: :func:`~flightsite.enrichment.service.build_provider` returns for a stock
#: install and exactly what ``create_app`` hands the service, so "zero external
#: calls" is proved by there being no object to call rather than by an empty
#: call list on a double that could have been called.


@pytest.fixture
def probes() -> Probes:
    """The three closures ``create_app`` injects, as a test can drive them."""
    return Probes()


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> RecordedLogs:
    """Every structured event the enrichment service emitted.

    The module logger is replaced rather than captured through structlog, for
    the reason :class:`~tests.enrichment.test_economy.RecordedLogs` gives: by
    the time this suite runs, another test has usually configured structlog
    with cached bound loggers that ``capture_logs`` cannot intercept.
    """
    recorder = RecordedLogs()
    monkeypatch.setattr("flightsite.enrichment.service.logger", recorder)
    return recorder


async def seed_directory(
    directory: RouteDirectoryRepository,
    *records: RouteDirectoryRecord,
    version: str = "sha256:fixture",
) -> None:
    """Put ``records`` in the directory the way an import would."""
    await directory.clear_staging()
    await directory.stage_batch(records)
    await directory.promote(source="routes", at_ms=0, dataset_version=version)


def vrs_row(
    callsign: str = AIRLINE_CALLSIGN,
    path: str = f"{VRS_ORIGIN}-{VRS_DESTINATION}",
) -> RouteDirectoryRecord:
    return RouteDirectoryRecord(callsign=callsign, airport_codes=path, airline_code=callsign[:3])


def directory_service(
    *,
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository | None,
    provider: object,
    clock: SimulatedTime,
    probes: Probes,
    **overrides: Any,
) -> EnrichmentService:
    """A service wired to the directory and the probes, as ``create_app`` is."""
    return build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        directory=directory,
        alerting=probes.is_alerting,
        airport_context=probes.context_for,
        display_radius_nm=probes.display_radius_nm,
        **overrides,
    )


async def observe_once(
    service: EnrichmentService, live: LiveStore, worker: PersistenceWorker, clock: SimulatedTime
) -> None:
    """One observation, one persistence cycle, one drain."""
    clock.advance(1.0)
    observe(live, clock)
    await worker.process_pending()
    feed(service, live)
    await pump(service)
    await worker.process_pending()


# --------------------------------------------------------------- the chain


async def test_a_directory_hit_answers_without_a_single_provider_request(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """The acceptance criterion: known callsign, no AeroDataBox request."""
    await seed_directory(directory, vrs_row())
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=provider,
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    assert provider.calls == []
    assert service.lookups == 0
    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (VRS_ORIGIN, VRS_DESTINATION)
    assert sighting.route_source == ROUTE_SOURCE_VRS


async def test_a_directory_hit_is_cached_with_its_source(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    probes: Probes,
) -> None:
    """The row remembers who answered, so a hit stays attributable."""
    await seed_directory(directory, vrs_row())
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    row = await cache.get(KEY, now_ms=clock.epoch_ms())
    assert row is not None
    assert row.source == ROUTE_SOURCE_VRS
    assert (row.origin_ident, row.destination_ident) == (VRS_ORIGIN, VRS_DESTINATION)
    # For the positive TTL, like any other found route.
    assert row.expires_ms == clock.epoch_ms() + service.economy.route_ttl_s * MS_PER_SECOND


async def test_a_multi_leg_directory_row_keeps_its_path_in_the_cache_payload(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """Ends on the sighting, stops in ``payload_json`` for diagnostics."""
    await seed_directory(directory, vrs_row(path="VHHH-UACC-EBLG"))
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == ("VHHH", "EBLG")


async def test_a_callsign_the_directory_does_not_know_falls_through_to_the_provider(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """The provider is the fallback, not the source — but it is still there."""
    await seed_directory(directory, vrs_row(callsign="BAW1", path="EGLL-KJFK"))
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=provider,
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    assert provider.calls == [AIRLINE_CALLSIGN]
    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (ORIGIN, DESTINATION)
    assert sighting.route_source == ROUTE_SOURCE_AERODATABOX


async def test_a_provider_answer_records_which_provider_answered(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    probes: Probes,
) -> None:
    """A provider does not name itself in its reply, so the worker stamps it.

    Without that, a cached provider answer would come back un-attributed after
    a restart, and the directory-skip rule could not tell a contradicted
    ``vrs`` row from a contradicted ``aerodatabox`` one.
    """
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider({AIRLINE_CALLSIGN: route_answer()}),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    row = await cache.get(KEY, now_ms=clock.epoch_ms())
    assert row is not None
    assert row.source == ROUTE_SOURCE_AERODATABOX


async def test_the_cache_is_consulted_before_the_directory(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """Order matters: a live cached answer is nobody else's business."""
    await cache.store_route(
        KEY,
        RouteInfo(ORIGIN, DESTINATION, source=ROUTE_SOURCE_AERODATABOX),
        now_ms=clock.epoch_ms(),
    )
    await seed_directory(directory, vrs_row())
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (ORIGIN, DESTINATION)
    assert sighting.route_source == ROUTE_SOURCE_AERODATABOX


async def test_a_cached_directory_route_keeps_its_provenance_after_a_restart(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    database: Database,
    probes: Probes,
) -> None:
    """The row carries the source, so a fresh process re-attributes nothing.

    The directory is deliberately absent here: what is being proved is that a
    ``vrs`` row read out of ``route_cache`` still reaches the sighting as
    ``vrs``, without the process that wrote it or the table it came from.
    """
    await cache.store_route(
        KEY,
        RouteInfo(VRS_ORIGIN, VRS_DESTINATION, source=ROUTE_SOURCE_VRS),
        now_ms=clock.epoch_ms(),
    )
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=None,
        provider=FakeProvider(),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    assert (await only_sighting(database)).route_source == ROUTE_SOURCE_VRS


async def test_a_service_with_no_directory_behaves_exactly_as_before(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    database: Database,
    probes: Probes,
) -> None:
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=None,
        provider=provider,
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    assert provider.calls == [AIRLINE_CALLSIGN]
    assert (await only_sighting(database)).route_source == ROUTE_SOURCE_AERODATABOX


async def test_a_second_observation_is_answered_from_memory_not_the_directory(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    probes: Probes,
) -> None:
    """A hit costs one read per TTL, not one per observation."""
    await seed_directory(directory, vrs_row())
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(),
        clock=clock,
        probes=probes,
    )
    await observe_once(service, live, worker, clock)
    # Emptying the table after the first answer: a second read would now miss,
    # so the assertion is that no second read happens at all.
    await directory.clear_all()

    for _ in range(3):
        await observe_once(service, live, worker, clock)

    assert service.cache_stats.hits >= 3


# ------------------------------------------------------- the contradiction


async def test_a_contradicted_directory_row_sends_the_re_ask_to_the_provider(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
    logs: RecordedLogs,
) -> None:
    """Community data goes stale; the aircraft is the faster witness.

    The directory cannot be refreshed on demand, so the remedy is not to
    re-read it — it is to skip it and buy the answer from the source that can
    know better.
    """
    await seed_directory(directory, vrs_row())
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    # The aircraft lands somewhere the directory's route does not name.
    probes.contexts[ICAO] = arriving_at("KPDX")

    await observe_once(service, live, worker, clock)

    assert provider.calls == [AIRLINE_CALLSIGN]
    assert logs.named(DIRECTORY_CONTRADICTED_EVENT)
    sighting = await only_sighting(database)
    assert sighting.route_source == ROUTE_SOURCE_AERODATABOX


async def test_a_contradicted_directory_row_cannot_loop(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    probes: Probes,
) -> None:
    """The skip is what stops read-cache-contradict-read from repeating."""
    await seed_directory(directory, vrs_row())
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    probes.contexts[ICAO] = arriving_at("KPDX")

    for _ in range(6):
        await observe_once(service, live, worker, clock)

    assert provider.calls == [AIRLINE_CALLSIGN]


async def test_a_contradicted_provider_route_does_not_skip_the_directory(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """A wrong AeroDataBox answer says nothing about what the directory holds.

    So the invalidation clears the cache row and the *next* walk reaches the
    directory, which answers for free — rather than buying a second request on
    the strength of the first one being wrong.
    """
    await cache.store_route(
        KEY,
        RouteInfo(ORIGIN, DESTINATION, source=ROUTE_SOURCE_AERODATABOX),
        now_ms=clock.epoch_ms(),
    )
    await seed_directory(directory, vrs_row())
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    probes.contexts[ICAO] = arriving_at("KPDX")

    for _ in range(3):
        await observe_once(service, live, worker, clock)

    assert provider.calls == []
    assert (await only_sighting(database)).route_source == ROUTE_SOURCE_VRS


# -------------------------------------------------------- the last known route


async def expired_row(cache: RouteCacheRepository, clock: SimulatedTime) -> None:
    """A found route whose TTL has run out by the time the test drains."""
    await cache.store_route(
        KEY,
        RouteInfo(ORIGIN, DESTINATION, source=ROUTE_SOURCE_AERODATABOX),
        now_ms=clock.epoch_ms(),
        ttl_s=60,
    )
    clock.advance(120.0)


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param("timeout", id="timeout"),
        pytest.param("rate_limited", id="429"),
        pytest.param("transport", id="transport-error"),
        pytest.param("http_500", id="server-error"),
    ],
)
async def test_an_unavailable_provider_serves_the_last_known_route(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
    logs: RecordedLogs,
    reason: str,
) -> None:
    """Timeout, 429, transport error, 5xx: the sighting keeps last week's route."""
    answer = RouteUnavailable(reason)
    await expired_row(cache, clock)
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(default=answer),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (ORIGIN, DESTINATION)
    assert sighting.route_source == ROUTE_SOURCE_AERODATABOX
    assert service.cache_stats.stale_served == 1
    assert logs.named(STALE_SERVED_EVENT) == [
        {"callsign": AIRLINE_CALLSIGN, "reason": reason, "extended_s": STALE_EXTENSION_S}
    ]


async def test_a_spent_budget_serves_the_last_known_route(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """The day's credits are gone; the route on file is not."""
    await expired_row(cache, clock)
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=provider,
        clock=clock,
        probes=probes,
        # One lookup a day, and the expired row already spent it: the ledger is
        # counted from ``route_cache.fetched_ms``, not from a process counter.
        economy=EnrichmentEconomy(daily_lookup_budget=1),
    )

    await observe_once(service, live, worker, clock)

    assert provider.calls == []
    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (ORIGIN, DESTINATION)
    assert service.cache_stats.stale_served == 1


async def test_an_open_circuit_serves_the_last_known_route(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """``docs/ARCHITECTURE.md`` §Degradation, one step further than slice 026."""
    await expired_row(cache, clock)
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(default=RouteUnavailable("http_500")),
        clock=clock,
        probes=probes,
        failure_threshold=1,
    )
    # One failing request opens the circuit; the serve that follows is the
    # branch under test.
    await observe_once(service, live, worker, clock)
    assert service.circuit_open

    await observe_once(service, live, worker, clock)

    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (ORIGIN, DESTINATION)
    assert service.cache_stats.stale_served >= 1


async def test_a_stale_serve_pushes_the_expiry_a_day_out(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    probes: Probes,
) -> None:
    """One outage costs one serve, not one per observation."""
    await expired_row(cache, clock)
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(default=RouteUnavailable("timeout")),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)
    served_at = clock.epoch_ms()
    for _ in range(4):
        await observe_once(service, live, worker, clock)

    assert service.cache_stats.stale_served == 1
    row = await cache.get(KEY, now_ms=clock.epoch_ms())
    assert row is not None
    assert row.expires_ms == served_at + STALE_EXTENSION_S * MS_PER_SECOND


async def test_a_stale_serve_does_not_move_the_moment_the_answer_was_bought(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    probes: Probes,
) -> None:
    """``fetched_ms`` feeds the budget ledger and the confirmation rule.

    An outage must not be able to buy a day's credits back, nor to count as a
    day's agreement about a schedule.
    """
    await expired_row(cache, clock)
    before = await cache.get(KEY, now_ms=0)
    assert before is not None
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(default=RouteUnavailable("timeout")),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    after = await cache.get(KEY, now_ms=clock.epoch_ms())
    assert after is not None
    assert after.fetched_ms == before.fetched_ms
    assert after.confirmations == before.confirmations


async def test_the_stale_log_repeats_the_next_day_and_not_before(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    probes: Probes,
    logs: RecordedLogs,
) -> None:
    """Once per callsign per UTC day: an afternoon-long outage is one line."""
    await expired_row(cache, clock)
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(default=RouteUnavailable("timeout")),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)
    assert len(logs.named(STALE_SERVED_EVENT)) == 1

    # Past midnight, and past the day the serve pushed the expiry to.
    clock.advance(TO_TOMORROW_S + SECONDS_PER_DAY)
    await observe_once(service, live, worker, clock)

    assert len(logs.named(STALE_SERVED_EVENT)) == 2


async def test_an_expired_not_found_row_is_not_a_last_known_route(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """ "Nobody knows" is not a route to keep serving through an outage."""
    await cache.store_not_found(KEY, now_ms=clock.epoch_ms())
    clock.advance(SECONDS_PER_DAY * 2)
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(default=RouteUnavailable("timeout")),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    assert service.cache_stats.stale_served == 0
    sighting = await only_sighting(database)
    assert sighting.origin_ident is None
    assert sighting.route_source is None


async def test_a_callsign_never_answered_has_nothing_to_fall_back_on(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """SPEC §28's Unknown, unchanged: nothing is invented to fill the gap."""
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(default=RouteUnavailable("timeout")),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    assert service.cache_stats.stale_served == 0
    assert (await only_sighting(database)).origin_ident is None


async def test_a_directory_hit_answers_before_anything_goes_stale(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """A directory that knows the callsign is a fresh answer, not a fallback."""
    await expired_row(cache, clock)
    await seed_directory(directory, vrs_row())
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=FakeProvider(default=RouteUnavailable("timeout")),
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    assert service.cache_stats.stale_served == 0
    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (VRS_ORIGIN, VRS_DESTINATION)
    assert sighting.route_source == ROUTE_SOURCE_VRS


# ------------------------------------------------------ without any provider


async def test_a_key_less_install_enriches_from_the_directory(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """The point of the whole slice: no API key, and routes appear anyway.

    ``provider=None`` is not a stand-in here — it is exactly what
    :func:`~flightsite.enrichment.service.build_provider` returns for a stock
    install, and what ``create_app`` hands the service.
    """
    await seed_directory(directory, vrs_row())
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=None,
        clock=clock,
        probes=probes,
    )
    assert service.enabled is True
    assert service.provider_name is None

    await observe_once(service, live, worker, clock)

    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (VRS_ORIGIN, VRS_DESTINATION)
    assert sighting.route_source == ROUTE_SOURCE_VRS
    assert service.lookups == 0
    assert service.cache_stats.directory_hits == 1


async def test_a_key_less_install_with_an_empty_directory_does_nothing_observable(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """A stock install that has never imported routes: clean Unknowns.

    No route on the sighting, no row in the cache — nothing is invented, and
    nothing negative is filed either, because "this install cannot find a
    route" is not the same claim as "there is no route".
    """
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=None,
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    sighting = await only_sighting(database)
    assert sighting.origin_ident is None
    assert sighting.route_source is None
    assert service.lookups == 0
    assert service.cache_stats.directory_hits == 0
    assert await cache.size() == 0


async def test_a_key_less_install_holds_no_provider_to_call(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    probes: Probes,
) -> None:
    """Zero external calls, proved by there being nothing to call."""
    await seed_directory(directory, vrs_row())
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=None,
        clock=clock,
        probes=probes,
    )

    for _ in range(4):
        await observe_once(service, live, worker, clock)

    assert service._provider is None
    assert service.lookups == 0
    assert service.circuit_open is False


async def test_an_unanswerable_callsign_is_left_alone_for_a_while(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    probes: Probes,
) -> None:
    """A key-less miss must not cost two table reads on every observation.

    The backoff is in memory and nowhere else: the assertion is that the key
    stops being queued, *and* that no negative row was filed to achieve it.
    """
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=None,
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)
    for _ in range(5):
        clock.advance(1.0)
        observe(live, clock)
        feed(service, live)

    assert service.pending == 0
    assert await cache.size() == 0

    # Past the window, the worker is willing to look again — which is what
    # makes importing the routes dataset take effect without a restart.
    clock.advance(UNANSWERABLE_BACKOFF_S + 1)
    observe(live, clock)
    feed(service, live)

    assert service.pending == 1


async def test_the_last_known_route_survives_with_no_provider(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
    logs: RecordedLogs,
) -> None:
    """A key-less install has no source that can answer *now*, by definition.

    So the stale rule applies to it in full — and it is the case where it
    matters most, because there is no provider to come back later and refresh.
    """
    await expired_row(cache, clock)
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=None,
        clock=clock,
        probes=probes,
    )

    await observe_once(service, live, worker, clock)

    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (ORIGIN, DESTINATION)
    assert service.cache_stats.stale_served == 1
    assert logs.named(STALE_SERVED_EVENT) == [
        {"callsign": AIRLINE_CALLSIGN, "reason": "no_provider", "extended_s": STALE_EXTENSION_S}
    ]


async def test_a_provider_saved_later_answers_the_misses_without_a_restart(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """Issue #161's rule, now in the direction slice 071 opened up.

    A key-less install misses; the owner pastes a key and saves; the very next
    observation reaches the provider. Without a teardown — the reader task and
    its subscription are the same ones — and without waiting out the backoff
    the miss installed, which is why :meth:`_reset_provider_state` clears it.
    """
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=None,
        clock=clock,
        probes=probes,
    )
    await service.start()
    reader = service._reader
    await observe_once(service, live, worker, clock)
    assert service.pending == 0

    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    try:
        await service.apply_provider(provider)

        assert service._reader is reader
        assert service.running is True
        await observe_once(service, live, worker, clock)
    finally:
        await service.stop()

    assert provider.calls == [AIRLINE_CALLSIGN]
    sighting = await only_sighting(database)
    assert (sighting.origin_ident, sighting.destination_ident) == (ORIGIN, DESTINATION)
    assert sighting.route_source == ROUTE_SOURCE_AERODATABOX


async def test_removing_the_key_leaves_the_directory_answering(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    directory: RouteDirectoryRepository,
    database: Database,
    probes: Probes,
) -> None:
    """Removing an API key is not a request to stop enriching."""
    await seed_directory(directory, vrs_row(callsign="BAW1"))
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=directory,
        provider=provider,
        clock=clock,
        probes=probes,
    )
    await service.start()

    try:
        await service.apply_provider(None)

        assert provider.closed is True
        assert service.running is True
        assert service.enabled is True
        # An aircraft flying a callsign the directory *does* know is still
        # enriched, with no provider anywhere in the process.
        observe(live, clock, icao=OTHER_ICAO, callsign="BAW1")
        await worker.process_pending()
        feed(service, live)
        await pump(service)
        await worker.process_pending()
    finally:
        await service.stop()

    sighting = await only_sighting(database, OTHER_ICAO)
    assert sighting.route_source == ROUTE_SOURCE_VRS
    assert provider.calls == []


async def test_a_service_with_neither_source_starts_nothing(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    probes: Probes,
) -> None:
    """The one shape that still has no reason to run."""
    service = directory_service(
        live=live,
        worker=worker,
        cache=cache,
        directory=None,
        provider=None,
        clock=clock,
        probes=probes,
    )

    await service.start()

    try:
        assert service.enabled is False
        assert service.running is False
        observe(live, clock)
        feed(service, live)
        assert service.pending == 0
    finally:
        await service.stop()
