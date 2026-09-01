"""The evaluation matrix: every condition alone, and AND combinations.

Roadmap slice 038's first acceptance criterion is *"each condition type + AND
combinations verified"*, and this module is that criterion. It is a matrix in
the literal sense — a table of (conditions, subject, expected) rows — because
that is the form in which a critical-coverage domain (SPEC §84) can be reviewed
rather than merely run: a reader checks the table against
``docs/DATA_MODEL.md`` §4.2's condition list and SPEC §43's semantics without
reading any code.

Three properties are asserted for every condition kind rather than only the
happy path, because each has been a real bug in some rule engine somewhere:

* it matches what it should,
* it does **not** match what it should not, and
* it does **not** match when the input it needs is *unknown*, which is
  ``docs/API.md`` §2.7 applied to a predicate — unknown is not a quiet yes.
"""

from __future__ import annotations

import pytest

from flightsite.alerts.evaluator import evaluate, matches
from flightsite.alerts.model import (
    AlertSubject,
    ClassificationCondition,
    RarityCondition,
    RuleConditions,
)
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.classification.vocabulary import MissionCategory
from flightsite.live import GroundState

from .conftest import claimed, missioned, rule, subject


def fires(conditions: RuleConditions, against: AlertSubject, **kwargs: object) -> bool:
    """Whether a rule with ``conditions`` matches ``against``."""
    return matches(rule(conditions), against, alert_radius_nm=kwargs.get("alert_radius_nm"))  # type: ignore[arg-type]


# ------------------------------------------------------------- classification

CLASSIFICATION_MATRIX = [
    # (condition, subject classification kwargs, expected)
    (ClassificationCondition(military=True), {"military": True}, True),
    (ClassificationCondition(military=True), {"government": True}, False),
    (ClassificationCondition(military=True), {}, False),
    (ClassificationCondition(government=True), {"government": True}, True),
    (ClassificationCondition(government=True), {"military": True}, False),
    (ClassificationCondition(law_enforcement=True), {"law_enforcement": True}, True),
    (ClassificationCondition(law_enforcement=True), {"government": True}, False),
    # Several flags on one condition are themselves an AND.
    (
        ClassificationCondition(military=True, government=True),
        {"military": True, "government": True},
        True,
    ),
    (ClassificationCondition(military=True, government=True), {"military": True}, False),
]


@pytest.mark.parametrize(("condition", "flags", "expected"), CLASSIFICATION_MATRIX)
def test_classification_flag_conditions(
    condition: ClassificationCondition, flags: dict[str, bool], expected: bool
) -> None:
    conditions = RuleConditions(classification=condition)

    assert fires(conditions, subject(classification=claimed(**flags))) is expected


def test_a_mission_condition_matches_only_that_mission() -> None:
    conditions = RuleConditions(
        classification=ClassificationCondition(mission=MissionCategory.MEDICAL)
    )

    assert fires(conditions, subject(classification=missioned(MissionCategory.MEDICAL)))
    assert not fires(conditions, subject(classification=missioned(MissionCategory.CARGO)))


def test_a_mission_condition_does_not_match_an_unclassified_aircraft() -> None:
    """``mission`` defaults to ``unknown`` on an airframe nobody has metadata
    for, and unknown satisfies no requirement."""
    conditions = RuleConditions(
        classification=ClassificationCondition(mission=MissionCategory.MILITARY)
    )

    assert not fires(conditions, subject(metadata_resolved=False))


# ------------------------------------------------------------------ type/model


def test_a_type_code_condition_matches_exactly_and_case_insensitively() -> None:
    conditions = RuleConditions(type_code="c17")

    assert fires(conditions, subject(type_code="C17"))
    assert not fires(conditions, subject(type_code="C130"))
    assert not fires(conditions, subject(type_code="C17X"))


def test_a_type_code_condition_does_not_match_an_unresolved_type() -> None:
    assert not fires(RuleConditions(type_code="C17"), subject(type_code=None))


def test_a_model_condition_matches_a_case_insensitive_substring() -> None:
    """The stored value is prose from a registry, so a user writing a rule
    means "Globemaster", not that string character for character."""
    conditions = RuleConditions(model="globemaster")

    assert fires(conditions, subject(model="Boeing C-17A Globemaster III"))
    assert not fires(conditions, subject(model="Boeing 737-800"))


