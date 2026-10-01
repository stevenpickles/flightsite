"""Version 2 of the conditions document (slice 089, issue #232).

Three things are pinned here, in the order the roadmap states them:

* **Existing rules load unchanged.** A version 1 document — byte for byte what
  the previous build wrote to ``alert_rules.conditions_json`` — parses into a
  version 2 document with exactly the conditions it had, describes itself in
  exactly the words it used to, and *evaluates identically*. The last of these
  is checked against an independent re-statement of the pre-089 evaluator over
  a grid of subjects that also varies every input the new conditions read, so
  a v1 rule that started reacting to ground speed or position would fail here.
* **Every new condition validates at write time**, with a refusal for each
  shape that could never match or could not be evaluated unambiguously.
* **Every new condition explains itself** in a reason phrase, in canonical
  units (kt, ft/min), in the existing style.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

from flightsite.alerts.evaluator import matches
from flightsite.alerts.model import (
    CONDITIONS_VERSION,
    MAX_SQUAWK_CODES,
    AlertSubject,
    RuleConditions,
    compile_glob,
)
from flightsite.classification.model import Classification
from flightsite.classification.vocabulary import MissionCategory
from flightsite.live import GroundState

from .conftest import claimed, missioned, rule, subject

SQUARE_AREA: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[-2.0, 50.0], [-1.0, 50.0], [-1.0, 51.0], [-2.0, 51.0]]],
}


def parse(document: dict[str, Any]) -> RuleConditions:
    return RuleConditions.model_validate(document)


def fires(document: dict[str, Any], against: AlertSubject) -> bool:
    return matches(rule(parse(document)), against, alert_radius_nm=None)


# ------------------------------------------------------- v1 loads unchanged

#: Stored text exactly as the pre-089 build's ``RuleConditions.to_json``
#: wrote it: sorted keys, no whitespace, defaults included, ``"version":1``.
V1_STORED: list[str] = [
    '{"applies_on_ground":false,"classification":{"government":false,'
    '"law_enforcement":false,"military":true},"version":1,"watchlist_any":false}',
    '{"applies_on_ground":false,"classification":{"government":false,'
    '"law_enforcement":true,"military":false,"mission":"medical"},"version":1,'
    '"watchlist_any":false}',
    '{"applies_on_ground":false,"type_code":"C17","version":1,"watchlist_any":false}',
    '{"applies_on_ground":false,"model":"Globemaster","version":1,"watchlist_any":false}',
    '{"applies_on_ground":false,"version":1,"watchlist_any":true}',
    '{"applies_on_ground":false,"rare_aircraft":{"max_sightings":1},"version":1,'
    '"watchlist_any":false}',
    '{"applies_on_ground":false,"rare_type":{"max_sightings":5},"version":1,"watchlist_any":false}',
    '{"applies_on_ground":false,"max_distance_nm":40.0,"min_distance_nm":5.0,'
    '"version":1,"watchlist_any":false}',
    '{"applies_on_ground":true,"max_alt_ft":5000.0,"min_alt_ft":500.0,"version":1,'
    '"watchlist_any":false}',
    '{"applies_on_ground":false,"classification":{"government":false,'
    '"law_enforcement":false,"military":true},"max_alt_ft":10000.0,'
    '"max_distance_nm":60.0,"version":1,"watchlist_any":true}',
]

#: The phrases each of the documents above described itself with before 089.
V1_DESCRIBES: list[tuple[str, ...]] = [
    ("military",),
    ("law enforcement and mission medical",),
    ("type C17",),
    ("model containing 'Globemaster'",),
    ("on any watchlist",),
    ("seen at most once here",),
    ("type seen on at most 5 airframes here",),
    ("at least 5 nm away", "within 40 nm"),
    ("at or above 500 ft", "at or below 5000 ft"),
    ("military", "on any watchlist", "within 60 nm", "at or below 10000 ft"),
]


def v1_reference(conditions: dict[str, Any], s: AlertSubject) -> bool:
    """The pre-089 evaluator, restated over the raw v1 document.

    Deliberately written against the JSON rather than the model, so it cannot
    share a bug with the code under test.
    """
    if s.on_ground and not conditions.get("applies_on_ground", False):
        return False
    c = conditions.get("classification")
    if c is not None:
        cl = s.classification
        if (c["military"] and not cl.military) or (c["government"] and not cl.government):
            return False
        if c["law_enforcement"] and not cl.law_enforcement:
            return False
        if "mission" in c and (cl.mission is None or cl.mission.value != c["mission"]):
            return False
    if "type_code" in conditions and (
        s.type_code is None or s.type_code.upper() != conditions["type_code"].upper()
    ):
        return False
    if "model" in conditions and (
        s.model is None or conditions["model"].casefold() not in s.model.casefold()
    ):
        return False
    if conditions.get("watchlist_any") and not s.watchlists:
        return False
    rare = conditions.get("rare_aircraft")
    if rare is not None and s.sightings_here > rare["max_sightings"]:
        return False
    rare_type = conditions.get("rare_type")
    if rare_type is not None and (
        s.type_aircraft_here is None or s.type_aircraft_here > rare_type["max_sightings"]
    ):
        return False
    for low_key, high_key, value in (
        ("min_distance_nm", "max_distance_nm", s.distance_nm),
        ("min_alt_ft", "max_alt_ft", s.altitude_ft),
    ):
        low, high = conditions.get(low_key), conditions.get(high_key)
        if low is None and high is None:
            continue
        if value is None or (high is not None and value > high):
            return False
        if low is not None and value < low:
            return False
    return True


def medical_police() -> Classification:
    """Law enforcement *and* mission medical, each with a claim behind it."""
    police = claimed(law_enforcement=True)
    medical = missioned(MissionCategory.MEDICAL)
    return replace(police, mission=medical.mission, mission_claim=medical.mission_claim)


#: No v2 inputs at all, and a full set of them. A v1 rule must not care.
V2_INPUTS: list[dict[str, Any]] = [
    {},
    {
        "ground_speed_kt": 450.0,
        "vertical_rate_fpm": -2_000.0,
        "emitter_category": "A3",
        "latitude": 50.5,
        "longitude": -1.5,
        "callsign": "RCH123",
        "registration": "N123AB",
        "squawk": "7000",
    },
]


def subject_grid() -> list[AlertSubject]:
    """Subjects varying every v1 input *and* every input v2 conditions read."""
    grid: list[AlertSubject] = []
    for (
        classification,
        type_code,
        distance,
        altitude,
        ground,
        watchlists,
        sightings,
        kinematics,
    ) in itertools.product(
        [
            Classification(),
            claimed(military=True),
            claimed(law_enforcement=True),
            medical_police(),
        ],
        [None, "C17", "a320"],
        [None, 3.0, 20.0, 80.0],
        [None, 400.0, 3_000.0, 30_000.0],
        [GroundState.AIRBORNE, GroundState.ON_GROUND],
        [(), ("Spotting",)],
        [1, 9],
        V2_INPUTS,
    ):
        grid.append(
            subject(
                classification=classification,
                type_code=type_code,
                model=None if type_code is None else "Boeing C-17A Globemaster III",
                distance_nm=distance,
                altitude_ft=altitude,
                ground_state=ground,
                watchlists=watchlists,
                sightings_here=sightings,
                type_aircraft_here=None if type_code is None else 4,
                **kinematics,
            )
        )
    return grid


@pytest.mark.parametrize(("stored", "describes"), list(zip(V1_STORED, V1_DESCRIBES, strict=True)))
def test_a_stored_v1_document_loads_as_v2_with_the_same_conditions(
    stored: str, describes: tuple[str, ...]
) -> None:
    loaded = RuleConditions.from_json(stored)

    assert loaded.version == CONDITIONS_VERSION == 2
    assert loaded.describe() == describes
    assert not loaded.extended
    # Re-saving changes only the version number: the lazy rewrite on save.
    resaved = json.loads(loaded.to_json())
    original = json.loads(stored)
    assert resaved == {**original, "version": 2}


@pytest.mark.parametrize("stored", V1_STORED)
def test_every_v1_rule_evaluates_identically(stored: str) -> None:
    """The roadmap's first acceptance criterion, over a 3 072-subject grid."""
    document = json.loads(stored)
    compiled = rule(RuleConditions.from_json(stored))
    grid = subject_grid()
    disagreements = [
        s for s in grid if matches(compiled, s, alert_radius_nm=None) != v1_reference(document, s)
    ]

    assert disagreements == []
    # The grid is not vacuous: each rule both matches and fails somewhere.
    outcomes = {v1_reference(document, s) for s in grid}
    assert outcomes == {True, False}


