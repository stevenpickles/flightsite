"""The AeroDataBox client, over ``httpx.MockTransport``.

The real provider builds the real URL and headers and parses the real response
shape; only the socket is replaced (``docs/TEST_STRATEGY.md`` §"No external
network in tests"). So a change to the endpoint, the auth header or the
document shape fails here rather than in production.

The response bodies are the documented ``FlightContract`` shape: a **bare JSON
array** of flight objects, with ``departure`` and ``arrival`` as top-level
siblings each carrying an ``airport`` with ``icao`` and ``iata``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from flightsite.enrichment import (
    API_BASE_URL,
    API_KEY_HEADER,
    FLIGHT_BY_CALLSIGN_PATH,
    AeroDataBoxProvider,
    RouteInfo,
    RouteNotFound,
    RouteRestricted,
    RouteUnavailable,
    aerodatabox,
    parse_route,
)
from flightsite.enrichment.aerodatabox import (
    CONNECT_TIMEOUT_S,
    REQUEST_TIMEOUT_S,
    USER_AGENT,
    build_client,
)
from tests.conftest import SECRET_SENTINEL
from tests.enrichment.conftest import mock_provider

CALLSIGN = "KLM1395"

#: Every fixture flight carries a number, so every parsed route carries this.
NUMBER_EXTRA = {"number": "KL1395"}


def flight(
    *,
    departure: dict[str, Any] | None = None,
    arrival: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """One ``FlightContract`` object, trimmed to what FlightSite reads."""
    document: dict[str, Any] = {"number": "KL1395", "callSign": CALLSIGN, **fields}
    if departure is not None:
        document["departure"] = departure
    if arrival is not None:
        document["arrival"] = arrival
    return document


def airport(icao: str | None = None, iata: str | None = None) -> dict[str, Any]:
    inner: dict[str, Any] = {"name": "Somewhere"}
    if icao is not None:
        inner["icao"] = icao
    if iata is not None:
        inner["iata"] = iata
    return {"airport": inner, "scheduledTime": {"utc": "2026-09-01T09:15:00Z"}}


def responder(response: httpx.Response) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return handler


# ------------------------------------------------------------- what is sent


async def test_the_request_is_the_documented_endpoint() -> None:
    """``GET /flights/callsign/{callsign}`` on the direct API host."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    provider, client = mock_provider(handler)
    async with client:
        await provider.lookup(CALLSIGN)

    assert str(seen[0].url) == f"{API_BASE_URL}{FLIGHT_BY_CALLSIGN_PATH}/{CALLSIGN}"
    assert seen[0].method == "GET"


async def test_the_key_travels_in_the_documented_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    provider, client = mock_provider(handler)
    async with client:
        await provider.lookup(CALLSIGN)

    assert seen[0].headers[API_KEY_HEADER] == SECRET_SENTINEL
    assert seen[0].headers["User-Agent"] == USER_AGENT


