"""The one-shot connection test and its internal endpoint."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.ingest import check_connection
from flightsite.ingest.connection_test import ConnectionTestError
from flightsite.ingest.types import DecoderEndpoint, DecoderFlavor

from .conftest import TEST_ENDPOINT, CountingClientFactory, ScriptedTransport, json_response


def factory_for(entry: httpx.Response | Exception) -> CountingClientFactory:
    return CountingClientFactory(ScriptedTransport([entry]))


# --------------------------------------------------------- the service


async def test_successful_test_reports_what_the_decoder_is_tracking(
    readsb_document: Any,
) -> None:
    result = await check_connection(
        TEST_ENDPOINT, client_factory=factory_for(json_response(readsb_document))
    )

    assert result.ok is True
    assert result.url == TEST_ENDPOINT.url
    assert result.aircraft_count == 7
    assert result.positioned_count == 6
    assert result.flavor is DecoderFlavor.READSB
    assert result.decoder_time is not None
    assert result.error is None
    assert result.elapsed_ms >= 0.0


async def test_a_quiet_decoder_still_passes(readsb_document: Any) -> None:
    empty = {"now": 1758124800.1, "messages": 12, "aircraft": []}

    result = await check_connection(TEST_ENDPOINT, client_factory=factory_for(json_response(empty)))

    # An empty sky is a working decoder, not a failed test.
    assert result.ok is True
    assert result.aircraft_count == 0


async def test_unreachable_host_is_reported_as_unreachable() -> None:
    result = await check_connection(
        TEST_ENDPOINT, client_factory=factory_for(httpx.ConnectError("connection refused"))
    )

    assert result.ok is False
    assert result.error is ConnectionTestError.UNREACHABLE
    assert result.detail is not None
    assert TEST_ENDPOINT.url in result.detail
    assert result.aircraft_count is None


async def test_a_timeout_is_reported_as_unreachable() -> None:
    result = await check_connection(
        TEST_ENDPOINT, client_factory=factory_for(httpx.ReadTimeout("timed out"))
    )

    assert result.ok is False
    assert result.error is ConnectionTestError.UNREACHABLE


async def test_wrong_path_is_reported_as_an_http_error() -> None:
    result = await check_connection(
        TEST_ENDPOINT,
        client_factory=factory_for(httpx.Response(status_code=404, text="not found")),
    )

    # The two decoders serve their JSON at different paths, so a 404 is the
    # single most common way a user gets this wrong.
    assert result.ok is False
    assert result.error is ConnectionTestError.HTTP_ERROR
    assert result.detail is not None
    assert "404" in result.detail


async def test_a_non_decoder_service_is_reported_as_an_invalid_document() -> None:
    result = await check_connection(
        TEST_ENDPOINT,
        client_factory=factory_for(httpx.Response(status_code=200, text="<html>hello</html>")),
    )

    assert result.ok is False
    assert result.error is ConnectionTestError.INVALID_DOCUMENT


async def test_valid_json_that_is_not_an_aircraft_feed_is_rejected() -> None:
    result = await check_connection(
        TEST_ENDPOINT, client_factory=factory_for(json_response({"status": "ok"}))
    )

    assert result.ok is False
    assert result.error is ConnectionTestError.INVALID_DOCUMENT
    assert result.detail is not None
    assert "aircraft" in result.detail


async def test_an_unexpected_client_failure_never_escapes() -> None:
    result = await check_connection(
        TEST_ENDPOINT, client_factory=factory_for(RuntimeError("transport exploded"))
    )

    assert result.ok is False
    assert result.error is ConnectionTestError.UNREACHABLE
    assert result.detail == "transport exploded"


async def test_the_client_is_closed_even_on_failure() -> None:
    factory = factory_for(httpx.ConnectError("refused"))

    await check_connection(TEST_ENDPOINT, client_factory=factory)

    assert factory.build_count == 1
    assert all(client.is_closed for client in factory.clients)


async def test_the_probe_identifies_legacy_dump1090fa(
    dump1090fa_legacy_document: Any,
) -> None:
    result = await check_connection(
        DecoderEndpoint(host="pi.local", port=8080, path="/dump1090-fa/data/aircraft.json"),
        client_factory=factory_for(json_response(dump1090fa_legacy_document)),
    )

    assert result.ok is True
    assert result.url == "http://pi.local:8080/dump1090-fa/data/aircraft.json"
    assert result.flavor is DecoderFlavor.DUMP1090_FA


# -------------------------------------------------------- the endpoint


@pytest.fixture
def mocked_decoder(monkeypatch: pytest.MonkeyPatch, readsb_document: Any) -> CountingClientFactory:
    """Point the connection test's default client at a mock transport."""
    factory = factory_for(json_response(readsb_document))
    monkeypatch.setattr(
        "flightsite.ingest.connection_test.build_client", lambda *_args, **_kwargs: factory()
    )
    return factory


@pytest.mark.parametrize("path", ["/api/internal/decoder/test"])
def test_endpoint_tests_a_supplied_endpoint(
    path: str, mocked_decoder: CountingClientFactory
) -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            path, json={"host": "pi.local", "port": 8080, "path": "/data/aircraft.json"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["url"] == "http://pi.local:8080/data/aircraft.json"
    assert body["aircraft_count"] == 7
    assert body["flavor"] == "readsb"


def test_endpoint_falls_back_to_the_configured_receiver(
    mocked_decoder: CountingClientFactory,
) -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/internal/decoder/test")

    assert response.status_code == 200
    # The default receiver from the settings model.
    assert response.json()["url"] == "http://127.0.0.1:8080/data/aircraft.json"


def test_endpoint_rejects_an_invalid_endpoint(mocked_decoder: CountingClientFactory) -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/decoder/test",
            json={"host": "pi.local", "port": 70000, "path": "aircraft.json"},
        )

    # Validated by the same model PUT /config uses: the wizard cannot test an
    # endpoint it would not be allowed to save.
    assert response.status_code == 422


def test_endpoint_reports_a_failure_as_a_result_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = factory_for(httpx.ConnectError("connection refused"))
    monkeypatch.setattr(
        "flightsite.ingest.connection_test.build_client", lambda *_args, **_kwargs: factory()
    )
    app = create_app()

    with TestClient(app) as client:
        response = client.post("/api/internal/decoder/test")

    # A UI needs to render the reason, so an unreachable decoder is a 200 with
    # ok=false rather than an HTTP error.
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "unreachable"


def test_connection_test_is_not_in_the_published_openapi_schema(
    mocked_decoder: CountingClientFactory,
) -> None:
    app = create_app()

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert not any("decoder" in path for path in schema["paths"])
