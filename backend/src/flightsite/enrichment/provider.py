"""The ``RouteEnrichmentProvider`` protocol (ADR-0006).

One small internal interface per integration category, implemented in-tree:
route lookup takes a callsign and returns a normalized answer with provenance
already decided at the boundary. Nothing downstream of this protocol knows what
an HTTP status code is, what the provider calls its fields, or that an API key
exists.

The protocol is deliberately narrower than the API behind it. AeroDataBox can
answer about registrations, ICAO addresses, flight numbers, aircraft images and
flight plans; FlightSite asks one question — *what route is this callsign
flying?* — and the interface says so. A wider surface would be capability the
domain does not want and quota the user would pay for.

``lookup`` never raises for an expected failure. Provider errors are values
(:class:`~flightsite.enrichment.model.RouteUnavailable`), because the caller's
response to one is a policy decision — count it, open a circuit, do not cache
it — and exceptions crossing this boundary would push HTTP concerns into the
module that makes that decision.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from flightsite.enrichment.model import RouteLookup


@runtime_checkable
class RouteEnrichmentProvider(Protocol):
    """Looks up the route of a flight identified by its callsign."""

    @property
    def name(self) -> str:
        """Provenance value this provider tags its answers with (§2.6)."""
        ...

    async def lookup(self, callsign: str) -> RouteLookup:
        """The route for ``callsign``, or why there is not one.

        Args:
            callsign: a normalized, eligibility-checked callsign in the ICAO
                flight-identification form (:mod:`flightsite.enrichment.policy`
                decides that; a provider does not re-litigate it).

        Returns:
            :class:`~flightsite.enrichment.model.RouteInfo` when a route was
            reported, :class:`~flightsite.enrichment.model.RouteNotFound` when
            the provider answered and has none, and
            :class:`~flightsite.enrichment.model.RouteUnavailable` when it could
            not be asked or its answer could not be used.
        """
        ...

    async def aclose(self) -> None:
        """Release whatever the provider holds open. Idempotent."""
        ...


__all__ = ["RouteEnrichmentProvider"]
