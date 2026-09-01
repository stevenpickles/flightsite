"""The shapes the curated data files are written in.

Separate from :mod:`flightsite.classification.model` (the engine's inputs and
outputs) and from :mod:`flightsite.classification.operators` (the logic that
reads them) so the data package can import these without importing the matcher
that consumes it, and so a reviewer reading ``data/operators.py`` can see the
whole vocabulary of a curated entry on one page.

The design rule for everything here: **a curated entry declares its own
consequences.** A group does not say "I am a police force" and leave the engine
to work out that police forces are governmental; it says
``government=True, law_enforcement=True, mission=LAW_ENFORCEMENT``. Entailment
rules hidden in code are exactly where a classification engine acquires
opinions nobody reviewed — is a national air force "government"? is a coast
guard "military"? — and those questions have different right answers in
different countries. Making each entry answer for itself puts the judgement in
the diff.
"""

from __future__ import annotations

from dataclasses import dataclass

from flightsite.classification.vocabulary import GroupKind, MissionCategory


@dataclass(frozen=True, slots=True)
class OperatorGroupSpec:
    """One curated operator group and everything membership of it implies.

    Args:
        slug: stable identifier, the ``operator_groups.slug`` value. Never
            reused for a different group and never renamed casually: it is what
            a saved filter or watchlist will reference.
        name: the human-readable group name. This is what ``docs/API.md`` §3.3
            publishes as ``operator_group``, so it is title case prose ("US
            Military"), not a slug.
        kind: what sort of organisation this is (§3.5 grouping, SPEC §38).
        mission: the mission category membership implies, or ``UNKNOWN`` for a
            group that says nothing about mission.
        military / government / law_enforcement: the flags membership implies.
        operators: exact operator names, in the spellings upstream databases
            actually use. Matched case- and punctuation-insensitively, so one
            entry covers ``"Delta Air Lines, Inc."`` and ``"DELTA AIR LINES
            INC"`` — but each *distinct* real-world spelling still earns its
            own entry, because the match is exact once normalized.
        callsigns: ICAO airline designators this group files under. Used only
            against a callsign in the standard ``AAA123`` form, and only as
            :data:`~flightsite.classification.vocabulary.Confidence.LOW`
            evidence.
    """

    slug: str
    name: str
    kind: GroupKind
    mission: MissionCategory = MissionCategory.UNKNOWN
    military: bool = False
    government: bool = False
    law_enforcement: bool = False
    operators: tuple[str, ...] = ()
    callsigns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OperatorPattern:
    """A phrase that identifies a group without naming a specific operator.

    There are thousands of county sheriff's offices and hospital air-ambulance
    services and no prospect of listing them, but their operator names share a
    phrase that means one thing. A pattern matches when its words appear as a
    consecutive run of words in the normalized operator name — *words*, not
    characters, so ``"police"`` matches ``"Kent Police"`` and not
    ``"Metropolitan"``.

    Patterns are :data:`~flightsite.classification.vocabulary.Confidence.MEDIUM`
    evidence, one band below an exact name, because a phrase can appear in a
    name that does not mean what it looks like.
    """

    phrase: str
    group_slug: str


@dataclass(frozen=True, slots=True)
class TypeRule:
    """What an ICAO type designator implies on its own.

    Only designators whose meaning is not in serious doubt appear in the
    curated tables. A type is never
    :data:`~flightsite.classification.vocabulary.Confidence.HIGH` evidence: an
    airframe's type says what it *is*, and operators put the same airframe to
    different uses.
    """

    type_code: str
    mission: MissionCategory
    military: bool = False


__all__ = ["OperatorGroupSpec", "OperatorPattern", "TypeRule"]
