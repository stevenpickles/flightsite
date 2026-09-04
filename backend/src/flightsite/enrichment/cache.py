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

The key is the callsign alone (:mod:`flightsite.enrichment.policy`), so the
expiry is the *whole* of the staleness rule — not, as it was until slice 070, a
bound on drift within a day whose date the key already carried. It is
deliberately asymmetric, and the asymmetry is now measured rather than assumed:

* A **found** route holds for :data:`DEFAULT_ROUTE_TTL_DAYS` days
  (``enrichment.route_ttl_days``, 1-30). A scheduled service flies the same
  pair of airports for a season, and on the owner's receiver 62 % of a day's
  airline callsigns had already been heard the day before — so a week-long
  answer turns roughly two lookups a day into one a week for the same flight.
* A **missing** route is often a schedule that has not been filed yet, so
  :data:`NEGATIVE_TTL_S` is a day: long enough that a callsign nobody has a
  route for costs one request rather than dozens, short enough that the
  schedule is worth re-asking about tomorrow.
* A **restricted** route (HTTP 451, issue #165) takes the *positive* TTL. It is
  an answer about the flight — the law does not change between sightings — and
  treating it as a failure is what let one business jet be re-requested nine
  times in twelve minutes.

Learned schedules
-----------------

A refresh that returns the same pair of airports as the stored row, on a
**different calendar day**, increments ``confirmations``. At
:data:`LEARNED_CONFIRMATIONS` the row is frozen for :data:`LEARNED_TTL_S` — 30
days — because three separate days agreeing is evidence of a schedule rather
than of a one-off, and re-buying it weekly is spending credits to learn what
FlightSite already knows. A *differing* answer resets the count to zero and the
row goes back to the ordinary TTL: the schedule changed, and the evidence for
the old one is worthless. Provenance never changes — the answer is still
AeroDataBox's, confirmed against itself, not FlightSite's own inference.

An expired row is not deleted on read. It is simply not returned, and the next
successful lookup overwrites it; :meth:`RouteCacheRepository.prune` clears the
accumulated dead rows when maintenance asks it to.
:meth:`RouteCacheRepository.invalidate` is the one place a *live* row is
deleted, and it exists for the consistency check
(:func:`flightsite.enrichment.policy.contradicts_route`): an aircraft that
lands somewhere its cached route does not name has disproved the row, and
waiting out the TTL would serve a wrong answer for a week.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.db.engine import Database
from flightsite.db.models import RouteCache
from flightsite.enrichment.model import (
    RouteCacheStatus,
    RouteInfo,
    RouteLookup,
    RouteNotFound,
)

SECONDS_PER_DAY: Final = 24 * 60 * 60

#: Default days a found route stays valid — ``enrichment.route_ttl_days``.
#: Seven, because a scheduled flight number flies the same pair of airports for
#: a season and the receiver hears two thirds of its callsigns again the next
#: day; a week is long enough to collect that saving and short enough that a
#: retimed service is corrected within one.
DEFAULT_ROUTE_TTL_DAYS: Final = 7

#: Bounds the setting accepts. Below a day the cache stops being a cache; above
#: a month the confirmation freeze below is the better instrument.
MIN_ROUTE_TTL_DAYS: Final = 1
MAX_ROUTE_TTL_DAYS: Final = 30

#: How long a found route stays valid when no TTL is given.
POSITIVE_TTL_S: Final = DEFAULT_ROUTE_TTL_DAYS * SECONDS_PER_DAY

#: How long a "no route" answer stays valid. Twenty-four hours — see the module
#: docstring for the asymmetry.
NEGATIVE_TTL_S: Final = SECONDS_PER_DAY

#: Separate calendar days of agreement that make a route a learned schedule.
#: Three: two consecutive days is a flight that ran twice, three is a pattern,
#: and each one costs a lookup, so the bar is set where the evidence starts
#: being worth more than the credits proving it.
LEARNED_CONFIRMATIONS: Final = 3

#: How long a learned route holds. Thirty days: an airline schedule season is
#: measured in months, and a month's freeze still re-checks every route often
#: enough that a retimed service is caught within one billing period — while
#: the consistency check catches a *changed* one the moment the aircraft flies
#: it (:func:`flightsite.enrichment.policy.contradicts_route`).
LEARNED_TTL_S: Final = 30 * SECONDS_PER_DAY

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
    confirmations: int = 0
    first_fetched_ms: int | None = None

    @property
    def learned(self) -> bool:
        """True once enough separate days have confirmed this answer."""
        return self.confirmations >= LEARNED_CONFIRMATIONS

    def as_lookup(self) -> RouteLookup:
        """The cached answer in the vocabulary a provider would have used.

        A stored :attr:`~flightsite.enrichment.model.RouteCacheStatus.ERROR` —
        which no slice writes, but which a database written by a later build
        could hold — and a stored ``RESTRICTED`` are both reported as "no
        route", not as an unavailability: the row records that the provider
        *answered*, and the honest display of an answer FlightSite cannot use
        is Unknown (``docs/API.md`` §2.7).
        """
        if self.status is RouteCacheStatus.OK and not (
            self.origin_ident is None and self.destination_ident is None
        ):
            return RouteInfo(
                origin_ident=self.origin_ident, destination_ident=self.destination_ident
            )
        return RouteNotFound()


@dataclass(frozen=True, slots=True)
class RouteWrite:
    """What storing a route did to the row that was already there.

    Returned so the service can count learned rows for diagnostics without
    re-reading the table, and so the confirmation rule has exactly one
    implementation — the one that had the old row in hand.
    """

    #: Separate calendar days that have now confirmed this answer.
    confirmations: int
    #: True when the row is frozen at :data:`LEARNED_TTL_S`.
    learned: bool
    #: True when *this* write is what made it learned. The transition, so a
    #: counter can be incremented without double-counting later refreshes.
    newly_learned: bool


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
            return _as_cached(row)

    async def store_route(
        self, cache_key: str, route: RouteInfo, *, now_ms: int, ttl_s: int = POSITIVE_TTL_S
    ) -> RouteWrite:
        """Record a found route, and count the days that have confirmed it.

        The confirmation rule lives here because this is the one place holding
        both the new answer and the old row. An answer identical to the stored
        one, first seen on a *different* UTC day, advances ``confirmations``;
        the same answer twice in one day advances nothing, because one day
        agreeing with itself is not a second day's evidence. A different answer
        resets the count and the first-seen moment — the schedule changed, and
        what was learned about the old one no longer applies.
        """
        async with self.database.writer_session() as session:
            row = await session.get(RouteCache, cache_key)
            origin = route.origin_ident
            destination = route.destination_ident
            was_learned = row is not None and row.confirmations >= LEARNED_CONFIRMATIONS
            confirmations, first_fetched_ms = _confirm(row, origin, destination, now_ms=now_ms)
            learned = confirmations >= LEARNED_CONFIRMATIONS
            self._put(
                session,
                row,
                cache_key=cache_key,
                status=RouteCacheStatus.OK,
                origin_ident=origin,
                destination_ident=destination,
                payload_json=_encode_extras(route.extras),
                now_ms=now_ms,
                ttl_s=LEARNED_TTL_S if learned else ttl_s,
                confirmations=confirmations,
                first_fetched_ms=first_fetched_ms,
            )
        return RouteWrite(
            confirmations=confirmations,
            learned=learned,
            newly_learned=learned and not was_learned,
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

    async def store_restricted(
        self, cache_key: str, *, now_ms: int, ttl_s: int = POSITIVE_TTL_S
    ) -> None:
        """Record that this flight is legally withheld (HTTP 451, issue #165).

        Filed at the *positive* TTL: a restriction is a property of the flight,
        not a bad minute on the network, so it is cached as firmly as a route.
        The row holds no idents, which is what makes the sighting read Unknown.
        """
        await self._write(
            cache_key,
            status=RouteCacheStatus.RESTRICTED,
            origin_ident=None,
            destination_ident=None,
            payload_json=None,
            now_ms=now_ms,
            ttl_s=ttl_s,
        )

    async def invalidate(self, cache_key: str) -> bool:
        """Delete one row outright; ``True`` if there was one.

        The consistency check's only write. Unlike :meth:`prune` this deletes a
        row that has *not* expired, because the aircraft it describes has just
        contradicted it — see
        :func:`flightsite.enrichment.policy.contradicts_route`.
        """
        statement = (
            delete(RouteCache)
            .where(RouteCache.cache_key == cache_key)
            .returning(RouteCache.cache_key)
        )
        async with self.database.writer_session() as session:
            return (await session.scalars(statement)).first() is not None

    async def count_fetched_since(self, since_ms: int) -> int:
        """Rows fetched at or after ``since_ms``. The daily budget's ledger.

        Counted from the table rather than from a process-local tally so that
        "lookups spent today" survives a restart: an install restarted at noon
        must not be handed a fresh day's budget.
        """
        statement = (
            select(func.count()).select_from(RouteCache).where(RouteCache.fetched_ms >= since_ms)
        )
        async with self.database.read_session() as session:
            return int(await session.scalar(statement) or 0)

    async def count_learned(self) -> int:
        """Rows confirmed on enough separate days to be frozen. Diagnostics."""
        statement = (
            select(func.count())
            .select_from(RouteCache)
            .where(RouteCache.confirmations >= LEARNED_CONFIRMATIONS)
        )
        async with self.database.read_session() as session:
            return int(await session.scalar(statement) or 0)

    async def prune(self, *, now_ms: int) -> int:
        """Delete every expired row; returns how many went.

        Not called on the lookup path: expiry is decided on read, and deleting
        one row per miss would turn every cache miss into a write.
        """
        # ``RETURNING`` rather than a driver rowcount, the same choice
        # :mod:`flightsite.db.meta` makes: it is typed and unambiguous where
        # rowcount is neither.
        statement = (
            delete(RouteCache)
            .where(RouteCache.expires_ms <= now_ms)
            .returning(RouteCache.cache_key)
        )
        async with self.database.writer_session() as session:
            return len((await session.scalars(statement)).all())

    async def size(self) -> int:
        """Rows currently held, expired or not. For tests and diagnostics."""
        async with self.database.read_session() as session:
            return int(await session.scalar(select(func.count()).select_from(RouteCache)) or 0)

    async def clear_all(self) -> int:
        """Delete every row, expired or not (SPEC §73's Clear Metadata Cache).

        Unlike :meth:`prune`, this is not bounded to expired rows: the whole
        cache is being emptied outright, on the same "delete what an import
        would recreate" logic ``flightsite.reset.service`` applies to the
        metadata tables — the next lookup simply asks the provider again.
        """
        statement = delete(RouteCache).returning(RouteCache.cache_key)
        async with self.database.writer_session() as session:
            return len((await session.scalars(statement)).all())

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
        """Store an answer that carries no confirmation history of its own."""
        async with self.database.writer_session() as session:
            row = await session.get(RouteCache, cache_key)
            self._put(
                session,
                row,
                cache_key=cache_key,
                status=status,
                origin_ident=origin_ident,
                destination_ident=destination_ident,
                payload_json=payload_json,
                now_ms=now_ms,
                ttl_s=ttl_s,
                confirmations=0,
                first_fetched_ms=now_ms,
            )

    @staticmethod
    def _put(
        session: AsyncSession,
        row: RouteCache | None,
        *,
        cache_key: str,
        status: RouteCacheStatus,
        origin_ident: str | None,
        destination_ident: str | None,
        payload_json: str | None,
        now_ms: int,
        ttl_s: int,
        confirmations: int,
        first_fetched_ms: int,
    ) -> None:
        """Insert or overwrite one row inside an open writer session."""
        expires_ms = now_ms + ttl_s * MS_PER_SECOND
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
                    confirmations=confirmations,
                    first_fetched_ms=first_fetched_ms,
                )
            )
            return
        row.status = status.value
        row.origin_ident = origin_ident
        row.destination_ident = destination_ident
        row.payload_json = payload_json
        row.fetched_ms = now_ms
        row.expires_ms = expires_ms
        row.confirmations = confirmations
        row.first_fetched_ms = first_fetched_ms


