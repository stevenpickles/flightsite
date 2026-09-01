"""The fold: one local day's sightings in, one ``daily_stats`` row out.

This module is the arithmetic half of slice 031 and it is deliberately pure —
no database, no clock, no configuration beyond the zone it is told to bucket
hours in. Every figure ``docs/DATA_MODEL.md`` §6.5 stores has its correct
answer computed here, so the slice's headline acceptance criterion — *"rollups
match brute-force recomputation on fixture data"* — is a property of a function
that can be handed randomized fixtures directly.

Which day a sighting belongs to
-------------------------------

**The receiver-local day its ``started_ms`` falls in.** A sighting that opens at
23:50 and closes at 00:20 counts once, on the day it opened, and it is not
split. Three reasons this is the right rule and not merely a convenient one:

* It is the rule the schema is already indexed for. §6.5's own note on "most
  frequently seen aircraft" describes that query as a ``GROUP BY aircraft_id``
  over ``ix_sightings_started``, which is a statement that a window of
  sightings is a range of ``started_ms``. A day-overlap rule would need a
  different index and would make a 30-day window read 31 days of rows.
* It makes every figure on the row a total function of one contiguous key
  range, which is what makes a rebuild cheap and exactly reproducible.
* It matches what a person means. "How many aircraft did I see yesterday" is
  about the sightings that *began* yesterday; attributing four minutes of a
  flight to today because it crossed midnight would make "unique aircraft" sum
  to more than the aircraft actually heard.

The rule is applied by the caller — the repository selects a day's facts by
``started_ms`` range — and restated here because the fold's hour bucketing
depends on it: :func:`fold_day` buckets by the local hour of ``started_ms``,
which is guaranteed to be inside the day being folded.

Idempotence, and why there is no accumulator
--------------------------------------------

:func:`fold_day` is a **total function of the facts in the bucket**, exactly as
slice 033's :func:`~flightsite.receiver_metrics.aggregate.summarize` is of its
raw samples, and the writer replaces the day's rows rather than adding to them.
Nothing accumulates, so nothing can accumulate twice — a rebuild interrupted by
a crash, a flush retried after a failed write, and an incremental update that
races a backfill all converge on the same rows.

Busiest hour
------------

The local hour in which the most sightings started, ties broken by the earliest
hour. It is only ever written for a **closed** day (§6.5: the in-progress day's
busiest hour comes from slice 033's ``receiver_metrics_hourly`` instead), which
is why :func:`fold_day` takes ``closed`` rather than deciding for itself: "is
this day over" is a question about the clock, and this module does not have one.

A fall-back day has 25 local hours and two of them are called the same number;
their sightings land in the same bucket, which is what the local wall clock
says and therefore what a reader of "busiest hour: 1am" expects. A
spring-forward day simply has no sightings in the hour that did not happen.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from zoneinfo import ZoneInfo

from flightsite.analytics.bucketing import HOURS_PER_DAY, local_day, local_hour
from flightsite.analytics.model import DayRollup, GroupCount, SightingFact


def busiest_hour(facts: Iterable[SightingFact], zone: ZoneInfo) -> int | None:
    """The local hour with the most sighting starts, or ``None`` for no starts.

    Ties go to the earliest hour: an arbitrary but *stable* choice, so two
    rebuilds of the same day can never disagree.
    """
    counts = [0] * HOURS_PER_DAY
    total = 0
    for fact in facts:
        counts[local_hour(fact.started_ms, zone)] += 1
        total += 1
    if total == 0:
        return None
    return max(range(HOURS_PER_DAY), key=lambda hour: (counts[hour], -hour))


def fold_day(
    day: str,
    facts: Iterable[SightingFact],
    *,
    zone: ZoneInfo,
    closed: bool,
) -> DayRollup:
    """Reduce one local day's sightings to the row §6.5 stores.

    Args:
        day: the receiver-local date being folded, ``YYYY-MM-DD``.
        facts: every sighting that *started* on that day. Order is irrelevant —
            the result is a function of the set.
        zone: the receiver's IANA zone, used only to bucket ``busiest_hour``.
        closed: whether the day is over. ``busiest_hour`` is written only when
            it is; see the module docstring.

    Returns:
        The rollup. A day with no facts folds to an all-zero row with
        ``max_range_nm`` and ``busiest_hour`` ``None`` — which is the correct
        row for a day the receiver was switched off, and is why the writer can
        replace a day's rows unconditionally.
    """
    materialized = list(facts)

    aircraft: set[int] = set()
    new_aircraft: set[int] = set()
    interesting = military = government = law_enforcement = 0
    max_range_nm: float | None = None
    type_aircraft: dict[str, set[int]] = {}
    type_sightings: dict[str, int] = {}
    operator_aircraft: dict[int, set[int]] = {}
    operator_sightings: dict[int, int] = {}

    for fact in materialized:
        aircraft.add(fact.aircraft_id)
        # "First-ever seen this day" is a statement about the airframe, not
        # about this sighting: an aircraft first heard at 08:00 and heard again
        # at 14:00 is one new aircraft, not two.
        if _same_day(fact.first_seen_ms, fact.started_ms, zone, day):
            new_aircraft.add(fact.aircraft_id)
        interesting += fact.interesting
        military += fact.military
        government += fact.government
        law_enforcement += fact.law_enforcement
        if fact.max_range_nm is not None and (
            max_range_nm is None or fact.max_range_nm > max_range_nm
        ):
            max_range_nm = fact.max_range_nm
        if fact.type_code is not None:
            type_sightings[fact.type_code] = type_sightings.get(fact.type_code, 0) + 1
            type_aircraft.setdefault(fact.type_code, set()).add(fact.aircraft_id)
        if fact.operator_group_id is not None:
            group = fact.operator_group_id
            operator_sightings[group] = operator_sightings.get(group, 0) + 1
            operator_aircraft.setdefault(group, set()).add(fact.aircraft_id)

    return DayRollup(
        day=day,
        unique_aircraft=len(aircraft),
        new_aircraft=len(new_aircraft),
        sightings=len(materialized),
        interesting=interesting,
        military=military,
        government=government,
        law_enforcement=law_enforcement,
        max_range_nm=max_range_nm,
        busiest_hour=busiest_hour(materialized, zone) if closed else None,
        types=_counts(type_sightings, type_aircraft),
        operators=_counts(operator_sightings, operator_aircraft),
    )


def _same_day(first_seen_ms: int, started_ms: int, zone: ZoneInfo, day: str) -> bool:
    """Whether the airframe's first-ever observation was on ``day``.

    Compared by *calendar date* rather than by the window bounds, because a
    fact is only ever folded into the day its ``started_ms`` falls in: if the
    airframe's first observation shares that date, the airframe is new today.
    The cheap identity check first is not micro-optimization — a first sighting
    is the common case for a new airframe, and it avoids two zone conversions.
    """
    if first_seen_ms == started_ms:
        return True
    return local_day(first_seen_ms, zone) == day


def _counts[K](sightings: Mapping[K, int], aircraft: Mapping[K, set[int]]) -> dict[K, GroupCount]:
    """Zip the two parallel tallies into one count per key."""
    return {
        key: GroupCount(sightings=count, unique_aircraft=len(aircraft[key]))
        for key, count in sorted(sightings.items(), key=lambda item: str(item[0]))
    }


__all__ = ["busiest_hour", "fold_day"]
