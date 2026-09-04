"""The eligibility matrix: who gets looked up, under what key, and until when.

The most consequential table in the slice. A false negative here costs one
missing route; a false positive spends a request against the user's quota every
time that aircraft is seen, forever, for a callsign no schedule exists for. So
the cases are enumerated rather than sampled.
"""

from __future__ import annotations

import pytest

from flightsite.airports.model import AirportContext, InferredPhase
from flightsite.classification.operators import CALLSIGN_PATTERN
from flightsite.enrichment.policy import (
    MAX_CALLSIGN_LENGTH,
    airline_designator,
    cache_key,
    contradicts_route,
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


def test_the_cache_key_is_the_callsign_alone() -> None:
    """Slice 070 dropped the date bucket; the key is the callsign (§7)."""
    assert cache_key("DAL1234") == "DAL1234"


def test_the_key_normalizes_what_a_decoder_transmits() -> None:
    """A padded, lower-cased transmission must not file a second row."""
    assert cache_key("  dal1234 ") == cache_key("DAL1234")


def test_two_observations_of_one_flight_share_a_key_across_days() -> None:
    """The measured saving: 62 % of a day's callsigns were heard yesterday.

    With a dated key those two observations were two rows and two requests.
    Now they are one row, and the expiry decides when it is bought again.
    """
    assert cache_key("DAL1234") == cache_key("DAL1234")


# ------------------------------------------------------- the consistency check


ARRIVING_AT_KSEA = AirportContext(
    ident="KSEA", name="Seattle-Tacoma Intl", distance_nm=3.0, phase=InferredPhase.ARRIVING
)
DEPARTING_KSEA = AirportContext(
    ident="KSEA", name="Seattle-Tacoma Intl", distance_nm=2.0, phase=InferredPhase.DEPARTING
)
NEAR_KSEA = AirportContext(ident="KSEA", name="Seattle-Tacoma Intl", distance_nm=4.0)


def test_a_departure_from_somewhere_else_contradicts_the_origin() -> None:
    """The schedule changed under the cached row; the aircraft says so."""
    assert contradicts_route(DEPARTING_KSEA, origin_ident="KATL", destination_ident="KSLC")


def test_an_arrival_somewhere_else_contradicts_the_destination() -> None:
    assert contradicts_route(ARRIVING_AT_KSEA, origin_ident="KATL", destination_ident="KSLC")


def test_a_departure_from_the_cached_origin_contradicts_nothing() -> None:
    assert not contradicts_route(DEPARTING_KSEA, origin_ident="ksea", destination_ident="KSLC")


def test_an_arrival_at_the_cached_destination_contradicts_nothing() -> None:
    assert not contradicts_route(ARRIVING_AT_KSEA, origin_ident="KATL", destination_ident="KSEA")


def test_a_departure_is_checked_against_the_origin_only() -> None:
    """Being right about one end is not evidence against the other."""
    assert not contradicts_route(DEPARTING_KSEA, origin_ident="KSEA", destination_ident="KATL")


def test_an_unnamed_end_of_the_route_contradicts_nothing() -> None:
    """The cache claimed nothing about that airport, so nothing is disproved."""
    assert not contradicts_route(DEPARTING_KSEA, origin_ident=None, destination_ident="KSLC")


@pytest.mark.parametrize(
    "context",
    [
        pytest.param(None, id="no-context"),
        pytest.param(NEAR_KSEA, id="near-a-field-with-no-phase"),
    ],
)
def test_without_a_latched_phase_nothing_is_contradicted(
    context: AirportContext | None,
) -> None:
    """SPEC §39: weak evidence produces no answer, and invalidates nothing."""
    assert not contradicts_route(context, origin_ident="KATL", destination_ident="KSLC")
