"""The sustained run: 500 aircraft at 1 Hz for long enough to see drift.

Marked ``load`` and therefore **excluded from the default suite** — the one
marker in this repo that is, and the reason is in ``pyproject.toml``: a run
long enough to be called sustained is minutes of wall clock, and in
``--realtime`` mode it is bounded by the clock rather than by the CPU, so no
amount of hardware makes it quick.

    uv run pytest -m load

What this adds over :mod:`tests.perf.test_harness`
--------------------------------------------------

The smoke run catches structural regressions; it runs for fifteen ticks and
cannot, even in principle, see anything that develops slowly. Two properties
here need duration and get it:

* **Memory does not drift.** SPEC §5's "comfortably below 1 GB" is a claim
  about a process that has been running, not one that has just started. The
  live set, its per-aircraft tracks and the metadata cache all reach steady
  state only after the population has turned over.
* **The pipeline does not fall behind.** A duty cycle measured over hundreds of
  ticks includes the expensive ones — the persistence flush interval, the
  scenario wrapping a large slice of the live set out and back in — that a
  short run may miss entirely.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from flightsite.perf.budgets import GateKind
from flightsite.perf.harness import HarnessReport, run_harness
from flightsite.perf.measure import Statistic
from flightsite.perf.workload import SUSTAINED_TICKS, WorkloadConfig

pytestmark = pytest.mark.load

#: Long enough to cross the persistence flush interval many times and to wrap
#: the demo scenario's sustained window at least once, so the run includes the
#: harshest ticks the scenario produces rather than only the calm ones.
SUSTAINED = WorkloadConfig(
    population=500,
    ticks=SUSTAINED_TICKS + 200,
    warmup_ticks=20,
    ws_clients=4,
)

#: Fraction of the run treated as the "early" window when checking for memory
#: drift. Comparing the first fifth against the last fifth is a coarse test,
#: deliberately: it is looking for a leak, not measuring an allocator.
DRIFT_WINDOW = 5

#: How much the late memory window may exceed the early one.
#:
#: Generous on purpose, because a large part of the growth across a run is
#: real and expected: the live store keeps an aircraft for 60 s after it stops
#: transmitting, so the resident population climbs from the batch size (~520)
#: towards ~790 and then plateaus, and the per-aircraft tracks and metadata
#: cache grow with it. Memory tracking a live set that is still filling is not
#: a leak.
#:
#: What this bound is for is unbounded growth, which by definition does not
#: plateau and blows through any constant factor. The *absolute* ceiling —
#: 1 GB, a hard gate — is what actually protects the budget; this is the
#: coarse shape check beside it.
DRIFT_ALLOWANCE = 2.5


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> HarnessReport:
    """One sustained run, shared by the whole module (see test_harness.py)."""
    data_dir: Path = tmp_path_factory.mktemp("perf-sustained")
    return asyncio.run(run_harness(SUSTAINED, data_dir=data_dir))


def test_the_sustained_run_reports(
    report: HarnessReport, capsys: pytest.CaptureFixture[str]
) -> None:
    """Print the table: on a qualification run this output *is* the artifact."""
    with capsys.disabled():
        print("\n" + report.format_table())
    assert report.measurement("live_population") is not None


def test_every_hard_gate_holds_over_the_full_run(report: HarnessReport) -> None:
    """The same gates as the smoke run, over hundreds of ticks instead of fifteen."""
    failures = [
        f"{verdict.budget.metric}: {verdict.observed:.3g} {verdict.budget.unit} "
        f"against {verdict.budget.asserted:.3g}"
        for verdict in report.failures()
    ]
    assert not failures, "; ".join(failures)


def test_memory_does_not_drift_across_the_run(report: HarnessReport) -> None:
    """A leak shows as the late window sitting far above the early one."""
    memory = report.measurement("memory_rss_mib")
    if memory is None:
        pytest.skip("no RSS source on this platform")

    window = max(1, memory.count // DRIFT_WINDOW)
    early = sorted(memory.samples[:window])[window // 2]
    late = sorted(memory.samples[-window:])[window // 2]
    assert late <= early * DRIFT_ALLOWANCE, (
        f"resident memory grew from {early:.0f} MiB to {late:.0f} MiB across "
        f"{report.config.ticks} ticks; {memory.summary}"
    )


def test_the_live_path_never_spends_a_whole_poll_on_one_tick(report: HarnessReport) -> None:
    """The "no live-state stalls" gate, read at the worst tick rather than the p95.

    Deliberately asserted against the *live* stages — the batch apply and the
    lifecycle sweep — and not against ``ingest_duty_cycle``, which would be the
    obvious choice and would be wrong.

    The duty cycle sums every stage because this harness drives them serially,
    and one tick in thirty includes the persistence worker's periodic flush
    (``flush_interval_s`` is 30 s), which rewrites several hundred sightings and
    on a dev machine takes well over a second. In the running product that work
    is on a separate task and cannot block ``live.apply`` (ADR-0008,
    ``docs/ARCHITECTURE.md`` §3.1), so it delays the next *write*, not the next
    *observation*. Asserting the summed maximum under a poll would therefore be
    asserting something the architecture does not claim, and it would fail on a
    healthy system.

    What must hold at every tick, with no exceptions and no averaging, is that
    the memory-only live path keeps up: if applying a batch and ageing the live
    set ever took a whole poll, the live picture really would be a backlog.
    """
    apply_ms = report.measurement("ingest_apply_ms")
    sweep_ms = report.measurement("live_sweep_ms")
    assert apply_ms is not None and sweep_ms is not None

    poll_ms = report.config.tick_interval_s * 1_000.0
    worst = apply_ms.statistic(Statistic.MAX) + sweep_ms.statistic(Statistic.MAX)
    assert worst < poll_ms, (
        f"the live path's worst tick cost {worst:.0f} ms of a {poll_ms:.0f} ms poll; "
        f"apply {apply_ms.summary}; sweep {sweep_ms.summary}"
    )


def test_the_reference_budgets_were_all_collected(report: HarnessReport) -> None:
    """A qualification run has to produce every trended figure, or the Pi 4
    baselines recorded from it would have holes."""
    missing = [
        verdict.budget.metric
        for verdict in report.verdicts()
        if verdict.budget.gate is GateKind.REFERENCE and not verdict.measured
    ]
    assert not missing, f"not measured: {missing}"
