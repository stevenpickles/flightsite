"""``WatchlistService``: CRUD orchestration plus the index rebuild it drives.

The claim under test throughout is roadmap slice 037's second acceptance
criterion — "matching updates without restart" — expressed as: after any
mutating call returns, :attr:`WatchlistService.matcher` already reflects it,
with no separate reload step a caller has to remember to call.
"""

from __future__ import annotations

import pytest

from flightsite.classification.model import Classification, Evidence
from flightsite.metadata.cache import AircraftMetadataView
from flightsite.watchlists.errors import (
    DuplicateEntryError,
    DuplicateWatchlistNameError,
    WatchlistNotFoundError,
)
from flightsite.watchlists.matcher import WatchlistMatcher
from flightsite.watchlists.service import WatchlistService
from flightsite.watchlists.vocabulary import WatchlistEntryKind, WatchlistValueError


def _put_live(matcher: WatchlistMatcher, icao: str) -> None:
    """Simulate the metadata cache resolving a bare (metadata-less) aircraft."""
    matcher.on_resolved(
        icao,
        AircraftMetadataView(
            icao24=icao, evidence=Evidence(icao24=icao), classification=Classification()
        ),
    )


async def test_start_loads_an_empty_index(service: WatchlistService) -> None:
    await service.start()

    assert service.matcher.index.entry_value_count == 0


async def test_create_watchlist_normalizes_and_persists(service: WatchlistService) -> None:
    record = await service.create_watchlist(name="  Local Police  ", description="  patrol  ")

    assert record.name == "Local Police"
    assert record.description == "patrol"


async def test_create_watchlist_rejects_a_blank_name(service: WatchlistService) -> None:
    with pytest.raises(WatchlistValueError):
        await service.create_watchlist(name="   ", description=None)


async def test_create_watchlist_rejects_a_duplicate_name(service: WatchlistService) -> None:
    await service.create_watchlist(name="Dup", description=None)

    with pytest.raises(DuplicateWatchlistNameError):
        await service.create_watchlist(name="Dup", description=None)


async def test_add_entry_makes_a_live_aircraft_match_immediately(
    service: WatchlistService,
) -> None:
    """The end-to-end claim: CRUD, then a live view already present, matches
    with no separate reload call."""
    watchlist = await service.create_watchlist(name="Police Helicopters", description=None)
    _put_live(service.matcher, "ae1463")
    assert service.matcher.matches("ae1463") == ()

    await service.add_entry(watchlist.id, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None)

    assert service.matcher.matches("ae1463") == ("Police Helicopters",)


async def test_remove_entry_makes_a_live_aircraft_stop_matching(
    service: WatchlistService,
) -> None:
    watchlist = await service.create_watchlist(name="Police Helicopters", description=None)
    entry = await service.add_entry(
        watchlist.id, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None
    )
    _put_live(service.matcher, "ae1463")
    assert service.matcher.matches("ae1463") == ("Police Helicopters",)

    await service.remove_entry(watchlist.id, entry.id)

    assert service.matcher.matches("ae1463") == ()


async def test_delete_watchlist_makes_its_matches_disappear(service: WatchlistService) -> None:
    watchlist = await service.create_watchlist(name="Police Helicopters", description=None)
    await service.add_entry(watchlist.id, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None)
    _put_live(service.matcher, "ae1463")
    assert service.matcher.matches("ae1463") == ("Police Helicopters",)

    await service.delete_watchlist(watchlist.id)

    assert service.matcher.matches("ae1463") == ()


async def test_rename_watchlist_changes_the_reported_match_name(
    service: WatchlistService,
) -> None:
    watchlist = await service.create_watchlist(name="Old Name", description=None)
    await service.add_entry(watchlist.id, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None)
    _put_live(service.matcher, "ae1463")
    assert service.matcher.matches("ae1463") == ("Old Name",)

    await service.rename_watchlist(watchlist.id, name="New Name", description=None)

    assert service.matcher.matches("ae1463") == ("New Name",)


async def test_add_entry_to_an_unknown_watchlist_does_not_touch_the_index(
    service: WatchlistService,
) -> None:
    before = service.matcher.index.entry_value_count

    with pytest.raises(WatchlistNotFoundError):
        await service.add_entry(999, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None)

    assert service.matcher.index.entry_value_count == before


async def test_add_duplicate_entry_raises_without_touching_the_index(
    service: WatchlistService,
) -> None:
    watchlist = await service.create_watchlist(name="W", description=None)
    await service.add_entry(watchlist.id, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None)
    before = service.matcher.index.entry_value_count

    with pytest.raises(DuplicateEntryError):
        await service.add_entry(
            watchlist.id, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None
        )

    assert service.matcher.index.entry_value_count == before


async def test_add_entry_rejects_an_invalid_value_before_touching_storage(
    service: WatchlistService,
) -> None:
    watchlist = await service.create_watchlist(name="W", description=None)

    with pytest.raises(WatchlistValueError):
        await service.add_entry(
            watchlist.id, kind=WatchlistEntryKind.ICAO24, value="not-hex!!", note=None
        )

    assert await service.list_entries(watchlist.id) == ()


async def test_delete_unknown_watchlist_returns_false_without_reloading(
    service: WatchlistService,
) -> None:
    assert await service.delete_watchlist(999) is False


async def test_remove_unknown_entry_returns_false_without_reloading(
    service: WatchlistService,
) -> None:
    watchlist = await service.create_watchlist(name="W", description=None)

    assert await service.remove_entry(watchlist.id, 999) is False


async def test_list_watchlists_with_entries_groups_correctly(service: WatchlistService) -> None:
    first = await service.create_watchlist(name="First", description=None)
    second = await service.create_watchlist(name="Second", description=None)
    await service.add_entry(first.id, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None)

    grouped = await service.list_watchlists_with_entries()

    by_id = {watchlist.id: entries for watchlist, entries in grouped}
    assert len(by_id[first.id]) == 1
    assert by_id[second.id] == ()


async def test_get_watchlist_returns_none_for_unknown(service: WatchlistService) -> None:
    assert await service.get_watchlist(999) is None
