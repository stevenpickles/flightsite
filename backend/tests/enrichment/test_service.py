"""The consumer, end to end over the real live store and persistence worker.

Nothing is stubbed here except the provider and the clock: a real live store
applies real decoder batches, a real persistence worker opens real sightings in
a real migrated database, and the API serializer builds the real §3.3 payload.
So "a sighting opens, enrichment lands, the event is written, the payload
carries the route with its provenance" is proved as one path rather than as
four units that agree by inspection.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from flightsite.api.serializers import aircraft_payload
from flightsite.counters import counters
from flightsite.db import Database
from flightsite.enrichment import EnrichmentService, RouteCacheRepository, RouteInfo
from flightsite.enrichment.model import RouteNotFound, RouteUnavailable
from flightsite.enrichment.service import ENRICHMENT_FAILURES_COUNTER
from flightsite.live import LiveStore
from flightsite.live.events import AircraftAppeared, AircraftRemoved, AircraftStale
from flightsite.sightings import PersistenceWorker
from flightsite.sightings.vocabulary import SightingEventType
from tests.enrichment.conftest import (
    AIRLINE_CALLSIGN,
    BASE_DATE,
    DESTINATION,
    ICAO,
    ORIGIN,
    OTHER_ICAO,
    FakeProvider,
    SimulatedTime,
    build_service,
    events_of,
    feed,
    mock_provider,
    observe,
    only_sighting,
    pump,
    route_answer,
)

KEY = f"{AIRLINE_CALLSIGN}:{BASE_DATE}"


async def enrich(service: EnrichmentService, live: LiveStore, worker: PersistenceWorker) -> None:
    """One full turn: persist the observation, enrich it, persist the route.

    The leading cycle is not ceremony. In the running app the worker ticks once
    a second and a lookup takes far longer than that, so by the time an answer
    arrives the accumulator it belongs to exists. Stepping both by hand means
    the test has to put them in that order itself.
    """
    await worker.process_pending()
    feed(service, live)
    await pump(service)
    await worker.process_pending()


# ------------------------------------------------------------- the happy path


async def test_an_eligible_sighting_gains_a_route(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    database: Database,
) -> None:
    """The slice's first acceptance criterion, from decoder batch to row."""
    observe(live, clock)
    await worker.process_pending()

    await enrich(service, live, worker)

    row = await only_sighting(database)
    assert (row.origin_ident, row.destination_ident) == (ORIGIN, DESTINATION)
    assert row.route_source == "aerodatabox"


async def test_the_arrival_is_a_sighting_event(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    database: Database,
) -> None:
    """SPEC §52: enrichment arriving is a change worth recording."""
    observe(live, clock)
    await worker.process_pending()
    clock.advance(30.0)

    await enrich(service, live, worker)

    row = await only_sighting(database)
    events = await events_of(database, row.id)
    enriched = [event for event in events if event.type == SightingEventType.ROUTE_ENRICHED]
    assert len(enriched) == 1
    assert enriched[0].ts_ms == clock.epoch_ms()
    assert '"source":"aerodatabox"' in (enriched[0].payload_json or "")


async def test_the_route_and_its_event_land_in_one_transaction(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    database: Database,
) -> None:
    """Riding the worker's cycle is what makes this true, not luck."""
    observe(live, clock)
    await worker.process_pending()
    feed(service, live)
    await pump(service)

    # Nothing has been written yet: the accumulator holds both.
    row_before = await only_sighting(database)
    assert row_before.origin_ident is None
    assert await events_of(database, row_before.id) == []

    await worker.process_pending()

    row = await only_sighting(database)
    assert row.origin_ident == ORIGIN
    assert len(await events_of(database, row.id)) == 1


async def test_the_live_payload_carries_the_route_and_its_provenance(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
) -> None:
    """``docs/API.md`` §2.6: the route block, attributed to the provider."""
    observe(live, clock)
    await enrich(service, live, worker)
    record = live.get(ICAO)
    assert record is not None

    payload = aircraft_payload(record, route=worker.route_for(ICAO))

    assert payload["route"] == {
        "origin": ORIGIN,
        "origin_name": None,
        "destination": DESTINATION,
        "destination_name": None,
    }
    assert payload["provenance"]["route"] == "aerodatabox"


