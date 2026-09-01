"""``MetadataCache``'s ``on_resolved`` observer hook (see the module docstring's
"Observing resolved views" section) — the seam roadmap slice 037's watchlist
matcher is built on.

These tests exercise the hook itself, generically: install, reclassify,
eviction (including the overflow-resync path), invalidation, and a failing
observer's isolation from the cache. Slice 037's own use of the hook is
covered end to end in ``tests/watchlists/test_cache_integration.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flightsite.db import Database
from flightsite.ingest import AircraftStateUpdate
from flightsite.live import LiveStore
from flightsite.logging import configure_logging
from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.cache import AircraftMetadataView, MetadataCache
from tests.metadata.conftest import IMPORT_MS, appear, record, settle
from tests.metadata.provider import InMemoryMetadataProvider

FLEET = [
    record("a00001", registration="N1AA", type_code="B738"),
    record("a00002", registration="N2BB", type_code="B738"),
]


class _Clock:
    """A monotonic clock the test drives by hand."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _Recorder:
    """Collects every ``(icao, view)`` call, in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, AircraftMetadataView | None]] = []

    def __call__(self, icao: str, view: AircraftMetadataView | None) -> None:
        self.calls.append((icao, view))


async def test_installing_an_entry_notifies_with_the_fresh_view(
    importer: MetadataImporter, registry: SourceRegistry, database: Database, live: LiveStore
) -> None:
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    recorder = _Recorder()
    cache = MetadataCache(database=database, live=live, on_resolved=recorder)
    await cache.start()
    try:
        appear(live, "a00001")
        await settle(cache)

        assert recorder.calls == [("a00001", cache.get("a00001"))]
        view = recorder.calls[0][1]
        assert view is not None
        assert view.metadata is not None
        assert view.metadata.type_code == "B738"
    finally:
        await cache.stop()


async def test_starting_warm_from_the_live_set_also_notifies(
    importer: MetadataImporter, registry: SourceRegistry, database: Database, live: LiveStore
) -> None:
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    appear(live, "a00001")
    recorder = _Recorder()
    cache = MetadataCache(database=database, live=live, on_resolved=recorder)

    await cache.start()
    try:
        assert recorder.calls == [("a00001", cache.get("a00001"))]
    finally:
        await cache.stop()


async def test_an_aircraft_nobody_knows_still_notifies_with_an_unknown_view(
    database: Database, live: LiveStore
) -> None:
    """§2.7: "resolved to nothing" is still a resolution the observer hears about."""
    recorder = _Recorder()
    cache = MetadataCache(database=database, live=live, on_resolved=recorder)
    await cache.start()
    try:
        appear(live, "beef01")
        await settle(cache)

        assert len(recorder.calls) == 1
        icao, view = recorder.calls[0]
        assert icao == "beef01"
        assert view is not None
        assert not view.known
    finally:
        await cache.stop()


async def test_a_reclassifying_callsign_change_notifies_again(
    importer: MetadataImporter, registry: SourceRegistry, database: Database
) -> None:
    clock = _Clock()
    store = LiveStore(clock=clock, stale_s=100.0, remove_s=200.0)
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    recorder = _Recorder()
    cache = MetadataCache(database=database, live=store, on_resolved=recorder)
    await cache.start()
    try:
        appear(store, "a00001")
        await settle(cache)
        recorder.calls.clear()

        now = datetime.fromtimestamp(IMPORT_MS / 1000, tz=UTC)
        store.apply_updates([AircraftStateUpdate(icao="a00001", timestamp=now, callsign="DAL123")])
        await settle(cache)

        assert recorder.calls == [("a00001", cache.get("a00001"))]
        view = recorder.calls[0][1]
        assert view is not None
        assert view.evidence.callsign == "DAL123"
    finally:
        await cache.stop()


async def test_removal_notifies_with_none(
    importer: MetadataImporter, registry: SourceRegistry, database: Database
) -> None:
    clock = _Clock()
    store = LiveStore(clock=clock, stale_s=1.0, remove_s=2.0)
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    recorder = _Recorder()
    cache = MetadataCache(database=database, live=store, on_resolved=recorder)
    await cache.start()
    try:
        appear(store, "a00001")
        await settle(cache)
        recorder.calls.clear()

        clock.value = 10.0
        store.sweep()
        await settle(cache)

        assert recorder.calls == [("a00001", None)]
    finally:
        await cache.stop()


async def test_an_aircraft_removed_before_resolution_never_notifies(
    importer: MetadataImporter, registry: SourceRegistry, database: Database
) -> None:
    clock = _Clock()
    store = LiveStore(clock=clock, stale_s=1.0, remove_s=2.0)
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    recorder = _Recorder()
    cache = MetadataCache(database=database, live=store, on_resolved=recorder)
    await cache.start()
    try:
        appear(store, "a00001")
        clock.value = 10.0
        store.sweep()
        await settle(cache)

        assert recorder.calls == []
    finally:
        await cache.stop()


async def test_overflow_resync_notifies_evictions_with_none(
    importer: MetadataImporter, registry: SourceRegistry, database: Database
) -> None:
    """The resync path (see the cache's ``_collect``) evicts through the same
    hook the ordinary removal path uses."""
    clock = _Clock()
    store = LiveStore(clock=clock, stale_s=1.0, remove_s=2.0)
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    recorder = _Recorder()
    cache = MetadataCache(database=database, live=store, queue_size=2, on_resolved=recorder)
    await cache.start()
    try:
        appear(store, "a00001")
        await settle(cache)
        recorder.calls.clear()

        clock.value = 10.0
        appear(store, "a00002", "beef01", "beef02", "beef03")
        store.sweep()
        await settle(cache)

        # a00001 aged out during the overflow episode and must have been
        # evicted through the observer, not merely dropped silently.
        evicted = [icao for icao, view in recorder.calls if view is None]
        assert "a00001" in evicted
    finally:
        await cache.stop()


async def test_invalidation_notifies_every_repopulated_aircraft(
    importer: MetadataImporter, registry: SourceRegistry, database: Database, live: LiveStore
) -> None:
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    recorder = _Recorder()
    cache = MetadataCache(database=database, live=live, on_resolved=recorder)
    await cache.start()
    try:
        appear(live, "a00001")
        await settle(cache)
        recorder.calls.clear()

        await cache.invalidate()

        assert [icao for icao, _ in recorder.calls] == ["a00001"]
    finally:
        await cache.stop()


async def test_a_failing_observer_is_isolated_and_logged(
    importer: MetadataImporter,
    registry: SourceRegistry,
    database: Database,
    live: LiveStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A broken observer must not turn a successful resolution into a cache miss."""
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    configure_logging(level="INFO")

    def _boom(icao: str, view: AircraftMetadataView | None) -> None:
        raise RuntimeError("watchlist index rebuild exploded")

    cache = MetadataCache(database=database, live=live, on_resolved=_boom)
    await cache.start()
    try:
        appear(live, "a00001")
        await settle(cache)

        # The cache's own resolution is unaffected by the observer blowing up.
        view = cache.get("a00001")
        assert view is not None
        assert view.known
    finally:
        await cache.stop()

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "metadata_cache_observer_error" in output
    assert "watchlist index rebuild exploded" in output


async def test_no_observer_is_the_default_and_costs_nothing(
    importer: MetadataImporter, registry: SourceRegistry, database: Database, live: LiveStore
) -> None:
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    cache = MetadataCache(database=database, live=live)
    await cache.start()
    try:
        appear(live, "a00001")
        await settle(cache)

        assert cache.get("a00001") is not None
    finally:
        await cache.stop()