async def test_the_callsign_is_the_only_thing_that_leaves() -> None:
    """``docs/SECURITY.md`` §10, asserted rather than asserted-in-prose.

    Nothing about the receiver — no position, no ICAO address, no registration
    — can reach the provider, because the request is built from a callsign and
    a key and has no body at all.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    provider, client = mock_provider(handler)
    async with client:
        await provider.lookup(CALLSIGN)

    request = seen[0]
    assert request.url.params == httpx.QueryParams()
    assert request.content == b""
    assert set(request.headers) <= {
        "host",
        "accept",
        "accept-encoding",
        "connection",
        "user-agent",
        API_KEY_HEADER.lower(),
    }


async def test_the_url_is_inspectable_without_a_request() -> None:
    provider, client = mock_provider(responder(httpx.Response(204)))
    async with client:
        assert provider.url_for(CALLSIGN).endswith(f"/flights/callsign/{CALLSIGN}")


def test_the_provider_names_its_own_provenance() -> None:
    provider, _ = mock_provider(responder(httpx.Response(204)))

    assert provider.name == "aerodatabox"


# ------------------------------------------------------- what comes back


async def test_a_flight_with_both_airports_becomes_a_route() -> None:
    provider, client = mock_provider(
        responder(
            httpx.Response(
                200,
                json=[flight(departure=airport("EHAM", "AMS"), arrival=airport("EGLL", "LHR"))],
            )
        )
    )
    async with client:
        result = await provider.lookup(CALLSIGN)

    assert result == RouteInfo(
        origin_ident="EHAM",
        destination_ident="EGLL",
        extras={"number": "KL1395"},
    )


async def test_iata_is_the_fallback_when_icao_is_absent() -> None:
    """An identifier the user recognizes beats a null; nothing is expanded."""
    provider, client = mock_provider(
        responder(
            httpx.Response(
                200, json=[flight(departure=airport(iata="AMS"), arrival=airport(iata="LHR"))]
            )
        )
    )
    async with client:
        result = await provider.lookup(CALLSIGN)

    assert result == RouteInfo(origin_ident="AMS", destination_ident="LHR", extras=NUMBER_EXTRA)


async def test_half_a_route_is_still_a_route() -> None:
    """A departure with no arrival is information, not an error."""
    assert parse_route([flight(departure=airport("EHAM"))]) == RouteInfo(
        origin_ident="EHAM", extras=NUMBER_EXTRA
    )


async def test_the_first_flight_of_the_array_is_the_one() -> None:
    """The endpoint orders by proximity to now; the head is this sighting's."""
    document = [
        flight(departure=airport("EHAM"), arrival=airport("EGLL")),
        flight(departure=airport("KJFK"), arrival=airport("KLAX")),
    ]

    assert parse_route(document) == RouteInfo(
        origin_ident="EHAM", destination_ident="EGLL", extras=NUMBER_EXTRA
    )


@pytest.mark.parametrize(
    "document",
    [
        pytest.param([], id="empty-array"),
        pytest.param([flight()], id="no-movement-blocks"),
        pytest.param([flight(departure={}, arrival={})], id="movements-with-no-airport"),
        pytest.param([flight(departure=airport(), arrival=airport())], id="airports-with-no-ident"),
        pytest.param([flight(departure={"airport": "EHAM"})], id="airport-is-not-an-object"),
        pytest.param([flight(departure=airport(icao="   "))], id="blank-ident"),
        pytest.param({"flights": []}, id="not-an-array"),
        pytest.param(["a string"], id="array-of-the-wrong-thing"),
        pytest.param(None, id="null"),
    ],
)
def test_nothing_usable_is_no_route_rather_than_a_guess(document: Any) -> None:
    """The one place a route could be invented, proved not to."""
    assert parse_route(document) == RouteNotFound()


def test_provider_extras_are_kept_for_diagnostics() -> None:
    result = parse_route(
        [flight(departure=airport("EHAM"), arrival=airport("EGLL"), status="EnRoute")]
    )

    assert isinstance(result, RouteInfo)
    assert result.extras == {"number": "KL1395", "status": "EnRoute"}


def test_an_ident_is_upper_cased_and_stripped() -> None:
    result = parse_route([flight(departure=airport(" eham "))])

    assert result == RouteInfo(origin_ident="EHAM", extras=NUMBER_EXTRA)


# ---------------------------------------------------------- what goes wrong


@pytest.mark.parametrize(
    "status", [pytest.param(204, id="no-content"), pytest.param(404, id="not-found")]
)
async def test_the_provider_answering_nothing_is_not_found(status: int) -> None:
    """Answered, and has no route: negative-cacheable, breaker untouched."""
    provider, client = mock_provider(responder(httpx.Response(status)))
    async with client:
        assert await provider.lookup(CALLSIGN) == RouteNotFound()


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        pytest.param(429, "rate_limited", id="rate-limited"),
        pytest.param(401, "http_401", id="rejected-key"),
        pytest.param(400, "http_400", id="bad-request"),
        pytest.param(500, "http_500", id="server-error"),
        pytest.param(503, "http_503", id="unavailable"),
    ],
)
async def test_an_error_status_is_unavailable_not_a_missing_route(status: int, reason: str) -> None:
    """Never negative-cached: none of these say anything about the flight."""
    provider, client = mock_provider(responder(httpx.Response(status, json={"error": "no"})))
    async with client:
        assert await provider.lookup(CALLSIGN) == RouteUnavailable(reason=reason)


