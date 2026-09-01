"""``route_cache``: hits, negative caching, TTL expiry and pruning.

SPEC §28's *cache aggressively, respect provider limits* is a claim about this
table, so it is tested against the real migrated schema rather than a stub.
"""

from __future__ import annotations

import pytest

from flightsite.db import Database, RouteCache
from flightsite.enrichment.cache import (
    MAX_PAYLOAD_BYTES,
    MS_PER_SECOND,
    NEGATIVE_TTL_S,
    POSITIVE_TTL_S,
    RouteCacheRepository,
    decode_extras,
)
from flightsite.enrichment.model import (
    RouteCacheStatus,
    RouteInfo,
    RouteNotFound,
)

KEY = "DAL1234:2026-08-30"
NOW_MS = 1_756_600_000_000


async def row_of(database: Database, key: str) -> RouteCache | None:
    async with database.read_session() as session:
        return await session.get(RouteCache, key)


async def test_a_stored_route_reads_back(cache: RouteCacheRepository) -> None:
    await cache.store_route(KEY, RouteInfo("KATL", "KSLC"), now_ms=NOW_MS)

    found = await cache.get(KEY, now_ms=NOW_MS)

    assert found is not None
    assert found.status is RouteCacheStatus.OK
    assert (found.origin_ident, found.destination_ident) == ("KATL", "KSLC")


async def test_a_key_never_asked_about_is_a_miss(cache: RouteCacheRepository) -> None:
    assert await cache.get(KEY, now_ms=NOW_MS) is None


async def test_a_stored_route_answers_as_the_provider_would(
    cache: RouteCacheRepository,
) -> None:
    """The cache speaks the provider's vocabulary, so the service has one path."""
    await cache.store_route(KEY, RouteInfo("KATL", "KSLC"), now_ms=NOW_MS)
    found = await cache.get(KEY, now_ms=NOW_MS)
    assert found is not None

    assert found.as_lookup() == RouteInfo("KATL", "KSLC")


async def test_a_negative_result_is_cached_and_reads_back_as_not_found(
    cache: RouteCacheRepository,
) -> None:
    """The gate that stops one unfiled callsign costing a request per sighting."""
    await cache.store_not_found(KEY, now_ms=NOW_MS)
    found = await cache.get(KEY, now_ms=NOW_MS)

    assert found is not None
    assert found.status is RouteCacheStatus.NOT_FOUND
    assert found.as_lookup() == RouteNotFound()


async def test_a_negative_expires_sooner_than_a_route(
    cache: RouteCacheRepository, database: Database
) -> None:
    """The asymmetry: an unfiled schedule is worth re-asking about today."""
    await cache.store_route(KEY, RouteInfo("KATL", "KSLC"), now_ms=NOW_MS)
    positive = await row_of(database, KEY)
    await cache.store_not_found(KEY, now_ms=NOW_MS)
    negative = await row_of(database, KEY)

    assert positive is not None and negative is not None
    assert positive.expires_ms == NOW_MS + POSITIVE_TTL_S * MS_PER_SECOND
    assert negative.expires_ms == NOW_MS + NEGATIVE_TTL_S * MS_PER_SECOND
    assert NEGATIVE_TTL_S < POSITIVE_TTL_S


@pytest.mark.parametrize(
    ("elapsed_s", "expected"),
    [
        pytest.param(POSITIVE_TTL_S - 1, True, id="inside-the-ttl"),
        pytest.param(POSITIVE_TTL_S, False, id="at-the-expiry"),
        pytest.param(POSITIVE_TTL_S + 1, False, id="past-the-expiry"),
    ],
)
async def test_a_row_stops_being_served_at_its_expiry(
    cache: RouteCacheRepository, elapsed_s: int, expected: bool
) -> None:
    await cache.store_route(KEY, RouteInfo("KATL", "KSLC"), now_ms=NOW_MS)

    found = await cache.get(KEY, now_ms=NOW_MS + elapsed_s * MS_PER_SECOND)

    assert (found is not None) is expected


async def test_an_expired_row_is_not_deleted_on_read(
    cache: RouteCacheRepository, database: Database
) -> None:
    """Expiry is a read decision; a miss must not become a write."""
    await cache.store_not_found(KEY, now_ms=NOW_MS)

    assert await cache.get(KEY, now_ms=NOW_MS + POSITIVE_TTL_S * MS_PER_SECOND) is None
    assert await row_of(database, KEY) is not None


