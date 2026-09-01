"""The conditions document: what it accepts, what it refuses, and its round trip.

``docs/DATA_MODEL.md`` §4.2 makes ``conditions_json`` an embedded
Pydantic-validated document with no SQL constraint of its own, so this model is
the *only* thing standing between a malformed rule and an engine trying to
evaluate it. Two families of refusal matter and both are here:

* a document that could not be evaluated (a bad type, an unknown key, a version
  this build does not know), and
* a document that *could* be evaluated but could never match anything — an
  empty condition set, a zero threshold, an inverted window. Those are the
  dangerous ones, because nothing fails at runtime: the rule simply never
  fires, and the user is left believing it is watching.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from flightsite.alerts.model import (
    CONDITIONS_VERSION,
    MAX_RARITY_THRESHOLD,
    ClassificationCondition,
    RarityCondition,
    RuleConditions,
)
from flightsite.classification.vocabulary import MissionCategory


def test_a_minimal_document_carries_the_schema_version() -> None:
    conditions = RuleConditions(watchlist_any=True)

    assert conditions.version == CONDITIONS_VERSION
    assert json.loads(conditions.to_json())["version"] == 1


def test_a_document_round_trips_through_the_stored_text() -> None:
    conditions = RuleConditions(
        classification=ClassificationCondition(military=True),
        max_distance_nm=50.0,
        min_alt_ft=1_000.0,
        applies_on_ground=True,
    )

    assert RuleConditions.from_json(conditions.to_json()) == conditions


def test_the_stored_text_is_stable_for_equal_documents() -> None:
    """Sorted keys and no whitespace, so two equal documents are equal text —
    which is what makes a round trip through the column comparable."""
    first = RuleConditions(
        max_distance_nm=50.0, classification=ClassificationCondition(military=True)
    )
    second = RuleConditions(
        classification=ClassificationCondition(military=True), max_distance_nm=50.0
    )

    assert first.to_json() == second.to_json()
    assert " " not in first.to_json()


def test_an_empty_condition_set_is_refused() -> None:
    """The one configuration a user can never have meant: a rule that matches
    every aircraft in the sky at whatever severity it declared."""
    with pytest.raises(ValidationError, match="at least one condition"):
        RuleConditions()


def test_a_classification_condition_that_requires_nothing_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least one of"):
        ClassificationCondition()


def test_a_classification_condition_cannot_require_mission_unknown() -> None:
    """It would fire on every airframe no metadata source has heard of — a rule
    about FlightSite's ignorance rather than about aircraft."""
    with pytest.raises(ValidationError, match="unknown"):
        ClassificationCondition(mission=MissionCategory.UNKNOWN)


@pytest.mark.parametrize("threshold", [0, -1, MAX_RARITY_THRESHOLD + 1])
def test_a_rarity_threshold_outside_its_bounds_is_refused(threshold: int) -> None:
    """Zero can never match, and a threshold in the thousands is not rarity."""
    with pytest.raises(ValidationError):
        RarityCondition(max_sightings=threshold)


def test_an_inverted_distance_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="min_distance_nm must be less than"):
        RuleConditions(min_distance_nm=100.0, max_distance_nm=50.0)


def test_an_equal_distance_window_is_refused() -> None:
    """Equal bounds admit exactly one float, which no real distance hits."""
    with pytest.raises(ValidationError, match="min_distance_nm must be less than"):
        RuleConditions(min_distance_nm=50.0, max_distance_nm=50.0)


def test_an_inverted_altitude_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="min_alt_ft must be less than"):
        RuleConditions(min_alt_ft=30_000.0, max_alt_ft=1_000.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_distance_nm": 0.0},
        {"max_distance_nm": 100_000.0},
        {"min_distance_nm": -1.0},
        {"max_alt_ft": 1_000_000.0},
        {"min_alt_ft": -50_000.0},
        {"type_code": ""},
        {"watchlist_id": 0},
    ],
)
def test_out_of_range_thresholds_are_refused(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RuleConditions(**kwargs)  # type: ignore[arg-type]


def test_an_unknown_key_is_refused() -> None:
    """``extra="forbid"`` matters more for a stored document than for a request
    body: a key a future build stops reading would sit in storage looking like
    a condition that is being applied."""
    with pytest.raises(ValueError, match="squawk"):
        RuleConditions.from_json('{"version": 1, "squawk": "7700"}')


def test_an_unknown_document_version_is_refused() -> None:
    """Decoding a newer format by guessing is worse than saying so — the same
    refusal the packed track encoding applies to an unknown version."""
    with pytest.raises(ValueError):
        RuleConditions.from_json('{"version": 2, "watchlist_any": true}')


def test_text_that_is_not_a_json_object_is_refused() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        RuleConditions.from_json("[1, 2, 3]")


def test_text_that_is_not_json_at_all_is_refused() -> None:
    with pytest.raises(ValueError):
        RuleConditions.from_json("not json")


def test_describe_names_every_condition_set() -> None:
    conditions = RuleConditions(
        classification=ClassificationCondition(military=True, mission=MissionCategory.MILITARY),
        type_code="C17",
        model="Globemaster",
        watchlist_id=3,
        rare_aircraft=RarityCondition(max_sightings=2),
        rare_type=RarityCondition(max_sightings=1),
        min_distance_nm=5.0,
        max_distance_nm=50.0,
        min_alt_ft=1_000.0,
        max_alt_ft=30_000.0,
    )

    described = conditions.describe()

    assert described == (
        "military and mission military",
        "type C17",
        "model containing 'Globemaster'",
        "on watchlist 3",
        "seen at most 2 time(s) here",
        "type seen on at most 1 airframe(s) here",
        "at least 5 nm away",
        "within 50 nm",
        "at or above 1000 ft",
        "at or below 30000 ft",
    )


def test_describe_names_the_any_watchlist_condition() -> None:
    assert RuleConditions(watchlist_any=True).describe() == ("on any watchlist",)


def test_applies_on_ground_defaults_to_false() -> None:
    """SPEC §40: ground traffic is excluded from relevant alerts unless a rule
    says otherwise."""
    assert RuleConditions(watchlist_any=True).applies_on_ground is False


def test_the_document_is_frozen() -> None:
    """A compiled rule is shared across every evaluation in a cycle; a mutable
    condition set would let one aircraft's evaluation change another's."""
    conditions = RuleConditions(watchlist_any=True)

    with pytest.raises(ValidationError):
        conditions.watchlist_any = False
