"""Normalization and validation per entry kind, and the cross-check against
``docs/DATA_MODEL.md`` §4.1's ``watchlist_entries.kind`` ``CHECK`` constraint.
"""

from __future__ import annotations

import re

import pytest

from flightsite.classification.vocabulary import MissionCategory
from flightsite.db.models import WATCHLIST_ENTRY_KIND_CHECK
from flightsite.watchlists.vocabulary import (
    MAX_NOTE_LENGTH,
    MAX_VALUE_LENGTH,
    VALID_CATEGORY_VALUES,
    WatchlistEntryKind,
    WatchlistValueError,
    normalize_and_validate,
    normalize_description,
    normalize_note,
    normalize_watchlist_name,
)


def _quoted_values(check: str) -> set[str]:
    inner = check.split("(", 1)[1].rstrip(")")
    return set(re.findall(r"'([^']*)'", inner))


def test_the_runtime_enum_matches_the_database_check_constraint() -> None:
    """The two vocabularies cannot import each other (see both modules'
    docstrings), so this is what catches them drifting apart."""
    assert _quoted_values(WATCHLIST_ENTRY_KIND_CHECK) == {kind.value for kind in WatchlistEntryKind}


def test_category_vocabulary_excludes_unknown() -> None:
    assert MissionCategory.UNKNOWN.value not in VALID_CATEGORY_VALUES
    assert {
        category.value for category in MissionCategory if category is not MissionCategory.UNKNOWN
    } == VALID_CATEGORY_VALUES


# ------------------------------------------------------------- icao24


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("ae1463", "ae1463"), ("AE1463", "ae1463"), ("  ae1463  ", "ae1463")],
)
def test_icao24_normalizes_to_lower_case(raw: str, expected: str) -> None:
    assert normalize_and_validate(WatchlistEntryKind.ICAO24, raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "ae146", "ae14633", "zzzzzz", "ae146g"])
def test_icao24_rejects_the_wrong_shape(raw: str) -> None:
    with pytest.raises(WatchlistValueError):
        normalize_and_validate(WatchlistEntryKind.ICAO24, raw)


# --------------------------------------------------------- registration


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("n12345", "N12345"), ("g-abcd", "G-ABCD"), (" vh-abc ", "VH-ABC")],
)
def test_registration_normalizes_to_upper_case(raw: str, expected: str) -> None:
    assert normalize_and_validate(WatchlistEntryKind.REGISTRATION, raw) == expected


@pytest.mark.parametrize("raw", ["", "-abc", "abc-", "a" * 20])
def test_registration_rejects_the_wrong_shape(raw: str) -> None:
    with pytest.raises(WatchlistValueError):
        normalize_and_validate(WatchlistEntryKind.REGISTRATION, raw)


# ----------------------------------------------------------- type_code


@pytest.mark.parametrize(("raw", "expected"), [("b738", "B738"), (" a320 ", "A320")])
def test_type_code_normalizes_to_upper_case(raw: str, expected: str) -> None:
    assert normalize_and_validate(WatchlistEntryKind.TYPE_CODE, raw) == expected


@pytest.mark.parametrize("raw", ["", "b", "b7380000"])
def test_type_code_rejects_the_wrong_shape(raw: str) -> None:
    with pytest.raises(WatchlistValueError):
        normalize_and_validate(WatchlistEntryKind.TYPE_CODE, raw)


# ------------------------------------------------------------- operator


def test_operator_normalizes_to_upper_case_free_text() -> None:
    assert (
        normalize_and_validate(WatchlistEntryKind.OPERATOR, "  Delta Air Lines  ")
        == "DELTA AIR LINES"
    )


def test_operator_rejects_blank() -> None:
    with pytest.raises(WatchlistValueError):
        normalize_and_validate(WatchlistEntryKind.OPERATOR, "   ")


def test_operator_rejects_over_length() -> None:
    with pytest.raises(WatchlistValueError):
        normalize_and_validate(WatchlistEntryKind.OPERATOR, "x" * (MAX_VALUE_LENGTH + 1))


# ------------------------------------------------------------- category


def test_category_normalizes_to_lower_case() -> None:
    assert normalize_and_validate(WatchlistEntryKind.CATEGORY, "MILITARY") == "military"


def test_category_accepts_every_valid_value() -> None:
    for value in VALID_CATEGORY_VALUES:
        assert normalize_and_validate(WatchlistEntryKind.CATEGORY, value) == value


def test_category_rejects_unknown() -> None:
    with pytest.raises(WatchlistValueError, match="must be one of"):
        normalize_and_validate(WatchlistEntryKind.CATEGORY, "unknown")


def test_category_rejects_a_value_outside_the_vocabulary() -> None:
    with pytest.raises(WatchlistValueError):
        normalize_and_validate(WatchlistEntryKind.CATEGORY, "spaceship")


# ----------------------------------------------------------------- note


def test_note_trims_and_passes_through() -> None:
    assert normalize_note("  keep an eye on this one  ") == "keep an eye on this one"


def test_note_blank_becomes_none() -> None:
    assert normalize_note("   ") is None
    assert normalize_note(None) is None


def test_note_rejects_over_length() -> None:
    with pytest.raises(WatchlistValueError):
        normalize_note("x" * (MAX_NOTE_LENGTH + 1))


# ------------------------------------------------------- name / description


def test_watchlist_name_trims() -> None:
    assert normalize_watchlist_name("  Local Police  ") == "Local Police"


def test_watchlist_name_rejects_blank() -> None:
    with pytest.raises(WatchlistValueError):
        normalize_watchlist_name("   ")


def test_watchlist_name_rejects_over_length() -> None:
    with pytest.raises(WatchlistValueError, match="at most"):
        normalize_watchlist_name("x" * 200)


def test_watchlist_description_blank_becomes_none() -> None:
    assert normalize_description("  ") is None
    assert normalize_description(None) is None
