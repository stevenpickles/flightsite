"""The load's shape, checked without running the load.

The expensive part of the harness is the pipeline; the part most likely to go
quietly wrong is the *scenario window* it draws traffic from. The demo roster
(slice 011) is deterministic but not fixed forever — a change to its category
weights, its spawn distribution or ``ROSTER_MULTIPLIER`` would move the
plateau, and the harness would carry on reporting healthy figures for a load
that had silently stopped being 500 aircraft.

:func:`flightsite.demo.scenario.batch_at` is pure, so that can be checked
directly, in milliseconds, with no application at all.
"""

from __future__ import annotations

import pytest

from flightsite.demo import DemoAdapter
from flightsite.perf.budgets import TARGET_AIRCRAFT
from flightsite.perf.workload import (
    SUSTAINED_FIRST_TICK,
    SUSTAINED_TICKS,
    TickCost,
    Workload,
    WorkloadConfig,
)

#: Sampling step through the window. Every tick would be thorough and slow for
#: no gain: the population moves smoothly, so a dip between samples of this
#: size cannot be large enough to matter.
STEP = 5


def test_every_tick_of_the_sustained_window_carries_the_target_population() -> None:
    """The window really is a plateau at or above SPEC §5's envelope.

    This is the assumption the whole harness rests on. If it breaks, the
    ``live_population`` hard gate starts failing for a reason that has nothing
    to do with the live store — so failing here instead, with a clear message,
    is worth the millisecond.
    """
    adapter = DemoAdapter(population=TARGET_AIRCRAFT)
    thin = {
        tick: len(adapter.batch_for_tick(tick).updates)
        for tick in range(SUSTAINED_FIRST_TICK, SUSTAINED_FIRST_TICK + SUSTAINED_TICKS, STEP)
        if len(adapter.batch_for_tick(tick).updates) < TARGET_AIRCRAFT
    }
    assert not thin, (
        "the demo scenario no longer holds 500 aircraft across the harness's "
        f"sustained window; thin ticks: {thin}"
    )


def test_the_window_starts_after_the_population_has_climbed() -> None:
    """A window starting at tick 0 would measure an almost-empty live set."""
    adapter = DemoAdapter(population=TARGET_AIRCRAFT)
    assert len(adapter.batch_for_tick(0).updates) < TARGET_AIRCRAFT
    assert len(adapter.batch_for_tick(SUSTAINED_FIRST_TICK).updates) >= TARGET_AIRCRAFT


def test_ticks_wrap_inside_the_window_rather_than_running_off_its_end() -> None:
    """A long run must stay on the plateau, not decay off the far side."""
    workload = Workload(WorkloadConfig())
    for offset in (0, 1, SUSTAINED_TICKS - 1, SUSTAINED_TICKS, SUSTAINED_TICKS * 3 + 7):
        tick = workload.scenario_tick(offset)
        assert SUSTAINED_FIRST_TICK <= tick < SUSTAINED_FIRST_TICK + SUSTAINED_TICKS
    assert workload.scenario_tick(0) == workload.scenario_tick(SUSTAINED_TICKS)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("population", 0),
        ("ticks", 0),
        ("warmup_ticks", -1),
        ("tick_interval_s", 0.0),
    ],
)
def test_an_impossible_configuration_is_rejected_at_construction(field: str, value: object) -> None:
    """Better than measuring nothing and reporting that everything passed."""
    with pytest.raises(ValueError):
        WorkloadConfig(**{field: value})  # type: ignore[arg-type]


def test_the_duty_cycle_is_every_stage_against_the_poll() -> None:
    """The "ingestion keeps up" gate is a sum, not a sample of one stage."""
    cost = TickCost(
        apply_ms=100.0,
        sweep_ms=50.0,
        alerts_ms=25.0,
        persistence_ms=20.0,
        broadcast_ms=5.0,
        population=500,
        events_written=0,
    )
    assert cost.total_ms == 200.0
    assert cost.duty_cycle(1.0) == pytest.approx(0.2)
    # Halving the poll interval doubles the fraction of it consumed.
    assert cost.duty_cycle(0.5) == pytest.approx(0.4)


def test_an_unstarted_workload_refuses_to_hand_out_components() -> None:
    """A None slipping through would surface as an unrelated AttributeError
    somewhere deep in a measurement."""
    workload = Workload(WorkloadConfig())
    for attribute in ("app", "live", "worker", "broadcaster"):
        with pytest.raises(RuntimeError, match="not started"):
            getattr(workload, attribute)
