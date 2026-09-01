"""The fold, against an independent brute-force recomputation.

Slice 031's headline acceptance criterion: *"rollups match brute-force
recomputation on fixture data (property test)"*. The property is asserted at
two levels, because a mismatch at either would be a different bug:

* **The pure fold** — :func:`~flightsite.analytics.rollup.fold_day` against
  :func:`~tests.analytics.conftest.brute_force_day` over randomized worlds, in
  both a DST zone and an odd-offset one.
* **The stored rows** — what a rebuild actually wrote to the four tables,
  against the same brute force. That is what catches a repository bug (a join
  that drops an unclassified airframe, a breakdown row that is not replaced)
  which a pure-function test cannot see.

The brute force is deliberately written in a different shape from the
implementation; :mod:`tests.analytics.conftest` says why.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from flightsite.analytics.bucketing import day_bounds_ms
from flightsite.analytics.model import DayRollup, GroupCount, SightingFact
from flightsite.analytics.repository import AnalyticsRepository
from flightsite.analytics.rollup import busiest_hour, fold_day
from flightsite.db import Database

from .conftest import KOLKATA, NEW_YORK, brute_force_day, seed_random_world, stored_rollup

#: A handful of seeds rather than one: the property should hold for any world,
#: and a single fixture would only ever exercise one arrangement of ties,
#: absent metadata and repeat visits.
SEEDS = (1, 7, 42, 1_009)

#: The two zones every correctness property is asserted in — a DST zone and a
#: half-hour-offset one (``docs/DATA_MODEL.md`` §10).
ZONES = (NEW_YORK, KOLKATA)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("zone_name", ZONES)
async def test_the_fold_matches_brute_force_on_a_randomized_world(
    database: Database, repository: AnalyticsRepository, seed: int, zone_name: str
) -> None:
    zone = ZoneInfo(zone_name)
    world = await seed_random_world(database, seed, zone=zone, days=6, sightings=120)

    for day in world.days():
        start_ms, end_ms = day_bounds_ms(day, zone)
        facts = await repository.facts_between(start_ms, end_ms)

        folded = fold_day(day, facts, zone=zone, closed=True)

        assert folded == brute_force_day(world, day, closed=True), day


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("zone_name", ZONES)
async def test_the_stored_rows_match_brute_force_on_a_randomized_world(
    database: Database, repository: AnalyticsRepository, seed: int, zone_name: str
) -> None:
    """What actually reached the four tables, not just what the fold computed."""
    zone = ZoneInfo(zone_name)
    world = await seed_random_world(database, seed, zone=zone, days=6, sightings=120)

    for day in world.days():
        start_ms, end_ms = day_bounds_ms(day, zone)
        await repository.replace_day(
            fold_day(day, await repository.facts_between(start_ms, end_ms), zone=zone, closed=True)
        )

    for day in world.days():
        assert await stored_rollup(repository, day) == brute_force_day(world, day, closed=True)


@pytest.mark.parametrize("zone_name", ZONES)
async def test_a_dst_transition_day_folds_the_hours_it_actually_had(
    database: Database, repository: AnalyticsRepository, zone_name: str
) -> None:
    """The randomized worlds are placed inside real day bounds, so a 23- or
    25-hour day carries exactly as many sightings as its length allows."""
    zone = ZoneInfo(zone_name)
    world = await seed_random_world(
        database, 3, zone=zone, first_day="2026-11-01", days=3, sightings=150
    )

    for day in world.days():
        start_ms, end_ms = day_bounds_ms(day, zone)
        facts = await repository.facts_between(start_ms, end_ms)
        folded = fold_day(day, facts, zone=zone, closed=True)

        assert folded.sightings == sum(
            1 for row in world.sightings if start_ms <= row.started_ms < end_ms
        )
        assert folded == brute_force_day(world, day, closed=True)


# ------------------------------------------------------------- the fold itself


def _fact(
    sighting_id: int,
    aircraft_id: int,
    started_ms: int,
    *,
    first_seen_ms: int | None = None,
    max_range_nm: float | None = None,
    type_code: str | None = None,
    operator_group_id: int | None = None,
) -> SightingFact:
    """One fact, defaulting an airframe's first observation to this sighting."""
    return SightingFact(
        sighting_id=sighting_id,
        aircraft_id=aircraft_id,
        started_ms=started_ms,
        first_seen_ms=started_ms if first_seen_ms is None else first_seen_ms,
        max_range_nm=max_range_nm,
        type_code=type_code,
        operator_group_id=operator_group_id,
    )


def test_a_day_with_no_sightings_folds_to_an_all_zero_row() -> None:
    """The correct row for a day the receiver was off — not an absent one."""
    rollup = fold_day("2026-06-02", (), zone=ZoneInfo(NEW_YORK), closed=True)

    assert rollup == DayRollup(day="2026-06-02")
    assert rollup.empty is True


