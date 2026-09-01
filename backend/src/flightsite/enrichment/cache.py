"""Reading and writing ``route_cache`` (``docs/DATA_MODEL.md`` §7).

SPEC §28: *cache aggressively, respect provider limits*. This is the half that
makes the second true — a callsign that has been asked about is not asked about
again, whether it is asked by another sighting, another aircraft flying the
same number tomorrow, or the same process after a restart.

Where this runs, and why it may open a session
----------------------------------------------

Off the hot path, always. Its only caller is
:class:`~flightsite.enrichment.service.EnrichmentService`, which lives on its
own task behind a bounded subscription exactly as the metadata cache does
(``docs/ARCHITECTURE.md`` §3.1: *"no live request or decoder poll ever waits on
SQLite"*). Nothing in :mod:`flightsite.live`, :mod:`flightsite.ingest` or the
API serializers reaches this module, so an SD card stalled on a write cannot
delay a decoder poll or a WebSocket frame.

Writes go through :meth:`~flightsite.db.engine.Database.writer_session`, the
same single writer the persistence worker uses (ADR-0001, ADR-0008). They are
small, infrequent — bounded by the rate limiter above them — and each is one
short transaction, so they interleave with the worker's cycles rather than
holding the write lock across anything.

TTLs
----

The cache key already carries a UTC date (:mod:`flightsite.enrichment.policy`),
so an expiry is not what stops yesterday's route being served for today. What
it does is bound staleness *within* a day, and it is deliberately asymmetric:

* A **found** route is stable — a filed flight rarely changes airports mid-day
  — so :data:`POSITIVE_TTL_S` is long, and the row is usually still valid for
  every later sighting of that flight.
* A **missing** route is often a schedule that has not been published yet, so
  :data:`NEGATIVE_TTL_S` is short enough that the same flight is worth asking
  about again later in the day, and long enough that a fleet of sightings of
  one callsign costs one request rather than dozens.

An expired row is not deleted on read. It is simply not returned, and the next
successful lookup overwrites it; :meth:`RouteCacheRepository.prune` clears the
accumulated dead rows when maintenance asks it to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import delete, func, select

from flightsite.db.engine import Database
from flightsite.db.models import RouteCache
from flightsite.enrichment.model import (
    RouteCacheStatus,
    RouteInfo,
    RouteLookup,
    RouteNotFound,
)

#: How long a found route stays valid. Twelve hours: comfortably the length of
#: any single flight, so every sighting of one flight shares one lookup, while
#: still bounded well inside the day the key already names.
POSITIVE_TTL_S: Final = 12 * 60 * 60

#: How long a "no route" answer stays valid. One hour — see the module
#: docstring for the asymmetry.
NEGATIVE_TTL_S: Final = 60 * 60

#: Cap on the JSON kept in ``payload_json``. Provider extras are two or three
#: short strings; anything larger is a response shape this build does not
#: understand, and storing it would be growth with no reader.
MAX_PAYLOAD_BYTES: Final = 512

MS_PER_SECOND: Final = 1_000


@dataclass(frozen=True, slots=True)
class CachedRoute:
    """One live ``route_cache`` row, as the service reads it."""

    status: RouteCacheStatus
    origin_ident: str | None
    destination_ident: str | None
    fetched_ms: int
    expires_ms: int

    def as_lookup(self) -> RouteLookup:
        """The cached answer in the vocabulary a provider would have used.

        A stored :attr:`~flightsite.enrichment.model.RouteCacheStatus.ERROR` —
        which this slice never writes, but which a database written by a later
        build could hold — is reported as "no route", not as an unavailability:
        the row records that the provider *answered*, and the honest display of
        an answer FlightSite cannot use is Unknown (``docs/API.md`` §2.7).
        """
        if self.status is RouteCacheStatus.OK and not (
            self.origin_ident is None and self.destination_ident is None
        ):
            return RouteInfo(
                origin_ident=self.origin_ident, destination_ident=self.destination_ident
            )
        return RouteNotFound()


@dataclass(frozen=True, slots=True)
class RouteCacheRepository:
    """Point lookups and writes over ``route_cache``."""

    database: Database

    async def get(self, cache_key: str, *, now_ms: int) -> CachedRoute | None:
        """The unexpired row for ``cache_key``, or ``None``.

        ``None`` covers both "never asked" and "asked, but the answer has
        expired", which are the same instruction to the caller: ask again.
        """
        async with self.database.read_session() as session:
            row = await session.get(RouteCache, cache_key)
            if row is None or row.expires_ms <= now_ms:
                return None
            return CachedRoute(
                status=RouteCacheStatus(row.status),
                origin_ident=row.origin_ident,
                destination_ident=row.destination_ident,
                fetched_ms=row.fetched_ms,
                expires_ms=row.expires_ms,
            )

    async def store_route(self, cache_key: str, route: RouteInfo, *, now_ms: int) -> None:
        """Record a found route, replacing whatever was filed under the key."""
        await self._write(
            cache_key,
            status=RouteCacheStatus.OK,
            origin_ident=route.origin_ident,
            destination_ident=route.destination_ident,
            payload_json=_encode_extras(route.extras),
            now_ms=now_ms,
            ttl_s=POSITIVE_TTL_S,
        )

    async def store_not_found(self, cache_key: str, *, now_ms: int) -> None:
        """Record that the provider has no route for this flight.

        The negative cache SPEC §28 asks for: without it, a callsign nobody has
        a schedule for would be looked up once per sighting, forever.
        """
        await self._write(
            cache_key,
            status=RouteCacheStatus.NOT_FOUND,
            origin_ident=None,
            destination_ident=None,
            payload_json=None,
            now_ms=now_ms,
            ttl_s=NEGATIVE_TTL_S,
        )

    async def prune(self, *, now_ms: int) -> int:
        """Delete every expired row; returns how many went.

        Not called on the lookup path: expiry is decided on read, and deleting
        one row per miss would turn every cache miss into a write.
        """
        async with self.database.writer_session() as session:
            result = await session.execute(
                delete(RouteCache).where(RouteCache.expires_ms <= now_ms)
            )
            return int(result.rowcount or 0)

    async def size(self) -> int:
        """Rows currently held, expired or not. For tests and diagnostics."""
        async with self.database.read_session() as session:
            return int(await session.scalar(select(func.count()).select_from(RouteCache)) or 0)

    async def _write(
        self,
        cache_key: str,
        *,
        status: RouteCacheStatus,
        origin_ident: str | None,
        destination_ident: str | None,
        payload_json: str | None,
        now_ms: int,
        ttl_s: int,
    ) -> None:
        expires_ms = now_ms + ttl_s * MS_PER_SECOND
        async with self.database.writer_session() as session:
            row = await session.get(RouteCache, cache_key)
            if row is None:
                session.add(
                    RouteCache(
                        cache_key=cache_key,
                        status=status.value,
                        origin_ident=origin_ident,
                        destination_ident=destination_ident,
                        payload_json=payload_json,
                        fetched_ms=now_ms,
                        expires_ms=expires_ms,
                    )
                )
                return
            row.status = status.value
            row.origin_ident = origin_ident
            row.destination_ident = destination_ident
            row.payload_json = payload_json
            row.fetched_ms = now_ms
            row.expires_ms = expires_ms


def _encode_extras(extras: dict[str, str]) -> str | None:
    """The provider extras as compact JSON, or ``None`` if there are none.

    Oversized extras are dropped rather than truncated: half a JSON document is
    not a document, and the column is a diagnostic convenience, not a record
    anything depends on.
    """
    if not extras:
        return None
    encoded = json.dumps(extras, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
        return None
    return encoded


def decode_extras(payload_json: str | None) -> dict[str, Any]:
    """The stored extras, or an empty mapping if there are none or it is bad.

    A row written by a different build is not a reason to fail a lookup: the
    route idents are in their own columns and are what the sighting needs.
    """
    if not payload_json:
        return {}
    try:
        decoded = json.loads(payload_json)
    except ValueError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


__all__ = [
    "MAX_PAYLOAD_BYTES",
    "MS_PER_SECOND",
    "NEGATIVE_TTL_S",
    "POSITIVE_TTL_S",
    "CachedRoute",
    "RouteCacheRepository",
    "decode_extras",
]
