"""Classification on the live path: computed once, off the hot path, and current.

Three properties, and they pull against each other, which is why they get their
own file:

* the API must be able to read a classification **without any I/O**, so it is
  computed when the cache entry is built;
* a callsign is the one classification input that changes during a flight, so a
  cached classification must **follow it**;
* and neither of those may put a database read back on the live path.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flightsite.classification.vocabulary import ClaimSource, Confidence, MissionCategory
from flightsite.db import Database
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.cache import MetadataCache
from tests.metadata.conftest import IMPORT_MS, record, settle
from tests.metadata.provider import InMemoryMetadataProvider

FLEET = [
    record("ae1463", operator_name="United States Air Force", type_code="C17", military_flag=True),
    record("a1b2c3", operator_name="Delta Air Lines", type_code="B739"),
    record("a44444", operator_name="Travis County Sheriff", type_code="EC45"),
    # An airliner type with no operator: the aircraft a callsign can improve.
    record("a88888", registration="N99999", type_code="B738"),
]


def _update(icao: str, *, callsign: str | None = None) -> AircraftStateUpdate:
    return AircraftStateUpdate(
        icao=icao,
        timestamp=datetime.fromtimestamp(IMPORT_MS / 1000, tz=UTC),
        position_source="adsb",
        position=Position(latitude=51.0, longitude=-1.0),
        altitude_ft=30_000.0,
        callsign=callsign,
    )


def _observe(live: LiveStore, icao: str, *, callsign: str | None = None) -> None:
    live.apply_updates([_update(icao, callsign=callsign)])


@pytest.fixture
async def populated(importer: MetadataImporter, registry: SourceRegistry) -> None:
    registry.register("mictronics", InMemoryMetadataProvider(FLEET))
    await importer.run()


@pytest.fixture
async def cache(database: Database, live: LiveStore) -> MetadataCache:
    return MetadataCache(database=database, live=live)


# -------------------------------------------------------------- population


async def test_an_entry_carries_its_classification_and_its_group(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    await cache.start()
    try:
        _observe(live, "ae1463")
        await settle(cache)

        view = cache.get("ae1463")
        assert view is not None
        assert view.classification.military is True
        assert view.classification.mission is MissionCategory.MILITARY
        assert view.classification.source is ClaimSource.MICTRONICS
        assert view.operator_group == "US Military"
    finally:
        await cache.stop()


async def test_an_unresolved_aircraft_has_a_complete_unknown_classification(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """Never ``None``: "we looked and found nothing" is an answer, not an absence."""
    await cache.start()
    try:
        _observe(live, "beef01")
        await settle(cache)

        view = cache.get("beef01")
        assert view is not None
        assert view.known is False
        assert view.classification.is_unknown
        assert view.operator_group is None
    finally:
        await cache.stop()


async def test_the_provenance_map_names_classification_and_grouping_as_ours(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """``docs/API.md`` §2.6 exists so a reader can tell a claim's owner."""
    await cache.start()
    try:
        _observe(live, "a44444")
        await settle(cache)

        view = cache.get("a44444")
        assert view is not None
        provenance = view.provenance()
        assert provenance["operator"] == "mictronics"
        assert provenance["classification"] == ClaimSource.HEURISTIC.value
        assert provenance["operator_group"] == "derived"
    finally:
        await cache.stop()


