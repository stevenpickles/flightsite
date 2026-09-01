"""The AeroDataBox route provider (ADR-0006, SPEC §28).

The one HTTP client FlightSite points at a commercial API, and the only place
in the process that touches the AeroDataBox key.

What is actually called
-----------------------

``GET https://api.aerodatabox.com/flights/callsign/{callsign}``

The flight endpoint is one parameterized template — ``/flights/{searchBy}/
{searchParam}`` with ``searchBy`` one of ``number | callsign | reg | icao24`` —
and FlightSite only ever spells the ``callsign`` form, which is why
:data:`FLIGHT_BY_CALLSIGN_PATH` is a fixed prefix rather than a search-mode
argument. Omitting the optional trailing date asks for the *nearest* occurrence
of that callsign, past or future, which is exactly the question a live sighting
poses.

Every optional expansion (``withAircraftImage``, ``withLocation``,
``withFlightPlan``) is left at its default of ``false``. They cost quota — a
flight plan doubles the request's unit cost — and FlightSite wants two airport
identifiers.

Authentication is the direct API's ``X-Api-Key`` header
(:data:`API_KEY_HEADER`). The same product is also resold through RapidAPI on a
different host with ``X-RapidAPI-Key``/``X-RapidAPI-Host``; FlightSite ships
one host because the configuration model has one key and ADR-0006 rules out a
provider selector in v1, and a second host would be a setting with no way to
tell the user which kind of key they hold.

The response is a **bare JSON array** of flight objects. Departure and arrival
are top-level siblings, each with an ``airport`` carrying ``icao`` and ``iata``.
``204 No Content`` means no flight matched; a ``200`` with an empty array means
the same thing and is treated identically.

What is sent, and what is not
-----------------------------

The callsign, in the path. Nothing else: no position, no ICAO address, no
registration, no receiver location, no timestamps beyond what TLS and HTTP put
on the wire themselves. ``docs/SECURITY.md`` §10 states this as the user-facing
promise and this module is where it is kept — every request this class makes is
built by :meth:`AeroDataBoxProvider._request` from a callsign and nothing else.

The key
-------

Held as a :class:`~pydantic.SecretStr` for the life of the object and unwrapped
only into the request header, inside the one method that builds a request. It
is never logged, never put in an exception message, never in a
:class:`~flightsite.enrichment.model.RouteUnavailable` reason, and never
returned. ``tests/enrichment/test_secrets.py`` proves that with a sentinel key
by sweeping every log record and every value this class produces.
"""

from __future__ import annotations

from typing import Any, Final

import httpx
import structlog
from pydantic import SecretStr

from flightsite.enrichment.model import (
    ROUTE_SOURCE_AERODATABOX,
    RouteInfo,
    RouteLookup,
    RouteNotFound,
    RouteUnavailable,
)

logger = structlog.get_logger(__name__)

#: The direct AeroDataBox API host.
API_BASE_URL: Final = "https://api.aerodatabox.com"

#: Path prefix of the callsign form of ``/flights/{searchBy}/{searchParam}``.
FLIGHT_BY_CALLSIGN_PATH: Final = "/flights/callsign"

#: Authentication header of the direct API.
API_KEY_HEADER: Final = "X-Api-Key"

#: Sent so the provider's logs can identify the client; carries the project
#: name and nothing about the receiver or its operator.
USER_AGENT: Final = "FlightSite/1.0 (+https://github.com/flightsite)"

#: Whole-request budget. Enrichment is never on a path anyone is waiting on, so
#: this is not a latency target — it is the bound on how long one worker task
#: sits on a socket before the answer stops being worth having.
REQUEST_TIMEOUT_S: Final = 10.0

#: Time allowed to establish the connection. Shorter than the whole-request
#: budget: a host that cannot be reached at all should fail fast and feed the
#: circuit breaker rather than consuming the full timeout.
CONNECT_TIMEOUT_S: Final = 5.0

#: HTTP statuses this provider treats as "asked and answered, no route".
_NOT_FOUND_STATUSES: Final[frozenset[int]] = frozenset({204, 404})

#: Extras kept in ``route_cache.payload_json`` for diagnostics: what the
#: provider called the flight, and what state it said it was in.
_EXTRA_KEYS: Final[tuple[str, ...]] = ("number", "status")


def _airport_ident(movement: Any) -> str | None:
    """The ICAO ident of a departure/arrival block, falling back to IATA.

    Every step is defensive because this reads a third-party document: a
    provider that changes a field's type must produce a missing route, never an
    exception on the enrichment task.
    """
    if not isinstance(movement, dict):
        return None
    airport = movement.get("airport")
    if not isinstance(airport, dict):
        return None
    for key in ("icao", "iata"):
        value = airport.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return None


def _first_flight(document: Any) -> dict[str, Any] | None:
    """The first flight object of a response, or ``None`` if there is none.

    The endpoint answers with an array ordered by proximity to now, so the
    first entry is the occurrence a live sighting is about. A response that is
    not a list of objects is not guessed at.
    """
    if not isinstance(document, list):
        return None
    for entry in document:
        if isinstance(entry, dict):
            return entry
    return None