def test_a_model_condition_does_not_match_an_unresolved_model() -> None:
    assert not fires(RuleConditions(model="Globemaster"), subject(model=None))


# ------------------------------------------------------------------ watchlists


def test_a_watchlist_any_condition_matches_membership_of_anything() -> None:
    conditions = RuleConditions(watchlist_any=True)

    assert fires(conditions, subject(watchlists=("Locals",)))
    assert not fires(conditions, subject(watchlists=()))


def test_a_watchlist_id_condition_matches_only_the_named_list() -> None:
    conditions = RuleConditions(watchlist_id=7)
    compiled = rule(conditions, watchlist_name="Locals")

    assert matches(compiled, subject(watchlists=("Locals",)), alert_radius_nm=None)
    assert not matches(compiled, subject(watchlists=("Others",)), alert_radius_nm=None)
    assert not matches(compiled, subject(watchlists=()), alert_radius_nm=None)


def test_a_watchlist_id_that_resolved_to_nothing_matches_nothing() -> None:
    """A rule about a deleted watchlist has no aircraft it can be true of, and
    silently promoting it to "any watchlist" would fire alerts nobody asked
    for."""
    compiled = rule(RuleConditions(watchlist_id=7), watchlist_name=None)

    assert compiled.unresolved_watchlist
    assert not matches(compiled, subject(watchlists=("Locals",)), alert_radius_nm=None)


# --------------------------------------------------------------------- rarity


@pytest.mark.parametrize(
    ("threshold", "seen", "expected"),
    [
        (1, 1, True),  # never seen here before
        (1, 2, False),
        (2, 1, True),
        (2, 2, True),  # "at or below", matching slice 031's own rare list
        (2, 3, False),
    ],
)
def test_rare_aircraft_thresholds_are_inclusive(threshold: int, seen: int, expected: bool) -> None:
    conditions = RuleConditions(rare_aircraft=RarityCondition(max_sightings=threshold))

    assert fires(conditions, subject(sightings_here=seen)) is expected


@pytest.mark.parametrize(
    ("threshold", "airframes", "expected"),
    [(1, 1, True), (1, 2, False), (3, 3, True), (3, 4, False)],
)
def test_rare_type_thresholds_are_inclusive(threshold: int, airframes: int, expected: bool) -> None:
    conditions = RuleConditions(rare_type=RarityCondition(max_sightings=threshold))

    assert fires(conditions, subject(type_aircraft_here=airframes)) is expected


def test_a_rare_type_condition_does_not_match_an_unresolved_type() -> None:
    """No resolved type means the question has no answer, and an unanswered
    requirement fails — the same rule every other condition follows."""
    conditions = RuleConditions(rare_type=RarityCondition(max_sightings=5))

    assert not fires(conditions, subject(type_aircraft_here=None))


# ------------------------------------------------------------------- distance


@pytest.mark.parametrize(
    ("conditions", "distance", "expected"),
    [
        (RuleConditions(max_distance_nm=50.0), 10.0, True),
        (RuleConditions(max_distance_nm=50.0), 50.0, True),
        (RuleConditions(max_distance_nm=50.0), 50.1, False),
        (RuleConditions(min_distance_nm=50.0), 60.0, True),
        (RuleConditions(min_distance_nm=50.0), 50.0, True),
        (RuleConditions(min_distance_nm=50.0), 49.9, False),
        (RuleConditions(min_distance_nm=20.0, max_distance_nm=60.0), 40.0, True),
        (RuleConditions(min_distance_nm=20.0, max_distance_nm=60.0), 10.0, False),
        (RuleConditions(min_distance_nm=20.0, max_distance_nm=60.0), 70.0, False),
    ],
)
def test_distance_windows_are_inclusive_at_both_bounds(
    conditions: RuleConditions, distance: float, expected: bool
) -> None:
    assert fires(conditions, subject(distance_nm=distance)) is expected


