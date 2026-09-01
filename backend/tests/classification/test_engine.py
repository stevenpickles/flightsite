"""The classification matrix: known aircraft in, exact claims out.

This is the file to read when asking whether FlightSite tells the truth about
aircraft. :data:`MATRIX` is a table of curated cases — a real military airframe,
a scheduled airline flight, a sheriff's helicopter, an air ambulance, a freight
aircraft, a light aeroplane on an N-number, an airliner nobody has operator data
for — each stated as :class:`Evidence` beside every flag, category, confidence
and provenance it must produce. Nothing is asserted loosely: a case that ends up
``unknown`` says so, and a case that ends up certain names the source it is
certain because of.

The cases run against the **shipped** curated data on purpose. Rule mechanics
are exercised separately against the toy directory
(:mod:`tests.classification.conftest`), but "does a Delta flight come out as
commercial passenger" is a question about the data FlightSite actually ships,
and it is worth failing when somebody edits that data wrongly.

The second half of the file is the honesty half: the cases where evidence is
weak, absent or self-contradictory and the answer must be ``unknown`` rather
than a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from flightsite.classification.engine import classify
from flightsite.classification.model import Evidence
from flightsite.classification.operators import OperatorDirectory
from flightsite.classification.vocabulary import (
    ClaimSource,
    Confidence,
    EvidenceBasis,
    IconCategory,
    MissionCategory,
)

_MISSION = MissionCategory
_ICON = IconCategory


@dataclass(frozen=True)
class Case:
    """One row of the classification matrix."""

    name: str
    evidence: Evidence
    military: bool = False
    government: bool = False
    law_enforcement: bool = False
    mission: MissionCategory = _MISSION.UNKNOWN
    icon: IconCategory = _ICON.UNKNOWN
    confidence: Confidence | None = None
    source: ClaimSource | None = None
    basis: EvidenceBasis | None = None


MATRIX: tuple[Case, ...] = (
    Case(
        # The aircraft docs/API.md §3.3 uses for its own example.
        name="military hex with the Mictronics bit and a service operator",
        evidence=Evidence(
            icao24="ae1463",
            military_flag=True,
            military_flag_source="mictronics",
            operator_name="United States Air Force",
            registration="05-8153",
            type_code="C17",
            callsign="RCH492",
        ),
        military=True,
        mission=_MISSION.MILITARY,
        icon=_ICON.MILITARY_TRANSPORT,
        confidence=Confidence.HIGH,
        source=ClaimSource.MICTRONICS,
        basis=EvidenceBasis.MILITARY_FLAG,
    ),
    Case(
        name="scheduled airline flight with a resolved operator",
        evidence=Evidence(
            icao24="a1b2c3",
            operator_name="Delta Air Lines, Inc.",
            registration="N302DN",
            type_code="B739",
            callsign="DAL1234",
        ),
        mission=_MISSION.COMMERCIAL_PASSENGER,
        icon=_ICON.AIRLINER,
        confidence=Confidence.HIGH,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.OPERATOR_NAME,
    ),
    Case(
        name="sheriff's helicopter, recognized by phrase",
        evidence=Evidence(
            icao24="a44444",
            operator_name="Los Angeles County Sheriff's Department",
            registration="N950LA",
            type_code="EC45",
        ),
        government=True,
        law_enforcement=True,
        mission=_MISSION.LAW_ENFORCEMENT,
        # The airframe is a helicopter whoever flies it: the type wins the icon.
        icon=_ICON.HELICOPTER,
        confidence=Confidence.MEDIUM,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.OPERATOR_PATTERN,
    ),
    Case(
        name="air ambulance operator, exact name",
        evidence=Evidence(
            icao24="a55555",
            operator_name="Air Methods Corporation",
            registration="N911AM",
            type_code="EC35",
        ),
        mission=_MISSION.MEDICAL,
        icon=_ICON.HELICOPTER,
        confidence=Confidence.HIGH,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.OPERATOR_NAME,
    ),
    Case(
        name="cargo carrier",
        evidence=Evidence(
            icao24="a66666",
            operator_name="Federal Express Corp",
            registration="N103FE",
            type_code="B763",
            callsign="FDX1234",
        ),
        mission=_MISSION.CARGO,
        icon=_ICON.CARGO,
        confidence=Confidence.HIGH,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.OPERATOR_NAME,
    ),
    Case(
        name="light aeroplane on an N-number, no operator",
        evidence=Evidence(icao24="a77777", registration="N12345", type_code="C172"),
        mission=_MISSION.GENERAL_AVIATION,
        icon=_ICON.LIGHT_AIRCRAFT,
        confidence=Confidence.MEDIUM,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.TYPE_CODE,
    ),
    Case(
        name="helicopter type and nothing else",
        evidence=Evidence(icao24="a88888", type_code="B407"),
        mission=_MISSION.HELICOPTER,
        icon=_ICON.HELICOPTER,
        confidence=Confidence.MEDIUM,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.TYPE_CODE,
    ),
    Case(
        name="combat type with no operator at all",
        evidence=Evidence(icao24="a99999", type_code="F16"),
        military=True,
        mission=_MISSION.MILITARY,
        icon=_ICON.MILITARY_JET,
        # A type match is never HIGH: it says what the airframe is, not who
        # flies it.
        confidence=Confidence.MEDIUM,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.TYPE_CODE,
    ),
    Case(
        name="coast guard: government and law enforcement, not military",
        evidence=Evidence(
            icao24="aa0001",
            operator_name="United States Coast Guard",
            type_code="H60",
        ),
        government=True,
        law_enforcement=True,
        mission=_MISSION.GOVERNMENT,
        icon=_ICON.HELICOPTER,
        confidence=Confidence.HIGH,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.OPERATOR_NAME,
    ),
    Case(
        name="federal law enforcement, exact name",
        evidence=Evidence(
            icao24="aa0002",
            operator_name="US Customs and Border Protection",
            type_code="C208",
        ),
        government=True,
        law_enforcement=True,
        mission=_MISSION.LAW_ENFORCEMENT,
        icon=_ICON.LAW_ENFORCEMENT,
        confidence=Confidence.HIGH,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.OPERATOR_NAME,
    ),
    Case(
        name="aerial firefighting operator",
        evidence=Evidence(
            icao24="aa0003",
            operator_name="Neptune Aviation Services",
            type_code="BA46",
        ),
        mission=_MISSION.FIREFIGHTING,
        icon=_ICON.FIREFIGHTING,
        confidence=Confidence.HIGH,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.OPERATOR_NAME,
    ),
    Case(
        name="flight school, recognized by phrase",
        evidence=Evidence(
            icao24="aa0004",
            operator_name="Sunrise Aviation Flight School",
            type_code="C152",
        ),
        mission=_MISSION.TRAINING,
        icon=_ICON.LIGHT_AIRCRAFT,
        confidence=Confidence.MEDIUM,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.OPERATOR_PATTERN,
    ),
    Case(
        name="fractional business jet operator",
        evidence=Evidence(icao24="aa0005", operator_name="NetJets Aviation", type_code="C56X"),
        mission=_MISSION.BUSINESS_AVIATION,
        icon=_ICON.BUSINESS_JET,
        confidence=Confidence.HIGH,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.OPERATOR_NAME,
    ),
    Case(
        name="airline callsign with no metadata at all",
        evidence=Evidence(icao24="aa0006", callsign="UAL2201"),
        mission=_MISSION.COMMERCIAL_PASSENGER,
        icon=_ICON.AIRLINER,
        # LOW: the aircraft is telling us, and nothing is checking.
        confidence=Confidence.LOW,
        source=ClaimSource.HEURISTIC,
        basis=EvidenceBasis.CALLSIGN,
    ),
)


@pytest.mark.parametrize("case", MATRIX, ids=lambda case: case.name)
def test_the_classification_matrix(case: Case) -> None:
    result = classify(case.evidence)

    assert result.military is case.military, "military flag"
    assert result.government is case.government, "government flag"
    assert result.law_enforcement is case.law_enforcement, "law enforcement flag"
    assert result.mission is case.mission, "mission category"
    assert result.icon_category is case.icon, "icon category"
    assert result.confidence is case.confidence, "published confidence"
    assert result.source is case.source, "published provenance"
    primary = result.primary_claim
    assert (None if primary is None else primary.basis) is case.basis, "evidence basis"


@pytest.mark.parametrize("case", MATRIX, ids=lambda case: case.name)
def test_every_matrix_assertion_has_a_claim_behind_it(case: Case) -> None:
    """SPEC §39's provenance rule, checked on every curated case at once."""
    result = classify(case.evidence)

    for flag, claim in (
        (result.military, result.military_claim),
        (result.government, result.government_claim),
        (result.law_enforcement, result.law_enforcement_claim),
    ):
        assert flag is (claim is not None)
    assert (result.mission is _MISSION.UNKNOWN) is (result.mission_claim is None)


