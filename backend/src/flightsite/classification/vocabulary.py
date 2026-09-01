"""The words classification is allowed to say.

Three vocabularies live here, and each one is closed for a different reason.

:class:`MissionCategory` is SPEC §39's list, spelled exactly as
``docs/DATA_MODEL.md`` §3.4's ``CHECK`` constraint spells it. The constraint is
generated from this enum (:data:`MISSION_CATEGORY_CHECK`), so the schema and
the engine cannot drift: a category the engine can produce is a category the
column accepts, by construction.

:class:`ClaimSource` is ``docs/API.md`` §2.8's provenance vocabulary, narrowed
to the three values §3.4 says a classification's ``*_src`` may take. It answers
*whose statement is this* — an upstream database's, or FlightSite's own.

:class:`Confidence` is the calibration SPEC §39 demands. It is a three-band
label rather than a free float because a float invites precision nobody has:
FlightSite cannot tell 0.82 from 0.79, and pretending otherwise is the "false
certainty" the spec forbids. The bands carry scores only because
``docs/DATA_MODEL.md`` §3.4 stores ``*_conf`` as ``REAL``; the score is a
storage detail, the label is the meaning, and :meth:`Confidence.from_score`
puts a stored row back into a band without depending on exact float equality.

:class:`IconCategory` is deliberately *not* the mission list. It is the map
icon hierarchy's own input (§3.4 gives the column no ``CHECK``, unlike
``mission_category``): what an aircraft *looks* like, which is a different
question from what it is *for*. A medical helicopter and a police helicopter
share a silhouette and not a mission.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class MissionCategory(StrEnum):
    """A broad use category for an airframe — SPEC §39, verbatim.

    ``UNKNOWN`` is a real answer and the default one. ``docs/API.md`` §2.7 is
    explicit that a classification with weak evidence *is* ``"unknown"`` rather
    than a best guess, so nothing here is a placeholder for a value the engine
    failed to compute: it is the value the engine computed.
    """

    COMMERCIAL_PASSENGER = "commercial_passenger"
    CARGO = "cargo"
    GENERAL_AVIATION = "general_aviation"
    BUSINESS_AVIATION = "business_aviation"
    MILITARY = "military"
    GOVERNMENT = "government"
    LAW_ENFORCEMENT = "law_enforcement"
    MEDICAL = "medical"
    FIREFIGHTING = "firefighting"
    TRAINING = "training"
    HELICOPTER = "helicopter"
    UNKNOWN = "unknown"


#: ``docs/DATA_MODEL.md`` §3.4's ``mission_category`` check, generated from the
#: enum so the column and the engine share one list rather than two copies of
#: one list. Enum iteration is declaration order, which is the order §3.4 lists
#: them in and is stable across interpreter runs.
MISSION_CATEGORY_CHECK: Final = "mission_category IN ({values})".format(
    values=", ".join(f"'{category.value}'" for category in MissionCategory)
)


class ClaimSource(StrEnum):
    """Who says so — ``docs/DATA_MODEL.md`` §3.4's ``*_src`` vocabulary.

    ``MICTRONICS`` and ``FAA`` mean *an upstream database asserted this*, and
    are used only where a source actually carries the fact (in practice the
    Mictronics military bit). ``HEURISTIC`` means *FlightSite derived this* —
    from its own curated operator and type data, or from a callsign pattern.
    The distinction is what lets a user tell "the aircraft database says this
    airframe is military" from "we recognized the operator's name", which are
    very different claims even when both are right.
    """

    MICTRONICS = "mictronics"
    FAA = "faa"
    HEURISTIC = "heuristic"


class EvidenceBasis(StrEnum):
    """*What* was recognized, one level finer than :class:`ClaimSource`.

    Not persisted: ``docs/DATA_MODEL.md`` §3.4 gives a classification row one
    ``*_src`` column per claim and that column takes the :class:`ClaimSource`
    vocabulary. This is the in-memory detail behind it — the thing tests assert
    on and the thing a future detail panel would explain a classification with.
    Keeping it out of the schema keeps the stored vocabulary the documented one.
    """

    #: An upstream database's military bit (the strongest evidence there is).
    MILITARY_FLAG = "military_flag"
    #: The resolved operator name matched a curated operator entry exactly.
    OPERATOR_NAME = "operator_name"
    #: The resolved operator name matched a curated word pattern ("… Sheriff").
    OPERATOR_PATTERN = "operator_pattern"
    #: The ICAO type designator matched a curated type entry.
    TYPE_CODE = "type_code"
    #: The callsign's airline prefix matched a curated operator entry.
    CALLSIGN = "callsign"


class Confidence(StrEnum):
    """How strongly FlightSite believes a claim.

    Three bands, because three is the number FlightSite can actually justify:

    * ``HIGH`` — an upstream database states the fact, or an exact match on a
      curated operator name whose meaning is unambiguous.
    * ``MEDIUM`` — a curated pattern or type match. Right nearly always, and
      wrong in ways a reader can imagine ("Springfield Police Department" is a
      police force; "Police Athletic League" would not be).
    * ``LOW`` — a callsign pattern. Self-declared by the aircraft, unverified
      against the airframe, and never on its own a reason to call something
      military, governmental or law enforcement (see
      :mod:`flightsite.classification.engine`).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def score(self) -> float:
        """The band's stored ``REAL`` (``docs/DATA_MODEL.md`` §3.4)."""
        return _CONFIDENCE_SCORES[self]

    @classmethod
    def from_score(cls, value: float) -> Confidence:
        """The band a stored score falls in.

        Banded by threshold rather than by equality: the column is a ``REAL``,
        and a value that has been through SQLite and back must land in the band
        it left in even if the last bit moved.
        """
        if value >= _HIGH_THRESHOLD:
            return cls.HIGH
        if value >= _MEDIUM_THRESHOLD:
            return cls.MEDIUM
        return cls.LOW


