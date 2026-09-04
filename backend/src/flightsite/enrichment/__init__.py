"""Optional online route enrichment (SPEC §28, ADR-0006, roadmap slice 026).

What this package is for
------------------------

An ADS-B transmission carries a callsign, never a route. FlightSite can ask a
third party what route that callsign is flying, and this package is the whole
of that ask: one provider protocol, one implementation, a cache, a rate limiter,
a circuit breaker, and a consumer that ties them to the sighting lifecycle.

It is **optional and off by default**. With no API key nothing here starts, no
socket is opened, and every route is ``null`` — which the UI renders as
*Unknown* (``docs/API.md`` §2.7) and which is a fully working FlightSite. The
package exists to add information when the user has chosen to buy it, never to
become a dependency of the core.

Module map:

========================================== =====================================
Module                                     Responsibility
========================================== =====================================
:mod:`~flightsite.enrichment.model`        the four answers a lookup can give
:mod:`~flightsite.enrichment.policy`       who may be looked up, under what key
:mod:`~flightsite.enrichment.provider`     the ``RouteEnrichmentProvider`` protocol
:mod:`~flightsite.enrichment.aerodatabox`  the one implementation, and the key
:mod:`~flightsite.enrichment.cache`        ``route_cache`` reads and writes
:mod:`~flightsite.enrichment.limits`       token bucket and circuit breaker
:mod:`~flightsite.enrichment.service`      the consumer that runs all of it
========================================== =====================================

The two promises
----------------

**It never blocks ingestion or the live path.** The service is a consumer of
the live event stream behind its own bounded subscription, on its own tasks —
the same topology as the metadata cache, and for the same reason
(``docs/ARCHITECTURE.md`` §3.1). Nothing in :mod:`flightsite.live`,
:mod:`flightsite.ingest` or the API serializers imports this package, so no
network call can end up on a decoder poll or a WebSocket frame. Routes reach
the database through
:meth:`~flightsite.sightings.worker.PersistenceWorker.apply_route`, riding the
persistence worker's cycle rather than opening a writer session of their own.

**It never invents a route.** A provider that cannot be reached, answers with
an error, withholds a flight for legal reasons, or reports no airports leaves
the sighting's route columns ``NULL``.
There is exactly one place a route can be written from
(:meth:`~flightsite.enrichment.service.EnrichmentService._apply`) and exactly
one thing it can write: what the provider said. SPEC §28's *Unknown when
uncertain* is a property of the code shape, not of a convention.

What leaves the network
-----------------------

A callsign, in the path of one HTTPS GET, plus the user's API key in a header.
Nothing else — no position, no ICAO address, no registration, no receiver
location. ``docs/SECURITY.md`` §10 states this to the user and
:mod:`~flightsite.enrichment.aerodatabox` is the single place it is kept.
"""

from __future__ import annotations

from flightsite.enrichment.aerodatabox import (
    API_BASE_URL,
    API_KEY_HEADER,
    FLIGHT_BY_CALLSIGN_PATH,
    REQUEST_TIMEOUT_S,
    AeroDataBoxProvider,
    parse_route,
)
from flightsite.enrichment.cache import (
    DEFAULT_ROUTE_TTL_DAYS,
    LEARNED_CONFIRMATIONS,
    LEARNED_TTL_S,
    NEGATIVE_TTL_S,
    POSITIVE_TTL_S,
    CachedRoute,
    RouteCacheRepository,
    RouteWrite,
)
from flightsite.enrichment.limits import (
    DEFAULT_COOLDOWN_S,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_RATE_PER_MINUTE,
    CircuitBreaker,
    TokenBucket,
)
from flightsite.enrichment.model import (
    ROUTE_SOURCE_AERODATABOX,
    RouteCacheStatus,
    RouteInfo,
    RouteLookup,
    RouteNotFound,
    RouteRestricted,
    RouteUnavailable,
)
from flightsite.enrichment.policy import (
    cache_key,
    contradicts_route,
    eligible_callsign,
    normalize_callsign,
)
from flightsite.enrichment.provider import RouteEnrichmentProvider
from flightsite.enrichment.service import (
    BUDGET_EXHAUSTED_EVENT,
    ENRICHMENT_FAILURES_COUNTER,
    BudgetStatus,
    CacheStats,
    EnrichmentEconomy,
    EnrichmentService,
    build_economy,
    build_provider,
)

__all__ = [
    "API_BASE_URL",
    "API_KEY_HEADER",
    "BUDGET_EXHAUSTED_EVENT",
    "DEFAULT_COOLDOWN_S",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_RATE_PER_MINUTE",
    "DEFAULT_ROUTE_TTL_DAYS",
    "ENRICHMENT_FAILURES_COUNTER",
    "FLIGHT_BY_CALLSIGN_PATH",
    "LEARNED_CONFIRMATIONS",
    "LEARNED_TTL_S",
    "NEGATIVE_TTL_S",
    "POSITIVE_TTL_S",
    "REQUEST_TIMEOUT_S",
    "ROUTE_SOURCE_AERODATABOX",
    "AeroDataBoxProvider",
    "BudgetStatus",
    "CacheStats",
    "CachedRoute",
    "CircuitBreaker",
    "EnrichmentEconomy",
    "EnrichmentService",
    "RouteCacheRepository",
    "RouteCacheStatus",
    "RouteEnrichmentProvider",
    "RouteInfo",
    "RouteLookup",
    "RouteNotFound",
    "RouteRestricted",
    "RouteUnavailable",
    "RouteWrite",
    "TokenBucket",
    "build_economy",
    "build_provider",
    "cache_key",
    "contradicts_route",
    "eligible_callsign",
    "normalize_callsign",
    "parse_route",
]
