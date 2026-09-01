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

``docs/DATA_MODEL.md`` §7 keys the cache on the normalized callsign **plus a
date bucket**. The date is not decoration: ``DAL1234`` is a different pair of
airports next month, so a key without it would eventually answer a question
nobody asked. The bucket is the UTC day of the observation, which is the same
day the provider's own schedule lookup defaults to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

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


def cache_key(callsign: str, at: datetime) -> str:
    """The ``route_cache.cache_key`` for ``callsign`` observed at ``at``.

    ``at`` must be timezone-aware; the bucket is its UTC calendar day, so two
    observations either side of local midnight in different zones still share
    one key when they share a UTC day.
    """
    if at.tzinfo is None:
        raise ValueError("refusing to bucket a naive datetime; timestamps must be UTC")
    return f"{callsign}:{at.astimezone(UTC).strftime('%Y-%m-%d')}"


__all__ = [
    "MAX_CALLSIGN_LENGTH",
    "airline_designator",
    "cache_key",
    "eligible_callsign",
    "normalize_callsign",
]
