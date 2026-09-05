"""The canonical budget table's own integrity.

``docs/PERFORMANCE.md`` renders :data:`flightsite.perf.budgets.BUDGETS` and
roadmap slice 050 asserts its results against it, so the table is an interface.
These tests guard the properties that interface promises: every SPEC §85 metric
is covered, every hard gate SPEC §85 names is actually hard, headroom is applied
in the right direction, and no budget is silently unenforceable.
"""

from __future__ import annotations

import pytest

from flightsite.perf.budgets import (
    APPLY_CI_HEADROOM,
    BUDGETS,
    CI_HEADROOM,
    DUTY_CYCLE_CI_HEADROOM,
    NO_HEADROOM,
    TARGET_AIRCRAFT,
    TICK_INTERVAL_S,
    Direction,
    GateKind,
    budget_for,
    hard_budgets,
    reference_budgets,
)
from flightsite.perf.measure import Statistic

#: SPEC §85's measurement list, verbatim in substance: "ingestion throughput;
#: live-state update latency; SQLite write latency; SQLite read/query latency;
#: WebSocket distribution; memory use; analytics query latency; startup;
#: unclean-shutdown recovery; multi-year database behavior". The last is roadmap
#: slice 050's scope and deliberately absent here.
SPEC_85_METRICS = frozenset(
    {
        "ingestion throughput",
        "live-state update latency",
        "SQLite write latency",
        "SQLite read/query latency",
        "WebSocket distribution",
        "memory use",
        "analytics query latency",
        "startup",
        "unclean-shutdown recovery",
    }
)

#: SPEC §85's hard-gate list: "ingestion keeps up; 500-aircraft workload remains
#: functional; no live-state stalls; memory below agreed budget; core APIs
#: responsive."
SPEC_85_HARD_GATES = frozenset(
    {
        "ingestion throughput",
        "500-aircraft workload remains functional",
        "live-state update latency",
        "memory use",
        "core APIs responsive",
    }
)


def test_metric_ids_are_unique() -> None:
    """A duplicate id would make one of the two budgets unreachable."""
    ids = [budget.metric for budget in BUDGETS]
    assert len(ids) == len(set(ids))


def test_every_spec_85_metric_has_a_budget() -> None:
    """The table covers SPEC §85's measurement list, less slice 050's part."""
    covered = {budget.spec_metric for budget in BUDGETS}
    assert covered >= SPEC_85_METRICS, f"uncovered: {SPEC_85_METRICS - covered}"


def test_every_spec_85_hard_gate_is_actually_hard() -> None:
    """The hybrid model only means anything if the hard half is enforced."""
    hard = {budget.spec_metric for budget in hard_budgets()}
    assert hard >= SPEC_85_HARD_GATES, f"not gated: {SPEC_85_HARD_GATES - hard}"


def test_the_reference_budgets_are_the_ones_spec_85_lets_be_trended() -> None:
    """Nothing on the hard list may quietly be demoted to a trend."""
    trended = {budget.spec_metric for budget in reference_budgets()}
    assert not (trended & SPEC_85_HARD_GATES)


def test_the_hard_gates_are_the_eleven_documented_ones() -> None:
    """The exact hard set, pinned as ``tests/perf/storage`` pins its three.

    The two checks above are supersets: they catch a SPEC §85 gate being
    demoted, but say nothing about the five rows ``docs/PERFORMANCE.md`` §5.5
    promoted on the recorded Pi baselines. Demoting one of those would restore
    the pre-promotion behaviour — measured, reported, never failing a run — and
    every other test in this module would still pass. Promotion was a decision
    somebody made and wrote down; reversing it has to be one too.
    """
    assert {budget.metric for budget in hard_budgets()} == {
        # SPEC §85's own hard-gate list.
        "live_population",
        "ingest_apply_ms",
        "ingest_duty_cycle",
        "live_sweep_ms",
        "api_live_ms",
        "memory_rss_mib",
        # Promoted in docs/PERFORMANCE.md §5.5, on the §5.4 and §5.5 baselines.
        "ws_fanout_ms",
        "db_read_ms",
        "analytics_query_ms",
        "startup_s",
        "recovery_s",
    }


def test_the_write_cycle_is_the_only_budget_still_trend_tracked() -> None:
    """§5.5 promoted five of the six, and recorded why the sixth was not.

    ``db_write_cycle_ms`` measured 678 ms on a Pi 4 SD card and 57.7 ms on a
    Pi 5 NVMe against a 250 ms budget, so neither reading calibrates it and
    promoting it on the faster one would fail the reference hardware for the
    storage most Pi 4 installs use. Issue #153 is the run that would settle it.
    Pinned in both directions, so neither promoting this row nor quietly adding
    another one beside it happens without a documented decision.
    """
    assert {budget.metric for budget in reference_budgets()} == {"db_write_cycle_ms"}


def test_the_live_population_floor_is_the_spec_5_envelope() -> None:
    budget = budget_for("live_population")
    assert budget.value == float(TARGET_AIRCRAFT)
    assert budget.direction is Direction.FLOOR
    assert budget.gate is GateKind.HARD


def test_headroom_relaxes_ceilings_upward_and_floors_downward() -> None:
    """A single multiplier applied blindly would tighten every floor fivefold."""
    ceiling = budget_for("ingest_apply_ms")
    assert ceiling.direction is Direction.CEILING
    assert ceiling.asserted == ceiling.value * ceiling.ci_headroom
    assert ceiling.asserted > ceiling.value

    floor = budget_for("live_population")
    assert floor.asserted == floor.value / floor.ci_headroom
    assert floor.asserted <= floor.value