async def test_a_legally_restricted_flight_is_its_own_answer() -> None:
    """Issue #165: HTTP 451 is a fact about the flight, not about the API.

    Read as an error it was a failure the breaker counted, so one restricted
    business jet was re-requested nine times in twelve minutes and opened the
    circuit twice. The provider now names it, and the service caches it.
    """
    provider, client = mock_provider(responder(httpx.Response(451, json={"error": "no"})))
    async with client:
        assert await provider.lookup(CALLSIGN) == RouteRestricted()


async def test_a_restricted_answer_is_logged_with_its_own_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A findable line, and one that never carries the request or the key.

    The module logger is replaced rather than captured through structlog: any
    test that has built the real application has configured structlog with
    cached bound loggers, and a cached logger cannot be intercepted.
    """
    recorded: list[tuple[str, dict[str, Any]]] = []

    class Recorder:
        def info(self, event: str, **fields: Any) -> None:
            recorded.append((event, fields))

    monkeypatch.setattr(aerodatabox, "logger", Recorder())
    provider, client = mock_provider(responder(httpx.Response(451)))
    async with client:
        await provider.lookup(CALLSIGN)

    events = [fields for event, fields in recorded if event == "enrichment_lookup_restricted"]
    assert events and events[0]["reason"] == "restricted"
    assert events[0]["callsign"] == CALLSIGN
    assert SECRET_SENTINEL not in str(events[0])


async def test_a_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    provider, client = mock_provider(handler)
    async with client:
        assert await provider.lookup(CALLSIGN) == RouteUnavailable(reason="timeout")


async def test_an_unreachable_host_is_unavailable() -> None:
    """The offline case: DNS, TLS, refused connection all land here."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    provider, client = mock_provider(handler)
    async with client:
        assert await provider.lookup(CALLSIGN) == RouteUnavailable(reason="transport_error")


async def test_a_body_that_is_not_json_is_unavailable() -> None:
    """Unparsable is not "no route": the provider may be fine and we are not."""
    provider, client = mock_provider(responder(httpx.Response(200, text="<html>oops</html>")))
    async with client:
        assert await provider.lookup(CALLSIGN) == RouteUnavailable(reason="unparsable")


# ------------------------------------------------------------- the lifecycle


async def test_an_injected_client_is_not_closed_by_the_provider() -> None:
    """The owner closes what it made; borrowing must not close a shared client."""
    provider, client = mock_provider(responder(httpx.Response(204)))
    async with client:
        await provider.aclose()

        assert client.is_closed is False


async def test_a_provider_that_made_its_own_client_closes_it() -> None:
    provider = AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL))
    # Reaching into the private client rather than making a request: the point
    # is the ownership rule, and issuing a real request would need a socket.
    provider._client = httpx.AsyncClient()
    provider._owns_client = True
    created = provider._client

    await provider.aclose()
    await provider.aclose()

    assert created.is_closed is True


def test_a_route_that_names_nothing_cannot_be_constructed() -> None:
    """The type refuses the fabricated route the parser refuses to build."""
    with pytest.raises(ValueError, match="at least one airport"):
        RouteInfo()


async def test_a_provider_with_no_injected_client_builds_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production path: nobody hands the app a client, so it makes one.

    The module-level :func:`~flightsite.enrichment.aerodatabox.build_client`
    seam is replaced with a mock-transport factory, so the lazy-construction
    branch runs for real without a socket. One client is built for both
    requests, and closing the provider closes it.
    """
    built: list[httpx.AsyncClient] = []

    def factory() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(responder(httpx.Response(204))))
        built.append(client)
        return client

    monkeypatch.setattr(aerodatabox, "build_client", factory)
    provider = AeroDataBoxProvider(api_key=SecretStr(SECRET_SENTINEL))

    assert await provider.lookup(CALLSIGN) == RouteNotFound()
    assert await provider.lookup(CALLSIGN) == RouteNotFound()
    await provider.aclose()
    await provider.aclose()

    assert len(built) == 1
    assert built[0].is_closed is True


def test_the_built_client_carries_the_request_timeouts() -> None:
    """The budgets are constants, and the default client actually uses them."""
    client = build_client()

    assert client.timeout.read == REQUEST_TIMEOUT_S
    assert client.timeout.connect == CONNECT_TIMEOUT_S