def test_a_distance_condition_does_not_match_an_aircraft_with_no_distance() -> None:
    """No receiver location, or a Mode S-only aircraft: FlightSite cannot place
    it, so it satisfies no statement about where it is."""
    assert not fires(RuleConditions(max_distance_nm=50.0), subject(distance_nm=None))
    assert not fires(RuleConditions(min_distance_nm=50.0), subject(distance_nm=None))


# ------------------------------------------------------------------- altitude


@pytest.mark.parametrize(
    ("conditions", "altitude", "expected"),
    [
        (RuleConditions(max_alt_ft=5_000.0), 3_000.0, True),
        (RuleConditions(max_alt_ft=5_000.0), 5_000.0, True),
        (RuleConditions(max_alt_ft=5_000.0), 5_001.0, False),
        (RuleConditions(min_alt_ft=30_000.0), 35_000.0, True),
        (RuleConditions(min_alt_ft=30_000.0), 30_000.0, True),
        (RuleConditions(min_alt_ft=30_000.0), 29_999.0, False),
        (RuleConditions(min_alt_ft=1_000.0, max_alt_ft=10_000.0), 5_000.0, True),
        (RuleConditions(min_alt_ft=1_000.0, max_alt_ft=10_000.0), 500.0, False),
    ],
)
def test_altitude_windows_are_inclusive_at_both_bounds(
    conditions: RuleConditions, altitude: float, expected: bool
) -> None:
    assert fires(conditions, subject(altitude_ft=altitude)) is expected


def test_an_altitude_condition_does_not_match_an_aircraft_with_no_altitude() -> None:
    assert not fires(RuleConditions(max_alt_ft=5_000.0), subject(altitude_ft=None))


# --------------------------------------------------------- AND combinations


def test_every_condition_must_hold_for_the_rule_to_match() -> None:
    """SPEC §43's ``AND``: the whole point of the v1 rule model."""
    conditions = RuleConditions(
        classification=ClassificationCondition(military=True),
        type_code="C17",
        max_distance_nm=50.0,
        min_alt_ft=1_000.0,
    )
    military_c17 = subject(
        classification=claimed(military=True),
        type_code="C17",
        distance_nm=20.0,
        altitude_ft=25_000.0,
    )

    assert fires(conditions, military_c17)


@pytest.mark.parametrize(
    "broken",
    [
        {"classification": None},
        {"type_code": "C130"},
        {"distance_nm": 200.0},
        {"altitude_ft": 500.0},
    ],
)
def test_one_failing_condition_defeats_the_whole_rule(broken: dict[str, object]) -> None:
    """Each row breaks exactly one of the four conditions the previous test
    satisfied, and each must be enough on its own."""
    conditions = RuleConditions(
        classification=ClassificationCondition(military=True),
        type_code="C17",
        max_distance_nm=50.0,
        min_alt_ft=1_000.0,
    )
    fields: dict[str, object] = {
        "classification": claimed(military=True),
        "type_code": "C17",
        "distance_nm": 20.0,
        "altitude_ft": 25_000.0,
    }
    fields.update(broken)

    assert not fires(conditions, subject(**fields))  # type: ignore[arg-type]


def test_a_watchlist_and_rarity_combination_needs_both() -> None:
    conditions = RuleConditions(watchlist_any=True, rare_aircraft=RarityCondition(max_sightings=2))

    assert fires(conditions, subject(watchlists=("Locals",), sightings_here=1))
    assert not fires(conditions, subject(watchlists=(), sightings_here=1))
    assert not fires(conditions, subject(watchlists=("Locals",), sightings_here=9))


# ------------------------------------------------------------- the two gates


def test_a_disabled_rule_never_matches() -> None:
    compiled = rule(RuleConditions(watchlist_any=True), enabled=False)

    assert not matches(compiled, subject(watchlists=("Locals",)), alert_radius_nm=None)


def test_ground_traffic_is_excluded_by_default() -> None:
    """SPEC §40: ground traffic is excluded from relevant alerts."""
    conditions = RuleConditions(classification=ClassificationCondition(military=True))
    on_ground = subject(
        classification=claimed(military=True),
        ground_state=GroundState.ON_GROUND,
        altitude_ft=None,
    )

    assert not fires(conditions, on_ground)


