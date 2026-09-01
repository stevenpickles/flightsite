"""The values the rollup fold consumes and produces.

Plain frozen dataclasses with no database, no clock and no timezone: the fold
in :mod:`flightsite.analytics.rollup` is a pure function from a sequence of
:class:`SightingFact` to a :class:`DayRollup`, which is what lets the
correctness property — *rollups equal a brute-force recomputation* — be stated
as an assertion about two Python values rather than about two SQL queries.

One fact per sighting
---------------------

:class:`SightingFact` is deliberately the *whole* input: everything any figure
in ``docs/DATA_MODEL.md`` §6.5 depends on, and nothing else. The repository
produces it from one join, the fold reads it, and no other information is
consulted anywhere in between. That is the property the convergence test rests
on — the incremental maintainer and the backfill job differ only in *which*
days they hand to the same fold, never in what the fold is given for a day.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SightingFact:
    """One sighting, reduced to what the daily rollup depends on.

    Args:
        sighting_id: the ``sightings`` row id. Carried so a fact is
            identifiable in a failing assertion, never folded into a figure.
        aircraft_id: the airframe, and the identity distinct counts are taken
            over. The surrogate id rather than the ICAO address, because that
            is what ``sightings`` actually stores (ADR-0004).
        started_ms: when the sighting opened. **This is the instant that
            decides which local day the sighting belongs to** — see
            :mod:`flightsite.analytics.rollup`.
        first_seen_ms: the airframe's first-ever observation. A sighting whose
            airframe was first seen inside the same local day is what makes
            that airframe count toward ``new_aircraft``.
        max_range_nm: the sighting's farthest detection, or ``None`` for a
            sighting that never had a usable position (SPEC §20).
        interesting: whether the sighting carries any alert severity
            (``max_alert_severity IS NOT NULL``, slice 038's column).
        military / government / law_enforcement: SPEC §39's classification
            flags for the airframe, ``False`` where nothing asserts them.
        type_code: the resolved ICAO type designator, or ``None`` when no
            metadata source has claimed one.
        operator_group_id: the curated operator group, or ``None`` when the
            airframe's operator is unknown or no group claims it.
    """

    sighting_id: int
    aircraft_id: int
    started_ms: int
    first_seen_ms: int
    max_range_nm: float | None = None
    interesting: bool = False
    military: bool = False
    government: bool = False
    law_enforcement: bool = False
    type_code: str | None = None
    operator_group_id: int | None = None


@dataclass(frozen=True, slots=True)
class GroupCount:
    """Per-day counts for one type designator or one operator group."""

    sightings: int
    unique_aircraft: int


@dataclass(frozen=True, slots=True)
class DayRollup:
    """Everything §6.5 stores for one receiver-local day.

    ``busiest_hour`` is ``None`` on two distinct occasions and both are honest:
    the day had no sightings at all, or the day is still in progress and §6.5
    reserves this column for the finalized closed-day value.
    """

    day: str
    unique_aircraft: int = 0
    new_aircraft: int = 0
    sightings: int = 0
    interesting: int = 0
    military: int = 0
    government: int = 0
    law_enforcement: int = 0
    max_range_nm: float | None = None
    busiest_hour: int | None = None
    types: dict[str, GroupCount] = field(default_factory=dict)
    operators: dict[int, GroupCount] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        """True when no sighting started on this day."""
        return self.sightings == 0


@dataclass(frozen=True, slots=True)
class TypeStat:
    """Since-T0 totals for one ICAO type designator (§6.5's ``type_stats``)."""

    type_code: str
    unique_aircraft: int
    total_sightings: int
    first_seen_ms: int
    last_seen_ms: int


__all__ = ["DayRollup", "GroupCount", "SightingFact", "TypeStat"]
