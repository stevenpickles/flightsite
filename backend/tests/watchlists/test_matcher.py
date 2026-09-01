"""``WatchlistMatcher``: matching per entry kind, index rebuild, and eviction.

Built directly against :class:`AircraftMetadataView` — the shape
:class:`~flightsite.metadata.cache.MetadataCache` hands to
:meth:`~flightsite.watchlists.matcher.WatchlistMatcher.on_resolved` — so these
tests exercise the matching logic itself without needing a running cache or
live store (that end-to-end wiring is
``tests/watchlists/test_cache_integration.py``).
"""

from __future__ import annotations

from flightsite.classification.model import Claim, Classification, Evidence
from flightsite.classification.vocabulary import (
    ClaimSource,
    Confidence,
    EvidenceBasis,
    MissionCategory,
)
from flightsite.metadata.cache import AircraftMetadataView
from flightsite.metadata.precedence import ResolvedMetadata
from flightsite.watchlists.matcher import WatchlistIndex, WatchlistMatcher
from flightsite.watchlists.model import WatchlistEntryRecord
from flightsite.watchlists.vocabulary import WatchlistEntryKind

WATCHLIST_NAMES = {1: "Police Helicopters", 2: "Rare Types"}


def match(
    index: WatchlistIndex,
    icao24: str,
    *,
    registration: str | None = None,
    type_code: str | None = None,
    operator: str | None = None,
    category: str | None = None,
) -> tuple[str, ...]:
    """``index.match`` with every field but ``icao24`` defaulted to unset."""
    return index.match(
        icao24=icao24,
        registration=registration,
        type_code=type_code,
        operator=operator,
        category=category,
    )


def entry(
    watchlist_id: int, kind: WatchlistEntryKind, value: str, entry_id: int = 1
) -> WatchlistEntryRecord:
    return WatchlistEntryRecord(
        id=entry_id, watchlist_id=watchlist_id, kind=kind, value=value, note=None, created_ms=0
    )


def _mission_claim(category: MissionCategory) -> Claim:
    return Claim(
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.TYPE_CODE,
        confidence=Confidence.MEDIUM,
        detail=f"test claim for {category.value}",
    )


def view(
    icao: str,
    *,
    registration: str | None = None,
    type_code: str | None = None,
    operator: str | None = None,
    mission: MissionCategory = MissionCategory.UNKNOWN,
) -> AircraftMetadataView:
    """A resolved view with just the fields matching cares about."""
    metadata = None
    if registration is not None or type_code is not None or operator is not None:
        metadata = ResolvedMetadata(
            icao24=icao,
            updated_ms=0,
            registration=registration,
            type_code=type_code,
            operator_name=operator,
        )
    classification = (
        Classification()
        if mission is MissionCategory.UNKNOWN
        else Classification(mission=mission, mission_claim=_mission_claim(mission))
    )
    return AircraftMetadataView(
        icao24=icao,
        metadata=metadata,
        evidence=Evidence(icao24=icao),
        classification=classification,
    )


# --------------------------------------------------------------- per kind


def test_matches_by_icao24() -> None:
    index = WatchlistIndex.build([entry(1, WatchlistEntryKind.ICAO24, "ae1463")], WATCHLIST_NAMES)

    assert match(index, "ae1463") == ("Police Helicopters",)
    assert match(index, "ae1464") == ()


def test_matches_by_registration() -> None:
    index = WatchlistIndex.build(
        [entry(1, WatchlistEntryKind.REGISTRATION, "N12345")], WATCHLIST_NAMES
    )

    assert match(index, "beef01", registration="N12345") == ("Police Helicopters",)


def test_matches_by_type_code() -> None:
    index = WatchlistIndex.build([entry(2, WatchlistEntryKind.TYPE_CODE, "EC35")], WATCHLIST_NAMES)

    assert match(index, "beef01", type_code="EC35") == ("Rare Types",)


def test_matches_by_operator() -> None:
    index = WatchlistIndex.build(
        [entry(1, WatchlistEntryKind.OPERATOR, "METROPOLITAN POLICE")], WATCHLIST_NAMES
    )

    assert match(index, "beef01", operator="METROPOLITAN POLICE") == ("Police Helicopters",)


def test_matches_by_category() -> None:
    index = WatchlistIndex.build(
        [entry(1, WatchlistEntryKind.CATEGORY, "military")], WATCHLIST_NAMES
    )

    assert match(index, "beef01", category="military") == ("Police Helicopters",)


