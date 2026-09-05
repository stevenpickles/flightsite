"""Enrichment settings taking effect on the save, not on the next restart.

The defect this pins (issue #161): the route provider was built exactly once,
in ``create_app``, from ``enrichment.aerodatabox_enabled`` and the key beside
it. ``PUT /api/internal/config`` applied alert templates, the receiver location
and a first-run ingestion start — and nothing else — so an owner who ticked
"enable route enrichment", pasted their AeroDataBox key and saved got two
values written to disk and a process that went on holding ``None``. Every route
stayed Unknown until the backend was restarted, and ``docs/CONFIGURATION.md``
listed ``enrichment.*`` under *Needs a restart* because of it. That is the same
bug as issues #110, #122 and #129, in the fourth subsystem to have captured a
setting at construction.

What is pinned here is wider than the ingestion hot-start next door, and
deliberately so. Ingestion is hot-**start** only — nothing → running — because
a running adapter owns a connection, a health history and a readiness
registration that a reconfiguration would strand. Enrichment owns none of
those: a bounded queue of callsigns it has not asked about yet, and an HTTP
client with no connection anyone is waiting on. So enabling, disabling *and*
re-keying are all applied, and the tests below say so one case at a time.

The negative half matters as much as the positive one. Switching enrichment off
must leave no object in the process that knows how to make the request, which
is the same guarantee ``test_app_wiring.py`` makes about a stock install — only
now it has to hold at every instant of the process's life rather than at boot.

Slice 071 changed what "off" *stops*, and these tests were rewritten to say so.
The offline route directory needs no key, so a save that removes one drops the
provider and leaves the worker running; a save that adds one installs the
provider in place, without cancelling the reader or shedding the queue. The
guarantee above is untouched — what changed is that it is now about the
provider alone rather than about the whole subsystem, which is why the
assertions below moved from ``enabled`` to ``provider_name``.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from flightsite.app import create_app
from flightsite.enrichment import (
    AeroDataBoxProvider,
    EnrichmentEconomy,
    EnrichmentService,
    RouteCacheRepository,
    RouteInfo,
)
from flightsite.enrichment.cache import MS_PER_SECOND, SECONDS_PER_DAY
from flightsite.enrichment.model import RouteUnavailable
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker
from tests.conftest import SECRET_SENTINEL
from tests.enrichment.conftest import (
    AIRLINE_CALLSIGN,
    ICAO,
    FakeProvider,
    SimulatedTime,
    build_service,
    feed,
    observe,
    pump,
    route_answer,
)

#: The document the Settings page sends when enrichment is switched on: the
#: flag and the key in one save, which is what the owner in issue #161 did.
ENABLE: dict[str, Any] = {
    "enrichment": {"aerodatabox_enabled": True, "aerodatabox_api_key": SECRET_SENTINEL}
}

#: And the one that switches it off again. The key stays stored; consent is
#: what was withdrawn.
DISABLE: dict[str, Any] = {"enrichment": {"aerodatabox_enabled": False}}


async def wait_until(condition: Callable[[], bool], *, timeout_s: float = 5.0) -> None:
    """Yield to the event loop until ``condition`` holds, or fail the test.

    Waits on an outcome rather than on a duration, so it can neither flake into
    a false pass nor assert anything about how long a task took to get there.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the condition was never reached")


# ------------------------------------------------------- applying to a service


async def test_a_provider_applied_before_start_is_the_one_start_uses(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """An app still being built takes the provider and waits for its lifespan.

    Starting here would be starting twice: ``create_app`` constructs the
    service and the lifespan hook starts it, so a provider applied in between
    must be installed and left alone.
    """
    service = build_service(live=live, worker=worker, cache=cache, provider=None, clock=clock)
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})

    await service.apply_provider(provider)

    assert service.enabled is True
    assert service.running is False

    await service.start()
    try:
        assert service.running is True
    finally:
        await service.stop()


