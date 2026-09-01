"""The eligibility matrix: who gets looked up, and under what key.

The most consequential table in the slice. A false negative here costs one
missing route; a false positive spends a request against the user's quota every
time that aircraft is seen, forever, for a callsign no schedule exists for. So
the cases are enumerated rather than sampled.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from flightsite.classification.operators import CALLSIGN_PATTERN
from flightsite.enrichment.policy import (
    MAX_CALLSIGN_LENGTH,
    airline_designator,
    cache_key,
    eligible_callsign,
    normalize_callsign,
)

ELIGIBLE = [
    pytest.param("DAL1234", "DAL1234", id="airline-flight"),
    pytest.param("BAW15", "BAW15", id="short-flight-number"),
    pytest.param("RCH492", "RCH492", id="air-mobility-command-is-the-icao-form"),
    pytest.param("UAL1A", "UAL1A", id="alphanumeric-suffix"),
    pytest.param("  dal1234 ", "DAL1234", id="padded-and-lower-cased"),
    pytest.param("SWA2495", "SWA2495", id="four-digit-number"),
]

INELIGIBLE = [
    pytest.param(None, id="absent"),
    pytest.param("", id="empty"),
    pytest.param("        ", id="all-padding"),
    pytest.param("N738AB", id="us-registration-flown-as-a-callsign"),
    pytest.param("GABCD", id="uk-registration"),
    pytest.param("VADER11", id="tactical-callsign"),
    pytest.param("BLKCT2", id="tactical-callsign-with-digits"),
    pytest.param("DAL", id="designator-with-no-flight-number"),
    pytest.param("D", id="single-character-fragment"),
    pytest.param("1234", id="digits-only"),
    pytest.param("DA1234", id="two-letter-designator"),
    pytest.param("DALT123", id="four-letter-prefix"),
    pytest.param("DAL-1234", id="punctuation"),
    pytest.param("DAL123456789", id="longer-than-a-flight-id-field"),
]


@pytest.mark.parametrize(("raw", "expected"), ELIGIBLE)
def test_icao_airline_callsigns_are_eligible(raw: str, expected: str) -> None:
    assert eligible_callsign(raw) == expected


@pytest.mark.parametrize("raw", INELIGIBLE)
def test_everything_else_is_not(raw: str | None) -> None:
    """A callsign that is not the ICAO flight form is never asked about."""
    assert eligible_callsign(raw) is None


def test_eligibility_is_the_classification_pattern() -> None:
    """One definition of "airline flight", reused rather than restated.

    :mod:`flightsite.classification.operators` already answers this question to
    match an operator group; two copies of the answer would drift.
    """
    for raw, expected in [(param.values[0], param.values[1]) for param in ELIGIBLE]:
        assert CALLSIGN_PATTERN.match(str(expected)) is not None
        assert eligible_callsign(str(raw)) == expected


def test_normalization_upper_cases_and_strips() -> None:
    assert normalize_callsign("  dal1234  ") == "DAL1234"


def test_normalization_rejects_an_over_long_field() -> None:
    """Eight characters is the ADS-B flight-id field; longer is an artifact."""
    assert normalize_callsign("A" * MAX_CALLSIGN_LENGTH) == "A" * MAX_CALLSIGN_LENGTH
    assert normalize_callsign("A" * (MAX_CALLSIGN_LENGTH + 1)) is None


def test_normalization_of_nothing_is_nothing() -> None:
    assert normalize_callsign(None) is None
    assert normalize_callsign("   ") is None


def test_the_designator_is_the_first_three_letters() -> None:
    assert airline_designator("DAL1234") == "DAL"


def test_a_callsign_that_is_not_the_form_has_no_designator() -> None:
    assert airline_designator("N738AB") is None


def test_the_cache_key_is_the_callsign_and_the_utc_day() -> None:
    at = datetime(2026, 8, 30, 22, 14, 31, tzinfo=UTC)

    assert cache_key("DAL1234", at) == "DAL1234:2026-08-30"


def test_two_observations_of_one_flight_share_a_key() -> None:
    """The whole point: one request per flight per day, not per sighting."""
    morning = datetime(2026, 8, 30, 6, 0, tzinfo=UTC)
    evening = datetime(2026, 8, 30, 23, 59, tzinfo=UTC)

    assert cache_key("DAL1234", morning) == cache_key("DAL1234", evening)


def test_the_same_flight_number_tomorrow_is_a_different_key() -> None:
    """A flight number is a fact about a *day*; the key says so."""
    today = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    tomorrow = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    assert cache_key("DAL1234", today) != cache_key("DAL1234", tomorrow)


def test_a_non_utc_timestamp_is_bucketed_by_its_utc_day() -> None:
    """Two zones either side of local midnight still share one UTC key."""
    tokyo = datetime(2026, 8, 31, 7, 0, tzinfo=timezone(timedelta(hours=9)))

    assert cache_key("DAL1234", tokyo) == "DAL1234:2026-08-30"


def test_a_naive_timestamp_is_refused() -> None:
    """The same rule the storage layer applies: no timestamp is assumed UTC."""
    with pytest.raises(ValueError, match="naive"):
        cache_key("DAL1234", datetime(2026, 8, 30, 22, 0))