async def test_the_route_block_is_present_and_null_before_enrichment(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """§2.7: unknown is a null value under a stable key, never a missing key."""
    observe(live, clock, callsign=None)
    record = live.get(ICAO)
    assert record is not None

    payload = aircraft_payload(record)

    assert payload["route"] == {
        "origin": None,
        "origin_name": None,
        "destination": None,
        "destination_name": None,
    }
    assert "route" not in payload["provenance"]


async def test_a_second_aircraft_on_the_same_flight_number_shares_one_lookup(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    provider: FakeProvider,
) -> None:
    observe(live, clock, ICAO)
    await enrich(service, live, worker)

    clock.advance(1.0)
    observe(live, clock, OTHER_ICAO)
    await enrich(service, live, worker)

    assert provider.calls == [AIRLINE_CALLSIGN]
    assert worker.route_for(OTHER_ICAO) is not None


# ------------------------------------------------------------- the gates


async def test_an_ineligible_callsign_is_never_looked_up(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    provider: FakeProvider,
) -> None:
    observe(live, clock, callsign="N738AB")

    await enrich(service, live, worker)

    assert provider.calls == []
    assert worker.route_for(ICAO) is None


async def test_a_repeated_observation_spends_one_request(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    provider: FakeProvider,
) -> None:
    """The acceptance criterion: the cache prevents duplicate queries."""
    for _ in range(5):
        clock.advance(1.0)
        observe(live, clock)
        await enrich(service, live, worker)

    assert provider.calls == [AIRLINE_CALLSIGN]


async def test_a_fresh_cache_row_answers_without_a_request(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    provider: FakeProvider,
) -> None:
    """A restart re-reads the table rather than re-buying the answer."""
    await cache.store_route(KEY, RouteInfo(ORIGIN, DESTINATION), now_ms=clock.epoch_ms())
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    observe(live, clock)

    await enrich(service, live, worker)

    assert provider.calls == []
    assert worker.route_for(ICAO) is not None


async def test_a_negative_cache_row_skips_the_request_and_leaves_unknown(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    provider: FakeProvider,
) -> None:
    await cache.store_not_found(KEY, now_ms=clock.epoch_ms())
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    observe(live, clock)

    await enrich(service, live, worker)

    assert provider.calls == []
    assert worker.route_for(ICAO) is None


async def test_a_provider_with_no_route_negative_caches_it(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    database: Database,
) -> None:
    """ "Unknown when uncertain": nothing is written to the sighting."""
    provider = FakeProvider(default=RouteNotFound())
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    observe(live, clock)

    await enrich(service, live, worker)

    assert provider.calls == [AIRLINE_CALLSIGN]
    assert await cache.get(KEY, now_ms=clock.epoch_ms()) is not None
    row = await only_sighting(database)
    assert (row.origin_ident, row.destination_ident, row.route_source) == (None, None, None)


# ------------------------------------------------------------- degradation


async def test_a_disabled_install_starts_nothing_and_calls_nothing(
    live: LiveStore, worker: PersistenceWorker, cache: RouteCacheRepository, clock: SimulatedTime
) -> None:
    """ "without key: zero external calls" — structurally, not by discipline."""
    service = build_service(live=live, worker=worker, cache=cache, provider=None, clock=clock)

    await service.start()
    observe(live, clock)
    feed(service, live)

    assert service.enabled is False
    assert service.running is False
    assert service.pending == 0
    assert service.lookups == 0
    await service.stop()


async def test_a_disabled_install_leaves_a_clean_unknown(
    live: LiveStore, worker: PersistenceWorker, cache: RouteCacheRepository, clock: SimulatedTime
) -> None:
    service = build_service(live=live, worker=worker, cache=cache, provider=None, clock=clock)
    observe(live, clock)
    await worker.process_pending()

    feed(service, live)
    await pump(service)
    record = live.get(ICAO)
    assert record is not None

    assert aircraft_payload(record, route=worker.route_for(ICAO))["route"] == {
        "origin": None,
        "origin_name": None,
        "destination": None,
        "destination_name": None,
    }


async def test_an_unavailable_provider_counts_a_failure_and_writes_nothing(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    database: Database,
) -> None:
    """The offline case: a clean Unknown, a counter, and no cached lie."""
    provider = FakeProvider(default=RouteUnavailable(reason="transport_error"))
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    observe(live, clock)

    await enrich(service, live, worker)

    assert counters.snapshot()[ENRICHMENT_FAILURES_COUNTER] == 1
    assert await cache.size() == 0
    row = await only_sighting(database)
    assert row.route_source is None


async def test_consecutive_failures_open_the_circuit_and_stop_the_requests(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker, cache: RouteCacheRepository
) -> None:
    provider = FakeProvider(default=RouteUnavailable(reason="transport_error"))
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        failure_threshold=2,
        cooldown_s=300.0,
    )

    for index in range(6):
        clock.advance(1.0)
        observe(live, clock, callsign=f"DAL{index}")
        await enrich(service, live, worker)

    assert service.circuit_open is True
    assert len(provider.calls) == 2


