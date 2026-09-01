"""``WatchlistRepository`` CRUD round-trips and its domain errors."""

from __future__ import annotations

import pytest

from flightsite.db import Database
from flightsite.watchlists.errors import (
    DuplicateEntryError,
    DuplicateWatchlistNameError,
    WatchlistNotFoundError,
)
from flightsite.watchlists.model import WatchlistEntryRecord, WatchlistRecord
from flightsite.watchlists.repository import WatchlistRepository
from flightsite.watchlists.vocabulary import WatchlistEntryKind

from .conftest import CREATED_MS


async def _make(
    repository: WatchlistRepository, name: str, description: str | None = None
) -> WatchlistRecord:
    return await repository.create_watchlist(
        name=name, description=description, created_ms=CREATED_MS
    )


async def _icao_entry(
    repository: WatchlistRepository, watchlist_id: int, value: str = "ae1463"
) -> WatchlistEntryRecord:
    return await repository.add_entry(
        watchlist_id, kind=WatchlistEntryKind.ICAO24, value=value, note=None, created_ms=CREATED_MS
    )


async def test_create_and_get_round_trip(repository: WatchlistRepository) -> None:
    created = await _make(repository, "Local Police", "patrol helicopters")

    fetched = await repository.get_watchlist(created.id)

    assert fetched == created
    assert created.name == "Local Police"
    assert created.description == "patrol helicopters"
    assert created.created_ms == CREATED_MS


async def test_get_unknown_watchlist_returns_none(repository: WatchlistRepository) -> None:
    assert await repository.get_watchlist(999) is None


async def test_list_watchlists_is_alphabetical(repository: WatchlistRepository) -> None:
    await _make(repository, "Zulu")
    await _make(repository, "Alpha")

    names = [watchlist.name for watchlist in await repository.list_watchlists()]

    assert names == ["Alpha", "Zulu"]


async def test_create_rejects_a_duplicate_name(repository: WatchlistRepository) -> None:
    await _make(repository, "Local Police")

    with pytest.raises(DuplicateWatchlistNameError):
        await _make(repository, "Local Police")


async def test_rename_updates_name_and_description(repository: WatchlistRepository) -> None:
    created = await _make(repository, "Old")

    renamed = await repository.rename_watchlist(
        created.id, name="New", description="now with a note"
    )

    assert renamed.name == "New"
    assert renamed.description == "now with a note"
    assert (await repository.get_watchlist(created.id)) == renamed


async def test_rename_allows_keeping_its_own_name(repository: WatchlistRepository) -> None:
    created = await _make(repository, "Same")

    renamed = await repository.rename_watchlist(created.id, name="Same", description="updated")

    assert renamed.description == "updated"


async def test_rename_rejects_colliding_with_another_watchlist(
    repository: WatchlistRepository,
) -> None:
    await _make(repository, "Taken")
    other = await _make(repository, "Other")

    with pytest.raises(DuplicateWatchlistNameError):
        await repository.rename_watchlist(other.id, name="Taken", description=None)


async def test_rename_unknown_watchlist_raises_not_found(repository: WatchlistRepository) -> None:
    with pytest.raises(WatchlistNotFoundError):
        await repository.rename_watchlist(999, name="X", description=None)


async def test_delete_removes_the_watchlist(repository: WatchlistRepository) -> None:
    created = await _make(repository, "Gone Soon")

    deleted = await repository.delete_watchlist(created.id)

    assert deleted is True
    assert await repository.get_watchlist(created.id) is None


async def test_delete_unknown_watchlist_returns_false(repository: WatchlistRepository) -> None:
    assert await repository.delete_watchlist(999) is False


async def test_delete_cascades_to_its_entries(
    repository: WatchlistRepository, database: Database
) -> None:
    """§4.1's ``ON DELETE CASCADE`` — enforced by SQLite because ADR-0001 runs
    with ``PRAGMA foreign_keys = ON``."""
    watchlist = await _make(repository, "Cascade Me")
    await _icao_entry(repository, watchlist.id)

    await repository.delete_watchlist(watchlist.id)

    assert await repository.list_entries(watchlist.id) == ()
    assert await repository.list_all_entries() == ()


# ------------------------------------------------------------------ entries


async def test_add_and_list_entries_round_trip(repository: WatchlistRepository) -> None:
    watchlist = await _make(repository, "W")

    entry = await repository.add_entry(
        watchlist.id,
        kind=WatchlistEntryKind.REGISTRATION,
        value="N12345",
        note="a note",
        created_ms=CREATED_MS,
    )

    entries = await repository.list_entries(watchlist.id)
    assert entries == (entry,)
    assert entry.watchlist_id == watchlist.id
    assert entry.kind is WatchlistEntryKind.REGISTRATION
    assert entry.value == "N12345"
    assert entry.note == "a note"


async def test_add_entry_to_an_unknown_watchlist_raises_not_found(
    repository: WatchlistRepository,
) -> None:
    with pytest.raises(WatchlistNotFoundError):
        await _icao_entry(repository, 999)


async def test_add_entry_rejects_a_duplicate_kind_and_value_on_the_same_watchlist(
    repository: WatchlistRepository,
) -> None:
    watchlist = await _make(repository, "W")
    await _icao_entry(repository, watchlist.id)

    with pytest.raises(DuplicateEntryError):
        await _icao_entry(repository, watchlist.id)


async def test_the_same_value_may_appear_on_two_different_watchlists(
    repository: WatchlistRepository,
) -> None:
    first = await _make(repository, "First")
    second = await _make(repository, "Second")

    await _icao_entry(repository, first.id)
    entry = await _icao_entry(repository, second.id)

    assert entry.watchlist_id == second.id


async def test_remove_entry(repository: WatchlistRepository) -> None:
    watchlist = await _make(repository, "W")
    entry = await _icao_entry(repository, watchlist.id)

    removed = await repository.remove_entry(watchlist.id, entry.id)

    assert removed is True
    assert await repository.list_entries(watchlist.id) == ()


async def test_remove_entry_from_an_unknown_watchlist_raises_not_found(
    repository: WatchlistRepository,
) -> None:
    with pytest.raises(WatchlistNotFoundError):
        await repository.remove_entry(999, 1)


async def test_remove_unknown_entry_returns_false(repository: WatchlistRepository) -> None:
    watchlist = await _make(repository, "W")

    assert await repository.remove_entry(watchlist.id, 999) is False


async def test_remove_entry_belonging_to_a_different_watchlist_returns_false(
    repository: WatchlistRepository,
) -> None:
    first = await _make(repository, "First")
    second = await _make(repository, "Second")
    entry = await _icao_entry(repository, first.id)

    assert await repository.remove_entry(second.id, entry.id) is False
    assert await repository.list_entries(first.id) == (entry,)


async def test_list_all_entries_spans_every_watchlist(repository: WatchlistRepository) -> None:
    first = await _make(repository, "First")
    second = await _make(repository, "Second")
    await _icao_entry(repository, first.id)
    await repository.add_entry(
        second.id,
        kind=WatchlistEntryKind.TYPE_CODE,
        value="B738",
        note=None,
        created_ms=CREATED_MS,
    )

    all_entries = await repository.list_all_entries()

    assert {entry.watchlist_id for entry in all_entries} == {first.id, second.id}