def _as_cached(row: RouteCache) -> CachedRoute:
    """One ORM row as the immutable value the service reads."""
    return CachedRoute(
        status=RouteCacheStatus(row.status),
        origin_ident=row.origin_ident,
        destination_ident=row.destination_ident,
        fetched_ms=row.fetched_ms,
        expires_ms=row.expires_ms,
        confirmations=row.confirmations,
        first_fetched_ms=row.first_fetched_ms,
    )


def utc_day_start_ms(epoch_ms: int) -> int:
    """Midnight UTC of the day ``epoch_ms`` falls in, in epoch milliseconds.

    The boundary both the daily budget and the confirmation rule are measured
    against, in one place so the two cannot disagree about when a day begins.
    """
    moment = datetime.fromtimestamp(epoch_ms / MS_PER_SECOND, UTC)
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * MS_PER_SECOND)


def _confirm(
    row: RouteCache | None, origin: str | None, destination: str | None, *, now_ms: int
) -> tuple[int, int]:
    """The ``(confirmations, first_fetched_ms)`` a route write should store."""
    if row is None or row.status != RouteCacheStatus.OK.value:
        return 0, now_ms
    if (row.origin_ident, row.destination_ident) != (origin, destination):
        return 0, now_ms
    first_fetched_ms = row.first_fetched_ms if row.first_fetched_ms is not None else row.fetched_ms
    if utc_day_start_ms(row.fetched_ms) == utc_day_start_ms(now_ms):
        # The same day agreeing with itself. Nothing was learned, and the row
        # keeps the count it already had.
        return row.confirmations, first_fetched_ms
    return row.confirmations + 1, first_fetched_ms


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
    "DEFAULT_ROUTE_TTL_DAYS",
    "LEARNED_CONFIRMATIONS",
    "LEARNED_TTL_S",
    "MAX_PAYLOAD_BYTES",
    "MAX_ROUTE_TTL_DAYS",
    "MIN_ROUTE_TTL_DAYS",
    "MS_PER_SECOND",
    "NEGATIVE_TTL_S",
    "POSITIVE_TTL_S",
    "SECONDS_PER_DAY",
    "CachedRoute",
    "RouteCacheRepository",
    "RouteWrite",
    "decode_extras",
    "utc_day_start_ms",
]
