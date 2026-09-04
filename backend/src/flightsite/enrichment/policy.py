"""Which callsigns may be asked about, and under what key the answer is filed.

SPEC §28 makes route enrichment conditional on *"sufficient flight context"*.
This module is the whole of that condition, kept apart from the service so the
matrix of what is and is not eligible is one readable table of tests.

The rule: a callsign is eligible only in the ICAO flight-identification form —
a three-letter airline designator followed by a flight number. That is
:data:`~flightsite.classification.operators.CALLSIGN_PATTERN`, reused here
rather than restated, because the two modules are asking the same question
("does this transmission name an airline flight?") and two copies of the answer
would drift.

What that excludes, deliberately:

* **Blank or absent callsigns.** Nothing to look up.
* **Registrations flown as callsigns** (``N738AB``, ``GABCD``) — general
  aviation, which files no airline schedule. Asking would spend the request
  budget on a guaranteed miss.
* **Tactical and military callsigns** (``RCH492`` is the exception that proves
  the rule — it *is* the ICAO form, ``RCH`` being Air Mobility Command's
  designator, so it is eligible and a provider that has it may answer).
  ``VADER11`` and ``BLKCT2`` are not the form and are not asked about.
* **Padded fragments** the decoder emits mid-transmission (``DAL``, ``D``).

A false negative here costs one missing route. A false positive costs a request
against a provider quota, every time that aircraft is seen, for nothing — so
the pattern is the strict one.

The cache key
-------------

``docs/DATA_MODEL.md`` §7 keys the cache on the normalized callsign, and on
nothing else. It carried a UTC date bucket until slice 070, on the reasoning
that ``DAL1234`` is a different pair of airports next month — which is true,
and was the wrong bound. Measured on the owner's receiver: 2,200-2,650 distinct
airline callsigns a day at ~190 lookups an hour, of which **62 % had been seen
the previous day** after only four days of history. A dated key was therefore
re-buying two thirds of yesterday's answers every morning, to protect against a
schedule change that happens on the scale of an airline season.

So the drift is now bounded by an *expiry* rather than by the key —
``enrichment.route_ttl_days`` (default 7) — and by two things the date bucket
could never do: a refresh that agrees on three separate days freezes the row
for 30 days, and an aircraft that departs or lands somewhere the cached route
does not name invalidates it immediately
(:func:`contradicts_route`). Rows written under the old dated keys are left to
expire; nothing reads them again.
"""

from __future__ import annotations

from typing import Final

from flightsite.airports.model import AirportContext, InferredPhase
from flightsite.classification.operators import CALLSIGN_PATTERN

#: Longest callsign a decoder can legitimately transmit (ADS-B flight id is
#: eight characters). Anything longer is a decoding artifact, not a flight.
MAX_CALLSIGN_LENGTH: Final = 8


def normalize_callsign(raw: str | None) -> str | None:
    """Upper-case and strip a transmitted callsign, or ``None`` if it is empty.

    Decoders pad the eight-character flight-id field with spaces and some emit
    it lower cased; both are the same callsign, and both must produce the same
    cache key.
    """
    if raw is None:
        return None
    cleaned = raw.strip().upper()
    if not cleaned or len(cleaned) > MAX_CALLSIGN_LENGTH:
        return None
    return cleaned


def eligible_callsign(raw: str | None) -> str | None:
    """The normalized callsign if it may be looked up, else ``None``.

    See the module docstring for what "may" means. Returning the normalized
    form rather than a bool is deliberate: every caller needs it next, and
    normalizing twice is how a lookup and its cache key come to disagree.
    """
    callsign = normalize_callsign(raw)
    if callsign is None or CALLSIGN_PATTERN.match(callsign) is None:
        return None
    return callsign


def airline_designator(callsign: str) -> str | None:
    """The three-letter ICAO airline designator of an eligible callsign."""
    match = CALLSIGN_PATTERN.match(callsign)
    return None if match is None else match.group(1)


def cache_key(callsign: str) -> str:
    """The ``route_cache.cache_key`` for ``callsign``.

    The normalized callsign itself. A function rather than the bare string
    because the key is a storage contract with one place that decides it: the
    lookup, the write and the invalidation must agree on the spelling, and
    three call sites normalizing on their own is how they come to disagree.
    """
    return callsign.strip().upper()


def contradicts_route(
    context: AirportContext | None,
    *,
    origin_ident: str | None,
    destination_ident: str | None,
) -> bool:
    """True when an aircraft's own behaviour disproves its cached route.

    The consistency check of slice 070, and the one thing that catches a
    changed schedule faster than the TTL does. Two readings count, both from
    the airport-context service's *latched* phase
    (:mod:`flightsite.airports.service`), which is an inference the trend gate
    has already committed to:

    * a **departure** from a field the cached route does not call the origin;
    * an **arrival** at a field it does not call the destination.

    Everything else is silence. A phase inferred for an unnamed half of the
    route (a route with only a destination, say) contradicts nothing, because
    the cache never claimed anything about that end — and a route being right
    about one airport is not evidence against the other, which is why each
    reading is checked against its own end alone.

    Idents are compared case-insensitively and nothing is derived: an IATA code
    cached against an ICAO-identified field reads as a contradiction, which
    costs one lookup and is the safe direction to be wrong in.
    """
    if context is None or context.phase is None:
        return False
    departing = context.phase is InferredPhase.DEPARTING
    expected = origin_ident if departing else destination_ident
    if expected is None:
        return False
    return expected.strip().upper() != context.ident.strip().upper()


__all__ = [
    "MAX_CALLSIGN_LENGTH",
    "airline_designator",
    "cache_key",
    "contradicts_route",
    "eligible_callsign",
    "normalize_callsign",
]
