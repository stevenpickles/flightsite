"""Emitter category, selected altitude and the decoder's emergency state.

Roadmap slice 086 (issue #229): three readsb fields FlightSite used to discard
now reach the domain update. Each is optional, each is validated at the edge
so nothing downstream has to defend against junk, and each is simply ``None``
on the legacy dump1090-fa field set, which never carried it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from flightsite.ingest.readsb import parse_document
from flightsite.ingest.types import AircraftStateBatch, AircraftStateUpdate

RECEIVED_AT = datetime(2030, 1, 1, tzinfo=UTC)
NOW = 1_758_124_800.0


def one(entry: dict[str, Any]) -> AircraftStateUpdate:
    """Normalize a single-aircraft document and return its only update."""
    batch = parse_document(
        {"now": NOW, "aircraft": [{"hex": "4ca87c", **entry}]}, received_at=RECEIVED_AT
    )
    assert len(batch) == 1, "a bad optional field must never cost the aircraft"
    return batch[0]


def by_icao(batch: AircraftStateBatch) -> dict[str, AircraftStateUpdate]:
    return {update.icao: update for update in batch}


# ------------------------------------------------------------ the fixtures


def test_readsb_fixture_carries_all_three(readsb_document: Any) -> None:
    updates = by_icao(parse_document(readsb_document, received_at=RECEIVED_AT))

    cruising = updates["4ca87c"]
    assert cruising.emitter_category == "A3"
    assert cruising.selected_altitude_ft == 36000.0
    # `"emergency": "none"` is the decoder saying there is no emergency.
    assert cruising.decoder_emergency is None

    squawking = updates["a7c3f1"]
    assert squawking.emitter_category == "A1"
    assert squawking.decoder_emergency == "general"
    assert squawking.selected_altitude_ft is None


def test_dump1090fa_modern_fixture_carries_them_too(dump1090fa_document: Any) -> None:
    update = by_icao(parse_document(dump1090fa_document, received_at=RECEIVED_AT))["a0f1b4"]

    assert update.emitter_category == "A3"
    assert update.selected_altitude_ft == 34000.0
    assert update.decoder_emergency is None


def test_legacy_dump1090fa_has_none_of_them(dump1090fa_legacy_document: Any) -> None:
    batch = parse_document(dump1090fa_legacy_document, received_at=RECEIVED_AT)

    assert len(batch) == 4
    for update in batch:
        assert update.emitter_category is None
        assert update.selected_altitude_ft is None
        assert update.decoder_emergency is None


# ------------------------------------------------------- emitter category


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A3", "A3"),
        ("A7", "A7"),
        ("B6", "B6"),
        ("C1", "C1"),
        ("D7", "D7"),
        ("A0", "A0"),
        ("a5", "A5"),
        (" B1 ", "B1"),
    ],
)
def test_well_formed_categories_pass_through(raw: str, expected: str) -> None:
    assert one({"category": raw}).emitter_category == expected


@pytest.mark.parametrize(
    "raw", ["E1", "A8", "A", "A33", "", "3A", 7, None, ["A3"], {"cat": "A3"}, True]
)
def test_malformed_categories_are_dropped(raw: object) -> None:
    assert one({"category": raw}).emitter_category is None


def test_absent_category_is_none() -> None:
    assert one({}).emitter_category is None


# ------------------------------------------------------ selected altitude


def test_mcp_selected_altitude_is_preferred_over_fms() -> None:
    update = one({"nav_altitude_mcp": 24000, "nav_altitude_fms": 37000})

    assert update.selected_altitude_ft == 24000.0


def test_fms_selected_altitude_is_the_fallback() -> None:
    assert one({"nav_altitude_fms": 37000}).selected_altitude_ft == 37000.0


def test_an_implausible_mcp_value_falls_back_to_fms() -> None:
    update = one({"nav_altitude_mcp": 250_000, "nav_altitude_fms": 11000})

    assert update.selected_altitude_ft == 11000.0


@pytest.mark.parametrize("raw", [250_000, -5_000, "high", None, True, float("nan")])
def test_implausible_selected_altitudes_are_dropped(raw: object) -> None:
    update = one({"nav_altitude_mcp": raw, "nav_altitude_fms": raw})

    assert update.selected_altitude_ft is None


def test_absent_selected_altitude_is_none() -> None:
    assert one({}).selected_altitude_ft is None


# ------------------------------------------------------- emergency state


@pytest.mark.parametrize("raw", ["general", "lifeguard", "minfuel", "nordo", "unlawful", "downed"])
def test_every_declared_emergency_passes_through(raw: str) -> None:
    assert one({"emergency": raw}).decoder_emergency == raw


def test_emergency_state_is_case_insensitive() -> None:
    assert one({"emergency": "NORDO"}).decoder_emergency == "nordo"


@pytest.mark.parametrize("raw", ["none", "reserved", "mayday", "", 7, None, ["nordo"], False])
def test_no_emergency_reserved_and_junk_are_none(raw: object) -> None:
    assert one({"emergency": raw}).decoder_emergency is None


def test_decoder_emergency_is_independent_of_the_squawk() -> None:
    """The acceptance case: `nordo` with an ordinary squawk is still `nordo`."""
    update = one({"emergency": "nordo", "squawk": "2341"})

    assert update.decoder_emergency == "nordo"
    assert update.squawk == "2341"


# ------------------------------------------------------- domain invariants


def test_the_domain_type_refuses_a_malformed_category() -> None:
    with pytest.raises(ValueError, match="emitter_category"):
        AircraftStateUpdate(icao="4ca87c", timestamp=RECEIVED_AT, emitter_category="Z9")


def test_the_domain_type_refuses_an_unknown_emergency() -> None:
    with pytest.raises(ValueError, match="decoder_emergency"):
        AircraftStateUpdate(
            icao="4ca87c",
            timestamp=RECEIVED_AT,
            decoder_emergency="mayday",  # type: ignore[arg-type]
        )