def test_a_v1_document_may_not_carry_v2_conditions() -> None:
    with pytest.raises(ValidationError, match="version 1 conditions document cannot carry"):
        parse({"version": 1, "squawk_in": ["7000"]})


def test_a_document_without_a_version_is_read_as_the_current_one() -> None:
    assert parse({"squawk_in": ["7000"]}).version == CONDITIONS_VERSION


def test_a_boolean_is_not_mistaken_for_version_1() -> None:
    with pytest.raises(ValidationError):
        parse({"version": True, "watchlist_any": True})


def test_a_v2_document_round_trips_through_the_stored_text() -> None:
    document = parse(
        {
            "squawk_in": ["7000", "1200"],
            "callsign_glob": "RCH*",
            "registration_glob": "N?23AB",
            "min_ground_speed_kt": 100,
            "max_ground_speed_kt": 300,
            "min_vertical_rate_fpm": -3000,
            "max_vertical_rate_fpm": 500,
            "emitter_category_in": ["A7", "A1"],
            "within_area": SQUARE_AREA,
        }
    )

    reloaded = RuleConditions.from_json(document.to_json())

    assert reloaded == document
    assert reloaded.to_json() == document.to_json()
    assert reloaded.within_area is not None
    assert reloaded.within_area.compiled == document.within_area.compiled  # type: ignore[union-attr]


