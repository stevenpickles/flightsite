"""The harness itself: a short run of the real pipeline, and the hard gates.

This is the in-suite half of SPEC §85's hybrid model. One smoke run of the
whole harness — the real application under demo-driven load at the SPEC §5
envelope — happens on every ordinary test run, and every hard gate is asserted
against it. The sustained version lives in :mod:`tests.perf.test_sustained`
behind the ``load`` marker, and the standalone version is ``flightsite-perf``.

Why a short run still gates honestly
------------------------------------

The gates here are structural, not statistical. A regression that put a
database round trip on the hot path, lost the delta batching in the
broadcaster, or turned an index scan into a table scan would blow through these
bounds on fifteen ticks exactly as it would on six hundred. What a short run
cannot see is slow drift — a leak, a queue that fills over minutes — which is
precisely what the ``load``-marked sustained run and the Pi 4 procedure in
``docs/PERFORMANCE.md`` exist for.

Shape of the fixture
--------------------

The run is built once for the module and every assertion reads it: building it
costs seconds, reading it costs nothing, and a per-test run would put a dozen
full applications through startup for no additional signal.

That makes it module-scoped, which is why it takes an explicit ``data_dir``
from ``tmp_path_factory`` instead of relying on the autouse
``isolated_data_dir`` fixture. Function-scoped fixtures are set up *after*
module-scoped ones, so ``FLIGHTSITE_DATA_DIR`` is not yet pointed anywhere safe
when this runs — an implicit resolution here would put a database wherever the
ambient environment happened to say, up to and including the working tree.
:func:`flightsite.app.create_app` takes the directory directly and skips
environment resolution entirely, so passing it is both safe and exact.

The fixture is synchronous and drives the harness with :func:`asyncio.run`,
because nothing any test here does is asynchronous: they all inspect a finished
report, which is a plain frozen dataclass with no loop affinity.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from flightsite.perf.budgets import BUDGETS, GateKind
from flightsite.perf.harness import HarnessReport, Verdict, run_harness
from flightsite.perf.measure import Measurement
from flightsite.perf.workload import WorkloadConfig

#: A smoke run: the full envelope's *population*, which is what the structural
#: gates depend on, over few enough ticks to keep an ordinary test run quick.
#: Population is never reduced — 500 aircraft is the load being gated, and a
#: run at fifty would measure something the product does not do.
SMOKE = WorkloadConfig(population=500, ticks=15, warmup_ticks=3, ws_clients=2)

#: Every tick is probed, so a fifteen-tick run still yields enough API samples
#: to read a p95 from rather than collapsing it onto the single worst request.
SMOKE_PROBE_EVERY = 1

#: Ticks of traffic the recovery leg builds before abandoning its database.
#: Trimmed from the harness default: recovery cost scales with the number of
#: open sightings, and the in-suite question is whether the repair path runs at
#: all, not what it costs on a Pi's SD card after ten minutes of traffic.
SMOKE_RECOVERY_TICKS = 8

HARD_METRICS = [budget.metric for budget in BUDGETS if budget.gate is GateKind.HARD]


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> HarnessReport:
    """One complete harness run — startup, load and recovery — for the module."""
    data_dir: Path = tmp_path_factory.mktemp("perf-smoke")
    return asyncio.run(
        run_harness(
            SMOKE,
            data_dir=data_dir,
            probe_every=SMOKE_PROBE_EVERY,
            recovery_ticks=SMOKE_RECOVERY_TICKS,
        )
    )


def verdict_for(report: HarnessReport, metric: str) -> Verdict:
    """The verdict for one metric, failing loudly if the table has no such row."""
    for verdict in report.verdicts():
        if verdict.budget.metric == metric:
            return verdict
    raise AssertionError(f"no verdict for {metric}")


def measurement_for(report: HarnessReport, metric: str) -> Measurement:
    measurement = report.measurement(metric)
    assert measurement is not None, f"{metric} was not measured"
    return measurement


def test_the_harness_measures_every_budget_in_the_table(
    report: HarnessReport, capsys: pytest.CaptureFixture[str]
) -> None:
    """A budget nothing measures is a budget nothing enforces.

    Memory is the one permitted gap, and only where the platform has no RSS
    source at all — in which case the report says so rather than reporting a
    zero, which would read as a perfect score.
    """
    with capsys.disabled():
        print("\n" + report.format_table())

    unmeasured = {verdict.budget.metric for verdict in report.verdicts() if not verdict.measured}
    allowed = set() if report.environment.rss_available else {"memory_rss_mib"}
    assert unmeasured <= allowed, f"unmeasured budgets: {unmeasured - allowed}"


def test_the_run_actually_carried_five_hundred_aircraft(report: HarnessReport) -> None:
    """Everything else is meaningless if the load was not the stated load."""
    population = measurement_for(report, "live_population")
    verdict = verdict_for(report, "live_population")
    observed = verdict.observed
    assert observed is not None
    assert verdict.passed, f"live set fell to {observed:.0f} aircraft; {population.summary}"


@pytest.mark.parametrize("metric", HARD_METRICS)
def test_each_hard_gate_holds(report: HarnessReport, metric: str) -> None:
    """SPEC §85's hard-gate list, one assertion each.

    Parametrized rather than looped so a failure names the budget that broke
    instead of stopping at the first one checked.
    """
    verdict = verdict_for(report, metric)
    if not verdict.measured:
        pytest.skip(f"{metric} is not measurable on this platform")
    measurement = measurement_for(report, metric)
    observed = verdict.observed
    assert observed is not None
    assert verdict.passed, (
        f"{metric}: {verdict.budget.statistic.value} was {observed:.3g} "
        f"{verdict.budget.unit} against a bound of {verdict.budget.asserted:.3g} "
        f"({verdict.budget.value:.3g} budget x {verdict.budget.ci_headroom} CI headroom); "
        f"{measurement.summary}"
    )


def test_the_report_agrees_with_its_own_verdicts(report: HarnessReport) -> None:
    """``passed`` is the conjunction of the measured hard gates, nothing looser."""
    expected = all(
        verdict.passed for verdict in report.verdicts() if verdict.budget.hard and verdict.measured
    )
    assert report.passed is expected
    assert report.failures() == tuple(
        verdict
        for verdict in report.verdicts()
        if verdict.budget.hard and verdict.measured and not verdict.passed
    )


def test_a_reference_budget_never_fails_the_run(report: HarnessReport) -> None:
    """The trend half of the hybrid model.

    Asserted structurally rather than by hoping a reference budget happens to
    be crossed on the day: whatever the numbers, nothing trend-tracked may
    appear among the failures.
    """
    for verdict in report.verdicts():
        if not verdict.budget.hard:
            assert verdict not in report.failures()


def test_the_json_form_round_trips_every_metric(report: HarnessReport) -> None:
    """Trend tracking across runs reads this, not the printed table."""
    payload = report.to_dict()
    assert payload["config"]["population"] == SMOKE.population
    assert payload["passed"] is report.passed
    for measurement in report.measurements:
        assert payload["metrics"][measurement.metric]["count"] == measurement.count
    for budget in BUDGETS:
        assert payload["verdicts"][budget.metric]["gate"] == budget.gate.value
        assert payload["verdicts"][budget.metric]["bound"] == budget.asserted


def test_the_formatted_table_is_ascii_only(report: HarnessReport) -> None:
    """It is printed to whatever console a machine being qualified has."""
    table = report.format_table()
    assert table.isascii(), "the report table must survive a serial console"
    for budget in BUDGETS:
        assert budget.metric in table


def test_startup_and_recovery_were_measured_on_their_own_terms(
    report: HarnessReport,
) -> None:
    """Both are single-shot measurements of a process that is not yet serving.

    Recorded here because they are easy to lose: a refactor that folded them
    into the tick loop would still produce numbers, but they would be numbers
    about a running process rather than a starting one.
    """
    startup = measurement_for(report, "startup_s")
    recovery = measurement_for(report, "recovery_s")
    assert startup.count == 1
    assert recovery.count == 1
    assert "open sightings" in recovery.note
