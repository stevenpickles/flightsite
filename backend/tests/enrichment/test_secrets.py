"""The API key must not escape — SPEC §29, and slice 026's fourth criterion.

Every test here drives the *real* provider with the sentinel key from
:mod:`tests.conftest` and then sweeps for that exact string. Sweeping for a
sentinel rather than asserting on masking is deliberate: masking is one way to
keep the promise, and a test that asserted the mask would pass a rewrite that
kept the mask and leaked the value somewhere else.

The one place the key is *supposed* to appear is the request header, and
:mod:`tests.enrichment.test_provider` asserts that. Everything else — logs,
exception text, returned values, the cache row, the API payload, the
configuration dump — is swept here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import structlog
from pydantic import SecretStr
from sqlalchemy import select

from flightsite.api.serializers import aircraft_payload
from flightsite.config.models import EnrichmentSettings, Settings
from flightsite.db import Database, RouteCache
from flightsite.enrichment import AeroDataBoxProvider, EnrichmentService, RouteCacheRepository
from flightsite.enrichment.service import build_provider
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker
from tests.conftest import SECRET_SENTINEL
from tests.enrichment.conftest import (
    DESTINATION,
    ICAO,
    ORIGIN,
    SimulatedTime,
    build_service,
    feed,
    mock_provider,
    observe,
    pump,
)


@pytest.fixture
def captured_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Route structlog through the stdlib logger ``caplog`` can see."""
    structlog.configure(
        processors=[structlog.stdlib.render_to_log_kwargs],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    caplog.set_level(logging.DEBUG)
    yield caplog
    structlog.reset_defaults()


def swept(records: list[logging.LogRecord]) -> str:
    """Every log record flattened into one string to search."""
    return "\n".join(f"{record.getMessage()} {record.__dict__}" for record in records)


def failing_handler(response: httpx.Response) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return handler


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(httpx.Response(401, text=f"bad key {SECRET_SENTINEL}"), id="rejected-key"),
        pytest.param(httpx.Response(429), id="rate-limited"),
        pytest.param(httpx.Response(500), id="server-error"),
        pytest.param(httpx.Response(200, text="not json"), id="unparsable"),
    ],
)
async def test_a_failed_lookup_never_logs_the_key(
    response: httpx.Response, captured_logs: pytest.LogCaptureFixture
) -> None:
    """Including the 401 whose *body* echoes it: the body is never logged."""
    provider, client = mock_provider(failing_handler(response))
    async with client:
        result = await provider.lookup("DAL1234")

    assert SECRET_SENTINEL not in swept(captured_logs.records)
    assert SECRET_SENTINEL not in repr(result)


async def test_a_transport_failure_never_logs_the_key(
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    """httpx exceptions can echo the request, which carries the header."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    provider, client = mock_provider(handler)
    async with client:
        result = await provider.lookup("DAL1234")

    assert SECRET_SENTINEL not in swept(captured_logs.records)
    assert SECRET_SENTINEL not in repr(result)


def test_the_provider_does_not_render_its_key() -> None:
    """``repr`` is where a key most often escapes into a traceback."""
    provider = AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL))

    assert SECRET_SENTINEL not in repr(provider)
    assert SECRET_SENTINEL not in str(provider)
    assert SECRET_SENTINEL not in provider.url_for("DAL1234")


def test_the_key_stays_secret_typed_from_settings_to_provider() -> None:
    """No ``get_secret_value`` between the config model and the request."""
    settings = Settings(
        enrichment=EnrichmentSettings(
            aerodatabox_enabled=True, aerodatabox_api_key=SecretStr(SECRET_SENTINEL)
        )
    )

    provider = build_provider(settings)

    assert isinstance(provider, AeroDataBoxProvider)
    assert SECRET_SENTINEL not in repr(settings)
    assert SECRET_SENTINEL not in json.dumps(settings.dump_public())


async def test_a_successful_enrichment_leaves_no_key_in_the_database(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    database: Database,
) -> None:
    """The cache row keeps provider extras; extras are not the request."""

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
        await worker.process_pending()
        feed(service, live)
        await pump(service)
        await worker.process_pending()

    async with database.read_session() as session:
        rows = list((await session.scalars(select(RouteCache))).all())
    assert rows
    assert all(SECRET_SENTINEL not in _row_text(row) for row in rows)


async def test_a_successful_enrichment_leaves_no_key_in_the_api_payload(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
) -> None:
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
        await worker.process_pending()
        feed(service, live)
        await pump(service)
    record = live.get(ICAO)
    assert record is not None

    payload = aircraft_payload(record, route=worker.route_for(ICAO))

    assert SECRET_SENTINEL not in json.dumps(payload)


async def test_starting_and_stopping_never_logs_the_key(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    """The lifecycle lines name the provider, never its credentials."""
    provider, client = mock_provider(failing_handler(httpx.Response(204)))
    service: EnrichmentService = build_service(
        live=live, worker=worker, cache=cache, provider=provider, clock=clock
    )
    async with client:
        await service.start()
        await service.stop()

    assert SECRET_SENTINEL not in swept(captured_logs.records)


async def test_reconfiguring_the_provider_never_logs_the_key(
    live: LiveStore,
    clock: SimulatedTime,
    worker: PersistenceWorker,
    cache: RouteCacheRepository,
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    """The config-apply path (issue #161) compares keys and logs the swap.

    Comparing is where a key is most tempting to unwrap, and
    ``enrichment_reconfigured`` is a line written on the very save that carries
    one. A whole lifecycle is swept — an equivalent provider declined, a
    re-key, a switch-off — and the replacement key contains the sentinel too,
    so a leak of either is caught by the same search.
    """
    service: EnrichmentService = build_service(
        live=live,
        worker=worker,
        cache=cache,
        provider=AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL)),
        clock=clock,
    )

    await service.apply_provider(AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL)))
    await service.apply_provider(AeroDataBoxProvider(api_key=SecretStr(f"{SECRET_SENTINEL}-two")))
    await service.apply_provider(None)

    assert SECRET_SENTINEL not in swept(captured_logs.records)


def _row_text(row: RouteCache) -> str:
    return " ".join(
        str(value)
        for value in (
            row.cache_key,
            row.status,
            row.origin_ident,
            row.destination_ident,
            row.payload_json,
        )
    )
