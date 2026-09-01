"""Domain records for watchlists and their entries.

Plain, immutable dataclasses rather than ORM instances crossing package
boundaries — the same shape :mod:`flightsite.airports.records` and
:mod:`flightsite.metadata.precedence` use, and for the same reason: a caller
outside :mod:`flightsite.watchlists.repository` should never need to know
whether a row came from the ORM, a raw SQL row, or a test fixture.
"""

from __future__ import annotations

from dataclasses import dataclass

from flightsite.watchlists.vocabulary import WatchlistEntryKind


@dataclass(frozen=True, slots=True)
class WatchlistRecord:
    """One watchlist (``docs/DATA_MODEL.md`` §4.1)."""

    id: int
    name: str
    description: str | None
    created_ms: int


@dataclass(frozen=True, slots=True)
class WatchlistEntryRecord:
    """One membership rule on a watchlist.

    ``value`` is already normalized for ``kind`` — see
    :mod:`flightsite.watchlists.vocabulary` — so a consumer never re-derives
    the normalization rule.
    """

    id: int
    watchlist_id: int
    kind: WatchlistEntryKind
    value: str
    note: str | None
    created_ms: int


__all__ = ["WatchlistEntryRecord", "WatchlistRecord"]
