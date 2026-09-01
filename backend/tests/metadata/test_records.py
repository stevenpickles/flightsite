"""Normalization at the provider boundary (ADR-0006).

The boundary's job is that two spellings of one airframe can never become two
airframes, and that a source saying nothing can never look like a source saying
something.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.metadata.records import (
    MIN_MANUFACTURE_YEAR,
    NormalizedAircraftRecord,
    RecordError,
    SourceArtifact,
    ValidationReport,
    normalize_icao24,
    normalize_record,
    normalize_text,
    normalize_year,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A0B1C2", "a0b1c2"),
        ("a0b1c2", "a0b1c2"),
        ("  A0B1C2  ", "a0b1c2"),
        ("0xA0B1C2", "a0b1c2"),
        ("~a0b1c2", "a0b1c2"),
    ],
)
def test_addresses_canonicalize_to_lowercase_hex(raw: str, expected: str) -> None:
    """The spellings real datasets use, all landing on one key."""
    assert normalize_icao24(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "zzzzzz", "a0b1c", "a0b1c22", "N302DN"])
def test_an_unusable_address_is_refused_not_repaired(raw: str) -> None:
    with pytest.raises(RecordError):
        normalize_icao24(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Delta Air Lines", "Delta Air Lines"),
        ("  Delta  Air   Lines  ", "Delta Air Lines"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_text_collapses_whitespace_and_empties_to_none(raw: object, expected: str | None) -> None:
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(2016, 2016), ("2016", 2016), (" 2016 ", 2016), ("", None), ("n/a", None), (1800, None)],
)
def test_a_garbled_year_is_dropped_rather_than_failing_the_row(
    raw: object, expected: int | None
) -> None:
    """A registry with a bad year is still worth its registration and owner."""
    assert normalize_year(raw) == expected


def test_the_year_floor_is_before_powered_flight() -> None:
    assert normalize_year(MIN_MANUFACTURE_YEAR) == MIN_MANUFACTURE_YEAR
    assert normalize_year(MIN_MANUFACTURE_YEAR - 1) is None


def test_type_designators_are_upper_cased() -> None:
    """Type is what rarity and type statistics group by; case would split it."""
    assert normalize_record(icao24="a0b1c2", type_code=" b738 ").type_code == "B738"


def test_a_normalized_record_keeps_every_field_it_was_given() -> None:
    result = normalize_record(
        icao24="A0B1C2",
        registration=" N302DN ",
        type_code="b739",
        model="Boeing 737-900ER",
        manufacture_year="2016",
        operator_name="Delta  Air  Lines",
        owner="Delta Air Lines Inc",
        military_flag=False,
        flags={"source_row": 12},
    )

    assert result == NormalizedAircraftRecord(
        icao24="a0b1c2",
        registration="N302DN",
        type_code="B739",
        model="Boeing 737-900ER",
        manufacture_year=2016,
        operator_name="Delta Air Lines",
        owner="Delta Air Lines Inc",
        military_flag=False,
        flags={"source_row": 12},
    )


def test_flags_serialize_deterministically() -> None:
    """Sorted keys, so an unchanged snapshot produces identical rows."""
    record = normalize_record(icao24="a0b1c2", flags={"b": 2, "a": 1})

    assert record.flags_json() == '{"a":1,"b":2}'


def test_no_flags_serialize_to_null() -> None:
    assert normalize_record(icao24="a0b1c2").flags_json() is None


def test_a_missing_field_is_none_not_a_default() -> None:
    """SPEC §39: FlightSite never substitutes a guess for a null."""
    record = normalize_record(icao24="a0b1c2")

    assert record.registration is None
    assert record.military_flag is None


def test_a_rejected_validation_report_must_give_a_reason() -> None:
    with pytest.raises(ValueError, match="must give a reason"):
        ValidationReport.rejected()


def test_a_rejection_reason_joins_every_error() -> None:
    report = ValidationReport.rejected("not JSON", "no rows")

    assert not report.ok
    assert report.reason() == "not JSON; no rows"


def test_an_accepted_report_can_still_carry_warnings() -> None:
    report = ValidationReport.accepted(expected_rows=10, warnings=["3 rows had no type"])

    assert report.ok
    assert report.warnings == ("3 rows had no type",)
    assert report.expected_rows == 10


def test_an_artifact_describes_itself_for_logs() -> None:
    artifact = SourceArtifact(path=Path("snapshot.json"), version="2026-08-31", size_bytes=1024)

    assert artifact.describe() == "2026-08-31 (1024 bytes)"
