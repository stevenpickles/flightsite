"""Invariants of the shipped curated data.

Not a test of *what* the data says — that is editorial, and changing it is the
whole point of keeping it in a data file. These are the properties a reviewer
cannot check by eye across a hundred entries: that the file builds at all, that
nothing claims a name twice, that a group asserting a flag also says what
mission it implies, and that the type tables do not contradict each other.

The one content assertion here is coverage: the file has to be big enough to
be worth having. SPEC §38 names the brands by way of example, and a seed set
that dropped to a dozen entries would pass every structural check while making
operator grouping useless.
"""

from __future__ import annotations

import pytest

from flightsite.classification.data.operators import OPERATOR_GROUPS, OPERATOR_PATTERNS
from flightsite.classification.data.types import (
    BUSINESS_JET_TYPE_CODES,
    LIGHT_AIRCRAFT_TYPE_CODES,
    MILITARY_TRANSPORT_TYPE_CODES,
    MILITARY_TYPE_CODES,
    ROTORCRAFT_TYPE_CODES,
)
from flightsite.classification.operators import default_directory, match_key
from flightsite.classification.specs import OperatorGroupSpec, OperatorPattern
from flightsite.classification.vocabulary import GroupKind, MissionCategory

#: Below this the seed set stops being useful for grouping (SPEC §38).
MINIMUM_GROUPS = 60


def test_the_shipped_data_builds() -> None:
    """Construction is where duplicate names and dangling patterns are caught."""
    assert default_directory().groups == OPERATOR_GROUPS


def test_the_seed_set_is_large_enough_to_be_worth_having() -> None:
    assert len(OPERATOR_GROUPS) >= MINIMUM_GROUPS


def test_every_group_covers_the_kinds_the_product_promises() -> None:
    kinds = {group.kind for group in OPERATOR_GROUPS}

    assert kinds == set(GroupKind)


@pytest.mark.parametrize("group", OPERATOR_GROUPS, ids=lambda group: group.slug)
def test_a_group_that_asserts_a_flag_also_declares_a_mission(group: OperatorGroupSpec) -> None:
    """Otherwise the engine would set a flag and leave the mission unexplained.

    The engine deliberately derives no mission from a flag — entailments live
    in the data — so a group with a flag and no mission would be silently
    half-classified.
    """
    if group.military or group.government or group.law_enforcement:
        assert group.mission is not MissionCategory.UNKNOWN


@pytest.mark.parametrize("group", OPERATOR_GROUPS, ids=lambda group: group.slug)
def test_a_law_enforcement_group_is_also_a_government_one(group: OperatorGroupSpec) -> None:
    """The call recorded in the data file's docstring, enforced across the file."""
    if group.law_enforcement:
        assert group.government


@pytest.mark.parametrize("group", OPERATOR_GROUPS, ids=lambda group: group.slug)
def test_a_group_has_a_readable_name_and_a_slug(group: OperatorGroupSpec) -> None:
    """``name`` is published as ``operator_group`` (``docs/API.md`` §3.3): prose, not a slug."""
    assert group.slug and group.slug == group.slug.lower()
    assert " " not in group.slug
    assert group.name.strip() == group.name and group.name


@pytest.mark.parametrize("group", OPERATOR_GROUPS, ids=lambda group: group.slug)
def test_a_group_with_no_names_and_no_designators_is_reachable_by_pattern(
    group: OperatorGroupSpec,
) -> None:
    """A group nothing can ever match is dead data, not a placeholder."""
    if group.operators or group.callsigns:
        return
    assert any(pattern.group_slug == group.slug for pattern in OPERATOR_PATTERNS), (
        f"{group.slug} has no operators, no callsigns and no pattern"
    )


def test_no_operator_name_normalizes_to_nothing() -> None:
    empty = [name for group in OPERATOR_GROUPS for name in group.operators if not match_key(name)]

    assert empty == []


@pytest.mark.parametrize("pattern", OPERATOR_PATTERNS, ids=lambda pattern: pattern.phrase)
def test_a_pattern_phrase_survives_normalization(pattern: OperatorPattern) -> None:
    """A phrase is compared against a normalized key, so it must already be one."""
    assert match_key(pattern.phrase) == pattern.phrase


def test_callsign_designators_are_three_upper_case_letters() -> None:
    designators = [code for group in OPERATOR_GROUPS for code in group.callsigns]

    assert designators
    assert all(len(code) == 3 and code.isalpha() and code.isupper() for code in designators)


# --------------------------------------------------------------- type tables


def test_the_type_tables_do_not_overlap_where_overlapping_would_contradict() -> None:
    """A type cannot be both a light aeroplane and a business jet."""
    assert not LIGHT_AIRCRAFT_TYPE_CODES & BUSINESS_JET_TYPE_CODES
    assert not LIGHT_AIRCRAFT_TYPE_CODES & MILITARY_TYPE_CODES
    assert not BUSINESS_JET_TYPE_CODES & MILITARY_TYPE_CODES
    assert not BUSINESS_JET_TYPE_CODES & ROTORCRAFT_TYPE_CODES
    assert not LIGHT_AIRCRAFT_TYPE_CODES & ROTORCRAFT_TYPE_CODES


def test_a_military_rotorcraft_is_allowed_to_be_both() -> None:
    """The one deliberate overlap: an Apache is a military helicopter.

    The engine resolves it — military mission, helicopter silhouette — so the
    overlap is meaningful rather than contradictory.
    """
    assert {"AH64", "H47"} == MILITARY_TYPE_CODES & ROTORCRAFT_TYPE_CODES


def test_military_transports_are_military_types() -> None:
    assert MILITARY_TRANSPORT_TYPE_CODES <= MILITARY_TYPE_CODES


def test_no_airliner_type_appears_in_any_table() -> None:
    """The absence that keeps the engine honest (``data/types.py``)."""
    airliners = {"B738", "B739", "A320", "A21N", "B77W", "A359", "E75L", "CRJ9", "B763"}
    tables = (
        MILITARY_TYPE_CODES,
        ROTORCRAFT_TYPE_CODES,
        LIGHT_AIRCRAFT_TYPE_CODES,
        BUSINESS_JET_TYPE_CODES,
    )

    for table in tables:
        assert not airliners & table


def test_type_designators_are_stored_upper_case() -> None:
    """``normalize_record`` upper-cases them, so a lower-case entry never matches."""
    for table in (
        MILITARY_TYPE_CODES,
        MILITARY_TRANSPORT_TYPE_CODES,
        ROTORCRAFT_TYPE_CODES,
        LIGHT_AIRCRAFT_TYPE_CODES,
        BUSINESS_JET_TYPE_CODES,
    ):
        assert all(code == code.upper() and code.isalnum() for code in table)
