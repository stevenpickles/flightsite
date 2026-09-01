"""What the engine is given and what it returns.

The two halves of SPEC §39's *"classification must have provenance and should
not claim certainty when evidence is weak"* are both structural here rather
than conventional.

**Provenance is not optional.** A flag on :class:`Classification` is true
exactly when a :class:`Claim` explains it; the invariant is checked in
``__post_init__``, so a classification that asserts something it cannot justify
cannot be constructed at all. There is no code path that sets ``military`` and
forgets to say why.

**Unknown is representable and is the default.** A bare
:class:`Classification` is three false flags, an ``unknown`` mission and an
``unknown`` icon category — the honest answer for an airframe nobody has
metadata for, and the value the engine returns when the evidence conflicts.
:attr:`Classification.is_unknown` names that state so callers do not have to
re-derive it, and it is what makes the API emit ``null`` (``docs/API.md`` §2.7)
rather than an object full of negatives.

:class:`Evidence` is deliberately a flat record of facts rather than a
reference to the database rows they came from. That is what makes
:func:`~flightsite.classification.engine.classify` a pure function testable
against a table of cases, which is the only way a classification matrix can be
reviewed as *data* — the thing this slice's honesty rests on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flightsite.classification.vocabulary import (
    ClaimSource,
    Confidence,
    EvidenceBasis,
    IconCategory,
    MissionCategory,
)


@dataclass(frozen=True, slots=True)
class Evidence:
    """Everything the engine is allowed to reason from, for one airframe.

    Assembled from the resolved metadata row, the per-source military bit, and
    the live callsign. Nothing else: an engine that could reach for altitude,
    speed or position would start inferring "helicopter" from a hover, which is
    precisely the guessing SPEC §39 rules out.

    ``military_flag_source`` is the *name of the metadata source* that set the
    bit (``mictronics`` or ``faa``), not a :class:`ClaimSource`, because that
    name is what provenance has to report. It is ``None`` when no source claims
    the airframe is military — which includes both "no source has heard of it"
    and "a source explicitly says it is civilian", since neither is a reason to
    say military.
    """

    icao24: str
    #: True only when some source positively asserts military status.
    military_flag: bool = False
    military_flag_source: str | None = None
    #: The resolved operator name, exactly as the winning source spells it.
    operator_name: str | None = None
    #: The resolved ICAO type designator, upper-case (``B738``, ``EC35``).
    type_code: str | None = None
    registration: str | None = None
    #: The callsign the aircraft is transmitting right now, if any. The only
    #: live-path input, and the weakest evidence the engine accepts.
    callsign: str | None = None


@dataclass(frozen=True, slots=True)
class Claim:
    """One reason FlightSite believes one thing.

    ``source`` is what gets persisted and published (``docs/DATA_MODEL.md``
    §3.4, ``docs/API.md`` §2.6); ``basis`` is the finer in-memory detail; and
    ``detail`` is a short phrase a person can read, which is what a future
    detail panel will show beside a classification instead of a bare source
    name.
    """

    source: ClaimSource
    basis: EvidenceBasis
    confidence: Confidence
    detail: str


@dataclass(frozen=True, slots=True)
class Classification:
    """One airframe's classification, with a claim behind every assertion.

    Every field defaults to the unknown answer, so ``Classification()`` is the
    complete, valid classification of an airframe nothing is known about.
    """

    military: bool = False
    military_claim: Claim | None = None
    government: bool = False
    government_claim: Claim | None = None
    law_enforcement: bool = False
    law_enforcement_claim: Claim | None = None
    mission: MissionCategory = MissionCategory.UNKNOWN
    mission_claim: Claim | None = None
    icon_category: IconCategory = IconCategory.UNKNOWN

    def __post_init__(self) -> None:
        """Refuse an assertion with nothing behind it, and vice versa.

        Both directions are bugs. A true flag with no claim is a classification
        FlightSite cannot justify; a claim beside a false flag is a claim about
        nothing. Checking here rather than trusting the engine means the
        invariant survives any future caller.
        """
        for flag, claim, name in (
            (self.military, self.military_claim, "military"),
            (self.government, self.government_claim, "government"),
            (self.law_enforcement, self.law_enforcement_claim, "law_enforcement"),
        ):
            if flag is not (claim is not None):
                raise ValueError(f"{name} flag and its claim must agree")
        if (self.mission is MissionCategory.UNKNOWN) is (self.mission_claim is not None):
            raise ValueError("a known mission needs a claim and an unknown one must not have any")

    @property
    def is_unknown(self) -> bool:
        """True when this classification asserts nothing at all.

        The condition the API uses to emit ``null`` instead of an object of
        negatives: "we looked and found nothing to say" reads as ``Unknown`` in
        the UI, which is ``docs/API.md`` §2.7's rule.
        """
        return not (
            self.military
            or self.government
            or self.law_enforcement
            or self.mission is not MissionCategory.UNKNOWN
            or self.icon_category is not IconCategory.UNKNOWN
        )

    @property
    def primary_claim(self) -> Claim | None:
        """The claim that best explains this classification, or ``None``.

        ``docs/API.md`` §3.3 gives the aircraft object one ``confidence`` and
        one ``provenance["classification"]`` entry, so the several claims have
        to collapse to one for publication. They collapse to the *most
        consequential* one — the order below is how a person reads a
        classification aloud — rather than to the most confident, because
        naming a ``high``-confidence mission beside an unexplained ``military``
        flag would attribute the wrong claim.

        The full per-claim detail is not lost: it is stored column by column in
        ``aircraft_classification`` (``docs/DATA_MODEL.md`` §3.4).
        """
        return (
            self.military_claim
            or self.law_enforcement_claim
            or self.government_claim
            or self.mission_claim
        )

    @property
    def confidence(self) -> Confidence | None:
        """The primary claim's confidence, or ``None`` when nothing is claimed."""
        claim = self.primary_claim
        return None if claim is None else claim.confidence

    @property
    def source(self) -> ClaimSource | None:
        """The primary claim's source — the API's ``provenance.classification``."""
        claim = self.primary_claim
        return None if claim is None else claim.source

    def payload(self) -> dict[str, Any] | None:
        """The ``docs/API.md`` §3.3 ``classification`` object, or ``None``.

        ``None`` for a classification that asserts nothing (§2.7: missing data
        is ``null`` and the UI renders ``Unknown``). Where a partial
        classification exists — a military airframe whose mission the evidence
        could not agree on — the object is emitted with ``mission`` spelled
        ``"unknown"``, which is §2.7's other half: a weak-evidence
        classification *is* ``"unknown"``, not a best guess.
        """
        if self.is_unknown:
            return None
        confidence = self.confidence
        return {
            "military": self.military,
            "government": self.government,
            "law_enforcement": self.law_enforcement,
            "mission": self.mission.value,
            "icon_category": self.icon_category.value,
            "confidence": None if confidence is None else confidence.value,
        }

    def as_row(self, icao24: str, *, updated_ms: int) -> dict[str, str | int | float | None]:
        """Column values for an ``aircraft_classification`` insert (§3.4)."""
        return {
            "icao24": icao24,
            "military": int(self.military),
            "military_src": _source(self.military_claim),
            "military_conf": _score(self.military_claim),
            "government": int(self.government),
            "government_src": _source(self.government_claim),
            "government_conf": _score(self.government_claim),
            "law_enforcement": int(self.law_enforcement),
            "law_enforcement_src": _source(self.law_enforcement_claim),
            "law_enforcement_conf": _score(self.law_enforcement_claim),
            "mission_category": self.mission.value,
            "mission_src": _source(self.mission_claim),
            "mission_conf": _score(self.mission_claim),
            "icon_category": self.icon_category.value,
            "updated_ms": updated_ms,
        }


def _source(claim: Claim | None) -> str | None:
    return None if claim is None else claim.source.value


def _score(claim: Claim | None) -> float | None:
    return None if claim is None else claim.confidence.score


__all__ = ["Claim", "Classification", "Evidence"]