async def test_the_circuit_closes_again_when_the_provider_recovers(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker, cache: RouteCacheRepository
) -> None:
    provider = FakeProvider(default=RouteUnavailable(reason="transport_error"))
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        failure_threshold=1,
        cooldown_s=300.0,
    )
    observe(live, clock, callsign="DAL9")
    await enrich(service, live, worker)
    assert service.circuit_open is True

    provider.default = route_answer()
    clock.advance(300.0)
    clock.advance(1.0)
    observe(live, clock)
    await enrich(service, live, worker)

    assert service.circuit_open is False
    assert worker.route_for(ICAO) is not None


async def test_the_rate_limiter_defers_rather_than_drops(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker, cache: RouteCacheRepository
) -> None:
    """A refused token keeps the key queued; a minute later it is spent."""
    provider = FakeProvider(default=route_answer())
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        rate_per_minute=60.0,
    )

    for index in range(12):
        clock.advance(0.001)
        observe(live, clock, f"a0000{index:x}", callsign=f"DAL{index}00")
    feed(service, live)
    for _ in range(20):
        await service.drain_once()

    assert len(provider.calls) == 10
    assert service.pending == 2

    clock.advance(60.0)
    for _ in range(4):
        await service.drain_once()

    assert len(provider.calls) == 12
    assert service.pending == 0


async def test_a_cached_route_still_applies_while_the_circuit_is_open(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker, cache: RouteCacheRepository
) -> None:
    """``docs/ARCHITECTURE.md`` §Degradation: cached enrichment persists."""
    provider = FakeProvider(default=RouteUnavailable(reason="transport_error"))
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        failure_threshold=1,
    )
    await cache.store_route(KEY, RouteInfo(ORIGIN, DESTINATION), now_ms=clock.epoch_ms())
    observe(live, clock, callsign="DAL9")
    await enrich(service, live, worker)
    assert service.circuit_open is True

    clock.advance(1.0)
    observe(live, clock)
    await enrich(service, live, worker)

    assert worker.route_for(ICAO) is not None


# ------------------------------------------------------------- the bounds


async def test_the_queue_sheds_the_oldest_and_counts_it(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker, cache: RouteCacheRepository
) -> None:
    """Bounded, drop-oldest, counted — the live stream's own policy."""
    provider = FakeProvider(default=route_answer())
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        pending_limit=3,
    )

    for index in range(6):
        clock.advance(0.001)
        observe(live, clock, f"a0000{index:x}", callsign=f"DAL{index}00")
    feed(service, live)

    assert service.pending == 3
    assert service.dropped == 3
    # The newest sky survived: what is overhead now is what is worth enriching.
    await service.drain_once()
    assert provider.calls == ["DAL300"]


async def test_a_route_already_applied_is_not_reapplied(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    database: Database,
) -> None:
    """Exactly one ``route_enriched`` event however many times it is delivered."""
    observe(live, clock)
    await enrich(service, live, worker)
    for _ in range(3):
        clock.advance(1.0)
        observe(live, clock)
        await enrich(service, live, worker)

    row = await only_sighting(database)
    events = await events_of(database, row.id)

    assert [event.type for event in events].count(SightingEventType.ROUTE_ENRICHED) == 1


async def test_an_answer_for_an_aircraft_that_has_gone_is_dropped_quietly(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
) -> None:
    """The lookup outlived the sighting; that is an outcome, not an error."""
    observe(live, clock)
    feed(service, live)
    await worker.process_pending()
    clock.advance(700.0)
    live.sweep()
    await worker.process_pending()
    await worker.process_pending()

    await pump(service)

    assert worker.route_for(ICAO) is None


# ---------------------------------------------------------------- lifecycle


async def test_start_and_stop_are_idempotent(
    service: EnrichmentService, provider: FakeProvider
) -> None:
    await service.start()
    await service.start()
    assert service.running is True

    await service.stop()
    await service.stop()

    assert service.running is False
    assert provider.closed is True