def test_an_aircraft_seen_twice_in_a_day_is_two_sightings_and_one_airframe() -> None:
    zone = ZoneInfo(NEW_YORK)
    start_ms = day_bounds_ms("2026-06-02", zone)[0]
    facts = (
        _fact(1, 10, start_ms + 3_600_000),
        _fact(2, 10, start_ms + 7_200_000, first_seen_ms=start_ms + 3_600_000),
    )

    rollup = fold_day("2026-06-02", facts, zone=zone, closed=True)

    assert (rollup.sightings, rollup.unique_aircraft, rollup.new_aircraft) == (2, 1, 1)


def test_an_airframe_first_seen_on_an_earlier_day_is_not_new_today() -> None:
    zone = ZoneInfo(NEW_YORK)
    yesterday_ms = day_bounds_ms("2026-06-01", zone)[0]
    today_ms = day_bounds_ms("2026-06-02", zone)[0]
    facts = (_fact(1, 10, today_ms + 60_000, first_seen_ms=yesterday_ms + 60_000),)

    rollup = fold_day("2026-06-02", facts, zone=zone, closed=True)

    assert (rollup.unique_aircraft, rollup.new_aircraft) == (1, 0)


def test_an_absent_max_range_does_not_beat_a_present_one() -> None:
    """A Mode S-only sighting (SPEC §20) contributes no range at all."""
    zone = ZoneInfo(NEW_YORK)
    start_ms = day_bounds_ms("2026-06-02", zone)[0]
    facts = (
        _fact(1, 10, start_ms, max_range_nm=None),
        _fact(2, 11, start_ms + 1_000, max_range_nm=41.5),
        _fact(3, 12, start_ms + 2_000, max_range_nm=None),
    )

    assert fold_day("2026-06-02", facts, zone=zone, closed=True).max_range_nm == pytest.approx(41.5)


def test_an_unresolved_type_and_operator_contribute_to_no_breakdown_row() -> None:
    """§2.7: unknown is unknown, not a bucket."""
    zone = ZoneInfo(NEW_YORK)
    start_ms = day_bounds_ms("2026-06-02", zone)[0]
    facts = (
        _fact(1, 10, start_ms, type_code=None, operator_group_id=None),
        _fact(2, 11, start_ms + 1_000, type_code="B738", operator_group_id=4),
    )

    rollup = fold_day("2026-06-02", facts, zone=zone, closed=True)

    assert rollup.sightings == 2
    assert rollup.types == {"B738": GroupCount(sightings=1, unique_aircraft=1)}
    assert rollup.operators == {4: GroupCount(sightings=1, unique_aircraft=1)}


def test_busiest_hour_is_written_only_for_a_closed_day() -> None:
    """§6.5 reserves the column for the finalized value; the live day is null."""
    zone = ZoneInfo(NEW_YORK)
    start_ms = day_bounds_ms("2026-06-02", zone)[0]
    facts = (_fact(1, 10, start_ms + 5 * 3_600_000),)

    assert fold_day("2026-06-02", facts, zone=zone, closed=True).busiest_hour == 5
    assert fold_day("2026-06-02", facts, zone=zone, closed=False).busiest_hour is None


def test_busiest_hour_breaks_a_tie_toward_the_earlier_hour() -> None:
    """Arbitrary, but stable: two rebuilds must never disagree."""
    zone = ZoneInfo(NEW_YORK)
    start_ms = day_bounds_ms("2026-06-02", zone)[0]
    facts = (
        _fact(1, 10, start_ms + 3 * 3_600_000),
        _fact(2, 11, start_ms + 9 * 3_600_000),
    )

    assert busiest_hour(facts, zone) == 3
    assert busiest_hour(reversed(facts), zone) == 3


def test_busiest_hour_of_a_fall_back_day_counts_both_passes_of_the_repeated_hour() -> None:
    """The wall clock said 01:xx twice; a reader of "busiest hour: 1am" means both."""
    zone = ZoneInfo(NEW_YORK)
    start_ms = day_bounds_ms("2026-11-01", zone)[0]
    facts = (
        _fact(1, 10, start_ms + 3_600_000),  # first 01:00 EDT
        _fact(2, 11, start_ms + 2 * 3_600_000),  # second 01:00, now EST
        _fact(3, 12, start_ms + 5 * 3_600_000),
    )

    assert busiest_hour(facts, zone) == 1


def test_the_fold_is_a_function_of_the_set_not_of_the_order() -> None:
    zone = ZoneInfo(KOLKATA)
    start_ms = day_bounds_ms("2026-06-02", zone)[0]
    facts = [
        _fact(index, index % 3, start_ms + index * 900_000, type_code="A320")
        for index in range(1, 12)
    ]

    assert fold_day("2026-06-02", facts, zone=zone, closed=True) == fold_day(
        "2026-06-02", reversed(facts), zone=zone, closed=True
    )
