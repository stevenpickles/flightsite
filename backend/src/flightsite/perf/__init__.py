"""The performance harness (SPEC §85, roadmap slice 049).

A repeatable load harness that drives the real application at the SPEC §5
envelope — ~500 concurrent aircraft at a 1 Hz decoder cadence — and measures
the SPEC §85 metric list against the canonical budget table in
:mod:`flightsite.perf.budgets`, which ``docs/PERFORMANCE.md`` renders.

Module map:

===================================== ======================================
Module                                Responsibility
===================================== ======================================
:mod:`~flightsite.perf.measure`       samples, summary statistics, RSS
:mod:`~flightsite.perf.budgets`       the canonical budget table
:mod:`~flightsite.perf.workload`      the real pipeline under 500-aircraft load
:mod:`~flightsite.perf.harness`       running scenarios, judging the report
:mod:`~flightsite.perf.cli`           ``flightsite-perf``
===================================== ======================================

Two ways in, and they measure the same thing:

* ``uv run flightsite-perf --realtime`` on the hardware being qualified — the
  Raspberry Pi 4 procedure in ``docs/PERFORMANCE.md``.
* ``tests/perf/`` in the suite, where a short smoke run enforces the hard gates
  on every PR and ``-m load`` runs the sustained version.

The harness measures; it does not change what it measures. In particular the
"no database on the hot path" invariant (``docs/ARCHITECTURE.md`` §3.1) is a
property the numbers here are evidence *for*, never something the harness may
relax to make a figure look better.
"""

from __future__ import annotations

from flightsite.perf.budgets import (
    BUDGETS,
    CI_HEADROOM,
    NO_HEADROOM,
    TARGET_AIRCRAFT,
    TICK_INTERVAL_S,
    Budget,
    Direction,
    GateKind,
    budget_for,
    hard_budgets,
    reference_budgets,
)
from flightsite.perf.harness import (
    HarnessReport,
    Verdict,
    measure_recovery,
    measure_startup,
    run_harness,
    run_load,
)
from flightsite.perf.measure import Measurement, Statistic, percentile, rss_bytes
from flightsite.perf.workload import TickCost, Workload, WorkloadConfig

__all__ = [
    "BUDGETS",
    "CI_HEADROOM",
    "NO_HEADROOM",
    "TARGET_AIRCRAFT",
    "TICK_INTERVAL_S",
    "Budget",
    "Direction",
    "GateKind",
    "HarnessReport",
    "Measurement",
    "Statistic",
    "TickCost",
    "Verdict",
    "Workload",
    "WorkloadConfig",
    "budget_for",
    "hard_budgets",
    "measure_recovery",
    "measure_startup",
    "percentile",
    "reference_budgets",
    "rss_bytes",
    "run_harness",
    "run_load",
]