def test_satisfaction_respects_the_direction() -> None:
    ceiling = budget_for("ingest_apply_ms")
    assert ceiling.satisfied_by(ceiling.asserted)
    assert ceiling.satisfied_by(0.0)
    assert not ceiling.satisfied_by(ceiling.asserted * 1.01)

    floor = budget_for("live_population")
    assert floor.satisfied_by(floor.asserted)
    assert floor.satisfied_by(floor.value * 2)
    assert not floor.satisfied_by(floor.asserted * 0.99)


@pytest.mark.parametrize("budget", BUDGETS, ids=lambda budget: budget.metric)
def test_every_budget_is_well_formed(budget: object) -> None:
    """Each row can actually be evaluated: positive bound, real headroom, prose."""
    assert isinstance(budget, type(BUDGETS[0]))
    assert budget.value > 0.0
    assert budget.ci_headroom >= NO_HEADROOM
    assert budget.unit
    assert budget.title
    assert budget.rationale.endswith("."), "a rationale is a sentence, not a fragment"
    assert budget.spec_metric


def test_quantity_budgets_carry_no_ci_headroom() -> None:
    """A 1 GB ceiling relaxed fivefold is not a gate, and a deterministic
    population floor does not vary with how loaded the machine is."""
    assert budget_for("memory_rss_mib").ci_headroom == NO_HEADROOM
    assert budget_for("live_population").ci_headroom == NO_HEADROOM


def test_timing_gates_use_the_suite_wide_headroom() -> None:
    """The same allowance tests/alerts/test_perf.py already uses."""
    assert budget_for("api_live_ms").ci_headroom == CI_HEADROOM
    assert budget_for("db_read_ms").ci_headroom == CI_HEADROOM
    assert budget_for("ws_fanout_ms").ci_headroom == CI_HEADROOM


def test_the_two_sized_headrooms_clear_every_flake_on_record() -> None:
    """Issues #166 and #170: the bound has to sit above the runner, not the run.

    Both gates failed release-train runs on shared GitHub runners while their
    medians stayed healthy, which is one contended tick setting a p95 rather
    than a pipeline that got slower. The numbers below are those runs. Pinned
    here because the argument for a non-default multiplier is entirely in them:
    a later edit that tightened either bound back towards the flakes would
    reopen the issues, and one that widened it much further would be asserting
    a bound the product could not fail.
    """
    duty = budget_for("ingest_duty_cycle")
    apply_ = budget_for("ingest_apply_ms")
    assert duty.ci_headroom == DUTY_CYCLE_CI_HEADROOM
    assert apply_.ci_headroom == APPLY_CI_HEADROOM

    # p95 fractions of a poll observed on 2026-09-02 and 2026-09-04, beside
    # medians of 0.08-0.11.
    for flake in (0.539, 0.542, 0.645, 0.73):
        assert duty.satisfied_by(flake), f"{flake} would still flake against {duty.asserted}"
    # p95 milliseconds from the same runs, beside medians of 37-41 ms.
    for flake_ms in (585.0, 658.0):
        assert apply_.satisfied_by(flake_ms), (
            f"{flake_ms} ms would still flake against {apply_.asserted} ms"
        )

    # A regression that doubles the median and carries the tail with it, i.e.
    # the flaking runs at twice their cost, still fails both.
    assert not duty.satisfied_by(0.73 * 2)
    assert not apply_.satisfied_by(658.0 * 2)

    # The budgets themselves — what the Pi is held to in docs/PERFORMANCE.md
    # §5 — are untouched by the widening.
    assert duty.value == 0.5
    assert apply_.value == 100.0


def test_the_apply_gate_stays_inside_the_duty_cycle_it_is_part_of() -> None:
    """The apply is one stage of the sum ``ingest_duty_cycle`` measures (§3.1).

    A component bound above the bound on the whole hot path would be dead
    text: the sum would fail first, every time.
    """
    apply_ms = budget_for("ingest_apply_ms").asserted
    duty_ms = budget_for("ingest_duty_cycle").asserted * TICK_INTERVAL_S * 1_000.0
    assert apply_ms < duty_ms


def test_a_duty_cycle_over_one_poll_can_never_pass() -> None:
    """The gate's whole purpose: a pipeline that cannot keep up must fail.

    Stated explicitly because the budget is a fraction of a poll, so its CI
    headroom is bounded from above by arithmetic rather than by taste: 0.5 x 2
    would assert a whole poll, at which point "ingestion keeps up" would
    tolerate a pipeline that does not. The multiplier is fractional for that
    reason alone: 1.8 asserts 0.9, which clears the worst flake on record by
    1.23x and stays strictly inside the poll being measured.
    """
    budget = budget_for("ingest_duty_cycle")
    assert budget.asserted < 1.0
    assert not budget.satisfied_by(1.0)


def test_budget_for_rejects_an_unknown_metric() -> None:
    with pytest.raises(KeyError):
        budget_for("no_such_metric")


def test_statistics_suit_their_directions() -> None:
    """A floor read off a maximum, or a ceiling off a minimum, would pass
    on a single lucky sample."""
    for budget in BUDGETS:
        if budget.direction is Direction.FLOOR:
            assert budget.statistic in {Statistic.MIN, Statistic.MEDIAN}
        else:
            assert budget.statistic in {
                Statistic.MEDIAN,
                Statistic.MEAN,
                Statistic.P95,
                Statistic.P99,
                Statistic.MAX,
            }