_CONFIDENCE_SCORES: Final[dict[Confidence, float]] = {
    Confidence.LOW: 0.4,
    Confidence.MEDIUM: 0.7,
    Confidence.HIGH: 0.95,
}

#: Band boundaries, placed midway between the stored scores so a value that
#: drifted cannot cross one.
_HIGH_THRESHOLD: Final = 0.85
_MEDIUM_THRESHOLD: Final = 0.55

#: Ranking used when two claims compete. Higher wins; equal is a genuine tie
#: and the engine treats a tie between *different* answers as unknown.
CONFIDENCE_ORDER: Final[dict[Confidence, int]] = {
    Confidence.LOW: 0,
    Confidence.MEDIUM: 1,
    Confidence.HIGH: 2,
}


class IconCategory(StrEnum):
    """The map icon hierarchy's category level (``docs/DATA_MODEL.md`` §3.4).

    A separate vocabulary from :class:`MissionCategory` on purpose: the icon
    layer asks *what shape is this*, and the mission list answers *what is it
    for*. The frontend registry (``frontend/src/features/map/aircraft/icons/
    resolveIcon.ts``) recognizes ``helicopter`` today and falls every other
    category through to the generic silhouette — which is exactly the designed
    behaviour, not a gap: the categories below are the vocabulary the icon set
    grows into, and emitting them now means a new silhouette is a frontend
    table entry rather than a backend change.
    """

    AIRLINER = "airliner"
    CARGO = "cargo"
    BUSINESS_JET = "business_jet"
    LIGHT_AIRCRAFT = "light_aircraft"
    HELICOPTER = "helicopter"
    MILITARY_JET = "military_jet"
    MILITARY_TRANSPORT = "military_transport"
    MILITARY = "military"
    GOVERNMENT = "government"
    LAW_ENFORCEMENT = "law_enforcement"
    MEDICAL = "medical"
    FIREFIGHTING = "firefighting"
    UNKNOWN = "unknown"


class GroupKind(StrEnum):
    """What kind of thing a curated operator group is.

    Drives nothing on its own — every classification consequence a group has is
    declared explicitly on the group (see
    :class:`~flightsite.classification.operators.OperatorGroupSpec`) — but it is
    what the Aircraft page will group and filter by, and it keeps the curated
    file honest: a group whose kind and declared mission disagree is a data bug
    a test can find.
    """

    PASSENGER = "passenger"
    CARGO = "cargo"
    GOVERNMENT = "government"
    LAW_ENFORCEMENT = "law_enforcement"
    MEDICAL = "medical"
    FIREFIGHTING = "firefighting"
    MILITARY = "military"
    OTHER = "other"


__all__ = [
    "CONFIDENCE_ORDER",
    "MISSION_CATEGORY_CHECK",
    "ClaimSource",
    "Confidence",
    "EvidenceBasis",
    "GroupKind",
    "IconCategory",
    "MissionCategory",
]