# ------------------------------------------------------- weak evidence is unknown


def test_an_airframe_nobody_has_heard_of_classifies_as_unknown() -> None:
    result = classify(Evidence(icao24="abcdef"))

    assert result.is_unknown
    assert result.mission is _MISSION.UNKNOWN
    assert result.icon_category is _ICON.UNKNOWN
    assert result.confidence is None
    # docs/API.md §2.7: the payload is null rather than an object of negatives.
    assert result.payload() is None


def test_an_airliner_type_with_no_operator_is_unknown_not_a_passenger_flight() -> None:
    """The single most tempting wrong answer in the whole engine.

    A 737 is flown by scheduled carriers, freight operators, charter companies
    and governments. The airframe does not decide, so there is no airliner
    table (see ``classification/data/types.py``) and the honest answer is
    ``unknown``.
    """
    result = classify(Evidence(icao24="a00001", registration="N12345", type_code="B738"))

    assert result.is_unknown


def test_a_registration_alone_says_nothing() -> None:
    """A GA N-number with no operator and no type is not "general aviation"."""
    result = classify(Evidence(icao24="a00002", registration="N738AB"))

    assert result.is_unknown


def test_a_registration_used_as_a_callsign_matches_no_airline() -> None:
    """``N738AB`` is not an ICAO designator plus a flight number."""
    result = classify(Evidence(icao24="a00003", callsign="N738AB"))

    assert result.is_unknown