async def test_an_unknown_classification_contributes_no_provenance_entry(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    await cache.start()
    try:
        _observe(live, "a88888")
        await settle(cache)

        view = cache.get("a88888")
        assert view is not None
        assert "classification" not in view.provenance()
        assert "operator_group" not in view.provenance()
    finally:
        await cache.stop()


# ---------------------------------------------------------------- callsigns


async def test_a_callsign_present_at_appear_is_classified_with_the_entry(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    await cache.start()
    try:
        _observe(live, "a88888", callsign="UAL2201")
        await settle(cache)

        view = cache.get("a88888")
        assert view is not None
        assert view.classification.mission is MissionCategory.COMMERCIAL_PASSENGER
        assert view.classification.confidence is Confidence.LOW
    finally:
        await cache.stop()


async def test_a_callsign_arriving_later_is_folded_in(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """The one input that moves mid-flight, and the reason the cache keeps evidence."""
    await cache.start()
    try:
        _observe(live, "a88888")
        await settle(cache)
        before = cache.get("a88888")
        assert before is not None and before.classification.is_unknown
        populations = cache.populations

        _observe(live, "a88888", callsign="UAL2201")
        await settle(cache)

        after = cache.get("a88888")
        assert after is not None
        assert after.classification.mission is MissionCategory.COMMERCIAL_PASSENGER
        # Reclassification is pure memory: no second read of the database.
        assert cache.populations == populations
    finally:
        await cache.stop()


async def test_a_changed_callsign_replaces_the_previous_inference(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    await cache.start()
    try:
        _observe(live, "a88888", callsign="UAL2201")
        await settle(cache)

        _observe(live, "a88888", callsign="FDX1234")
        await settle(cache)

        view = cache.get("a88888")
        assert view is not None
        assert view.classification.mission is MissionCategory.CARGO
    finally:
        await cache.stop()


async def test_a_callsign_never_displaces_a_metadata_classification(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    """Tier one wins: the operator says what this is, whatever it files as."""
    await cache.start()
    try:
        _observe(live, "a1b2c3", callsign="FDX1234")
        await settle(cache)

        view = cache.get("a1b2c3")
        assert view is not None
        assert view.classification.mission is MissionCategory.COMMERCIAL_PASSENGER
        assert view.classification.confidence is Confidence.HIGH
    finally:
        await cache.stop()


async def test_an_observation_that_does_not_change_the_callsign_changes_nothing(
    populated: None, cache: MetadataCache, live: LiveStore
) -> None:
    await cache.start()
    try:
        _observe(live, "a1b2c3", callsign="DAL1")
        await settle(cache)
        first = cache.get("a1b2c3")

        _observe(live, "a1b2c3", callsign="DAL1")
        await settle(cache)

        assert cache.get("a1b2c3") == first
    finally:
        await cache.stop()


# -------------------------------------------------------- refresh and recovery


async def test_an_invalidated_cache_reclassifies_against_the_new_dataset(
    populated: None,
    cache: MetadataCache,
    live: LiveStore,
    importer: MetadataImporter,
    registry: SourceRegistry,
) -> None:
    """A new import can change any claim; the live set must not keep the old one."""
    await cache.start()
    try:
        _observe(live, "a1b2c3")
        await settle(cache)
        assert cache.get("a1b2c3") is not None

        registry.get("mictronics").provider.records = [  # type: ignore[attr-defined]
            record("a1b2c3", operator_name="Federal Express Corp", type_code="B763")
        ]
        await importer.run()
        await cache.invalidate()

        view = cache.get("a1b2c3")
        assert view is not None
        assert view.classification.mission is MissionCategory.CARGO
        assert view.operator_group == "FedEx Express"
    finally:
        await cache.stop()


async def test_an_overflowed_subscription_reclassifies_what_it_kept(
    populated: None, database: Database, live: LiveStore
) -> None:
    """A shed event may have hidden a callsign, so the snapshot decides."""
    cache = MetadataCache(database=database, live=live, queue_size=1)
    await cache.start()
    try:
        _observe(live, "a88888")
        await settle(cache)
        assert cache.get("a88888") is not None

        # Overflow the subscription: several events, one queue slot.
        for _ in range(4):
            _observe(live, "a88888", callsign="UAL2201")
            _observe(live, "a1b2c3")
        await settle(cache)

        view = cache.get("a88888")
        assert view is not None
        assert view.classification.mission is MissionCategory.COMMERCIAL_PASSENGER
    finally:
        await cache.stop()
