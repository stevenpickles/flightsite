"""The ADR-0006 boundary for airport rows: what is repaired, what is refused.

The line this module tests is the one :mod:`flightsite.airports.records` draws:
a row is *rejected* rather than guessed at when the field is load-bearing, and
degraded to ``None`` when it is not. Getting that backwards in either direction
is a real bug — a rejected row loses an airport, and a repaired coordinate puts
one somewhere it is not.
"""

from __future__ import annotations

import pytest

from flightsite.airports.records import (
    IMPORTED_AIRPORT_TYPES,
    MAX_ELEVATION_FT,
    MIN_ELEVATION_FT,
    AirportRecordError,
    normalize_airport,
    normalize_coordinate,
    normalize_country,
    normalize_elevation,
    normalize_iata,
    normalize_ident,
)


def test_a_whole_row_normalizes() -> None:
    record = normalize_airport(
        ident=" ksea ",
        name="  Seattle-Tacoma   International ",
        type="large_airport",
        lat="47.4502",
        lon="-122.3088",
        iata="sea",
        elevation_ft="433",
        iso_country="us",
        upstream_id="3577",
    )

    assert record.ident == "KSEA"
    # Internal whitespace runs collapse; the name is a display string and
    # "Seattle-Tacoma   International" is the same field.
    assert record.name == "Seattle-Tacoma International"
    assert record.lat == pytest.approx(47.4502)
    assert record.lon == pytest.approx(-122.3088)
    assert record.iata == "SEA"
    assert record.elevation_ft == 433
    assert record.iso_country == "US"
    assert record.upstream_id == 3577


# ------------------------------------------------------------------- idents


@pytest.mark.parametrize("raw", ["ksea", "KSEA", " KSea "])
def test_idents_are_upper_cased(raw: str) -> None:
    """A case split would make one airport two — SQLite compares byte for byte."""
    assert normalize_ident(raw) == "KSEA"


@pytest.mark.parametrize("raw", ["00AK", "CA-0001", "EGLL", "X"])
def test_local_and_gps_idents_are_accepted(raw: str) -> None:
    """`ident` is an ICAO code where one exists and a local code where it is not."""
    assert normalize_ident(raw) == raw.upper()


@pytest.mark.parametrize("raw", ["", "   ", None, "K SEA", "K.SEA", "A" * 13])
def test_an_unusable_ident_is_refused(raw: object) -> None:
    """The one field whose absence makes the row meaningless: it is the key."""
    with pytest.raises(AirportRecordError):
        normalize_ident(raw)


# -------------------------------------------------------------- coordinates


@pytest.mark.parametrize(("raw", "expected"), [("0", 0.0), ("-90", -90.0), ("47.45", 47.45)])
def test_coordinates_parse(raw: str, expected: float) -> None:
    assert normalize_coordinate(raw, limit=90.0, what="latitude") == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", None, "north", "90.1", "-90.1"])
def test_an_unusable_coordinate_is_refused(raw: object) -> None:
    """Refused, never clamped: an airport at the wrong place is worse than none."""
    with pytest.raises(AirportRecordError):
        normalize_coordinate(raw, limit=90.0, what="latitude")


def test_longitude_gets_its_own_limit() -> None:
    assert normalize_coordinate("179.95", limit=180.0, what="longitude") == pytest.approx(179.95)
    with pytest.raises(AirportRecordError):
        normalize_coordinate("180.1", limit=180.0, what="longitude")


# --------------------------------------------------------- optional fields


@pytest.mark.parametrize(("raw", "expected"), [("sea", "SEA"), ("LHR", "LHR")])
def test_iata_codes_are_upper_cased(raw: str, expected: str) -> None:
    assert normalize_iata(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "SEAT", "SE", "S1A"])
def test_a_malformed_iata_code_is_dropped_not_refused(raw: object) -> None:
    """The column exists to be looked up by; a malformed key answers no lookup."""
    assert normalize_iata(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("433", 433), ("433.6", 434), ("-1200", -1200), ("0", 0)],
)
def test_elevations_parse_to_whole_feet(raw: str, expected: int) -> None:
    assert normalize_elevation(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", None, "high", str(MIN_ELEVATION_FT - 1), str(MAX_ELEVATION_FT + 1)],
)
def test_an_implausible_elevation_becomes_unknown(raw: object) -> None:
    """A garbled elevation is not a reason to lose the airport."""
    assert normalize_elevation(raw) is None


@pytest.mark.parametrize(("raw", "expected"), [("us", "US"), ("GB", "GB")])
def test_country_codes_are_upper_cased(raw: str, expected: str) -> None:
    assert normalize_country(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "USA", "U", "U1"])
def test_a_malformed_country_becomes_unknown(raw: object) -> None:
    assert normalize_country(raw) is None


# ---------------------------------------------------------- whole records


@pytest.mark.parametrize("missing", ["name", "type"])
def test_a_row_with_no_name_or_type_is_refused(missing: str) -> None:
    """Both are non-nullable in ``docs/DATA_MODEL.md`` §3.6."""
    fields: dict[str, object] = {
        "ident": "KSEA",
        "name": "Seattle-Tacoma",
        "type": "large_airport",
        "lat": "47.45",
        "lon": "-122.31",
    }
    fields[missing] = "   "

    with pytest.raises(AirportRecordError):
        normalize_airport(**fields)  # type: ignore[arg-type]


def test_a_row_with_no_upstream_id_still_normalizes() -> None:
    """The surrogate id is a convenience; the sink numbers a row that lacks one."""
    record = normalize_airport(
        ident="KSEA",
        name="Seattle-Tacoma",
        type="large_airport",
        lat="47.45",
        lon="-122.31",
        upstream_id="not-a-number",
    )

    assert record.upstream_id is None


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_a_row_with_no_upstream_id_at_all_normalizes(raw: object) -> None:
    """The id is a convenience; the sink numbers a row that lacks one."""
    record = normalize_airport(
        ident="KSEA",
        name="Seattle-Tacoma",
        type="large_airport",
        lat="47.45",
        lon="-122.31",
        upstream_id=raw,
    )

    assert record.upstream_id is None


def test_the_imported_type_filter_is_exactly_the_four_documented_kinds() -> None:
    """Closed fields, seaplane bases and balloonports stay out — see the module.

    Pinned as a test because the choice is a judgement about what FlightSite
    will *claim*, not an implementation detail: naming a closed runway as the
    airport an aircraft is arriving at would be a confident falsehood.
    """
    assert {
        "large_airport",
        "medium_airport",
        "small_airport",
        "heliport",
    } == IMPORTED_AIRPORT_TYPES
    for excluded in ("closed", "seaplane_base", "balloonport"):
        assert excluded not in IMPORTED_AIRPORT_TYPES
