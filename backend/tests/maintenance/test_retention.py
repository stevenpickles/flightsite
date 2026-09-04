"""Retention pruning: expired ``route_cache`` rows go, live ones stay.

``docs/DATA_MODEL.md`` §7 gives the cache TTL semantics and §9 lists it as the
one TTL-pruned table. Until this slice, expiry was enforced only on *read*
(:mod:`flightsite.enrichment.cache`) — an expired row was not returned, but it
was never deleted either, so the dead rows accumulated for the life of the
install.

Correctness here means one thing above all: pruning and reading must agree.
Every assertion below is therefore made through the enrichment repository's own
:meth:`~flightsite.enrichment.cache.RouteCacheRepository.get`, not through a
query this test wrote — a pruner that deleted rows the reader still considered
live would pass a hand-written query and fail here.
"""

from __future__ import annotations

from flightsite.enrichment.cache import (
    MS_PER_SECOND,
    NEGATIVE_TTL_S,
    POSITIVE_TTL_S,
    RouteCacheRepository,
)
from flightsite.enrichment.model import RouteInfo
from flightsite.maintenance.retention import ROUTE_CACHE_TASK, RetentionTask, RouteCachePruner
from tests.maintenance.conftest import BASE_MS

LHR_JFK = RouteInfo(origin_ident="EGLL", destination_ident="KJFK")


async def test_the_pruner_advertises_the_name_diagnostics_uses(
    route_cache: RouteCacheRepository,
) -> None:
    pruner = RouteCachePruner(route_cache)

    assert pruner.name == ROUTE_CACHE_TASK
    assert isinstance(pruner, RetentionTask)


async def test_nothing_is_deleted_while_every_row_is_live(
    route_cache: RouteCacheRepository,
) -> None:
    await route_cache.store_route("BAW117-2026-08-31", LHR_JFK, now_ms=BASE_MS)
    await route_cache.store_not_found("XXX999-2026-08-31", now_ms=BASE_MS)

    pruned = await RouteCachePruner(route_cache).prune(now_ms=BASE_MS + 1)

    assert pruned == 0
    assert await route_cache.size() == 2


async def test_expired_rows_are_removed_and_fresh_ones_kept(
    route_cache: RouteCacheRepository,
) -> None:
    """The asymmetric TTLs mean one instant can expire one row and not the other.

    A negative answer lives a day and a found route a week (slice 070), so a
    prune between the two must take exactly one of them. That is a sharper
    assertion than "expired rows go": it proves the pruner reads each row's own
    ``expires_ms`` rather than applying one age to the whole table.
    """
    await route_cache.store_route("BAW117", LHR_JFK, now_ms=BASE_MS)
    await route_cache.store_not_found("XXX999", now_ms=BASE_MS)
    assert NEGATIVE_TTL_S < POSITIVE_TTL_S
    between_the_two = BASE_MS + (NEGATIVE_TTL_S + 60) * MS_PER_SECOND

    pruned = await RouteCachePruner(route_cache).prune(now_ms=between_the_two)

    assert pruned == 1
    assert await route_cache.size() == 1
    # Through the repository's own reader, which is the agreement that matters.
    assert await route_cache.get("BAW117", now_ms=between_the_two) is not None
    assert await route_cache.get("XXX999", now_ms=between_the_two) is None


async def test_a_row_expiring_exactly_now_is_pruned(route_cache: RouteCacheRepository) -> None:
    """The boundary the reader uses (``expires_ms <= now``) is the one used here.

    If the two disagreed by a millisecond there would be an instant at which a
    row is unreadable but undeletable — a row that can never be served and
    never be cleaned up.
    """
    await route_cache.store_not_found("XXX999-2026-08-31", now_ms=BASE_MS)
    expiry_ms = BASE_MS + NEGATIVE_TTL_S * MS_PER_SECOND

    assert await route_cache.get("XXX999-2026-08-31", now_ms=expiry_ms) is None
    assert await RouteCachePruner(route_cache).prune(now_ms=expiry_ms) == 1


async def test_pruning_the_whole_cache_leaves_it_empty_and_reusable(
    route_cache: RouteCacheRepository,
) -> None:
    """A pruned key can be looked up again and refilled — the point of a cache."""
    for index in range(20):
        await route_cache.store_route(f"BAW{index:03d}-2026-08-31", LHR_JFK, now_ms=BASE_MS)
    long_after = BASE_MS + (POSITIVE_TTL_S + 1) * MS_PER_SECOND

    assert await RouteCachePruner(route_cache).prune(now_ms=long_after) == 20
    assert await route_cache.size() == 0

    await route_cache.store_route("BAW000-2026-08-31", LHR_JFK, now_ms=long_after)
    refilled = await route_cache.get("BAW000-2026-08-31", now_ms=long_after)
    assert refilled is not None
    assert refilled.origin_ident == "EGLL"


async def test_pruning_an_empty_cache_is_a_no_op(route_cache: RouteCacheRepository) -> None:
    assert await RouteCachePruner(route_cache).prune(now_ms=BASE_MS) == 0
