"""``route_cache``: hits, negative caching, TTL expiry and pruning.

SPEC §28's *cache aggressively, respect provider limits* is a claim about this
table, so it is tested against the real migrated schema rather than a stub.
"""

from __future__ import annotations

import pytest

from flightsite.db import Database, RouteCache
from flightsite.enrichment.cache import (
    LEARNED_CONFIRMATIONS,
    LEARNED_TTL_S,
    MAX_PAYLOAD_BYTES,
    MS_PER_SECOND,
    NEGATIVE_TTL_S,
    POSITIVE_TTL_S,
    SECONDS_PER_DAY,
    RouteCacheRepository,
    RouteWrite,
    decode_extras,
    utc_day_start_ms,
)
from flightsite.enrichment.model import (
    RouteCacheStatus,
    RouteInfo,
    RouteNotFound,
)

KEY = "DAL1234"
#: 2026-08-30T21:06:40Z - a fixed instant well inside a UTC day, so "the same
#: day" and "the next day" are exact rather than nearly.
NOW_MS = 1_756_588_000_000
NEXT_DAY_MS = NOW_MS + SECONDS_PER_DAY * MS_PER_SECOND
ROUTE = RouteInfo("KATL", "KSLC")
OTHER_ROUTE = RouteInfo("KSEA", "KPDX")


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
    """The asymmetry: an unfiled schedule is worth re-asking about tomorrow."""
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


# ------------------------------------------------------ the TTL is a setting


async def test_the_positive_ttl_comes_from_the_caller(
    cache: RouteCacheRepository, database: Database
) -> None:
    """``enrichment.route_ttl_days``: the repository stores what it is given.

    The default is a week, but the number belongs to the configuration, so the
    repository takes it per write rather than reading a setting of its own.
    """
    ttl_s = 3 * SECONDS_PER_DAY
    await cache.store_route(KEY, ROUTE, now_ms=NOW_MS, ttl_s=ttl_s)
    row = await row_of(database, KEY)

    assert row is not None
    assert row.expires_ms == NOW_MS + ttl_s * MS_PER_SECOND


async def test_the_default_positive_ttl_is_a_week(
    cache: RouteCacheRepository, database: Database
) -> None:
    await cache.store_route(KEY, ROUTE, now_ms=NOW_MS)
    row = await row_of(database, KEY)

    assert row is not None
    assert row.expires_ms == NOW_MS + 7 * SECONDS_PER_DAY * MS_PER_SECOND


async def test_a_missing_route_is_cached_for_a_day(
    cache: RouteCacheRepository, database: Database
) -> None:
    """Twenty-four hours: an unfiled schedule is worth one ask per day."""
    await cache.store_not_found(KEY, now_ms=NOW_MS)
    row = await row_of(database, KEY)

    assert NEGATIVE_TTL_S == SECONDS_PER_DAY
    assert row is not None
    assert row.expires_ms == NOW_MS + SECONDS_PER_DAY * MS_PER_SECOND


# --------------------------------------------------------- restricted (#165)


async def test_a_restricted_flight_is_cached_like_an_answer(
    cache: RouteCacheRepository, database: Database
) -> None:
    """Issue #165: 451 is a fact about the flight, so it takes the long TTL."""
    await cache.store_restricted(KEY, now_ms=NOW_MS)
    row = await row_of(database, KEY)

    assert row is not None
    assert row.status == RouteCacheStatus.RESTRICTED.value
    assert row.expires_ms == NOW_MS + POSITIVE_TTL_S * MS_PER_SECOND


async def test_a_restricted_row_reads_as_no_route(cache: RouteCacheRepository) -> None:
    """The law saying no is Unknown to the user: not a route, not an error."""
    await cache.store_restricted(KEY, now_ms=NOW_MS)
    found = await cache.get(KEY, now_ms=NOW_MS)

    assert found is not None
    assert found.status is RouteCacheStatus.RESTRICTED
    assert found.as_lookup() == RouteNotFound()


# ---------------------------------------------------------- learned schedules


async def test_the_same_answer_on_a_later_day_confirms_the_row(
    cache: RouteCacheRepository,
) -> None:
    first = await cache.store_route(KEY, ROUTE, now_ms=NOW_MS)
    second = await cache.store_route(KEY, ROUTE, now_ms=NEXT_DAY_MS)

    assert (first.confirmations, second.confirmations) == (0, 1)
    assert not second.learned


async def test_the_same_answer_twice_in_one_day_confirms_nothing(
    cache: RouteCacheRepository,
) -> None:
    """One day agreeing with itself is not a second day of evidence."""
    await cache.store_route(KEY, ROUTE, now_ms=NOW_MS)
    again = await cache.store_route(KEY, ROUTE, now_ms=NOW_MS + 60 * MS_PER_SECOND)

    assert again.confirmations == 0


