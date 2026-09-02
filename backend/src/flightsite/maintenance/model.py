"""What a maintenance cycle produces: job outcomes, database statistics, report.

Everything here is a frozen, JSON-shaped value object. The
:class:`MaintenanceReport` the service retains is read by slice 042's
diagnostics surface, so it holds only primitives, enums with string values, and
mappings of the two — never a live handle, a session, or a callable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

#: What a job measured, in a shape that serializes as-is. Deliberately a plain
#: mapping of scalars rather than a per-job dataclass: every job reports
#: something different, and slice 042's diagnostics surface renders it as
#: key/value pairs either way.
JobDetail = Mapping[str, str | int | float]

#: Job name: ``PRAGMA quick_check`` (SPEC §70's *integrity checking*).
QUICK_CHECK_JOB: Final = "quick_check"

#: Job name: ``PRAGMA optimize`` (SPEC §70's *SQLite optimization*).
OPTIMIZE_JOB: Final = "optimize"

#: Job name: WAL checkpoint management.
CHECKPOINT_JOB: Final = "wal_checkpoint"

#: Job name: the retention-pruning executor (SPEC §70's *retention pruning*).
RETENTION_JOB: Final = "retention"

#: Job name: the guarded ``VACUUM`` (SPEC §70's *only when justified and safe*).
VACUUM_JOB: Final = "vacuum"

#: Every job the service schedules, in the order a cycle attempts them.
JOB_NAMES: Final[tuple[str, ...]] = (
    QUICK_CHECK_JOB,
    RETENTION_JOB,
    OPTIMIZE_JOB,
    CHECKPOINT_JOB,
    VACUUM_JOB,
)


class JobOutcome(StrEnum):
    """How one attempt at one job ended.

    ``SKIPPED`` is a first-class success, not a near-failure: the guarded
    ``VACUUM`` declining to run because the reclaimable space does not justify
    it is the policy working, and a diagnostics reader must be able to tell
    that apart from a ``VACUUM`` that was tried and failed.
    """

    OK = "ok"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class JobResult:
    """The value a job body returns: an outcome plus whatever it measured."""

    outcome: JobOutcome
    detail: JobDetail = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JobReport:
    """The last attempt at one job, as diagnostics sees it."""

    name: str
    outcome: JobOutcome
    started_ms: int
    duration_ms: int
    detail: JobDetail = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QuickCheckOutcome:
    """The retained result of the most recent integrity check.

    Retained even — especially — when it failed: SPEC §70 asks for *useful
    diagnostics*, and the rows ``PRAGMA quick_check`` returned are the only
    description of the damage FlightSite has.
    """

    healthy: bool
    checked_ms: int
    rows: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class VacuumRefusal:
    """Why the last ``VACUUM`` attempt declined to run, with its measurements.

    The guard's verdict has always been in the job's diagnostics detail, but as
    a bare word: an operator asking "why has this never vacuumed?" read
    ``insufficient_free_space`` and had no way to see whether the shortfall was
    a gigabyte or a hundred. That matters because ``VACUUM`` builds a complete
    second copy, so the requirement scales with the database — on a multi-year
    history it can exceed anything the card will ever have free, and the one
    mechanism that reclaims freelist space is then refused permanently rather
    than until tonight (``docs/PERFORMANCE.md`` §7.7, issue #116).

    Reported for every refusal, not only the free-space one, so the Health page
    always has an answer; ``required_free_bytes`` and ``available_free_bytes``
    are what make the free-space case actionable.
    """

    reason: str
    required_free_bytes: int
    available_free_bytes: int


@dataclass(frozen=True, slots=True)
class DatabaseStats:
    """A point-in-time measurement of the database file and its free pages.

    ``page_count`` and ``freelist_count`` come from SQLite; ``file_bytes``,
    ``wal_bytes`` and ``free_bytes`` from the filesystem. The two views differ
    on purpose: SQLite's page arithmetic describes the *logical* database,
    which is what a ``VACUUM`` would rewrite, while the file sizes describe
    what is actually consuming the SD card.
    """

    page_count: int
    page_size: int
    freelist_count: int
    file_bytes: int
    wal_bytes: int
    free_bytes: int

    @property
    def db_bytes(self) -> int:
        """Logical database size: the pages SQLite accounts for."""
        return self.page_count * self.page_size

    @property
    def reclaimable_bytes(self) -> int:
        """Bytes a ``VACUUM`` would hand back to the filesystem."""
        return self.freelist_count * self.page_size

    @property
    def reclaimable_ratio(self) -> float:
        """Free pages as a fraction of all pages; ``0.0`` for an empty file."""
        if self.page_count <= 0:
            return 0.0
        return self.freelist_count / self.page_count


@dataclass(frozen=True, slots=True)
class MaintenanceReport:
    """Everything the service knows about its own recent work.

    Held on :class:`~flightsite.maintenance.service.MaintenanceService` and
    rebuilt on every read, so a caller can never mutate the service's state
    through a report it was handed.
    """

    cycles: int = 0
    last_cycle_ms: int | None = None
    jobs: Mapping[str, JobReport] = field(default_factory=dict)
    quick_check: QuickCheckOutcome | None = None
    stats: DatabaseStats | None = None
    #: The last ``VACUUM`` refusal, or ``None`` if the guard has not refused
    #: since the last one ran (and ``None`` before the job has ever been due).
    vacuum_refusal: VacuumRefusal | None = None

    @property
    def healthy(self) -> bool:
        """True unless the last attempt at some job failed.

        A never-run service is healthy: nothing has gone wrong yet, and
        reporting a problem before the first cycle would be an invention.
        """
        return all(report.outcome is not JobOutcome.FAILED for report in self.jobs.values())


__all__ = [
    "CHECKPOINT_JOB",
    "JOB_NAMES",
    "OPTIMIZE_JOB",
    "QUICK_CHECK_JOB",
    "RETENTION_JOB",
    "VACUUM_JOB",
    "DatabaseStats",
    "JobDetail",
    "JobOutcome",
    "JobReport",
    "JobResult",
    "MaintenanceReport",
    "QuickCheckOutcome",
    "VacuumRefusal",
]