def parse_route(document: Any) -> RouteLookup:
    """Turn one decoded response body into a route answer.

    Split out from the request so the shape rules are testable without HTTP,
    and so the one place that could invent a route — this one — is small enough
    to read in full. It never does: a flight object with no usable airport
    identifier yields :class:`~flightsite.enrichment.model.RouteNotFound`, which
    the API renders as Unknown (``docs/API.md`` §2.7).
    """
    flight = _first_flight(document)
    if flight is None:
        return RouteNotFound()
    origin = _airport_ident(flight.get("departure"))
    destination = _airport_ident(flight.get("arrival"))
    if origin is None and destination is None:
        return RouteNotFound()
    extras = {
        key: value
        for key in _EXTRA_KEYS
        if isinstance(value := flight.get(key), str) and value.strip()
    }
    return RouteInfo(origin_ident=origin, destination_ident=destination, extras=extras)


class AeroDataBoxProvider:
    """Looks a callsign's route up against the AeroDataBox flight API.

    Args:
        api_key: the AeroDataBox key. Kept secret-typed end to end; see the
            module docstring for what that guarantees.
        client: an ``httpx.AsyncClient`` to borrow. Injected by tests with a
            mock transport, so the suite exercises the real request-building
            and response-parsing code with no network
            (``docs/TEST_STRATEGY.md`` §"No external network in tests"). When
            omitted the provider builds and owns one.
        base_url: the API host, overridable so a test's mock transport can
            assert the exact URL that would be requested.
    """

    __slots__ = ("_api_key", "_base_url", "_client", "_owns_client")

    def __init__(
        self,
        *,
        api_key: SecretStr,
        client: httpx.AsyncClient | None = None,
        base_url: str = API_BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None

    @property
    def name(self) -> str:
        """The §2.6 provenance value for routes this provider supplies."""
        return ROUTE_SOURCE_AERODATABOX

    def url_for(self, callsign: str) -> str:
        """The URL a lookup of ``callsign`` would request.

        Public because it is the readable statement of what leaves the network
        (``docs/SECURITY.md`` §10), and a test asserts against it directly.
        """
        return f"{self._base_url}{FLIGHT_BY_CALLSIGN_PATH}/{callsign}"

    async def lookup(self, callsign: str) -> RouteLookup:
        """The route AeroDataBox reports for ``callsign``.

        Never raises for an expected failure: a timeout, an unreachable host, a
        rate limit, a rejected key and an unparsable body all come back as
        :class:`~flightsite.enrichment.model.RouteUnavailable` with a short
        slug, which the service counts and feeds to the circuit breaker without
        ever writing it to the cache.
        """
        try:
            response = await self._request(callsign)
        except httpx.TimeoutException:
            return self._unavailable("timeout", callsign)
        except httpx.HTTPError:
            # Every transport failure httpx models — DNS, TLS, connection
            # refused, a malformed response line. The exception itself is not
            # logged: it can echo the request, and the request carries the key.
            return self._unavailable("transport_error", callsign)

        if response.status_code in _NOT_FOUND_STATUSES:
            return RouteNotFound()
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            return self._unavailable("rate_limited", callsign)
        if response.status_code >= httpx.codes.BAD_REQUEST:
            return self._unavailable(f"http_{response.status_code}", callsign)

        try:
            document = response.json()
        except ValueError:
            return self._unavailable("unparsable", callsign)
        return parse_route(document)

    async def aclose(self) -> None:
        """Close the HTTP client if this provider created it. Idempotent."""
        client, self._client = self._client, None
        if client is not None and self._owns_client:
            await client.aclose()

    # ------------------------------------------------------------ the request

    async def _request(self, callsign: str) -> httpx.Response:
        """Issue the one request this provider knows how to make.

        The only place the key is unwrapped, and the only place a URL is built.
        Both facts are what make ``docs/SECURITY.md`` §10's list auditable: the
        request carries the callsign in its path, the key in a header, and
        nothing else.
        """
        client = self._client
        if client is None:
            client = self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
            )
            self._owns_client = True
        return await client.get(
            self.url_for(callsign),
            headers={
                API_KEY_HEADER: self._api_key.get_secret_value(),
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=httpx.Timeout(REQUEST_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
        )

    @staticmethod
    def _unavailable(reason: str, callsign: str) -> RouteUnavailable:
        """Log a failed lookup and return it as a value.

        The callsign is logged because it is already in FlightSite's own
        sighting records and is what makes the line useful; the URL, the
        headers and the response body are not, because one of them is the key.
        """
        logger.info("enrichment_lookup_unavailable", reason=reason, callsign=callsign)
        return RouteUnavailable(reason=reason)


__all__ = [
    "API_BASE_URL",
    "API_KEY_HEADER",
    "CONNECT_TIMEOUT_S",
    "FLIGHT_BY_CALLSIGN_PATH",
    "REQUEST_TIMEOUT_S",
    "USER_AGENT",
    "AeroDataBoxProvider",
    "parse_route",
]
