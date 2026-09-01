"""Persistence for ``watchlists`` and ``watchlist_entries`` (§4.1).

Every write pre-checks the uniqueness rule it would otherwise rely on a
``UNIQUE`` constraint violation to report, and raises the matching domain
error from :mod:`flightsite.watchlists.errors` instead. That is safe against a
concurrent duplicate — not merely convenient — because ADR-0001's single
writer connection and :meth:`~flightsite.db.engine.Database.writer_session`'s
own lock make the check-then-insert atomic: no other writer can interleave
between the ``SELECT`` and the ``INSERT`` in the same session. The ``UNIQUE``
constraints stay in the schema as the backstop of last resort, not as the
primary error path — reading a clear ``DuplicateWatchlistNameError`` message
out of a caught ``IntegrityError`` would mean parsing SQLite's own text.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from flightsite.db import Database, Watchlist, WatchlistEntry
from flightsite.watchlists.errors import (
    DuplicateEntryError,
    DuplicateWatchlistNameError,
    WatchlistNotFoundError,
)
from flightsite.watchlists.model import WatchlistEntryRecord, WatchlistRecord
from flightsite.watchlists.vocabulary import WatchlistEntryKind


def _watchlist_record(row: Watchlist) -> WatchlistRecord:
    return WatchlistRecord(
        id=row.id, name=row.name, description=row.description, created_ms=row.created_ms
    )


def _entry_record(row: WatchlistEntry) -> WatchlistEntryRecord:
    return WatchlistEntryRecord(
        id=row.id,
        watchlist_id=row.watchlist_id,
        kind=WatchlistEntryKind(row.kind),
        value=row.value,
        note=row.note,
        created_ms=row.created_ms,
    )


@dataclass(frozen=True, slots=True)
class WatchlistRepository:
    """Persistence operations for watchlists and their entries."""

    database: Database

    async def list_watchlists(self) -> tuple[WatchlistRecord, ...]:
        """Every watchlist, alphabetical by name — the order the management UI shows."""
        statement = select(Watchlist).order_by(Watchlist.name)
        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).scalars().all()
        return tuple(_watchlist_record(row) for row in rows)

    async def get_watchlist(self, watchlist_id: int) -> WatchlistRecord | None:
        """One watchlist, or ``None`` if ``watchlist_id`` does not exist."""
        async with self.database.read_session() as session:
            row = await session.get(Watchlist, watchlist_id)
        return None if row is None else _watchlist_record(row)

    async def create_watchlist(
        self, *, name: str, description: str | None, created_ms: int
    ) -> WatchlistRecord:
        """Create a watchlist.

        Raises:
            DuplicateWatchlistNameError: a watchlist named ``name`` already exists.
        """
        async with self.database.writer_session() as session:
            existing = await session.scalar(select(Watchlist.id).where(Watchlist.name == name))
            if existing is not None:
                raise DuplicateWatchlistNameError(f"a watchlist named {name!r} already exists")
            row = Watchlist(name=name, description=description, created_ms=created_ms)
            session.add(row)
            await session.flush()
            return _watchlist_record(row)

    async def rename_watchlist(
        self, watchlist_id: int, *, name: str, description: str | None
    ) -> WatchlistRecord:
        """Replace a watchlist's name and description (``PUT``, full replace).

        Raises:
            WatchlistNotFoundError: no watchlist has ``watchlist_id``.
            DuplicateWatchlistNameError: another watchlist already has ``name``.
        """
        async with self.database.writer_session() as session:
            row = await session.get(Watchlist, watchlist_id)
            if row is None:
                raise WatchlistNotFoundError(f"no watchlist with id {watchlist_id}")
            if name != row.name:
                existing = await session.scalar(
                    select(Watchlist.id).where(Watchlist.name == name, Watchlist.id != watchlist_id)
                )
                if existing is not None:
                    raise DuplicateWatchlistNameError(f"a watchlist named {name!r} already exists")
            row.name = name
            row.description = description
            await session.flush()
            return _watchlist_record(row)

    async def delete_watchlist(self, watchlist_id: int) -> bool:
        """Delete a watchlist and every entry on it (``ON DELETE CASCADE``).

        Returns ``False`` rather than raising when ``watchlist_id`` does not
        exist — delete is naturally idempotent, and the internal API answers
        a ``404`` from that rather than from a caught exception.
        """
        async with self.database.writer_session() as session:
            row = await session.get(Watchlist, watchlist_id)
            if row is None:
                return False
            await session.delete(row)
        return True

    async def list_entries(self, watchlist_id: int) -> tuple[WatchlistEntryRecord, ...]:
        """One watchlist's entries, ordered by kind then value."""
        statement = (
            select(WatchlistEntry)
            .where(WatchlistEntry.watchlist_id == watchlist_id)
            .order_by(WatchlistEntry.kind, WatchlistEntry.value)
        )
        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).scalars().all()
        return tuple(_entry_record(row) for row in rows)

    async def list_all_entries(self) -> tuple[WatchlistEntryRecord, ...]:
        """Every entry across every watchlist.

        The one query :mod:`flightsite.watchlists.service` uses to rebuild the
        in-memory match index — off the live path entirely (see
        :mod:`flightsite.watchlists.matcher`), run only at startup and after a
        CRUD change.
        """
        async with self.database.read_session() as session:
            rows = (await session.execute(select(WatchlistEntry))).scalars().all()
        return tuple(_entry_record(row) for row in rows)

    async def add_entry(
        self,
        watchlist_id: int,
        *,
        kind: WatchlistEntryKind,
        value: str,
        note: str | None,
        created_ms: int,
    ) -> WatchlistEntryRecord:
        """Add one entry. ``value`` must already be normalized for ``kind``.

        Raises:
            WatchlistNotFoundError: no watchlist has ``watchlist_id``.
            DuplicateEntryError: this exact ``(kind, value)`` is already on
                this watchlist.
        """
        async with self.database.writer_session() as session:
            watchlist = await session.get(Watchlist, watchlist_id)
            if watchlist is None:
                raise WatchlistNotFoundError(f"no watchlist with id {watchlist_id}")
            existing = await session.scalar(
                select(WatchlistEntry.id).where(
                    WatchlistEntry.watchlist_id == watchlist_id,
                    WatchlistEntry.kind == kind.value,
                    WatchlistEntry.value == value,
                )
            )
            if existing is not None:
                raise DuplicateEntryError(f"{kind.value} {value!r} is already on this watchlist")
            row = WatchlistEntry(
                watchlist_id=watchlist_id,
                kind=kind.value,
                value=value,
                note=note,
                created_ms=created_ms,
            )
            session.add(row)
            await session.flush()
            return _entry_record(row)

    async def remove_entry(self, watchlist_id: int, entry_id: int) -> bool:
        """Remove one entry from a watchlist.

        Returns ``False`` when ``entry_id`` does not exist or belongs to a
        different watchlist — the internal API answers a ``404`` from that,
        the same idempotent shape :meth:`delete_watchlist` follows.

        Raises:
            WatchlistNotFoundError: no watchlist has ``watchlist_id``.
        """
        async with self.database.writer_session() as session:
            watchlist = await session.get(Watchlist, watchlist_id)
            if watchlist is None:
                raise WatchlistNotFoundError(f"no watchlist with id {watchlist_id}")
            row = await session.get(WatchlistEntry, entry_id)
            if row is None or row.watchlist_id != watchlist_id:
                return False
            await session.delete(row)
        return True


__all__ = ["WatchlistRepository"]