async def test_three_confirming_days_freeze_the_row_for_a_month(
    cache: RouteCacheRepository, database: Database
) -> None:
    """The acceptance criterion: after three confirmations, expiry is 30 days."""
    writes = [
        await cache.store_route(KEY, ROUTE, now_ms=NOW_MS + day * SECONDS_PER_DAY * MS_PER_SECOND)
        for day in range(LEARNED_CONFIRMATIONS + 1)
    ]
    last_ms = NOW_MS + LEARNED_CONFIRMATIONS * SECONDS_PER_DAY * MS_PER_SECOND
    row = await row_of(database, KEY)

    assert [write.confirmations for write in writes] == [0, 1, 2, 3]
    assert [write.learned for write in writes] == [False, False, False, True]
    assert [write.newly_learned for write in writes] == [False, False, False, True]
    assert row is not None
    assert row.expires_ms == last_ms + LEARNED_TTL_S * MS_PER_SECOND


async def test_a_learned_row_stays_learned_without_counting_twice(
    cache: RouteCacheRepository,
) -> None:
    """``newly_learned`` is the transition, so a counter cannot double-count."""
    write = RouteWrite(confirmations=0, learned=False, newly_learned=False)
    for day in range(LEARNED_CONFIRMATIONS + 2):
        write = await cache.store_route(
            KEY, ROUTE, now_ms=NOW_MS + day * SECONDS_PER_DAY * MS_PER_SECOND
        )

    assert write.learned is True
    assert write.newly_learned is False


async def test_a_differing_answer_resets_the_confirmations(
    cache: RouteCacheRepository, database: Database
) -> None:
    """The schedule changed; what was learned about the old one is worthless."""
    for day in range(LEARNED_CONFIRMATIONS + 1):
        await cache.store_route(KEY, ROUTE, now_ms=NOW_MS + day * SECONDS_PER_DAY * MS_PER_SECOND)
    changed_ms = NOW_MS + (LEARNED_CONFIRMATIONS + 1) * SECONDS_PER_DAY * MS_PER_SECOND

    write = await cache.store_route(KEY, OTHER_ROUTE, now_ms=changed_ms)
    row = await row_of(database, KEY)

    assert write == RouteWrite(confirmations=0, learned=False, newly_learned=False)
    assert row is not None
    assert row.confirmations == 0
    assert row.first_fetched_ms == changed_ms
    assert row.expires_ms == changed_ms + POSITIVE_TTL_S * MS_PER_SECOND


async def test_the_first_fetch_is_remembered_across_confirmations(
    cache: RouteCacheRepository, database: Database
) -> None:
    await cache.store_route(KEY, ROUTE, now_ms=NOW_MS)
    await cache.store_route(KEY, ROUTE, now_ms=NEXT_DAY_MS)
    row = await row_of(database, KEY)

    assert row is not None
    assert (row.first_fetched_ms, row.fetched_ms) == (NOW_MS, NEXT_DAY_MS)


async def test_a_negative_answer_does_not_confirm_a_route(
    cache: RouteCacheRepository, database: Database
) -> None:
    """A day the provider had no route is not a day it agreed with itself."""
    await cache.store_route(KEY, ROUTE, now_ms=NOW_MS)
    await cache.store_not_found(KEY, now_ms=NEXT_DAY_MS)
    write = await cache.store_route(KEY, ROUTE, now_ms=NEXT_DAY_MS + MS_PER_SECOND)
    row = await row_of(database, KEY)

    assert write.confirmations == 0
    assert row is not None
    assert row.confirmations == 0


async def test_learned_rows_are_counted(cache: RouteCacheRepository) -> None:
    """What diagnostics reports as ``cache.learned``."""
    for day in range(LEARNED_CONFIRMATIONS + 1):
        await cache.store_route(KEY, ROUTE, now_ms=NOW_MS + day * SECONDS_PER_DAY * MS_PER_SECOND)
    await cache.store_route("UAL9", ROUTE, now_ms=NOW_MS)

    assert await cache.count_learned() == 1


# ---------------------------------------------------- invalidation and ledger


async def test_invalidation_deletes_a_live_row(
    cache: RouteCacheRepository, database: Database
) -> None:
    """The consistency check's remedy: not "expire it" but "it is wrong"."""
    await cache.store_route(KEY, ROUTE, now_ms=NOW_MS)

    assert await cache.invalidate(KEY) is True
    assert await row_of(database, KEY) is None
    assert await cache.get(KEY, now_ms=NOW_MS) is None


async def test_invalidating_nothing_is_not_an_error(cache: RouteCacheRepository) -> None:
    assert await cache.invalidate(KEY) is False


async def test_rows_fetched_today_are_counted(cache: RouteCacheRepository) -> None:
    """The budget's ledger, which is what makes it survive a restart."""
    day_ms = utc_day_start_ms(NOW_MS)
    await cache.store_route("DAL1", ROUTE, now_ms=day_ms - MS_PER_SECOND)
    await cache.store_route("DAL2", ROUTE, now_ms=day_ms)
    await cache.store_not_found("DAL3", now_ms=NOW_MS)

    assert await cache.count_fetched_since(day_ms) == 2


def test_a_utc_day_starts_at_midnight() -> None:
    """One definition of "a day", shared by the budget and the confirmations."""
    day_ms = utc_day_start_ms(NOW_MS)

    assert day_ms <= NOW_MS
    assert NOW_MS - day_ms < SECONDS_PER_DAY * MS_PER_SECOND
    assert utc_day_start_ms(NEXT_DAY_MS) == day_ms + SECONDS_PER_DAY * MS_PER_SECOND
