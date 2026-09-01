"""The closed vocabularies, and the two places they have to agree with.

SPEC §39's category list appears three times — in the enum, in the SQL ``CHECK``
``docs/DATA_MODEL.md`` §3.4 defines, and in the migration that creates the
column. Two of those are strings that cannot import the third
(``db`` must not depend on ``classification``), so the agreement is asserted
here rather than assumed.
"""

from __future__ import annotations

import pytest

from flightsite.classification.vocabulary import (
    MISSION_CATEGORY_CHECK,
    ClaimSource,
    Confidence,
    IconCategory,
    MissionCategory,
)
from flightsite.db.models import MISSION_CATEGORY_CHECK as MODELS_MISSION_CHECK

#: SPEC §39, read off the specification rather than off the enum.
SPEC_CATEGORIES = (
    "commercial_passenger",
    "cargo",
    "general_aviation",
    "business_aviation",
    "military",
    "government",
    "law_enforcement",
    "medical",
    "firefighting",
    "training",
    "helicopter",
    "unknown",
)


def test_the_mission_categories_are_exactly_the_spec_list() -> None:
    assert tuple(category.value for category in MissionCategory) == SPEC_CATEGORIES


def test_the_generated_check_matches_the_one_the_schema_uses() -> None:
    """``db.models`` cannot import this enum, so the two must be compared."""
    assert MISSION_CATEGORY_CHECK == MODELS_MISSION_CHECK


def test_the_check_names_every_category_and_nothing_else() -> None:
    quoted = MISSION_CATEGORY_CHECK.split("(", 1)[1].rstrip(")")
    listed = tuple(value.strip().strip("'") for value in quoted.split(","))

    assert listed == SPEC_CATEGORIES


def test_claim_sources_are_the_documented_subset_of_the_provenance_vocabulary() -> None:
    """``docs/DATA_MODEL.md`` §3.4: ``mictronics | faa | heuristic``."""
    assert {source.value for source in ClaimSource} == {"mictronics", "faa", "heuristic"}


@pytest.mark.parametrize("band", list(Confidence))
def test_a_confidence_band_survives_a_round_trip_through_its_stored_score(
    band: Confidence,
) -> None:
    """The column is a ``REAL``; the label is what the band means."""
    assert Confidence.from_score(band.score) is band


def test_confidence_scores_are_ordered_low_to_high() -> None:
    assert Confidence.LOW.score < Confidence.MEDIUM.score < Confidence.HIGH.score


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (1.0, Confidence.HIGH),
        (0.9, Confidence.HIGH),
        (0.7000000000001, Confidence.MEDIUM),
        (0.6, Confidence.MEDIUM),
        (0.4, Confidence.LOW),
        (0.0, Confidence.LOW),
        (-1.0, Confidence.LOW),
    ],
)
def test_a_stored_score_lands_in_the_band_it_left_in(score: float, expected: Confidence) -> None:
    """Banded by threshold, so a value that drifted cannot cross a boundary."""
    assert Confidence.from_score(score) is expected


def test_the_icon_vocabulary_is_not_the_mission_vocabulary() -> None:
    """§3.4 gives ``icon_category`` no CHECK precisely because they differ.

    They overlap where a mission and a silhouette happen to share a name, but
    the icon set answers "what shape is this" and grows with the artwork.
    """
    icons = {category.value for category in IconCategory}
    missions = {category.value for category in MissionCategory}

    assert icons != missions
    assert "military_transport" in icons and "military_transport" not in missions
    assert "commercial_passenger" in missions and "commercial_passenger" not in icons
    # The one the frontend registry actually draws today
    # (frontend/src/features/map/aircraft/icons/resolveIcon.ts).
    assert IconCategory.HELICOPTER.value == "helicopter"
