"""Watchlists as one object the application wires up.

Mirrors :class:`flightsite.metadata.service.MetadataService`'s shape: the app
holds one :class:`WatchlistService`, the internal CRUD API
(``docs/API.md`` §5) calls its methods rather than touching
:mod:`flightsite.watchlists.repository` directly, and every method that
changes what a watchlist means — create, rename, delete, add entry, remove
entry — rebuilds the in-memory match index before returning. That ordering is
what makes "matching updates without restart" (roadmap slice 037's second
acceptance criterion) true of the CRUD surface: a client that just created a
watchlist and immediately requests the live picture sees the new membership on
its very next frame, not after some later reconciliation.

Value normalization and format validation
(:mod:`flightsite.watchlists.vocabulary`) happen here, once, before either
repository call or index rebuild sees a value — so a rejected entry never
reaches the database and the index is never rebuilt from something invalid.
"""

from __future__ import annotations

from collections.abc import Callable

from flightsite.db import Database, utc_now_ms
from flightsite.watchlists.matcher import WatchlistMatcher
from flightsite.watchlists.model import WatchlistEntryRecord, WatchlistRecord
from flightsite.watchlists.repository import WatchlistRepository
from flightsite.watchlists.vocabulary import (
    WatchlistEntryKind,
    normalize_and_validate,
    normalize_description,
    normalize_note,
    normalize_watchlist_name,
)

#: UTC epoch-millisecond source, injected for tests.
ClockFn = Callable[[], int]


class WatchlistService:
    """Watchlist CRUD plus the live match index it keeps current.

    Args:
        database: the application database.
        clock: UTC epoch-millisecond source, injected for tests.
    """

    __slots__ = ("_clock", "_matcher", "_repository")

    def __init__(self, *, database: Database, clock: ClockFn = utc_now_ms) -> None:
        self._repository = WatchlistRepository(database)
        self._matcher = WatchlistMatcher()
        self._clock = clock

    @property
    def matcher(self) -> WatchlistMatcher:
        """The live match index — read on the aircraft path, never written there."""
        return self._matcher

    async def start(self) -> None:
        """Load the index from the database.

        Called before :meth:`flightsite.metadata.MetadataService.start` in
        the lifespan hook, so the matcher already has real entries loaded by
        the time the metadata cache's warm-up visits the current live set —
        without that ordering, the very first population round would compute
        every aircraft's matches against an empty index and nothing would be
        flagged until the next CRUD change.
        """
        await self.reload_index()

    async def reload_index(self) -> None:
        """Rebuild the match index from the database's current contents.

        Two reads, not one join, and that is fine: watchlists are configured
        at human scale (dozens of watchlists and entries, edited through a
        settings-style UI), so this runs at startup and after a CRUD change —
        never on the live path — and its cost is irrelevant next to either.
        """
        watchlists = await self._repository.list_watchlists()
        entries = await self._repository.list_all_entries()
        names = {watchlist.id: watchlist.name for watchlist in watchlists}
        self._matcher.reload(entries, names)

    # --------------------------------------------------------- watchlists

    async def list_watchlists(self) -> tuple[WatchlistRecord, ...]:
        """Every watchlist, alphabetical by name."""
        return await self._repository.list_watchlists()

    async def get_watchlist(self, watchlist_id: int) -> WatchlistRecord | None:
        """One watchlist, or ``None`` if it does not exist."""
        return await self._repository.get_watchlist(watchlist_id)

    async def list_watchlists_with_entries(
        self,
    ) -> tuple[tuple[WatchlistRecord, tuple[WatchlistEntryRecord, ...]], ...]:
        """Every watchlist paired with its own entries, in one round trip.

        The management UI's list view wants an entry count per watchlist
        (``docs/API.md`` §5); grouping
        :meth:`~flightsite.watchlists.repository.WatchlistRepository.list_all_entries`
        by ``watchlist_id`` here costs the same two queries
        :meth:`reload_index` already runs, rather than one query per
        watchlist.
        """
        watchlists = await self._repository.list_watchlists()
        entries = await self._repository.list_all_entries()
        grouped: dict[int, list[WatchlistEntryRecord]] = {
            watchlist.id: [] for watchlist in watchlists
        }
        for entry in entries:
            grouped.setdefault(entry.watchlist_id, []).append(entry)
        return tuple((watchlist, tuple(grouped[watchlist.id])) for watchlist in watchlists)

    async def create_watchlist(self, *, name: str, description: str | None) -> WatchlistRecord:
        """Create a watchlist and rebuild the match index.

        Raises:
            WatchlistValueError: ``name`` or ``description`` fails validation.
            DuplicateWatchlistNameError: a watchlist named ``name`` already exists.
        """
        record = await self._repository.create_watchlist(
            name=normalize_watchlist_name(name),
            description=normalize_description(description),
            created_ms=self._clock(),
        )
        await self.reload_index()
        return record

    async def rename_watchlist(
        self, watchlist_id: int, *, name: str, description: str | None
    ) -> WatchlistRecord:
        """Replace a watchlist's name/description and rebuild the match index.

        Raises:
            WatchlistValueError: ``name`` or ``description`` fails validation.
            WatchlistNotFoundError: no watchlist has ``watchlist_id``.
            DuplicateWatchlistNameError: another watchlist already has ``name``.
        """
        record = await self._repository.rename_watchlist(
            watchlist_id,
            name=normalize_watchlist_name(name),
            description=normalize_description(description),
        )
        await self.reload_index()
        return record

    async def delete_watchlist(self, watchlist_id: int) -> bool:
        """Delete a watchlist (and every entry on it) and rebuild the index.

        Returns ``False`` for an unknown ``watchlist_id`` without rebuilding
        anything — nothing changed, so there is nothing to recompute.
        """
        deleted = await self._repository.delete_watchlist(watchlist_id)
        if deleted:
            await self.reload_index()
        return deleted

    # ------------------------------------------------------------ entries

    async def list_entries(self, watchlist_id: int) -> tuple[WatchlistEntryRecord, ...]:
        """One watchlist's entries, ordered by kind then value."""
        return await self._repository.list_entries(watchlist_id)

    async def add_entry(
        self, watchlist_id: int, *, kind: WatchlistEntryKind, value: str, note: str | None
    ) -> WatchlistEntryRecord:
        """Validate, normalize and add one entry; rebuild the match index.

        Raises:
            WatchlistValueError: ``value`` fails ``kind``'s format rule, or
                ``note`` is too long.
            WatchlistNotFoundError: no watchlist has ``watchlist_id``.
            DuplicateEntryError: this exact ``(kind, value)`` is already on
                this watchlist.
        """
        record = await self._repository.add_entry(
            watchlist_id,
            kind=kind,
            value=normalize_and_validate(kind, value),
            note=normalize_note(note),
            created_ms=self._clock(),
        )
        await self.reload_index()
        return record

    async def remove_entry(self, watchlist_id: int, entry_id: int) -> bool:
        """Remove one entry and rebuild the match index.

        Raises:
            WatchlistNotFoundError: no watchlist has ``watchlist_id``.

        Returns ``False`` when ``entry_id`` does not exist (or belongs to a
        different watchlist) without rebuilding anything.
        """
        removed = await self._repository.remove_entry(watchlist_id, entry_id)
        if removed:
            await self.reload_index()
        return removed


__all__ = ["ClockFn", "WatchlistService"]
