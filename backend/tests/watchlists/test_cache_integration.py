"""End-to-end: watchlist matching against live, demo-style traffic.

Unlike ``tests/watchlists/test_matcher.py`` (which builds
:class:`~flightsite.metadata.cache.AircraftMetadataView` objects by hand),
this wires the real pipeline slice 037's roadmap acceptance criterion is
about: a :class:`~flightsite.metadata.MetadataImporter` run over a small
in-memory fleet, a real :class:`~flightsite.metadata.cache.MetadataCache`
subscribed to a real :class:`~flightsite.live.LiveStore`, and a real
:class:`~flightsite.watchlists.WatchlistService` registered as the cache's
``on_resolved`` observer — exactly how ``flightsite.app.create_app`` wires the
two together. Aircraft "appear" the same way a decoder poll would, and every
entry kind is exercised against metadata and classification the real
pipeline resolved, not a hand-built stand-in.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.metadata import MetadataImporter, MetadataService, SourceRegistry
from flightsite.watchlists import WatchlistEntryKind, WatchlistService
from tests.metadata.conftest import appear, record, settle
from tests.metadata.provider import InMemoryMetadataProvider

#: A small demo-style fleet: an airliner with a curated passenger operator (for
#: registration/operator/category-by-operator matching), and a helicopter type
#: with no curated operator (for type-code and category-by-type matching).
FLEET = [
    record(
        "a00001",
        registration="N1AA",
        type_code="B738",
        operator_name="Delta Air Lines",
    ),
    record("a00002", registration="N2BB", type_code="EC35"),
]


class _Clock:
    """A monotonic clock the test drives by hand."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def registry() -> SourceRegistry:
    return SourceRegistry()


@pytest.fixture
async def populated(registry: SourceRegistry, database: Database, isolated_data_dir: Path) -> None:
    importer = MetadataImporter(database=database, registry=registry, data_dir=isolated_data_dir)
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def live(clock: _Clock) -> LiveStore:
    """A live store with a hand-driven clock, generous thresholds by default."""
    return LiveStore(clock=clock, stale_s=100.0, remove_s=200.0)


@pytest.fixture
async def wired(
    database: Database, live: LiveStore, registry: SourceRegistry, isolated_data_dir: Path
) -> AsyncIterator[tuple[WatchlistService, MetadataService]]:
    """A watchlist service registered as the metadata cache's observer —
    exactly the seam ``flightsite.app.create_app`` wires."""
    watchlists = WatchlistService(database=database)
    await watchlists.start()
    metadata = MetadataService(
        database=database,
        live=live,
        data_dir=isolated_data_dir,
        registry=registry,
        on_resolved=watchlists.matcher.on_resolved,
    )
    await metadata.start()
    try:
        yield watchlists, metadata
    finally:
        await metadata.stop()


async def _settle(metadata: MetadataService) -> None:
    await settle(metadata.cache)


async def test_icao24_entry_matches_live_demo_traffic(
    populated: None, wired: tuple[WatchlistService, MetadataService], live: LiveStore
) -> None:
    watchlists, metadata = wired
    created = await watchlists.create_watchlist(name="Tracked Hex", description=None)
    await watchlists.add_entry(
        created.id, kind=WatchlistEntryKind.ICAO24, value="a00001", note=None
    )

    appear(live, "a00001", "a00002")
    await _settle(metadata)

    assert watchlists.matcher.matches("a00001") == ("Tracked Hex",)
    assert watchlists.matcher.matches("a00002") == ()


async def test_registration_entry_matches_live_demo_traffic(
    populated: None, wired: tuple[WatchlistService, MetadataService], live: LiveStore
) -> None:
    watchlists, metadata = wired
    created = await watchlists.create_watchlist(name="Tail Numbers", description=None)
    await watchlists.add_entry(
        created.id, kind=WatchlistEntryKind.REGISTRATION, value="n1aa", note=None
    )

    appear(live, "a00001")
    await _settle(metadata)

    assert watchlists.matcher.matches("a00001") == ("Tail Numbers",)


