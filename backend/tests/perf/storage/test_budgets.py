"""The storage budget table's own integrity.

Mirrors ``tests/perf/test_budgets.py`` for slice 049's table. A budget table is
data that nothing else validates: a duplicated metric id, a floor with a CI
headroom that makes it looser than stated, or a hard gate nobody measures would
all sit there looking authoritative. These tests are what stop that.
"""

from __future__ import annotations

import pytest

from flightsite.perf.budgets import BUDGETS, CI_HEADROOM, NO_HEADROOM, Budget, Direction, GateKind
from flightsite.perf.storage_qualification.budgets import (
    HIGH_RES_WINDOW_DAYS,
    STORAGE_BUDGETS,
    hard_storage_budgets,
    reference_storage_budgets,
    storage_budget_for,
)
from flightsite.receiver_metrics.service import DEFAULT_HIGH_RES_DAYS

#: SPEC §86's list, which every row must map onto.
SPEC_86_ITEMS = {
    "realistic synthetic multi-year dataset",
    "database growth",
    "query responsiveness",
    "index behavior",
    "downsampling",
    "retention pruning",
    "backup size",
    "restore behavior",
    "Pi storage I/O",
    "analytics performance",
}


def test_metric_ids_are_unique() -> None:
    """Two rows with one id would make ``storage_budget_for`` silently wrong."""
    ids = [budget.metric for budget in STORAGE_BUDGETS]
    assert len(ids) == len(set(ids))


def test_the_two_tables_do_not_share_metric_ids() -> None:
    """A metric measured by both harnesses would report two different things.

    The tables are deliberately separate (see ``budgets.py``); an id colliding
    across them would make a JSON report ambiguous and a doc row unattributable.
    """
    storage = {budget.metric for budget in STORAGE_BUDGETS}
    load = {budget.metric for budget in BUDGETS}
    assert not (storage & load), f"ids used by both budget tables: {storage & load}"


@pytest.mark.parametrize("budget", STORAGE_BUDGETS, ids=lambda budget: budget.metric)
def test_every_budget_answers_a_spec_86_item(budget: Budget) -> None:
    """A budget that answers nothing in SPEC §86 does not belong in this table."""
    assert budget.spec_metric in SPEC_86_ITEMS, (
        f"{budget.metric} claims to cover {budget.spec_metric!r}, which SPEC §86 does not list"
    )


@pytest.mark.parametrize("budget", STORAGE_BUDGETS, ids=lambda budget: budget.metric)
def test_every_budget_explains_itself(budget: Budget) -> None:
    """The rationale is what makes a number reviewable rather than arbitrary."""
    assert len(budget.rationale) > 80, f"{budget.metric} has no real rationale"
    assert budget.unit
    assert budget.title


@pytest.mark.parametrize("budget", STORAGE_BUDGETS, ids=lambda budget: budget.metric)
def test_headroom_is_only_applied_to_durations(budget: Budget) -> None:
    """``docs/PERFORMANCE.md`` §1: a quantity budget gets no CI headroom.

    Relaxing a byte count or a row count fivefold for a busy machine would be
    meaningless — neither varies with load — so only the time-valued budgets
    carry :data:`CI_HEADROOM`.
    """
    time_units = {"ms", "s", "s/GB"}
    if budget.unit in time_units:
        assert budget.ci_headroom in {CI_HEADROOM, NO_HEADROOM}
    else:
        assert budget.ci_headroom == NO_HEADROOM, (
            f"{budget.metric} measures {budget.unit}, which does not vary with machine load"
        )


@pytest.mark.parametrize("budget", STORAGE_BUDGETS, ids=lambda budget: budget.metric)
def test_headroom_always_loosens_never_tightens(budget: Budget) -> None:
    """A ceiling's bound rises with headroom; a floor's falls."""
    if budget.direction is Direction.CEILING:
        assert budget.asserted >= budget.value
    else:
        assert budget.asserted <= budget.value


@pytest.mark.parametrize("budget", STORAGE_BUDGETS, ids=lambda budget: budget.metric)
def test_satisfaction_is_decided_on_the_right_side_of_the_bound(budget: Budget) -> None:
    """``satisfied_by`` must agree with the row's own direction."""
    bound = budget.asserted
    if budget.direction is Direction.CEILING:
        assert budget.satisfied_by(bound)
        assert not budget.satisfied_by(bound * 1.01 + 1e-9)
    else:
        assert budget.satisfied_by(bound)
        assert not budget.satisfied_by(bound * 0.99 - 1e-9)


def test_the_hard_gates_are_the_three_documented_ones() -> None:
    """Hard gating is a deliberate, short list (see ``budgets.py``'s docstring).

    Pinned so that promoting a budget to a hard gate is a decision somebody
    makes and records, not something that happens in passing.
    """
    assert {budget.metric for budget in hard_storage_budgets()} == {
        "dataset_days",
        "metrics_raw_days",
        "downsample_coverage",
    }


def test_latency_budgets_stay_reference_until_a_pi_baseline_exists() -> None:
    """``docs/PERFORMANCE.md`` §5.3 owns promotion, and no Pi 4 run is recorded.

    Slice 049's table says slice 050 *qualifies* ``db_read_ms`` and
    ``analytics_query_ms`` at multi-year scale. Qualifying is not promoting:
    doing the second on a developer machine would state a Pi 4 budget on
    evidence from something that is not a Pi 4.
    """
    for metric in ("history_query_ms", "analytics_scale_ms", "rarity_query_ms", "vacuum_s"):
        assert storage_budget_for(metric).gate is GateKind.REFERENCE


def test_hard_and_reference_partition_the_table() -> None:
    """Every row is exactly one or the other."""
    hard = set(hard_storage_budgets())
    reference = set(reference_storage_budgets())
    assert hard | reference == set(STORAGE_BUDGETS)
    assert not (hard & reference)


def test_the_retention_window_matches_the_products_default() -> None:
    """The gate is stated against the window the product actually applies.

    ADR-0009's default is 14 days and lives in the receiver-metrics service.
    A budget stating a different window would pass or fail for a reason that
    has nothing to do with retention working.
    """
    assert HIGH_RES_WINDOW_DAYS == DEFAULT_HIGH_RES_DAYS


def test_the_window_gate_allows_the_hour_rounding_but_not_a_second_day() -> None:
    """The prune boundary rounds down to an hour start, so a correct prune can
    leave a little over the window standing — and no more."""
    budget = storage_budget_for("metrics_raw_days")
    assert budget.satisfied_by(HIGH_RES_WINDOW_DAYS + 1 / 24)
    assert not budget.satisfied_by(HIGH_RES_WINDOW_DAYS + 2)


def test_lookup_rejects_an_unknown_metric() -> None:
    assert storage_budget_for("dataset_days").metric == "dataset_days"
    with pytest.raises(KeyError):
        storage_budget_for("dataset_dayz")