async def test_the_running_service_enriches_from_its_own_tasks(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
) -> None:
    """The wiring the app actually uses, not just the hand-stepped path."""
    await service.start()
    try:
        observe(live, clock)
        await worker.process_pending()
        for _ in range(8):
            await asyncio.sleep(0)
            await service.wait_idle()
            if worker.route_for(ICAO) is not None:
                break
    finally:
        await service.stop()

    assert worker.route_for(ICAO) is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("pending_limit", 0, id="pending-limit"),
        pytest.param("answer_limit", 0, id="answer-limit"),
    ],
)
def test_a_meaningless_bound_is_refused(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_service(
            live=live,
            worker=worker,
            cache=cache,
            provider=FakeProvider(),
            clock=clock,
            **{field: value},
        )


async def test_the_real_provider_runs_through_the_service(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker, cache: RouteCacheRepository
) -> None:
    """One test with no fake provider at all: mock transport, real client."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "number": "DL1234",
                    "departure": {"airport": {"icao": ORIGIN}},
                    "arrival": {"airport": {"icao": DESTINATION}},
                }
            ],
        )

    provider, client = mock_provider(handler)
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    async with client:
        observe(live, clock)
        await enrich(service, live, worker)

    route = worker.route_for(ICAO)
    assert route is not None
    assert (route.origin_ident, route.destination_ident) == (ORIGIN, DESTINATION)


# --------------------------------------------------------- the reader task


async def test_the_reader_drains_a_burst_and_recovers_from_an_overflow(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker, cache: RouteCacheRepository
) -> None:
    """A shed live event costs a delayed lookup, never a resync or a stall."""
    provider = FakeProvider(default=route_answer())
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        queue_size=2,
    )
    await service.start()
    try:
        for index in range(6):
            clock.advance(0.001)
            observe(live, clock, f"a0000{index:x}", callsign=f"DAL{index}00")
        for _ in range(8):
            await asyncio.sleep(0)
    finally:
        await service.stop()

    # The tail survived: the newest sky is the one worth enriching.
    assert service.pending > 0


async def test_an_event_that_carries_no_new_observation_is_ignored(
    service: EnrichmentService, live: LiveStore, clock: SimulatedTime
) -> None:
    """Staleness announces silence; removal names an aircraft already gone."""
    observe(live, clock)
    record = live.get(ICAO)
    assert record is not None

    service.consider(AircraftStale(aircraft=record, at=record.last_seen))
    service.consider(AircraftRemoved(aircraft=record, at=record.last_seen))

    assert service.pending == 0


async def test_two_aircraft_queued_on_one_callsign_coalesce(
    service: EnrichmentService,
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    provider: FakeProvider,
) -> None:
    """Queued together, before either is drained: one key, two waiters."""
    observe(live, clock, ICAO)
    clock.advance(0.001)
    observe(live, clock, OTHER_ICAO)
    await worker.process_pending()
    feed(service, live)

    assert service.pending == 1

    await pump(service)
    await worker.process_pending()

    assert provider.calls == [AIRLINE_CALLSIGN]
    assert worker.route_for(ICAO) is not None
    assert worker.route_for(OTHER_ICAO) is not None


async def test_an_aircraft_seen_mid_lookup_rides_the_request_in_flight(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker, cache: RouteCacheRepository
) -> None:
    """A second airframe on the same number must not buy a second answer."""
    observe(live, clock, ICAO)
    clock.advance(0.001)
    observe(live, clock, OTHER_ICAO)
    await worker.process_pending()

    class LateArrival(FakeProvider):
        """Publishes a second observation while the first lookup is open."""

        service: EnrichmentService

        async def lookup(self, callsign: str) -> RouteInfo | RouteNotFound | RouteUnavailable:
            record = live.get(OTHER_ICAO)
            assert record is not None
            self.service.consider(AircraftAppeared(aircraft=record, at=record.last_seen))
            return await super().lookup(callsign)

    provider = LateArrival(default=route_answer())
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    provider.service = service
    record = live.get(ICAO)
    assert record is not None
    service.consider(AircraftAppeared(aircraft=record, at=record.last_seen))

    await pump(service)
    await worker.process_pending()

    assert provider.calls == [AIRLINE_CALLSIGN]
    assert worker.route_for(OTHER_ICAO) is not None


async def test_remembered_answers_are_bounded(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker, cache: RouteCacheRepository
) -> None:
    """Evicting an answer costs one cache read, never a second request."""
    provider = FakeProvider(default=route_answer())
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        answer_limit=1,
    )

    for index in range(3):
        clock.advance(1.0)
        observe(live, clock, f"a0000{index:x}", callsign=f"DAL{index}00")
        await enrich(service, live, worker)

    # The evicted key is re-asked about, and the cache table answers it.
    clock.advance(1.0)
    observe(live, clock, "a00000", callsign="DAL000")
    await enrich(service, live, worker)

    assert provider.calls == ["DAL000", "DAL100", "DAL200"]
