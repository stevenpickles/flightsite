"""The guard matrix: when a checkpoint and a ``VACUUM`` are allowed to happen.

SPEC §70 permits ``VACUUM`` *only when justified and safe*, and the roadmap's
acceptance criterion is that it "triggers only under justified conditions
(tested)". These are those tests. They run against fabricated statistics
because that is the only honest way to describe a four-gigabyte database that
is 30% dead space, or a card with no room for a second copy of it.

Every condition is checked twice — once just inside the threshold and once just
outside — so a boundary that moves has to move deliberately.
"""

from __future__ import annotations

import pytest

from flightsite.maintenance.model import DatabaseStats
from flightsite.maintenance.policy import (
    VACUUM_MIN_DB_BYTES,
    VACUUM_MIN_FREE_SPACE_FACTOR,
    VACUUM_MIN_RECLAIMABLE_RATIO,
    WAL_CHECKPOINT_THRESHOLD_BYTES,
    VacuumVerdict,
    should_checkpoint,
    vacuum_decision,
)
from tests.maintenance.conftest import PAGE_SIZE, make_stats

#: A database comfortably past the size floor, so a test that is about some
#: *other* condition is not accidentally about the floor.
BIG = 4 * VACUUM_MIN_DB_BYTES

#: Reclaimable fraction comfortably past the ratio floor, for the same reason.
WASTEFUL = VACUUM_MIN_RECLAIMABLE_RATIO + 0.10


def test_a_healthy_wal_is_left_alone() -> None:
    assert should_checkpoint(make_stats(wal_bytes=0)) is False
    assert should_checkpoint(make_stats(wal_bytes=1024)) is False


def test_the_checkpoint_threshold_is_exclusive_at_the_boundary() -> None:
    """Exactly at the threshold is still fine; one byte past it is not.

    The distinction matters because the threshold is compared against a real
    file size every hour: a ``>=`` here would checkpoint a log that is exactly
    the documented size, which is not what "exceeds" means.
    """
    assert should_checkpoint(make_stats(wal_bytes=WAL_CHECKPOINT_THRESHOLD_BYTES)) is False
    assert should_checkpoint(make_stats(wal_bytes=WAL_CHECKPOINT_THRESHOLD_BYTES + 1)) is True


def test_a_small_database_is_never_vacuumed() -> None:
    """Below the size floor the reclaimable space cannot justify a rewrite."""
    stats = make_stats(db_bytes=VACUUM_MIN_DB_BYTES - PAGE_SIZE, reclaimable_ratio=0.90)

    decision = vacuum_decision(stats, under_pressure=False)

    assert decision.verdict is VacuumVerdict.BELOW_SIZE_FLOOR
    assert decision.should_run is False


def test_a_database_at_the_size_floor_is_eligible() -> None:
    stats = make_stats(db_bytes=VACUUM_MIN_DB_BYTES, reclaimable_ratio=WASTEFUL)

    assert vacuum_decision(stats, under_pressure=False).verdict is VacuumVerdict.RUN


def test_a_modest_freelist_is_healthy_not_waste() -> None:
    """Free pages are *reused*; only a persistently large freelist is waste."""
    stats = make_stats(db_bytes=BIG, reclaimable_ratio=VACUUM_MIN_RECLAIMABLE_RATIO / 2)

    decision = vacuum_decision(stats, under_pressure=False)

    assert decision.verdict is VacuumVerdict.LITTLE_RECLAIMABLE
    assert decision.reclaimable_ratio == pytest.approx(VACUUM_MIN_RECLAIMABLE_RATIO / 2, abs=1e-3)


def test_the_reclaimable_ratio_boundary_is_inclusive() -> None:
    """At the documented ratio the rewrite is justified; just below it is not."""
    at_threshold = make_stats(db_bytes=BIG, reclaimable_ratio=VACUUM_MIN_RECLAIMABLE_RATIO)
    below = DatabaseStats(
        page_count=at_threshold.page_count,
        page_size=at_threshold.page_size,
        freelist_count=at_threshold.freelist_count - 1,
        file_bytes=at_threshold.file_bytes,
        wal_bytes=at_threshold.wal_bytes,
        free_bytes=at_threshold.free_bytes,
    )

    just_below = vacuum_decision(below, under_pressure=False)

    assert vacuum_decision(at_threshold, under_pressure=False).verdict is VacuumVerdict.RUN
    assert just_below.verdict is VacuumVerdict.LITTLE_RECLAIMABLE