async def test_enabling_on_a_running_app_starts_the_worker_and_looks_up(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug itself: enrichment off at boot, enabled at runtime, working.

    Driven through the service's own tasks rather than through ``consider`` and
    ``drain_once`` — the point of the fix is that a subscription and two tasks
    come into existence on the save, which is exactly what stepping the service
    by hand would hide.
    """
    monkeypatch.setattr("flightsite.enrichment.service.IDLE_POLL_S", 0.01)
    service = build_service(live=live, worker=worker, cache=cache, provider=None, clock=clock)
    # The lifespan of an install that booted with enrichment off: `start` was
    # called, and started nothing.
    await service.start()
    assert service.running is False
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})

    await service.apply_provider(provider)

    try:
        assert service.enabled is True
        assert service.running is True

        observe(live, clock)
        await worker.process_pending()
        await wait_until(lambda: provider.calls == [AIRLINE_CALLSIGN])
        await wait_until(lambda: worker.route_for(ICAO) is not None)
    finally:
        await service.stop()


async def test_disabling_stops_the_worker_and_closes_the_provider(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """Switching off restores the stock install's structural guarantee.

    Not "the worker ignores events" but "there is no provider": the object that
    knows how to make the request is closed and dropped, so the promise
    ``docs/SECURITY.md`` §10 makes — AeroDataBox is contacted only while
    enrichment is enabled — is kept by the object graph again.
    """
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    await service.start()
    assert service.running is True

    await service.apply_provider(None)

    assert service.running is False
    assert service.enabled is False
    assert provider.closed is True
    # And nothing queues, so nothing could be asked even if a task returned.
    observe(live, clock)
    feed(service, live)
    assert service.pending == 0
    assert await service.drain_once() is False


async def test_a_key_change_swaps_the_provider_and_starts_again(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """Re-keying swaps the client in place — never two clients, never a restart.

    Slice 071 changed the *how* and not the guarantee. It used to be a stop and
    a start, which cost a cancelled reader, a released subscription and a lost
    queue for a change no running task holds a reference to: ``_request`` reads
    ``self._provider`` at the moment it asks. Now the new provider is installed
    and the old one's client closed, and the tasks never notice — so the
    assertion that matters, that the replaced provider is closed and the new
    one is not, is unchanged, and the reader identity assertion is inverted.
    """
    first = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = build_service(live=live, worker=worker, cache=cache, provider=first, clock=clock)
    await service.start()
    reader = service._reader
    second = FakeProvider({AIRLINE_CALLSIGN: route_answer()})

    await service.apply_provider(second)

    try:
        assert service._provider is second
        assert first.closed is True
        assert second.closed is False
        assert service.running is True
        # The same reader, on the same subscription: nothing was torn down.
        assert service._reader is reader
    finally:
        await service.stop()


async def test_the_new_provider_is_installed_before_the_old_client_is_closed(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """The swap's ordering, which the worker's survival depends on (slice 071).

    Closing a client is the one ``await`` in the swap, and since slice 071 the
    worker runs right through it. ``AeroDataBoxProvider`` builds its client
    lazily, so a drain that reached :meth:`_request` during that await, while
    ``self._provider`` still named the provider being closed, would build it a
    *fresh* client and send the key the owner had just removed. Installing
    first closes that window: whoever asks during the close asks the new
    provider, or asks nobody.
    """
    closed_against: list[Any] = []

    class RecordingProvider(FakeProvider):
        async def aclose(self) -> None:
            closed_against.append(service._provider)
            await super().aclose()

    first = RecordingProvider({AIRLINE_CALLSIGN: route_answer()})
    service = build_service(live=live, worker=worker, cache=cache, provider=first, clock=clock)
    second = RecordingProvider({AIRLINE_CALLSIGN: route_answer()})

    await service.apply_provider(second)

    assert closed_against == [second]
    assert first.closed is True

    # And the same the other way: removing the key leaves nothing to ask
    # while the client that could have answered is still closing.
    await service.apply_provider(None)

    assert closed_against == [second, None]


async def test_an_unchanged_configuration_leaves_the_running_worker_alone(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """The common case, and the reason the comparison is by configuration.

    Every save reaches the apply step with a freshly built provider — saving
    the map style builds one, saving a watchlist builds one — so an identity
    test would cancel both tasks and resubscribe on every save of every
    setting. Object identity is asserted deliberately: an equivalent provider
    must be *declined*, not installed.
    """
    provider = AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL))
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    await service.start()
    tasks = (service._reader, service._worker)

    await service.apply_provider(AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL)))

    try:
        assert service._provider is provider
        assert (service._reader, service._worker) == tasks
    finally:
        await service.stop()


async def test_a_save_that_leaves_enrichment_off_starts_nothing(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """``None`` matching ``None`` is the no-op every stock install takes."""
    service = build_service(live=live, worker=worker, cache=cache, provider=None, clock=clock)
    await service.start()

    await service.apply_provider(None)

    assert service.enabled is False
    assert service.running is False


async def test_swapping_the_provider_resets_the_failure_circuit(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """A run of failures earned by the old key says nothing about the new one.

    Without this the install most likely to re-key — the one whose key was
    being rejected — would spend its first cooldown refusing every lookup it
    had just paid for.
    """
    failing = FakeProvider(default=RouteUnavailable(reason="rate_limited"))
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=failing,
        clock=clock,
        failure_threshold=1,
    )
    observe(live, clock)
    await worker.process_pending()
    feed(service, live)
    await pump(service)
    assert service.circuit_open is True
    assert service.lookups == 1

    await service.apply_provider(FakeProvider({AIRLINE_CALLSIGN: route_answer()}))

    assert service.circuit_open is False
    # Per-provider totals start again with the provider they describe.
    assert service.lookups == 0
    assert service.pending == 0
    assert failing.closed is True


# --------------------------------------------------- applying a spending plan


async def test_a_changed_budget_applies_without_restarting_the_worker(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """Slice 070's numbers are adopted in place, not by a teardown.

    A budget is not a provider: nothing about it invalidates the subscription,
    the queue or the remembered answers, and restarting for it would shed a
    queue of callsigns for a setting that does not change who is asked.
    """
    provider = AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL))
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    await service.start()
    tasks = (service._reader, service._worker)

    await service.apply_provider(
        AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL)),
        EnrichmentEconomy(route_ttl_days=3, daily_lookup_budget=25),
    )

    try:
        assert service.economy == EnrichmentEconomy(route_ttl_days=3, daily_lookup_budget=25)
        assert service._provider is provider
        assert (service._reader, service._worker) == tasks
        assert service.budget.limit == 25
    finally:
        await service.stop()


async def test_an_unchanged_budget_is_still_the_no_op_every_save_takes(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """The whole configuration is compared, so an unrelated save changes nothing."""
    economy = EnrichmentEconomy(route_ttl_days=3, daily_lookup_budget=25)
    provider = AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL))
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        economy=economy,
    )
    await service.start()
    tasks = (service._reader, service._worker)

    await service.apply_provider(AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL)), economy)

    try:
        assert service._provider is provider
        assert (service._reader, service._worker) == tasks
    finally:
        await service.stop()


async def test_a_changed_ttl_is_used_by_the_next_answer_stored(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """A setting that applied on the next restart would be a setting in a file."""
    provider = FakeProvider({AIRLINE_CALLSIGN: route_answer()})
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)

    await service.apply_provider(provider, EnrichmentEconomy(route_ttl_days=2))
    observe(live, clock)
    feed(service, live)
    await pump(service)

    row = await cache.get(AIRLINE_CALLSIGN, now_ms=clock.epoch_ms())
    assert row is not None
    assert row.expires_ms == clock.epoch_ms() + 2 * SECONDS_PER_DAY * MS_PER_SECOND


async def test_raising_a_spent_budget_resumes_lookups_on_the_save(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """Otherwise the owner who noticed the cap would wait until midnight."""
    provider = FakeProvider(default=route_answer())
    service = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=provider,
        clock=clock,
        economy=EnrichmentEconomy(daily_lookup_budget=1),
    )
    for index in range(2):
        clock.advance(1.0)
        observe(live, clock, f"a0000{index:x}", callsign=f"DAL{index}00")
        feed(service, live)
        await pump(service)
    assert provider.calls == ["DAL000"]

    await service.apply_provider(provider, EnrichmentEconomy(daily_lookup_budget=5))
    await pump(service)

    assert provider.calls == ["DAL000", "DAL100"]
    assert service.budget.used_today == 2
    assert service.budget.remaining == 3


async def test_lowering_the_budget_below_what_is_spent_stops_lookups(
    live: LiveStore,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    clock: SimulatedTime,
) -> None:
    """``remaining`` is clamped at zero rather than going negative."""
    await cache.store_route("DAL000", RouteInfo("KATL", "KSLC"), now_ms=clock.epoch_ms())
    await cache.store_route("DAL100", RouteInfo("KATL", "KSLC"), now_ms=clock.epoch_ms())
    provider = FakeProvider(default=route_answer())
    service = build_service(live=live, worker=worker, cache=cache, provider=provider, clock=clock)
    await service.start()

    await service.apply_provider(provider, EnrichmentEconomy(daily_lookup_budget=1))
    observe(live, clock, "a00003", callsign="DAL300")
    feed(service, live)
    await pump(service)
    await service.stop()

    assert provider.calls == []
    assert service.budget.remaining == 0


# ------------------------------------------------------- applying through PUT


@pytest.fixture
def client(isolated_data_dir: Path) -> Iterator[TestClient]:
    """The real app, through its lifespan, on an empty data directory."""
    with TestClient(create_app(isolated_data_dir)) as test_client:
        yield test_client


def enrichment_of(client: TestClient) -> EnrichmentService:
    """The running app's enrichment service."""
    service: EnrichmentService = client.app.state.enrichment  # type: ignore[attr-defined]
    return service


def emitted_events(output: str) -> list[dict[str, Any]]:
    """Every structured log line the app printed, decoded.

    Read from the process's own output rather than through ``caplog``, because
    ``configure_logging`` runs inside ``create_app`` and would reconfigure
    structlog out from under a fixture that had already redirected it.
    """
    events = []
    for line in output.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue  # interleaved non-JSON output, e.g. a traceback
    return events


def test_a_save_that_enables_enrichment_starts_the_provider(client: TestClient) -> None:
    """The owner's report, end to end: tick the box, paste the key, save.

    What the save changes since slice 071 is the *provider*, not whether
    enrichment runs: the app always wires the offline route directory, so the
    worker was already going and ``enabled`` was already true. ``provider_name``
    is the assertion that means "this install can now reach AeroDataBox".
    """
    service = enrichment_of(client)
    assert service.provider_name is None
    assert service.enabled is True

    response = client.put("/api/internal/config", json=ENABLE)

    assert response.status_code == 200
    assert service.provider_name == "aerodatabox"
    assert service.running is True
    assert isinstance(service._provider, AeroDataBoxProvider)
    # The key was stored, and the response still does not carry it.
    assert response.json()["secrets_set"] == {"enrichment.aerodatabox_api_key": True}
    assert SECRET_SENTINEL not in response.text


def test_the_flag_builds_the_provider_when_the_key_is_already_stored(
    client: TestClient,
) -> None:
    """The other order the Settings page allows: key first, consent second.

    Holding a key is not consent to use it, so the first save must build no
    provider — and the second must not need the key sent again. The worker runs
    throughout either way, because the directory needs no key.
    """
    service = enrichment_of(client)

    client.put(
        "/api/internal/config", json={"enrichment": {"aerodatabox_api_key": SECRET_SENTINEL}}
    )
    assert service.provider_name is None
    assert service.running is True

    client.put("/api/internal/config", json={"enrichment": {"aerodatabox_enabled": True}})

    assert service.provider_name == "aerodatabox"
    assert service.running is True


def test_a_save_that_disables_enrichment_drops_the_provider_not_the_worker(
    client: TestClient,
) -> None:
    """Withdrawing consent takes effect on the save, like granting it.

    What it withdraws is the *online* provider. Removing an API key is not a
    request to stop enriching, and since slice 071 it does not: the directory
    is the primary source and keeps answering, so the worker keeps running and
    only the object that could have made a request is closed and dropped.
    """
    service = enrichment_of(client)
    client.put("/api/internal/config", json=ENABLE)
    assert service.running is True

    response = client.put("/api/internal/config", json=DISABLE)

    assert response.status_code == 200
    assert service.provider_name is None
    assert service.running is True
    assert service.enabled is True
    # The key is still stored — it is the flag that was turned off.
    assert response.json()["secrets_set"] == {"enrichment.aerodatabox_api_key": True}


def test_a_saved_budget_and_ttl_reach_the_running_worker(client: TestClient) -> None:
    """Issue #167 end to end: type two numbers, save, and they are in force."""
    service = enrichment_of(client)
    client.put("/api/internal/config", json=ENABLE)
    provider, reader = service._provider, service._reader

    response = client.put(
        "/api/internal/config",
        json={"enrichment": {"route_ttl_days": 14, "daily_lookup_budget": 500}},
    )

    assert response.status_code == 200
    assert service.economy.route_ttl_days == 14
    assert service.economy.daily_lookup_budget == 500
    assert service.budget.limit == 500
    # And the worker kept everything it was doing: a number is not a re-key.
    assert service._provider is provider
    assert service._reader is reader
    assert service.running is True


def test_the_budget_can_be_set_before_enrichment_is_enabled(client: TestClient) -> None:
    """The Settings page can be filled in in any order, as it always could."""
    service = enrichment_of(client)

    client.put("/api/internal/config", json={"enrichment": {"daily_lookup_budget": 40}})

    assert service.provider_name is None
    assert service.economy.daily_lookup_budget == 40


def test_a_save_about_another_section_leaves_the_worker_untouched(client: TestClient) -> None:
    """Saving the display radius must not restart the enrichment worker.

    Identity on both the provider and the reader task, because a save that
    rebuilt either would be shedding a subscription and a queue of pending
    lookups for a setting that has nothing to do with enrichment.
    """
    service = enrichment_of(client)
    client.put("/api/internal/config", json=ENABLE)
    provider, reader = service._provider, service._reader

    response = client.put("/api/internal/config", json={"display_radius_nm": 90.0})

    assert response.status_code == 200
    assert service._provider is provider
    assert service._reader is reader
    assert service.running is True


def test_a_failing_apply_still_saves_the_configuration(
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The configuration is validated, written and live before this runs.

    So a failure here can only turn a save that succeeded into a 500 about it.
    Same rule as the three apply entries beside it — reported, and swallowed.
    """

    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("no provider today")

    monkeypatch.setattr("flightsite.api.internal.build_provider", explode)
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        response = client.put("/api/internal/config", json=ENABLE)

        assert response.status_code == 200
        assert app.state.settings.enrichment.aerodatabox_enabled is True
        # No provider was built, so none was installed — and the worker goes on
        # answering from the directory, which is not what failed.
        assert app.state.enrichment.provider_name is None

    captured = capsys.readouterr()
    failures = [
        event
        for event in emitted_events(captured.out + captured.err)
        if event.get("event") == "config_apply_failed" and event.get("setting") == "enrichment"
    ]
    assert failures, "a swallowed failure must still be reported"
    assert failures[0]["error_type"] == "RuntimeError"
    # And the report of the failure does not carry what provoked it.
    assert SECRET_SENTINEL not in json.dumps(failures[0])