# --------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "document",
    [
        {"squawk_in": []},
        {"squawk_in": ["7800"]},  # 8 is not octal
        {"squawk_in": ["700"]},
        {"squawk_in": ["07000"]},
        {"squawk_in": [7000]},  # a number loses leading zeros; strings only
        {"squawk_in": [f"{n:04o}" for n in range(MAX_SQUAWK_CODES + 1)]},
        {"callsign_glob": ""},
        {"callsign_glob": "RCH 1"},
        {"callsign_glob": "X" * 33},
        {"registration_glob": "\t"},
        {"min_ground_speed_kt": -1},
        {"max_ground_speed_kt": 0},
        {"max_ground_speed_kt": 2_001},
        {"min_ground_speed_kt": 300, "max_ground_speed_kt": 300},
        {"min_vertical_rate_fpm": -20_001},
        {"max_vertical_rate_fpm": 20_001},
        {"min_vertical_rate_fpm": 500, "max_vertical_rate_fpm": -500},
        {"emitter_category_in": []},
        {"emitter_category_in": ["E1"]},
        {"emitter_category_in": ["A8"]},
        {"emitter_category_in": ["a3"]},
        {"within_area": {"type": "Polygon", "coordinates": []}},
        {"within_area": {"type": "MultiPolygon", "coordinates": SQUARE_AREA["coordinates"]}},
        {"within_area": {"coordinates": [[[0, 0], [1, 0]]]}},
        {"within_area": {**SQUARE_AREA, "name": "home"}},
    ],
)
def test_a_never_matching_or_malformed_v2_condition_is_refused(document: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse(document)


def test_an_area_with_a_hole_is_refused_by_name() -> None:
    hole = [[-1.8, 50.2], [-1.2, 50.2], [-1.2, 50.8], [-1.8, 50.8]]
    with pytest.raises(ValidationError, match="may not have holes"):
        parse(
            {"within_area": {"type": "Polygon", "coordinates": [*SQUARE_AREA["coordinates"], hole]}}
        )


def test_an_area_crossing_the_antimeridian_is_refused_by_name() -> None:
    ring = [[179.5, 10.0], [-179.5, 10.0], [-179.5, 11.0], [179.5, 11.0]]
    with pytest.raises(ValidationError, match="antimeridian"):
        parse({"within_area": {"type": "Polygon", "coordinates": [ring]}})


def test_an_unclosed_area_is_stored_closed() -> None:
    area = parse({"within_area": SQUARE_AREA}).within_area

    assert area is not None
    ring = area.coordinates[0]
    assert ring[0] == ring[-1]
    assert area.vertex_count == 4


def test_sets_are_stored_sorted_and_without_duplicates() -> None:
    document = parse({"squawk_in": ["7000", "1200", "7000"], "emitter_category_in": ["B2", "A1"]})

    assert document.squawk_in == ("1200", "7000")
    assert document.emitter_category_in == ("A1", "B2")


def test_an_emergency_squawk_is_allowed_in_a_rule() -> None:
    assert parse({"squawk_in": ["7700"]}).describe() == ("squawking 7700",)


# -------------------------------------------------------------------- globs


@pytest.mark.parametrize(
    ("pattern", "value", "expected"),
    [
        ("RCH*", "RCH123", True),
        ("RCH*", "rch123", True),  # case-insensitive both ways
        ("rch*", "RCH123", True),
        ("RCH*", "XRCH1", False),  # anchored at the start
        ("*123", "RCH123", True),
        ("*123", "RCH1234", False),  # anchored at the end
        ("N?23AB", "N123AB", True),
        ("N?23AB", "N23AB", False),  # ? is exactly one character
        ("N?23AB", "N1123AB", False),
        ("G-AB*", "G-ABCD", True),
        ("G.AB*", "GXABCD", False),  # "." is a literal dot, not a regex wildcard
        ("[AB]*", "A123", False),  # "[" is literal: no character classes
        ("[AB]*", "[AB]1", True),
        ("N+1", "NN1", False),  # "+" is literal
        ("***", "", True),  # collapsed runs of * still match the empty string
        ("A**B", "AXYB", True),
    ],
)
def test_glob_semantics(pattern: str, value: str, expected: bool) -> None:
    assert (compile_glob(pattern).fullmatch(value) is not None) is expected


def test_a_pathological_glob_compiles_to_a_linear_pattern() -> None:
    assert compile_glob("*" * 32).pattern == ".*"


# ------------------------------------------------------------- evaluation


EVALUATION_MATRIX: list[tuple[dict[str, Any], dict[str, Any], bool]] = [
    # squawk_in
    ({"squawk_in": ["1200", "7000"]}, {"squawk": "7000"}, True),
    ({"squawk_in": ["1200", "7000"]}, {"squawk": "7001"}, False),
    ({"squawk_in": ["1200"]}, {"squawk": None}, False),
    # callsign_glob — matched against the live callsign, trailing space trimmed
    ({"callsign_glob": "RCH*"}, {"callsign": "RCH871"}, True),
    ({"callsign_glob": "RCH*"}, {"callsign": "RCH871  "}, True),
    ({"callsign_glob": "RCH*"}, {"callsign": "BAW1"}, False),
    ({"callsign_glob": "RCH*"}, {"callsign": None}, False),
    # registration_glob — matched against the resolved registration
    ({"registration_glob": "N?23AB"}, {"registration": "N423AB"}, True),
    ({"registration_glob": "G-*"}, {"registration": "N423AB"}, False),
    ({"registration_glob": "G-*"}, {"registration": None}, False),
    # ground speed, inclusive at both bounds
    ({"min_ground_speed_kt": 100, "max_ground_speed_kt": 200}, {"ground_speed_kt": 100.0}, True),
    ({"min_ground_speed_kt": 100, "max_ground_speed_kt": 200}, {"ground_speed_kt": 200.0}, True),
    ({"min_ground_speed_kt": 100, "max_ground_speed_kt": 200}, {"ground_speed_kt": 99.9}, False),
    ({"max_ground_speed_kt": 200}, {"ground_speed_kt": 200.1}, False),
    ({"max_ground_speed_kt": 200}, {"ground_speed_kt": None}, False),
    # vertical rate, negative descending
    ({"max_vertical_rate_fpm": -1500}, {"vertical_rate_fpm": -2_000.0}, True),
    ({"max_vertical_rate_fpm": -1500}, {"vertical_rate_fpm": -1_000.0}, False),
    ({"min_vertical_rate_fpm": 1000}, {"vertical_rate_fpm": 1_000.0}, True),
    ({"min_vertical_rate_fpm": -500, "max_vertical_rate_fpm": 500}, {"vertical_rate_fpm": 0}, True),
    ({"min_vertical_rate_fpm": 1000}, {"vertical_rate_fpm": None}, False),
    # emitter category
    ({"emitter_category_in": ["A7"]}, {"emitter_category": "A7"}, True),
    ({"emitter_category_in": ["A7", "B1"]}, {"emitter_category": "A3"}, False),
    ({"emitter_category_in": ["A7"]}, {"emitter_category": None}, False),
    # within_area — note GeoJSON order: [lon, lat]
    ({"within_area": SQUARE_AREA}, {"latitude": 50.5, "longitude": -1.5}, True),
    ({"within_area": SQUARE_AREA}, {"latitude": 50.0, "longitude": -1.5}, True),  # on edge
    ({"within_area": SQUARE_AREA}, {"latitude": 52.0, "longitude": -1.5}, False),  # bbox miss
    ({"within_area": SQUARE_AREA}, {"latitude": -1.5, "longitude": 50.5}, False),  # axes swapped
    ({"within_area": SQUARE_AREA}, {"latitude": None, "longitude": None}, False),
]


@pytest.mark.parametrize(("document", "facts", "expected"), EVALUATION_MATRIX)
def test_each_v2_condition_alone(
    document: dict[str, Any], facts: dict[str, Any], expected: bool
) -> None:
    assert fires(document, subject(**facts)) is expected


def test_v2_conditions_combine_with_v1_conditions_by_and() -> None:
    document: dict[str, Any] = {
        "classification": {"military": True},
        "max_alt_ft": 10_000,
        "callsign_glob": "RCH*",
        "max_ground_speed_kt": 250,
        "within_area": SQUARE_AREA,
    }
    everything: dict[str, Any] = {
        "classification": claimed(military=True),
        "altitude_ft": 3_000.0,
        "callsign": "RCH42",
        "ground_speed_kt": 180.0,
        "latitude": 50.5,
        "longitude": -1.5,
    }

    assert fires(document, subject(**everything))
    spoilers: list[tuple[str, Any]] = [
        ("classification", Classification()),
        ("altitude_ft", 12_000.0),
        ("callsign", "BAW42"),
        ("ground_speed_kt", 400.0),
        ("longitude", -0.5),
    ]
    for key, spoiler in spoilers:
        assert not fires(document, subject(**{**everything, key: spoiler})), key


def test_v2_conditions_still_respect_the_ground_gate() -> None:
    facts: dict[str, Any] = {"squawk": "7000", "ground_state": GroundState.ON_GROUND}

    assert not fires({"squawk_in": ["7000"]}, subject(**facts))
    assert fires({"squawk_in": ["7000"], "applies_on_ground": True}, subject(**facts))


# ------------------------------------------------------------ reason phrases


@pytest.mark.parametrize(
    ("document", "phrases"),
    [
        ({"squawk_in": ["1200"]}, ("squawking 1200",)),
        ({"squawk_in": ["7000", "1200"]}, ("squawking 1200 or 7000",)),
        ({"squawk_in": ["0020", "1200", "7000"]}, ("squawking 0020, 1200 or 7000",)),
        ({"callsign_glob": "RCH*"}, ("callsign matching 'RCH*'",)),
        ({"registration_glob": "N?23AB"}, ("registration matching 'N?23AB'",)),
        ({"emitter_category_in": ["A7"]}, ("emitter category A7",)),
        ({"emitter_category_in": ["B2", "A1"]}, ("emitter category A1 or B2",)),
        (
            {"min_ground_speed_kt": 80, "max_ground_speed_kt": 250},
            ("ground speed at least 80 kt", "ground speed at most 250 kt"),
        ),
        (
            {"min_vertical_rate_fpm": -3000, "max_vertical_rate_fpm": -1000},
            ("vertical rate at or above -3000 ft/min", "vertical rate at or below -1000 ft/min"),
        ),
        ({"min_vertical_rate_fpm": 1500}, ("vertical rate at or above +1500 ft/min",)),
        ({"within_area": SQUARE_AREA}, ("inside a drawn area of 4 vertices",)),
    ],
)
def test_each_v2_condition_describes_itself(
    document: dict[str, Any], phrases: tuple[str, ...]
) -> None:
    assert parse(document).describe() == phrases


def test_squawk_phrases_do_not_borrow_the_emergency_wording() -> None:
    """The built-in alert already says "emergency"; a user's own squawk rule
    says what it matches and nothing more, so the two never read alike."""
    (phrase,) = parse({"squawk_in": ["7500", "7600", "7700"]}).describe()

    assert "emergency" not in phrase.casefold()


def test_v2_phrases_follow_every_v1_phrase() -> None:
    document = parse({"squawk_in": ["7000"], "type_code": "C17", "max_alt_ft": 5_000})

    assert document.describe() == ("type C17", "at or below 5000 ft", "squawking 7000")


# ------------------------------------------------------------- compilation


def test_a_v1_rule_compiles_to_no_extended_conditions() -> None:
    """The evaluator's whole v2 cost for a v1 rule is one ``is None`` check."""
    for stored in V1_STORED:
        assert rule(RuleConditions.from_json(stored)).extended is None


def test_a_v2_rule_is_compiled_once_with_the_rule_not_per_aircraft() -> None:
    conditions = parse({"squawk_in": ["7000"], "callsign_glob": "RCH*", "within_area": SQUARE_AREA})
    compiled = rule(conditions)

    extended = compiled.extended
    assert extended is not None
    assert extended.squawks == frozenset({"7000"})
    assert extended.callsign is not None
    assert extended.callsign.pattern == "RCH.*"
    # The area is the very object compiled when the document was parsed.
    assert conditions.within_area is not None
    assert extended.area is conditions.within_area.compiled