def test_a_rule_may_opt_in_to_ground_traffic() -> None:
    conditions = RuleConditions(
        classification=ClassificationCondition(military=True), applies_on_ground=True
    )
    on_ground = subject(
        classification=claimed(military=True),
        ground_state=GroundState.ON_GROUND,
        altitude_ft=None,
    )

    assert fires(conditions, on_ground)


def test_an_unknown_ground_state_is_not_treated_as_on_the_ground() -> None:
    """FlightSite does not infer the ground from altitude and speed
    (:mod:`flightsite.live.aircraft`), so treating unknown as on-the-ground
    would silently suppress alerts for every aircraft whose decoder is quiet
    about it."""
    conditions = RuleConditions(classification=ClassificationCondition(military=True))
    unknown = subject(classification=claimed(military=True), ground_state=GroundState.UNKNOWN)

    assert fires(conditions, unknown)


def test_the_alert_radius_bounds_every_rule_when_it_is_configured() -> None:
    """SPEC §66 makes the alert radius a property of the installation, not of a
    rule, so it applies before any condition is examined."""
    conditions = RuleConditions(classification=ClassificationCondition(military=True))
    far = subject(classification=claimed(military=True), distance_nm=300.0)
    near = subject(classification=claimed(military=True), distance_nm=30.0)

    assert not fires(conditions, far, alert_radius_nm=100.0)
    assert fires(conditions, near, alert_radius_nm=100.0)
    assert fires(conditions, far, alert_radius_nm=None)


def test_the_alert_radius_is_inclusive_at_its_bound() -> None:
    conditions = RuleConditions(classification=ClassificationCondition(military=True))
    at_bound = subject(classification=claimed(military=True), distance_nm=100.0)

    assert fires(conditions, at_bound, alert_radius_nm=100.0)


def test_the_alert_radius_does_not_exclude_an_aircraft_it_cannot_place() -> None:
    """FlightSite cannot place it, so it cannot place it outside — and SPEC §66's
    own instruction is not to discard what the receiver actually sees."""
    conditions = RuleConditions(classification=ClassificationCondition(military=True))
    unplaced = subject(classification=claimed(military=True), distance_nm=None)

    assert fires(conditions, unplaced, alert_radius_nm=10.0)


# ------------------------------------------------------------------- evaluate


def test_evaluate_returns_every_matching_rule_highest_severity_first() -> None:
    rules = [
        rule(RuleConditions(watchlist_any=True), rule_id=1, severity=AlertSeverity.INFO),
        rule(
            RuleConditions(classification=ClassificationCondition(military=True)),
            rule_id=2,
            severity=AlertSeverity.HIGH,
        ),
        rule(RuleConditions(type_code="B738"), rule_id=3, severity=AlertSeverity.INTERESTING),
    ]
    military = subject(classification=claimed(military=True), watchlists=("Locals",))

    proposals = evaluate(military, rules)

    assert [proposal.rule_id for proposal in proposals] == [2, 1]
    assert [proposal.severity for proposal in proposals] == [
        AlertSeverity.HIGH,
        AlertSeverity.INFO,
    ]


def test_evaluate_is_stable_for_equal_severities() -> None:
    """Two evaluations of the same instant must produce the same tuple, so the
    interesting block's reasons list can be compared as a document."""
    rules = [
        rule(RuleConditions(watchlist_any=True), rule_id=5, severity=AlertSeverity.HIGH),
        rule(RuleConditions(type_code="C17"), rule_id=2, severity=AlertSeverity.HIGH),
    ]
    both = subject(watchlists=("Locals",), type_code="C17")

    assert [proposal.rule_id for proposal in evaluate(both, rules)] == [2, 5]


def test_a_match_key_names_the_rule_and_the_reason_names_its_name() -> None:
    """``docs/API.md`` §3.3's own example is ``"Rule: Military aircraft"``."""
    compiled = rule(
        RuleConditions(classification=ClassificationCondition(military=True)),
        rule_id=4,
        name="Military aircraft",
    )

    (proposal,) = evaluate(subject(classification=claimed(military=True)), [compiled])

    assert proposal.key == "rule:4"
    assert proposal.reason == "Rule: Military aircraft"
    assert not proposal.is_builtin


def test_evaluate_with_no_rules_and_nothing_special_returns_nothing() -> None:
    assert evaluate(subject(), []) == ()
