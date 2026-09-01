"""The metadata & rarity cache: population, eviction, invalidation, counters."""

from __future__ import annotations

import pytest

from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.metadata import MetadataImporter, MetadataService, SourceRegistry
from flightsite.metadata.cache import MetadataCache
from flightsite.metadata.registry import ImportPhase
from tests.metadata.conftest import appear, record, seed_aircraft, settle
from tests.metadata.provider import InMemoryMetadataProvider

FLEET = [
    record(
        "a00001",
        registration="N1AA",
        type_code="B738",
        model="Boeing 737-800",
        operator_name="Delta Air Lines",
    ),
    record("a00002", registration="N2BB", type_code="B738"),
    record("a00003", registration="N3CC", type_code="A320"),
]


@pytest.fixture
async def populated(
    importer: MetadataImporter, registry: SourceRegistry, database: Database
) -> None:
    """A metadata dataset plus the aircraft history rarity counts come from."""
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()
    await seed_aircraft(database, {"a00001": 42, "a00002": 1, "a00003": 7})


@pytest.fixture
async def cache(database: Database, live: LiveStore) -> MetadataCache:
    return MetadataCache(database=database, live=live)


# ------------------------------------------------------------- population


async def test_an_appear_event_populates_metadata_and_provenance(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    await cache.start()
    try:
        appear(live, "a00001")
        await settle(cache)

        view = cache.get("a00001")
        assert view is not None
        assert view.known
        assert view.type_code == "B738"
        assert view.metadata is not None
        assert view.metadata.operator_name == "Delta Air Lines"
        assert view.provenance()["operator"] == "mictronics"
    finally:
        await cache.stop()


async def test_an_aircraft_nobody_has_metadata_for_resolves_to_unknown(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """ "We looked and nobody knows" is a different answer from "not yet"."""
    await cache.start()
    try:
        appear(live, "beef01")
        await settle(cache)

        view = cache.get("beef01")
        assert view is not None
        assert not view.known
        assert view.provenance() == {}
        assert view.type_code is None
    finally:
        await cache.stop()


async def test_an_aircraft_that_never_appeared_is_not_in_the_cache(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    await cache.start()
    try:
        appear(live, "a00001")
        await settle(cache)

        assert cache.get("a00002") is None
    finally:
        await cache.stop()


async def test_a_whole_batch_resolves_in_one_population_round(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """The batching the latency budget depends on: one round, not one per event."""
    await cache.start()
    try:
        before = cache.populations
        appear(live, "a00001", "a00002", "a00003")
        await settle(cache)

        assert cache.size == 3
        assert cache.populations == before + 1
    finally:
        await cache.stop()


async def test_starting_warms_from_the_current_live_set(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """An aircraft already live when the cache starts gets no appear event."""
    appear(live, "a00001")

    await cache.start()
    try:
        assert cache.get("a00001") is not None
    finally:
        await cache.stop()


async def test_repeated_updates_do_not_repopulate(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """Only appearances cost a read; the 1 Hz update stream costs nothing."""
    await cache.start()
    try:
        appear(live, "a00001")
        await settle(cache)
        after_appear = cache.populations

        for _ in range(10):
            appear(live, "a00001")
        await settle(cache)

        assert cache.populations == after_appear
    finally:
        await cache.stop()


# ---------------------------------------------------------------- eviction


async def test_removal_evicts_the_entry(
    populated: None, database: Database, live: LiveStore
) -> None:
    """Eviction is what bounds the cache to the live set."""
    clock = _Clock()
    store = LiveStore(clock=clock, stale_s=1.0, remove_s=2.0)
    cache = MetadataCache(database=database, live=store)
    await cache.start()
    try:
        appear(store, "a00001")
        await settle(cache)
        assert cache.size == 1

        clock.value = 10.0
        store.sweep()
        await settle(cache)

        assert cache.get("a00001") is None
        assert cache.size == 0
    finally:
        await cache.stop()


async def test_an_aircraft_removed_before_resolution_is_never_resolved(
    populated: None, database: Database
) -> None:
    """Appear and remove inside one drain must not leave a stale entry."""
    clock = _Clock()
    store = LiveStore(clock=clock, stale_s=1.0, remove_s=2.0)
    cache = MetadataCache(database=database, live=store)
    await cache.start()
    try:
        appear(store, "a00001")
        clock.value = 10.0
        store.sweep()
        await settle(cache)

        assert cache.size == 0
    finally:
        await cache.stop()


async def test_an_overflowed_subscription_resyncs_from_the_live_snapshot(
    populated: None, database: Database
) -> None:
    """The documented recovery: rebuild from the snapshot, not the event gap.

    A shed event can hide either half of the truth — an appear the cache never
    learned of, or a removal it never learned of — so the resync has to add
    *and* evict. Both are provoked here: one aircraft is cached and then leaves
    while the queue is overflowing, and four appear that the cache never saw.
    """
    clock = _Clock()
    store = LiveStore(clock=clock, stale_s=1.0, remove_s=2.0)
    cache = MetadataCache(database=database, live=store, queue_size=2)
    await cache.start()
    try:
        appear(store, "a00001")
        await settle(cache)
        assert cache.size == 1

        clock.value = 10.0
        appear(store, "a00002", "a00003", "beef01", "beef02")
        store.sweep()
        await settle(cache)

        assert cache.get("a00001") is None
        assert cache.get("a00003") is not None
        assert cache.size == 4
    finally:
        await cache.stop()


# --------------------------------------------------------- rarity counters


async def test_sighting_counts_come_from_the_persisted_lifetime_figure(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """SPEC §44 rarity reads ``aircraft.sighting_count`` (DATA_MODEL §2.2)."""
    await cache.start()
    try:
        appear(live, "a00001", "a00002", "a00003")
        await settle(cache)

        assert cache.sighting_count("a00001") == 42
        assert cache.sighting_count("a00002") == 1
        assert cache.sighting_count("a00003") == 7
    finally:
        await cache.stop()


async def test_an_airframe_with_no_history_has_no_count(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """Never persisted is ``None``, not zero: nobody has counted it yet."""
    await cache.start()
    try:
        appear(live, "beef01")
        await settle(cache)

        assert cache.sighting_count("beef01") is None
    finally:
        await cache.stop()


async def test_sighting_count_of_an_aircraft_that_is_not_live_is_none(
    populated: None, cache: MetadataCache
) -> None:
    await cache.start()
    try:
        assert cache.sighting_count("a00001") is None
    finally:
        await cache.stop()


async def test_type_counts_are_resident_and_match_the_fixture_history(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """Two B738 airframes and one A320 in the seeded history."""
    await cache.start()
    try:
        assert cache.type_counts() == {"B738": 2, "A320": 1}
        assert cache.type_count("B738") == 2
        assert cache.type_count_size == 2

        appear(live, "a00001")
        await settle(cache)
        view = cache.get("a00001")
        assert view is not None
        assert view.type_count == 2
    finally:
        await cache.stop()


async def test_an_unseen_type_counts_zero(populated: None, cache: MetadataCache) -> None:
    """The map holds every recorded type, so absence is a count of none."""
    await cache.start()
    try:
        assert cache.type_count("CONC") == 0
    finally:
        await cache.stop()


# ------------------------------------------------------------ invalidation


async def test_an_import_repopulates_the_live_set(
    database: Database,
    live: LiveStore,
    registry: SourceRegistry,
    service: MetadataService,
) -> None:
    """The whole invalidation path, through the service the app wires."""
    appear(live, "a00001")
    await settle(service.cache)
    provider = InMemoryMetadataProvider([record("a00001", type_code="B738")])
    registry.register("mictronics", provider)

    view = service.cache.get("a00001")
    assert view is not None
    assert not view.known

    await service.update()

    refreshed = service.cache.get("a00001")
    assert refreshed is not None
    assert refreshed.type_code == "B738"


async def test_invalidation_picks_up_changed_metadata_for_a_live_aircraft(
    live: LiveStore, registry: SourceRegistry, service: MetadataService
) -> None:
    provider = InMemoryMetadataProvider([record("a00001", type_code="B738")])
    registry.register("mictronics", provider)
    await service.update()
    appear(live, "a00001")
    await settle(service.cache)

    provider.records = [record("a00001", type_code="A320")]
    provider.version = "mict-2"
    await service.update()

    view = service.cache.get("a00001")
    assert view is not None
    assert view.type_code == "A320"


async def test_invalidation_refreshes_the_type_counts(
    database: Database, live: LiveStore, registry: SourceRegistry, service: MetadataService
) -> None:
    await seed_aircraft(database, {"a00001": 5})
    registry.register("mictronics", InMemoryMetadataProvider([record("a00001", type_code="B738")]))

    await service.update()

    assert service.cache.type_counts() == {"B738": 1}


async def test_a_run_where_every_source_failed_does_not_invalidate(
    populated: None, live: LiveStore, registry: SourceRegistry, service: MetadataService
) -> None:
    """Nothing changed, so paying for a repopulation would be waste."""
    appear(live, "a00001")
    await settle(service.cache)
    registry.register(
        "faa", InMemoryMetadataProvider([record("a00009")], fail_at=ImportPhase.DOWNLOAD)
    )

    run = await service.update(["faa"])

    assert not run.changed_data
    assert service.cache.get("a00001") is not None


# --------------------------------------------------------------- lifecycle


async def test_start_and_stop_are_idempotent(cache: MetadataCache) -> None:
    await cache.stop()
    await cache.start()
    await cache.start()
    assert cache.running

    await cache.stop()
    await cache.stop()
    assert not cache.running


# ------------------------------------------------------------ lookup service


async def test_a_live_aircraft_is_looked_up_from_memory(
    database: Database, live: LiveStore, registry: SourceRegistry, service: MetadataService
) -> None:
    """No I/O at all for the live set: the cache already holds the answer."""
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await service.update()
    await seed_aircraft(database, {"a00001": 42})
    appear(live, "a00001")
    await settle(service.cache)

    view = await service.lookup("a00001")

    assert view is service.cache.get("a00001")
    assert view is not None
    assert view.type_code == "B738"


async def test_an_aircraft_that_is_not_live_is_looked_up_from_the_database(
    database: Database, registry: SourceRegistry, service: MetadataService
) -> None:
    """The historical half: an aircraft page for something last seen in March."""
    await seed_aircraft(database, {"a00003": 7})
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await service.update()

    view = await service.lookup("a00003")

    assert service.cache.get("a00003") is None
    assert view is not None
    assert view.type_code == "A320"
    assert view.sighting_count == 7
    assert view.type_count == 1
    assert view.provenance()["registration"] == "mictronics"


async def test_an_observed_aircraft_nobody_has_metadata_for_is_still_found(
    database: Database, service: MetadataService
) -> None:
    """Seen but undescribed is a different answer from never heard of."""
    await seed_aircraft(database, {"beef01": 3})

    view = await service.lookup("beef01")

    assert view is not None
    assert not view.known
    assert view.sighting_count == 3


async def test_an_address_flightsite_knows_nothing_about_looks_up_as_none(
    service: MetadataService,
) -> None:
    assert await service.lookup("beef99") is None


async def test_the_service_exposes_merged_status(
    registry: SourceRegistry, service: MetadataService
) -> None:
    registry.register("mictronics", InMemoryMetadataProvider([record("a00001", type_code="B738")]))
    await service.update()

    statuses = {status.source: status for status in await service.statuses()}

    assert statuses["mictronics"].status.value == "ok"
    assert not statuses["mictronics"].run.running
    assert statuses["mictronics"].run.phase is ImportPhase.DONE


async def test_a_registered_source_that_never_ran_still_reports(
    registry: SourceRegistry, service: MetadataService
) -> None:
    registry.register("faa", InMemoryMetadataProvider())

    statuses = await service.statuses()

    assert [status.source for status in statuses] == ["faa"]
    assert statuses[0].status.value == "never_run"


async def test_a_stored_source_this_build_no_longer_ships_is_still_reported(
    database: Database, service: MetadataService
) -> None:
    """The rows in ``aircraft_metadata`` came from somewhere; say where."""
    from sqlalchemy import text

    async with database.writer_session() as session:
        await session.execute(
            text("INSERT INTO metadata_sources (source, status) VALUES ('gone', 'ok')")
        )

    statuses = await service.statuses()

    assert [status.source for status in statuses] == ["gone"]


class _Clock:
    """A monotonic clock the test drives by hand."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value