def test_a_military_flag_contradicting_a_civil_operator_yields_an_unknown_mission() -> None:
    """Equally strong evidence disagreeing is not knowing.

    The flag still stands — an upstream database asserting military status is a
    fact about the airframe — but what it is *for* is genuinely unclear, and
    FlightSite says so rather than preferring whichever rule ran first.
    """
    result = classify(
        Evidence(
            icao24="a00004",
            military_flag=True,
            military_flag_source="mictronics",
            operator_name="Delta Air Lines",
            type_code="B738",
        )
    )

    assert result.military is True
    assert result.mission is _MISSION.UNKNOWN
    assert result.mission_claim is None
    # Still publishable: the military claim is what the payload reports.
    assert result.payload() is not None
    assert result.confidence is Confidence.HIGH


def test_a_stronger_operator_match_beats_a_weaker_type_match() -> None:
    """A civil Hercules operator outranks the type's military reputation."""
    result = classify(Evidence(icao24="a00005", operator_name="Kalitta Air", type_code="C130"))

    assert result.mission is _MISSION.CARGO
    assert result.military is True  # the type is still evidence, at MEDIUM
    assert result.military_claim is not None
    assert result.military_claim.confidence is Confidence.MEDIUM


def test_a_callsign_never_outranks_metadata() -> None:
    """Tier two is consulted only when tier one is empty."""
    result = classify(
        Evidence(icao24="a00006", operator_name="Federal Express Corp", callsign="DAL9")
    )

    assert result.mission is _MISSION.CARGO
    assert result.confidence is Confidence.HIGH