async def test_type_code_entry_matches_live_demo_traffic(
    populated: None, wired: tuple[WatchlistService, MetadataService], live: LiveStore
) -> None:
    watchlists, metadata = wired
    created = await watchlists.create_watchlist(name="Rotorcraft", description=None)
    await watchlists.add_entry(
        created.id, kind=WatchlistEntryKind.TYPE_CODE, value="ec35", note=None
    )

    appear(live, "a00001", "a00002")
    await _settle(metadata)

    assert watchlists.matcher.matches("a00002") == ("Rotorcraft",)
    assert watchlists.matcher.matches("a00001") == ()


async def test_operator_entry_matches_live_demo_traffic(
    populated: None, wired: tuple[WatchlistService, MetadataService], live: LiveStore
) -> None:
    watchlists, metadata = wired
    created = await watchlists.create_watchlist(name="Delta Flights", description=None)
    await watchlists.add_entry(
        created.id, kind=WatchlistEntryKind.OPERATOR, value="delta air lines", note=None
    )

    appear(live, "a00001", "a00002")
    await _settle(metadata)

    assert watchlists.matcher.matches("a00001") == ("Delta Flights",)
    assert watchlists.matcher.matches("a00002") == ()


async def test_category_entry_matches_live_demo_traffic(
    populated: None, wired: tuple[WatchlistService, MetadataService], live: LiveStore
) -> None:
    """The curated operator directory (not the database) resolves the
    airliner's mission; the rotorcraft table resolves the helicopter's."""
    watchlists, metadata = wired
    passenger = await watchlists.create_watchlist(name="Passenger Flights", description=None)
    await watchlists.add_entry(
        passenger.id, kind=WatchlistEntryKind.CATEGORY, value="commercial_passenger", note=None
    )
    rotorcraft = await watchlists.create_watchlist(name="Helicopters", description=None)
    await watchlists.add_entry(
        rotorcraft.id, kind=WatchlistEntryKind.CATEGORY, value="helicopter", note=None
    )

    appear(live, "a00001", "a00002")
    await _settle(metadata)

    assert watchlists.matcher.matches("a00001") == ("Passenger Flights",)
    assert watchlists.matcher.matches("a00002") == ("Helicopters",)


async def test_matching_updates_without_a_restart(
    populated: None, wired: tuple[WatchlistService, MetadataService], live: LiveStore
) -> None:
    """Roadmap slice 037's second acceptance criterion, end to end: create a
    watchlist entry against an aircraft already live, with no reconnect and no
    process restart, and the very next lookup reflects it."""
    watchlists, metadata = wired
    appear(live, "a00001")
    await _settle(metadata)

    created = await watchlists.create_watchlist(name="Late Addition", description=None)
    assert watchlists.matcher.matches("a00001") == ()

    await watchlists.add_entry(
        created.id, kind=WatchlistEntryKind.ICAO24, value="a00001", note=None
    )

    assert watchlists.matcher.matches("a00001") == ("Late Addition",)


async def test_an_aircraft_matching_two_watchlists_reports_both(
    populated: None, wired: tuple[WatchlistService, MetadataService], live: LiveStore
) -> None:
    watchlists, metadata = wired
    by_hex = await watchlists.create_watchlist(name="By Hex", description=None)
    await watchlists.add_entry(by_hex.id, kind=WatchlistEntryKind.ICAO24, value="a00001", note=None)
    by_operator = await watchlists.create_watchlist(name="By Operator", description=None)
    await watchlists.add_entry(
        by_operator.id, kind=WatchlistEntryKind.OPERATOR, value="delta air lines", note=None
    )

    appear(live, "a00001")
    await _settle(metadata)

    assert watchlists.matcher.matches("a00001") == ("By Hex", "By Operator")


async def test_a_departed_aircraft_is_no_longer_flagged(
    populated: None,
    wired: tuple[WatchlistService, MetadataService],
    live: LiveStore,
    clock: _Clock,
) -> None:
    watchlists, metadata = wired
    created = await watchlists.create_watchlist(name="Tracked Hex", description=None)
    await watchlists.add_entry(
        created.id, kind=WatchlistEntryKind.ICAO24, value="a00001", note=None
    )
    appear(live, "a00001")
    await _settle(metadata)
    assert watchlists.matcher.matches("a00001") == ("Tracked Hex",)

    clock.value = 1000.0
    live.sweep()
    await _settle(metadata)

    assert watchlists.matcher.matches("a00001") == ()
    assert watchlists.matcher.live_count == 0
