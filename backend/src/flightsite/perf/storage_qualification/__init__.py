"""Multi-year storage qualification (SPEC §86, roadmap slice 050).

SPEC §86: *"Before v1.0.0, test against a realistic synthetic multi-year
dataset. Verify: database growth; query responsiveness; index behavior;
downsampling; retention pruning; backup size; restore behavior; Pi storage
I/O; analytics performance."*

This package is that test, as a maintained tool rather than a script somebody
ran once:

* :mod:`.scenarios` — the two calibration receivers ``docs/DATA_MODEL.md`` §9
  sizes the product against, as data.
* :mod:`.traffic` — the domain model: diurnal rhythm, aircraft population
  reuse, realistic track lengths. Pure, seeded, database-free.
* :mod:`.generator` — writes that traffic into a real database as the rows the
  persistence worker would have committed.
* :mod:`.budgets` — the storage budget table, in slice 049's hybrid gate model.
* :mod:`.qualify` — generates, probes, prunes, backs up, vacuums, and judges.
* :mod:`.report` — the measurements, verdicts and findings.
* :mod:`.cli` — ``flightsite-storage-qual``, the standalone entry point the
  Raspberry Pi 4 procedure in ``docs/PERFORMANCE.md`` invokes.
"""

from __future__ import annotations

from flightsite.perf.storage_qualification.budgets import (
    STORAGE_BUDGETS,
    hard_storage_budgets,
    reference_storage_budgets,
    storage_budget_for,
)
from flightsite.perf.storage_qualification.generator import (
    GenerationConfig,
    GenerationResult,
    HistoryGenerator,
    TableGrowth,
    generate_history,
)
from flightsite.perf.storage_qualification.qualify import run_qualification
from flightsite.perf.storage_qualification.report import ProbeResult, StorageReport
from flightsite.perf.storage_qualification.scenarios import (
    SCENARIO_A,
    SCENARIO_B,
    SCENARIOS,
    Scenario,
    scenario_for,
)

__all__ = [
    "SCENARIOS",
    "SCENARIO_A",
    "SCENARIO_B",
    "STORAGE_BUDGETS",
    "GenerationConfig",
    "GenerationResult",
    "HistoryGenerator",
    "ProbeResult",
    "Scenario",
    "StorageReport",
    "TableGrowth",
    "generate_history",
    "hard_storage_budgets",
    "reference_storage_budgets",
    "run_qualification",
    "scenario_for",
    "storage_budget_for",
]
