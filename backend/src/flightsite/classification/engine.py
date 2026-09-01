"""The classification engine: evidence in, claims out, nothing hidden.

One pure function, :func:`classify`. It is pure because the honesty property
SPEC §39 asks for is only checkable if the whole decision is a function of its
inputs — a classification matrix test is a table of ``Evidence`` beside the
``Classification`` it must produce, and that is the artifact a person actually
reviews when asking "does FlightSite lie?".

The rules, in the order they fire
---------------------------------

**Flags.** ``military``, ``government`` and ``law_enforcement`` are each set by
the strongest claim available for them:

* ``military`` — an upstream military bit (``HIGH``, and the only ``HIGH``
  military evidence there is); a curated operator group declaring itself
  military (``HIGH`` on an exact name, ``MEDIUM`` on a phrase); or a type
  designator with no civil operation (``MEDIUM``).
* ``government`` and ``law_enforcement`` — only a curated operator group, which
  declares its own flags (see
  :mod:`flightsite.classification.data.operators`).

**A callsign never sets a flag.** Not military, not government, and
emphatically not law enforcement. A callsign is transmitted by the aircraft,
unverified, and changes between flights; calling an airframe a police aircraft
on that basis would be the exact false certainty SPEC §39 forbids, and would do
it about the one category where being wrong matters most.

**Mission**, in two tiers. Tier one is what somebody *asserted*: the military
claim, and the mission the matched operator group declares. Tier two is
consulted only when tier one is empty, and holds what can be *inferred* from
the airframe or the callsign: a rotorcraft type, a light-aeroplane type, a
business-jet type, an airline callsign designator.

Two tiers rather than one confidence ranking because the two kinds of evidence
answer different questions. A police helicopter has a ``MEDIUM`` operator
phrase saying *law enforcement* and a ``MEDIUM`` type saying *helicopter*, and
those do not compete — the operator wins because it says what the aircraft is
*doing*, which is what a mission category is. Ranking them together would make
that aircraft's mission a coin flip between two true statements.

**Conflict inside a tier yields ``unknown``.** When the strongest claims in a
tier disagree about the category, the mission is ``unknown`` with no claim
behind it. Not the first one, not the one from the more prestigious source: a
tie between two equally-supported answers is the definition of not knowing, and
``docs/API.md`` §2.7 says so in as many words. The flags survive — an airframe
can be known-military while its mission is genuinely unclear.

**Icon category** is derived last and separately (:func:`icon_category_for`),
because it answers "what shape is this" rather than "what is it for". A
rotorcraft type wins it outright: a police helicopter, a medical helicopter and
a news helicopter share a silhouette.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from flightsite.classification.data.types import (
    BUSINESS_JET_TYPE_CODES,
    LIGHT_AIRCRAFT_TYPE_CODES,
    MILITARY_TRANSPORT_TYPE_CODES,
    MILITARY_TYPE_CODES,
    ROTORCRAFT_TYPE_CODES,
)
from flightsite.classification.model import Claim, Classification, Evidence
from flightsite.classification.operators import (
    OperatorDirectory,
    OperatorMatch,
    default_directory,
)
from flightsite.classification.vocabulary import (
    CONFIDENCE_ORDER,
    ClaimSource,
    Confidence,
    EvidenceBasis,
    IconCategory,
    MissionCategory,
)

#: Metadata source names that may appear on a military bit, mapped to the
#: provenance vocabulary. A source outside this map is reported as
#: ``heuristic`` rather than published under a name ``docs/API.md`` §2.8 does
#: not define.
_FLAG_SOURCES: Final[dict[str, ClaimSource]] = {
    ClaimSource.MICTRONICS.value: ClaimSource.MICTRONICS,
    ClaimSource.FAA.value: ClaimSource.FAA,
}

#: Mission implied by a type designator, when nothing stronger is known.
#: Checked in this order and at most one applies, so an AH-64 is military
#: rather than an unresolvable tie between military and helicopter.
_TYPE_MISSIONS: Final[tuple[tuple[frozenset[str], MissionCategory], ...]] = (
    (MILITARY_TYPE_CODES, MissionCategory.MILITARY),
    (ROTORCRAFT_TYPE_CODES, MissionCategory.HELICOPTER),
    (LIGHT_AIRCRAFT_TYPE_CODES, MissionCategory.GENERAL_AVIATION),
    (BUSINESS_JET_TYPE_CODES, MissionCategory.BUSINESS_AVIATION),
)

#: Icon category for a mission, where the mission decides the silhouette.
_MISSION_ICONS: Final[dict[MissionCategory, IconCategory]] = {
    MissionCategory.COMMERCIAL_PASSENGER: IconCategory.AIRLINER,
    MissionCategory.CARGO: IconCategory.CARGO,
    MissionCategory.BUSINESS_AVIATION: IconCategory.BUSINESS_JET,
    MissionCategory.GENERAL_AVIATION: IconCategory.LIGHT_AIRCRAFT,
    MissionCategory.TRAINING: IconCategory.LIGHT_AIRCRAFT,
    MissionCategory.HELICOPTER: IconCategory.HELICOPTER,
    MissionCategory.LAW_ENFORCEMENT: IconCategory.LAW_ENFORCEMENT,
    MissionCategory.GOVERNMENT: IconCategory.GOVERNMENT,
    MissionCategory.MEDICAL: IconCategory.MEDICAL,
    MissionCategory.FIREFIGHTING: IconCategory.FIREFIGHTING,
    MissionCategory.MILITARY: IconCategory.MILITARY,
}


def classify(evidence: Evidence, *, directory: OperatorDirectory | None = None) -> Classification:
    """Classify one airframe from :class:`Evidence`. Pure.

    Args:
        evidence: everything known about the airframe. Absent facts are
            ``None``/``False``, and absence is never treated as a negative
            claim — an airframe no source describes classifies as unknown, not
            as civilian.
        directory: curated operator data. Defaults to the shipped directory;
            injected by tests that want a small, legible table.

    Returns:
        A :class:`Classification` in which every assertion has a
        :class:`~flightsite.classification.model.Claim` behind it.
    """
    resolved = directory if directory is not None else default_directory()
    operator = resolved.match(evidence.operator_name)
    callsign = resolved.match_callsign(evidence.callsign)
    type_code = evidence.type_code

    military = _strongest(_military_claims(evidence, operator, type_code))
    # Only a curated group sets these two, and only because it declares that it
    # does. There is no inference here at all — see the module docstring on why
    # a callsign is never allowed near a law-enforcement claim.
    government = _operator_claim(operator) if operator and operator.group.government else None
    law_enforcement = (
        _operator_claim(operator) if operator and operator.group.law_enforcement else None
    )

    mission, mission_claim = _mission(military, operator, callsign, type_code)
    return Classification(
        military=military is not None,
        military_claim=military,
        government=government is not None,
        government_claim=government,
        law_enforcement=law_enforcement is not None,
        law_enforcement_claim=law_enforcement,
        mission=mission,
        mission_claim=mission_claim,
        icon_category=icon_category_for(
            mission=mission, military=military is not None, type_code=type_code
        ),
    )


def icon_category_for(
    *, mission: MissionCategory, military: bool, type_code: str | None
) -> IconCategory:
    """The map icon hierarchy's category for one aircraft.

    A rotorcraft designator decides it outright, ahead of everything else: the
    icon layer draws what an aircraft *is*, and every helicopter is drawn as a
    helicopter whoever operates it. After that, a military airframe is drawn by
    its military role where the type says which one, and otherwise the mission
    decides.

    ``UNKNOWN`` is a real answer here too. The frontend's resolver falls an
    unrecognized category through to the generic silhouette
    (``frontend/src/features/map/aircraft/icons/resolveIcon.ts``), so an honest
    ``unknown`` renders exactly as it should rather than as a wrong shape.
    """
    if (type_code is not None and type_code in ROTORCRAFT_TYPE_CODES) or (
        mission is MissionCategory.HELICOPTER
    ):
        return IconCategory.HELICOPTER
    if military:
        if type_code is not None and type_code in MILITARY_TRANSPORT_TYPE_CODES:
            return IconCategory.MILITARY_TRANSPORT
        if type_code is not None and type_code in MILITARY_TYPE_CODES:
            return IconCategory.MILITARY_JET
        return IconCategory.MILITARY
    return _MISSION_ICONS.get(mission, IconCategory.UNKNOWN)


# ------------------------------------------------------------------ the rules


def _military_claims(
    evidence: Evidence, operator: OperatorMatch | None, type_code: str | None
) -> list[Claim]:
    """Every reason to call this airframe military, strongest first."""
    claims: list[Claim] = []
    if evidence.military_flag:
        source = evidence.military_flag_source
        claims.append(
            Claim(
                source=_FLAG_SOURCES.get(source or "", ClaimSource.HEURISTIC),
                basis=EvidenceBasis.MILITARY_FLAG,
                confidence=Confidence.HIGH,
                detail=f"{source or 'metadata'} military flag",
            )
        )
    if operator is not None and operator.group.military:
        claims.append(_operator_claim(operator))
    if type_code is not None and type_code in MILITARY_TYPE_CODES:
        claims.append(
            Claim(
                source=ClaimSource.HEURISTIC,
                basis=EvidenceBasis.TYPE_CODE,
                confidence=Confidence.MEDIUM,
                detail=f"type {type_code} has no civil operation",
            )
        )
    return claims


def _mission(
    military: Claim | None,
    operator: OperatorMatch | None,
    callsign: OperatorMatch | None,
    type_code: str | None,
) -> tuple[MissionCategory, Claim | None]:
    """Resolve the mission category across the two evidence tiers."""
    asserted: list[tuple[MissionCategory, Claim]] = []
    if military is not None:
        asserted.append((MissionCategory.MILITARY, military))
    if operator is not None and operator.group.mission is not MissionCategory.UNKNOWN:
        asserted.append((operator.group.mission, _operator_claim(operator)))
    if asserted:
        return _settle(asserted)

    inferred: list[tuple[MissionCategory, Claim]] = []
    if type_code is not None:
        for codes, category in _TYPE_MISSIONS:
            if type_code in codes:
                inferred.append(
                    (
                        category,
                        Claim(
                            source=ClaimSource.HEURISTIC,
                            basis=EvidenceBasis.TYPE_CODE,
                            confidence=Confidence.MEDIUM,
                            detail=f"type {type_code}",
                        ),
                    )
                )
                break
    if callsign is not None and callsign.group.mission is not MissionCategory.UNKNOWN:
        inferred.append((callsign.group.mission, _operator_claim(callsign)))
    if inferred:
        return _settle(inferred)
    return MissionCategory.UNKNOWN, None


def _settle(
    candidates: Sequence[tuple[MissionCategory, Claim]],
) -> tuple[MissionCategory, Claim | None]:
    """The mission the strongest candidates agree on, or ``unknown``.

    Equally-strong candidates naming different categories are a genuine
    disagreement, and FlightSite answers a disagreement with ``unknown`` rather
    than by preferring whichever rule happened to run first.
    """
    best = max(CONFIDENCE_ORDER[claim.confidence] for _, claim in candidates)
    top = [entry for entry in candidates if CONFIDENCE_ORDER[entry[1].confidence] == best]
    if len({category for category, _ in top}) > 1:
        return MissionCategory.UNKNOWN, None
    return top[0]


def _strongest(claims: Sequence[Claim]) -> Claim | None:
    """The most confident claim, ties broken by the order rules fired in."""
    if not claims:
        return None
    return max(claims, key=lambda claim: CONFIDENCE_ORDER[claim.confidence])


def _operator_claim(match: OperatorMatch) -> Claim:
    """A claim attributing something to a curated operator match."""
    return Claim(
        source=ClaimSource.HEURISTIC,
        basis=match.basis,
        confidence=match.confidence,
        detail=f"operator group {match.group.slug} via {match.matched!r}",
    )


__all__ = ["classify", "icon_category_for"]