def test_a_full_card_stops_a_vacuum_that_would_otherwise_run() -> None:
    """``VACUUM`` writes a whole second copy; filling the card would be an outage."""
    stats = make_stats(
        db_bytes=BIG,
        reclaimable_ratio=WASTEFUL,
        free_bytes=int(BIG * VACUUM_MIN_FREE_SPACE_FACTOR) - 1,
    )

    assert (
        vacuum_decision(stats, under_pressure=False).verdict
        is VacuumVerdict.INSUFFICIENT_FREE_SPACE
    )


def test_a_refusal_states_the_gap_not_only_its_name() -> None:
    """Issue #116: ``insufficient_free_space`` alone is not an answer.

    ``VACUUM`` builds a complete second copy, so the requirement scales with
    the database: on a multi-year history it can exceed anything the card will
    ever have free, and the operator cannot tell that apart from a shortfall
    that clears overnight unless both numbers are reported.
    """
    available = int(BIG * VACUUM_MIN_FREE_SPACE_FACTOR) - 1
    stats = make_stats(db_bytes=BIG, reclaimable_ratio=WASTEFUL, free_bytes=available)

    decision = vacuum_decision(stats, under_pressure=False)

    assert decision.verdict is VacuumVerdict.INSUFFICIENT_FREE_SPACE
    assert decision.required_free_bytes == int(BIG * VACUUM_MIN_FREE_SPACE_FACTOR)
    assert decision.free_bytes == available
    assert decision.free_bytes < decision.required_free_bytes


def test_exactly_the_required_free_space_is_enough() -> None:
    stats = make_stats(
        db_bytes=BIG, reclaimable_ratio=WASTEFUL, free_bytes=int(BIG * VACUUM_MIN_FREE_SPACE_FACTOR)
    )

    assert vacuum_decision(stats, under_pressure=False).verdict is VacuumVerdict.RUN


def test_pressure_defers_an_otherwise_justified_vacuum() -> None:
    """A justified rewrite still waits for a quiet moment."""
    stats = make_stats(db_bytes=BIG, reclaimable_ratio=WASTEFUL)

    decision = vacuum_decision(stats, under_pressure=True)

    assert decision.verdict is VacuumVerdict.INGESTION_PRESSURE
    assert decision.should_run is False


def test_a_structural_reason_outranks_a_transient_one() -> None:
    """A database that would never qualify says so, even while under pressure.

    Otherwise an operator asking "why has this never vacuumed?" would be told
    "the receiver was busy" every time, and would go looking for a quiet window
    that would not have helped.
    """
    stats = make_stats(db_bytes=1024, reclaimable_ratio=WASTEFUL)

    assert vacuum_decision(stats, under_pressure=True).verdict is VacuumVerdict.BELOW_SIZE_FLOOR


def test_the_decision_carries_the_measurements_behind_it() -> None:
    """Diagnostics report the numbers, not just the answer."""
    stats = make_stats(db_bytes=BIG, reclaimable_ratio=0.5)

    decision = vacuum_decision(stats, under_pressure=False)

    assert decision.db_bytes == stats.db_bytes
    assert decision.reclaimable_bytes == stats.reclaimable_bytes
    assert decision.reclaimable_ratio == pytest.approx(0.5, abs=1e-3)


def test_an_empty_database_reports_no_reclaimable_fraction() -> None:
    """A file with no pages must not divide by zero on the way to a verdict."""
    stats = DatabaseStats(
        page_count=0, page_size=PAGE_SIZE, freelist_count=0, file_bytes=0, wal_bytes=0, free_bytes=0
    )

    assert stats.reclaimable_ratio == 0.0
    assert vacuum_decision(stats, under_pressure=False).verdict is VacuumVerdict.BELOW_SIZE_FLOOR
