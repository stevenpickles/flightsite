"""Automated, conservative database maintenance (SPEC §70, slice 044).

Five jobs on one low-frequency task: an integrity check, a retention-pruning
executor, ``PRAGMA optimize``, WAL checkpoint management, and a heavily guarded
``VACUUM``. Everything is automatic and every threshold is a module constant —
SPEC §70's *no routine user babysitting* means this slice adds no configuration
key and no user-facing control.

* :mod:`flightsite.maintenance.service` — the scheduler and the job bodies.
* :mod:`flightsite.maintenance.policy` — the thresholds, and the pure decisions
  that read them.
* :mod:`flightsite.maintenance.retention` — the prunable domains, and the
  documented boundary against the ones that prune themselves.
* :mod:`flightsite.maintenance.stats` — measuring the database file.
* :mod:`flightsite.maintenance.model` — the report slice 042's diagnostics
  surface reads.
"""

from __future__ import annotations

from flightsite.maintenance.model import (
    CHECKPOINT_JOB,
    JOB_NAMES,
    OPTIMIZE_JOB,
    QUICK_CHECK_JOB,
    RETENTION_JOB,
    VACUUM_JOB,
    DatabaseStats,
    JobDetail,
    JobOutcome,
    JobReport,
    JobResult,
    MaintenanceReport,
    QuickCheckOutcome,
    VacuumRefusal,
)
from flightsite.maintenance.policy import (
    VACUUM_MAX_LIVE_AIRCRAFT,
    VACUUM_MIN_DB_BYTES,
    VACUUM_MIN_FREE_SPACE_FACTOR,
    VACUUM_MIN_RECLAIMABLE_RATIO,
    WAL_CHECKPOINT_THRESHOLD_BYTES,
    VacuumDecision,
    VacuumVerdict,
    should_checkpoint,
    vacuum_decision,
)
from flightsite.maintenance.retention import ROUTE_CACHE_TASK, RetentionTask, RouteCachePruner
from flightsite.maintenance.service import (
    CHECKPOINT_INTERVAL_MS,
    DEFAULT_CYCLE_INTERVAL_S,
    OPTIMIZE_INTERVAL_MS,
    QUICK_CHECK_INTERVAL_MS,
    RETENTION_INTERVAL_MS,
    VACUUM_INTERVAL_MS,
    MaintenanceService,
)
from flightsite.maintenance.stats import gather_stats, wal_path

__all__ = [
    "CHECKPOINT_INTERVAL_MS",
    "CHECKPOINT_JOB",
    "DEFAULT_CYCLE_INTERVAL_S",
    "JOB_NAMES",
    "OPTIMIZE_INTERVAL_MS",
    "OPTIMIZE_JOB",
    "QUICK_CHECK_INTERVAL_MS",
    "QUICK_CHECK_JOB",
    "RETENTION_INTERVAL_MS",
    "RETENTION_JOB",
    "ROUTE_CACHE_TASK",
    "VACUUM_INTERVAL_MS",
    "VACUUM_JOB",
    "VACUUM_MAX_LIVE_AIRCRAFT",
    "VACUUM_MIN_DB_BYTES",
    "VACUUM_MIN_FREE_SPACE_FACTOR",
    "VACUUM_MIN_RECLAIMABLE_RATIO",
    "WAL_CHECKPOINT_THRESHOLD_BYTES",
    "DatabaseStats",
    "JobDetail",
    "JobOutcome",
    "JobReport",
    "JobResult",
    "MaintenanceReport",
    "MaintenanceService",
    "QuickCheckOutcome",
    "RetentionTask",
    "RouteCachePruner",
    "VacuumDecision",
    "VacuumRefusal",
    "VacuumVerdict",
    "gather_stats",
    "should_checkpoint",
    "vacuum_decision",
    "wal_path",
]