def test_an_aircraft_matching_no_entry_gets_nothing() -> None:
    index = WatchlistIndex.build([entry(1, WatchlistEntryKind.ICAO24, "ae1463")], WATCHLIST_NAMES)

    assert match(index, "000000") == ()


def test_matches_from_two_different_watchlists_are_both_reported() -> None:
    entries = [
        entry(1, WatchlistEntryKind.ICAO24, "ae1463", entry_id=1),
        entry(2, WatchlistEntryKind.ICAO24, "ae1463", entry_id=2),
    ]
    index = WatchlistIndex.build(entries, WATCHLIST_NAMES)

    assert match(index, "ae1463") == ("Police Helicopters", "Rare Types")


def test_an_entry_naming_a_deleted_watchlist_is_skipped() -> None:
    index = WatchlistIndex.build([entry(999, WatchlistEntryKind.ICAO24, "ae1463")], WATCHLIST_NAMES)

    assert match(index, "ae1463") == ()


# ----------------------------------------------------------- case folding


def test_registration_matching_is_case_insensitive_through_the_matcher() -> None:
    """The stored value is upper-case; a source that supplied lower-case still matches."""
    matcher = WatchlistMatcher()
    matcher.reload([entry(1, WatchlistEntryKind.REGISTRATION, "N12345")], WATCHLIST_NAMES)

    matcher.on_resolved("beef01", view("beef01", registration="n12345"))

    assert matcher.matches("beef01") == ("Police Helicopters",)


def test_a_mission_of_unknown_never_matches_a_category_entry() -> None:
    matcher = WatchlistMatcher()
    matcher.reload([entry(1, WatchlistEntryKind.CATEGORY, "military")], WATCHLIST_NAMES)

    matcher.on_resolved("beef01", view("beef01"))

    assert matcher.matches("beef01") == ()


# ------------------------------------------------------------- the matcher


def test_matches_is_empty_for_an_aircraft_never_resolved() -> None:
    matcher = WatchlistMatcher()

    assert matcher.matches("beef01") == ()


def test_on_resolved_installs_and_computes_matches() -> None:
    matcher = WatchlistMatcher()
    matcher.reload([entry(1, WatchlistEntryKind.ICAO24, "ae1463")], WATCHLIST_NAMES)

    matcher.on_resolved("ae1463", view("ae1463"))

    assert matcher.matches("ae1463") == ("Police Helicopters",)
    assert matcher.live_count == 1


def test_on_resolved_with_none_evicts_the_aircraft() -> None:
    matcher = WatchlistMatcher()
    matcher.reload([entry(1, WatchlistEntryKind.ICAO24, "ae1463")], WATCHLIST_NAMES)
    matcher.on_resolved("ae1463", view("ae1463"))

    matcher.on_resolved("ae1463", None)

    assert matcher.matches("ae1463") == ()
    assert matcher.live_count == 0


def test_reload_recomputes_every_tracked_aircraft_with_no_new_view() -> None:
    """A CRUD change updates existing live aircraft without a fresh resolution."""
    matcher = WatchlistMatcher()
    matcher.on_resolved("ae1463", view("ae1463"))
    assert matcher.matches("ae1463") == ()

    matcher.reload([entry(1, WatchlistEntryKind.ICAO24, "ae1463")], WATCHLIST_NAMES)

    assert matcher.matches("ae1463") == ("Police Helicopters",)


def test_reload_can_also_remove_a_match_when_an_entry_is_deleted() -> None:
    matcher = WatchlistMatcher()
    matcher.reload([entry(1, WatchlistEntryKind.ICAO24, "ae1463")], WATCHLIST_NAMES)
    matcher.on_resolved("ae1463", view("ae1463"))
    assert matcher.matches("ae1463") == ("Police Helicopters",)

    matcher.reload([], WATCHLIST_NAMES)

    assert matcher.matches("ae1463") == ()


def test_reload_before_any_resolution_leaves_nothing_to_recompute() -> None:
    matcher = WatchlistMatcher()

    matcher.reload([entry(1, WatchlistEntryKind.ICAO24, "ae1463")], WATCHLIST_NAMES)

    assert matcher.matches("ae1463") == ()
    assert matcher.live_count == 0


def test_index_property_exposes_the_currently_loaded_index() -> None:
    matcher = WatchlistMatcher()

    matcher.reload([entry(1, WatchlistEntryKind.ICAO24, "ae1463")], WATCHLIST_NAMES)

    assert matcher.index.entry_value_count == 1