# ------------------------------------------- what a callsign is never allowed to do


def test_a_callsign_cannot_raise_the_law_enforcement_flag(
    toy_directory: OperatorDirectory,
) -> None:
    """The rule that matters most, asserted against a group that would allow it.

    ``toy-police`` declares a callsign designator *and* the law-enforcement
    flag. A callsign match therefore has everything it would need — and still
    must not set the flag, because a callsign is transmitted by the aircraft
    and verified by nobody.
    """
    result = classify(Evidence(icao24="a00007", callsign="TPD100"), directory=toy_directory)

    assert result.law_enforcement is False
    assert result.government is False
    assert result.military is False
    assert result.mission is _MISSION.LAW_ENFORCEMENT
    assert result.confidence is Confidence.LOW


def test_a_callsign_cannot_raise_the_military_flag(toy_directory: OperatorDirectory) -> None:
    result = classify(Evidence(icao24="a00008", callsign="TOY42"), directory=toy_directory)

    assert result.military is False
    assert result.mission is _MISSION.COMMERCIAL_PASSENGER


def test_an_operator_name_can_raise_the_flag_the_same_callsign_cannot(
    toy_directory: OperatorDirectory,
) -> None:
    """The contrast that makes the previous two tests mean something."""
    result = classify(
        Evidence(icao24="a00009", operator_name="Toy City Police"), directory=toy_directory
    )

    assert result.law_enforcement is True
    assert result.government is True
    assert result.confidence is Confidence.HIGH


def test_a_group_that_declares_no_consequences_classifies_nothing(
    toy_directory: OperatorDirectory,
) -> None:
    """Being grouped is not itself a classification (SPEC §38 is additive)."""
    result = classify(
        Evidence(icao24="a0000a", operator_name="Toy Holdings"), directory=toy_directory
    )

    assert result.is_unknown


def test_a_military_group_does_not_imply_government(
    toy_directory: OperatorDirectory,
) -> None:
    """SPEC §39 lists them separately; the curated data decides, and it says no."""
    result = classify(
        Evidence(icao24="a0000b", operator_name="Toy Armed Forces"), directory=toy_directory
    )

    assert result.military is True
    assert result.government is False


# --------------------------------------------------------------- icon derivation


@pytest.mark.parametrize(
    ("type_code", "expected"),
    [
        ("EC35", _ICON.HELICOPTER),
        ("C17", _ICON.MILITARY_TRANSPORT),
        ("F16", _ICON.MILITARY_JET),
        (None, _ICON.MILITARY),
        ("B738", _ICON.MILITARY),
    ],
)
def test_a_military_airframes_silhouette_follows_its_type(
    type_code: str | None, expected: IconCategory
) -> None:
    result = classify(
        Evidence(
            icao24="a0000c",
            military_flag=True,
            military_flag_source="mictronics",
            type_code=type_code,
        )
    )

    assert result.icon_category is expected


def test_a_rotorcraft_type_wins_the_icon_over_every_mission() -> None:
    """A medical helicopter and a police helicopter are drawn the same."""
    medical = classify(Evidence(icao24="a0000d", operator_name="Air Methods", type_code="EC35"))
    police = classify(Evidence(icao24="a0000e", operator_name="Kent Police", type_code="EC35"))

    assert medical.icon_category is police.icon_category is _ICON.HELICOPTER
    assert medical.mission is not police.mission


def test_an_unknown_military_flag_source_is_reported_as_heuristic() -> None:
    """§2.8's provenance vocabulary is closed; an unknown source is not added to it."""
    result = classify(
        Evidence(icao24="a0000f", military_flag=True, military_flag_source="somebody-else")
    )

    assert result.military is True
    assert result.source is ClaimSource.HEURISTIC
