"""The result type: an assertion cannot exist without the claim behind it.

SPEC §39's provenance requirement is enforced by :class:`Classification`'s
constructor rather than by the engine, so it holds for every caller that ever
builds one. These tests are that guarantee, plus the two projections the rest
of the system reads it through: the ``docs/API.md`` §3.3 payload and the
``docs/DATA_MODEL.md`` §3.4 row.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from flightsite.classification.model import Claim, Classification
from flightsite.classification.vocabulary import (
    ClaimSource,
    Confidence,
    EvidenceBasis,
    IconCategory,
    MissionCategory,
)

FLAG_CLAIM = Claim(
    source=ClaimSource.MICTRONICS,
    basis=EvidenceBasis.MILITARY_FLAG,
    confidence=Confidence.HIGH,
    detail="mictronics military flag",
)
GROUP_CLAIM = Claim(
    source=ClaimSource.HEURISTIC,
    basis=EvidenceBasis.OPERATOR_NAME,
    confidence=Confidence.MEDIUM,
    detail="operator group",
)


def test_the_empty_classification_is_a_complete_valid_answer() -> None:
    result = Classification()

    assert result.is_unknown
    assert result.mission is MissionCategory.UNKNOWN
    assert result.primary_claim is None
    assert result.confidence is None
    assert result.source is None


@pytest.mark.parametrize(
    "build",
    [
        lambda: Classification(military=True),
        lambda: Classification(government=True),
        lambda: Classification(law_enforcement=True),
    ],
    ids=["military", "government", "law_enforcement"],
)
def test_a_flag_without_a_claim_cannot_be_constructed(
    build: Callable[[], Classification],
) -> None:
    with pytest.raises(ValueError, match="flag and its claim must agree"):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: Classification(military_claim=FLAG_CLAIM),
        lambda: Classification(government_claim=FLAG_CLAIM),
        lambda: Classification(law_enforcement_claim=FLAG_CLAIM),
    ],
    ids=["military", "government", "law_enforcement"],
)
def test_a_claim_beside_a_false_flag_cannot_be_constructed(
    build: Callable[[], Classification],
) -> None:
    """A claim about nothing is as wrong as an assertion about nothing."""
    with pytest.raises(ValueError, match="flag and its claim must agree"):
        build()


def test_a_known_mission_needs_a_claim() -> None:
    with pytest.raises(ValueError, match="known mission needs a claim"):
        Classification(mission=MissionCategory.CARGO)


def test_an_unknown_mission_must_not_carry_one() -> None:
    with pytest.raises(ValueError, match="known mission needs a claim"):
        Classification(mission=MissionCategory.UNKNOWN, mission_claim=GROUP_CLAIM)


def test_the_primary_claim_is_the_most_consequential_not_the_most_confident() -> None:
    """§3.3 publishes one confidence; it must describe the headline assertion."""
    result = Classification(
        military=True,
        military_claim=GROUP_CLAIM,
        mission=MissionCategory.MILITARY,
        mission_claim=FLAG_CLAIM,
    )

    assert result.primary_claim is GROUP_CLAIM
    assert result.confidence is Confidence.MEDIUM


def test_the_claim_order_runs_military_then_law_then_government_then_mission() -> None:
    government_only = Classification(government=True, government_claim=GROUP_CLAIM)
    with_law = Classification(
        government=True,
        government_claim=GROUP_CLAIM,
        law_enforcement=True,
        law_enforcement_claim=FLAG_CLAIM,
    )

    assert government_only.primary_claim is GROUP_CLAIM
    assert with_law.primary_claim is FLAG_CLAIM


# ------------------------------------------------------------------- payload


def test_an_unknown_classification_serializes_as_null() -> None:
    assert Classification().payload() is None


def test_a_partial_classification_still_serializes_with_an_unknown_mission() -> None:
    """§2.7: weak evidence *is* ``unknown``; it is not omitted and not guessed."""
    payload = Classification(military=True, military_claim=FLAG_CLAIM).payload()

    assert payload == {
        "military": True,
        "government": False,
        "law_enforcement": False,
        "mission": "unknown",
        "icon_category": "unknown",
        "confidence": "high",
    }


def test_the_payload_keys_are_exactly_the_documented_ones() -> None:
    payload = Classification(
        mission=MissionCategory.CARGO,
        mission_claim=GROUP_CLAIM,
        icon_category=IconCategory.CARGO,
    ).payload()

    assert payload is not None
    assert set(payload) == {
        "military",
        "government",
        "law_enforcement",
        "mission",
        "icon_category",
        "confidence",
    }
    assert payload["mission"] == "cargo"
    assert payload["icon_category"] == "cargo"
    assert payload["confidence"] == "medium"


def test_the_payload_carries_json_booleans_not_integers() -> None:
    payload = Classification(military=True, military_claim=FLAG_CLAIM).payload()

    assert payload is not None
    assert payload["military"] is True
    assert payload["government"] is False


# ----------------------------------------------------------------------- row


def test_a_row_pairs_every_flag_with_its_source_and_score() -> None:
    row = Classification(
        military=True,
        military_claim=FLAG_CLAIM,
        mission=MissionCategory.MILITARY,
        mission_claim=FLAG_CLAIM,
        icon_category=IconCategory.MILITARY_TRANSPORT,
    ).as_row("ae1463", updated_ms=1_756_600_000_000)

    assert row["icao24"] == "ae1463"
    assert row["military"] == 1
    assert row["military_src"] == "mictronics"
    assert row["military_conf"] == Confidence.HIGH.score
    assert row["mission_category"] == "military"
    assert row["icon_category"] == "military_transport"
    assert row["updated_ms"] == 1_756_600_000_000


def test_an_unasserted_flag_has_no_source_and_no_score() -> None:
    """A ``NULL`` pair is the shape of "nothing asserts this"."""
    row = Classification().as_row("abcdef", updated_ms=1)

    assert row["government"] == 0
    assert row["government_src"] is None
    assert row["government_conf"] is None
    assert row["mission_src"] is None
    assert row["mission_conf"] is None


def test_a_stored_score_reads_back_as_the_band_it_was_written_from() -> None:
    row = Classification(
        mission=MissionCategory.MEDICAL,
        mission_claim=GROUP_CLAIM,
        icon_category=IconCategory.MEDICAL,
    ).as_row("abcdef", updated_ms=1)
    stored = row["mission_conf"]

    assert isinstance(stored, float)
    assert Confidence.from_score(stored) is Confidence.MEDIUM
