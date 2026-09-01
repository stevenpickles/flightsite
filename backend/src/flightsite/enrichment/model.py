"""What a route lookup can answer, and the vocabulary the cache stores.

Three outcomes, modelled as three types rather than as one nullable record,
because the difference between them decides what happens next and a
``None``-returning function would erase it:

* :class:`RouteInfo` — the provider named at least one airport. Applied to the
  sighting and cached until the day's key expires.
* :class:`RouteNotFound` — the provider answered, and has no route for this
  flight. Negative-cached, so a scheduled-but-unfiled callsign is asked about
  once rather than once per sighting.
* :class:`RouteUnavailable` — the provider could not be asked, or could not
  answer: a timeout, a 429, a 5xx, an open circuit, a response that did not
  parse. **Never cached.** It is a statement about the network, not about the
  flight, and storing it would turn one bad minute into hours of false
  "no route" (SPEC §28: Unknown when uncertain, never a fabricated route).

Airport identifiers
-------------------

ICAO is preferred and IATA is the fallback, because ``docs/API.md`` §3.6 and
§2.6 both show four-letter ICAO idents (``KATL``, ``PHIK``) and slice 027's
airport dataset is keyed the same way. A provider that offers only an IATA code
still yields a usable answer — an identifier the user recognizes is worth more
than a null — and it is stored exactly as given, never expanded into an ICAO
code FlightSite guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

#: ``sightings.route_source`` for a route this provider supplied
#: (``docs/API.md`` §2.8 provenance vocabulary, ``ROUTE_SOURCE_CHECK``).
ROUTE_SOURCE_AERODATABOX: Final = "aerodatabox"


class RouteCacheStatus(StrEnum):
    """``route_cache.status`` (``docs/DATA_MODEL.md`` §7).

    :attr:`ERROR` is part of the storage contract and is not written by this
    slice — see :data:`flightsite.db.models.ROUTE_CACHE_STATUS_CHECK` for why
    the vocabulary is fixed before the code that would write it exists, and why
    an unavailable provider is deliberately not one of these.
    """

    #: The provider named a route; :class:`RouteInfo` round-trips through it.
    OK = "ok"
    #: The provider answered and has no route for this flight.
    NOT_FOUND = "not_found"
    #: Reserved: a provider answering definitively and unusably for one key.
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RouteInfo:
    """A route an external provider reported for one flight.

    At least one ident must be present: an instance with neither would be a
    route that says nothing, and the honest answer to that is
    :class:`RouteNotFound`. Idents are stored as the provider gave them, upper
    cased and stripped; nothing here derives, completes or corrects a code.

    ``extras`` is the small provider-specific detail kept in
    ``route_cache.payload_json`` for diagnostics — the flight number and status,
    never the request and therefore never the API key.
    """

    origin_ident: str | None = None
    destination_ident: str | None = None
    extras: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.origin_ident is None and self.destination_ident is None:
            raise ValueError("a RouteInfo must name at least one airport; use RouteNotFound")


@dataclass(frozen=True, slots=True)
class RouteNotFound:
    """The provider answered, and knows no route for this flight."""


@dataclass(frozen=True, slots=True)
class RouteUnavailable:
    """The provider could not be asked, or could not answer.

    ``reason`` is a short stable slug for logs and counters (``timeout``,
    ``rate_limited``, ``http_500``, ``unparsable``, ``circuit_open``). It never
    carries a URL, a header or a response body, so it cannot become a route to
    leak the API key through.
    """

    reason: str


#: What :meth:`~flightsite.enrichment.provider.RouteEnrichmentProvider.lookup`
#: returns. Exhaustive: a caller matching all three has handled every case.
RouteLookup = RouteInfo | RouteNotFound | RouteUnavailable


__all__ = [
    "ROUTE_SOURCE_AERODATABOX",
    "RouteCacheStatus",
    "RouteInfo",
    "RouteLookup",
    "RouteNotFound",
    "RouteUnavailable",
]