async def test_a_later_answer_replaces_an_earlier_one(
    cache: RouteCacheRepository,
) -> None:
    await cache.store_not_found(KEY, now_ms=NOW_MS)
    await cache.store_route(KEY, RouteInfo("KATL", "KSLC"), now_ms=NOW_MS)

    found = await cache.get(KEY, now_ms=NOW_MS)

    assert found is not None
    assert found.status is RouteCacheStatus.OK
    assert await cache.size() == 1


async def test_pruning_removes_only_what_has_expired(
    cache: RouteCacheRepository,
) -> None:
    await cache.store_not_found("gone:2026-08-30", now_ms=NOW_MS)
    await cache.store_route(KEY, RouteInfo("KATL", "KSLC"), now_ms=NOW_MS)

    removed = await cache.prune(now_ms=NOW_MS + NEGATIVE_TTL_S * MS_PER_SECOND)

    assert removed == 1
    assert await cache.size() == 1
    assert await cache.get(KEY, now_ms=NOW_MS) is not None


async def test_provider_extras_round_trip(cache: RouteCacheRepository, database: Database) -> None:
    await cache.store_route(
        KEY,
        RouteInfo("KATL", "KSLC", extras={"number": "DL1234", "status": "EnRoute"}),
        now_ms=NOW_MS,
    )
    row = await row_of(database, KEY)

    assert row is not None
    assert decode_extras(row.payload_json) == {"number": "DL1234", "status": "EnRoute"}


async def test_oversized_extras_are_dropped_rather_than_truncated(
    cache: RouteCacheRepository, database: Database
) -> None:
    """Half a JSON document is not a document, and nothing reads this column."""
    await cache.store_route(
        KEY,
        RouteInfo("KATL", "KSLC", extras={"number": "X" * (MAX_PAYLOAD_BYTES + 1)}),
        now_ms=NOW_MS,
    )
    row = await row_of(database, KEY)

    assert row is not None
    assert row.payload_json is None
    assert (row.origin_ident, row.destination_ident) == ("KATL", "KSLC")


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(None, id="absent"),
        pytest.param("", id="empty"),
        pytest.param("{not json", id="unparsable"),
        pytest.param("[1, 2]", id="not-an-object"),
    ],
)
def test_unreadable_extras_never_fail_a_lookup(payload: str | None) -> None:
    """A row written by a different build must not cost a route it holds."""
    assert decode_extras(payload) == {}


async def test_a_row_stored_as_error_reads_as_no_route(
    cache: RouteCacheRepository, database: Database
) -> None:
    """The reserved status a later build could write, read honestly today.

    ``error`` records that the provider *answered*, so it is Unknown, not an
    unavailability that would keep the circuit breaker guessing.
    """
    await cache.store_not_found(KEY, now_ms=NOW_MS)
    async with database.writer_session() as session:
        row = await session.get(RouteCache, KEY)
        assert row is not None
        row.status = RouteCacheStatus.ERROR.value

    found = await cache.get(KEY, now_ms=NOW_MS)

    assert found is not None
    assert found.as_lookup() == RouteNotFound()


async def test_clear_all_empties_the_table_regardless_of_expiry(
    cache: RouteCacheRepository,
) -> None:
    """SPEC §73's Clear Metadata Cache: unlike ``prune``, unexpired rows go too."""
    await cache.store_route(KEY, RouteInfo("KATL", "KSLC"), now_ms=NOW_MS)
    await cache.store_not_found("still-fresh:2026-08-30", now_ms=NOW_MS)

    removed = await cache.clear_all()

    assert removed == 2
    assert await cache.size() == 0
    assert await cache.get(KEY, now_ms=NOW_MS) is None


async def test_clear_all_on_an_empty_cache_removes_nothing(cache: RouteCacheRepository) -> None:
    """Idempotent, and the state of every install that has enriched nothing yet."""
    assert await cache.clear_all() == 0
    assert await cache.size() == 0


async def test_an_ok_row_with_no_idents_reads_as_no_route(
    cache: RouteCacheRepository, database: Database
) -> None:
    """Defence in depth: a route object cannot be built from two nulls."""
    await cache.store_not_found(KEY, now_ms=NOW_MS)
    async with database.writer_session() as session:
        row = await session.get(RouteCache, KEY)
        assert row is not None
        row.status = RouteCacheStatus.OK.value

    found = await cache.get(KEY, now_ms=NOW_MS)

    assert found is not None
    assert found.as_lookup() == RouteNotFound()
