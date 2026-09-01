"""The maintenance scheduler: five jobs, five cadences, one hourly task.

``docs/ARCHITECTURE.md`` §3.3 lists *"stats poller / maintenance scheduler —
low-frequency background tasks"*, and ``docs/ARCHITECTURE.md`` §5 gives
``maintenance/`` the line *"integrity checks, pruning execution, optimize/VACUUM
policy"*. This module is that line. SPEC §70 states the contract it has to
satisfy: conservative automation, integrity checking, retention pruning, SQLite
optimization, ``VACUUM`` only when justified and safe, useful diagnostics, and
**no routine user babysitting** — so every interval and every threshold here is
a module constant, and this slice introduces no configuration key at all.

Shape
-----

One task on an hourly cycle. Each cycle asks each job whether its own cadence
has elapsed and runs the ones that say yes, so a cheap job can be hourly and an
expensive one daily without a task each:

======================= ========= ==================================================
``quick_check``         daily     ``PRAGMA quick_check``; the result is retained
``retention``           hourly    the pruning executor (:mod:`.retention`)
``optimize``            daily     ``PRAGMA optimize``
``wal_checkpoint``      hourly    ``TRUNCATE`` checkpoint above a size threshold
``vacuum``              daily     evaluated daily, run almost never (:mod:`.policy`)
======================= ========= ==================================================

The order within a cycle is the order of the table and it is not arbitrary:
integrity is verified before anything mutates the file; pruning runs before the
free-space measurements so ``vacuum`` judges the freelist the prune just grew;
the checkpoint runs before ``vacuum`` so a rewrite is never done with a large
log still outstanding.

Independence
------------

Jobs share a cycle, not a fate. Every job body runs inside its own
``try``/``except``: one that raises is recorded as failed, increments
``db_errors``, logs, and the cycle carries straight on to the next. That is the
property the corruption drill turns into a test — on a genuinely smashed
database ``quick_check`` reports the damage loudly and the service keeps
running, cycle after cycle, rather than taking the process down or falling
silent.

Contention
----------

Nothing here can slow ingestion, and the reason is structural rather than
careful: the decoder poll path and :meth:`~flightsite.live.store.LiveStore.apply`
never touch SQLite at all (``docs/ARCHITECTURE.md`` §3.1). What maintenance
*can* delay is another *writer*, and it does so through the same
:class:`~flightsite.db.engine.Database` writer lock as everything else, so a
persistence-worker transaction queues behind a checkpoint in the application
instead of colliding with it in the file. The one job that holds that lock for
a long time is ``VACUUM``, which is exactly why it is guarded.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final

import structlog

from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.clock import MS_PER_SECOND, utc_now_ms
from flightsite.db.engine import QUICK_CHECK_OK, Database
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.live.store import LiveStore
from flightsite.maintenance.model import (
    CHECKPOINT_JOB,
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
)
from flightsite.maintenance.policy import (
    VACUUM_MAX_LIVE_AIRCRAFT,
    WAL_CHECKPOINT_THRESHOLD_BYTES,
    should_checkpoint,
    vacuum_decision,
)
from flightsite.maintenance.retention import RetentionTask
from flightsite.maintenance.stats import gather_stats

logger = structlog.get_logger(__name__)

MS_PER_HOUR: Final = 60 * 60 * MS_PER_SECOND
MS_PER_DAY: Final = 24 * MS_PER_HOUR

#: How often the task wakes. An hour is the coarsest cadence any job needs and
#: the finest any job wants: nothing here is urgent, and a Pi should not be
#: woken to decide that there is nothing to do.
DEFAULT_CYCLE_INTERVAL_S: Final = 60.0 * 60.0

#: Cadence of ``PRAGMA quick_check``. Daily, matching the once-per-boot check
#: :mod:`flightsite.db.startup` already runs: an appliance that stays up for
#: months would otherwise verify its integrity exactly once, at install.
QUICK_CHECK_INTERVAL_MS: Final = MS_PER_DAY

#: Cadence of ``PRAGMA optimize``. Daily is what SQLite's own documentation
#: recommends for a long-running application; it is cheap and usually a no-op.
OPTIMIZE_INTERVAL_MS: Final = MS_PER_DAY

#: Cadence of the WAL size check. Hourly — the check is a ``stat()``, and a
#: checkpoint only follows when the log has actually grown past its threshold.
CHECKPOINT_INTERVAL_MS: Final = MS_PER_HOUR

#: Cadence of the retention executor. Hourly: the work is one indexed
#: ``DELETE`` per prunable table, and a shorter tail of dead cache rows is
#: worth an hourly statement that usually deletes nothing.
RETENTION_INTERVAL_MS: Final = MS_PER_HOUR

#: Cadence at which the ``VACUUM`` guard is *evaluated*. Daily. How often a
#: ``VACUUM`` actually runs is :mod:`flightsite.maintenance.policy`'s answer,
#: and on a healthy install it is "never".
VACUUM_INTERVAL_MS: Final = MS_PER_DAY

#: What an operator should do about a failed integrity check. Recorded in the
#: log event rather than left to the reader: by the time this fires, the useful
#: action is a restore, and guessing at repairs makes things worse.
CORRUPTION_REMEDIATION: Final = (
    "database integrity check failed. FlightSite keeps running and the live "
    "picture is unaffected, but stored history may be damaged. Stop FlightSite "
    "and restore the database from the most recent backup, or move the file "
    "aside to start fresh. Do not attempt in-place repair."
)

#: A source of UTC epoch milliseconds, injected so cadence tests run against a
#: hand-driven clock rather than ``asyncio.sleep``.
EpochClock = Callable[[], int]
Sleeper = Callable[[float], Awaitable[None]]

#: How the service measures the database. Injected so the ``VACUUM`` guard
#: matrix can be driven from fabricated statistics — reproducing a 4 GB
#: database that is 30% freelist is not something a unit test can do for real.
StatsProbe = Callable[[], Awaitable[DatabaseStats]]


@dataclass(frozen=True, slots=True)
class _Job:
    """One scheduled job: what it is called, how often, and what it does."""

    name: str
    interval_ms: int
    run: Callable[[], Awaitable[JobResult]]


class MaintenanceService:
    """Runs FlightSite's database housekeeping, unattended and conservatively.

    Args:
        database: the application database. Every statement that mutates it
            goes through :meth:`~flightsite.db.engine.Database.maintenance_connection`,
            which takes the process's single writer lock.
        retention: the prunable domains this service is responsible for. The
            app wires exactly one (``route_cache``); the boundary against the
            domains that prune themselves is documented in
            :mod:`flightsite.maintenance.retention`.
        live: the live aircraft registry, read only for the ``VACUUM`` pressure
            heuristic. ``None`` disables that half of the heuristic; the writer
            -lock half still applies.
        cycle_interval_s: how often the task wakes.
        clock: UTC epoch-millisecond source, used for cadences and timestamps.
        sleep: awaited between cycles; injected so tests drive the cadence.
        counters: registry receiving ``db_errors`` for every failed job.
        stats: how the database is measured; defaults to reading it for real.
    """

    __slots__ = (
        "_clock",
        "_counters",
        "_cycle_interval_s",
        "_cycles",
        "_database",
        "_jobs",
        "_last_cycle_ms",
        "_last_run_ms",
        "_latest_stats",
        "_live",
        "_quick_check",
        "_reports",
        "_retention",
        "_sleep",
        "_stats",
        "_task",
    )

    def __init__(
        self,
        *,
        database: Database,
        retention: Sequence[RetentionTask] = (),
        live: LiveStore | None = None,
        cycle_interval_s: float = DEFAULT_CYCLE_INTERVAL_S,
        clock: EpochClock = utc_now_ms,
        sleep: Sleeper = asyncio.sleep,
        counters: CounterRegistry = default_counters,
        stats: StatsProbe | None = None,
    ) -> None:
        if cycle_interval_s <= 0.0:
            raise ValueError("cycle_interval_s must be greater than zero")

        self._database = database
        self._retention = tuple(retention)
        self._live = live
        self._cycle_interval_s = cycle_interval_s
        self._clock = clock
        self._sleep = sleep
        self._counters = counters
        self._stats: StatsProbe = stats if stats is not None else self._measure

        self._task: asyncio.Task[None] | None = None
        self._reports: dict[str, JobReport] = {}
        self._last_run_ms: dict[str, int] = {}
        self._quick_check: QuickCheckOutcome | None = None
        self._latest_stats: DatabaseStats | None = None
        self._cycles = 0
        self._last_cycle_ms: int | None = None

        # Built once, in cycle order (see the module docstring).
        self._jobs: tuple[_Job, ...] = (
            _Job(QUICK_CHECK_JOB, QUICK_CHECK_INTERVAL_MS, self._run_quick_check),
            _Job(RETENTION_JOB, RETENTION_INTERVAL_MS, self._run_retention),
            _Job(OPTIMIZE_JOB, OPTIMIZE_INTERVAL_MS, self._run_optimize),
            _Job(CHECKPOINT_JOB, CHECKPOINT_INTERVAL_MS, self._run_checkpoint),
            _Job(VACUUM_JOB, VACUUM_INTERVAL_MS, self._run_vacuum),
        )

    # ------------------------------------------------------------ inspection

    @property
    def running(self) -> bool:
        """True while the maintenance task is alive."""
        return self._task is not None and not self._task.done()

    @property
    def report(self) -> MaintenanceReport:
        """Everything this service knows about its own recent work.

        Rebuilt on every read from an independent copy of the job table, so a
        caller — slice 042's diagnostics endpoint above all — cannot mutate the
        service's state through the value it is handed.
        """
        return MaintenanceReport(
            cycles=self._cycles,
            last_cycle_ms=self._last_cycle_ms,
            jobs=dict(self._reports),
            quick_check=self._quick_check,
            stats=self._latest_stats,
        )

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Start the maintenance task. Idempotent.

        Nothing runs immediately: the first cycle is one interval away, which
        keeps housekeeping out of the busiest minute of the process's life —
        startup has just migrated the schema, integrity-checked it, backfilled
        the rollups and recovered any open sightings.
        """
        if self.running:
            return
        self._task = asyncio.create_task(self._loop(), name="flightsite-maintenance")
        logger.info(
            "maintenance_started",
            cycle_interval_s=self._cycle_interval_s,
            retention_tasks=[task.name for task in self._retention],
        )

    async def stop(self) -> None:
        """Stop the maintenance task. Idempotent.

        Nothing is flushed on the way out: every job is complete when it
        returns, and a cancelled cycle simply leaves the remaining jobs for the
        next process. That is the whole reason this subsystem holds no buffered
        state — a maintenance pass is never half-committed.
        """
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("maintenance_stopped", cycles=self._cycles)

    async def _loop(self) -> None:
        while True:
            await self._sleep(self._cycle_interval_s)
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                # run_cycle already absorbs every per-job failure, so reaching
                # here means the scheduler itself broke. The loop outliving it
                # matters more than the cycle: a dead task would leave the
                # database unmaintained with nothing saying so.
                logger.warning(
                    "maintenance_cycle_error", error=str(exc), error_type=type(exc).__name__
                )

    # ----------------------------------------------------------- one cycle

    async def run_cycle(self) -> MaintenanceReport:
        """Run every job whose cadence has elapsed; return the fresh report.

        Split out from the loop so tests drive one cycle at a time against a
        hand-driven clock, with no sleeping and no background task. Never
        raises on a job's behalf.
        """
        now_ms = self._clock()
        for job in self._jobs:
            if self._due(job, now_ms):
                await self._attempt(job, now_ms)

        self._cycles += 1
        self._last_cycle_ms = now_ms
        await self._refresh_stats()
        return self.report

    def _due(self, job: _Job, now_ms: int) -> bool:
        """True if ``job`` has never run, or last ran a full interval ago."""
        last = self._last_run_ms.get(job.name)
        return last is None or now_ms - last >= job.interval_ms

    async def _attempt(self, job: _Job, now_ms: int) -> None:
        """Run one job, absorb whatever it does, and record the outcome.

        The cadence is stamped before the body runs, so a job that fails waits
        its own interval before trying again rather than retrying every cycle:
        a database that cannot be checkpointed this hour will not be
        checkpointable next hour either, and hourly retries would turn one
        problem into a log flood.
        """
        self._last_run_ms[job.name] = now_ms
        started = time.monotonic()
        try:
            result = await job.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = JobResult(
                JobOutcome.FAILED,
                {"error_type": type(exc).__name__, "error": str(exc)[:200]},
            )

        duration_ms = int((time.monotonic() - started) * MS_PER_SECOND)
        report = JobReport(
            name=job.name,
            outcome=result.outcome,
            started_ms=now_ms,
            duration_ms=duration_ms,
            detail=dict(result.detail),
        )
        self._reports[job.name] = report

        if result.outcome is JobOutcome.FAILED:
            # One place increments the counter, whether the body raised or
            # returned a failure — so a job cannot be counted twice, or missed.
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.error(
                "maintenance_job",
                job=job.name,
                outcome=result.outcome.value,
                duration_ms=duration_ms,
                detail=report.detail,
            )
            return
        logger.info(
            "maintenance_job",
            job=job.name,
            outcome=result.outcome.value,
            duration_ms=duration_ms,
            detail=report.detail,
        )

    async def _refresh_stats(self) -> None:
        """Re-measure the database for the report, tolerating a failure.

        A database too damaged to answer ``PRAGMA page_count`` is precisely
        when diagnostics must still be reachable, so this cannot be allowed to
        fail a cycle that has already done its work.
        """
        try:
            self._latest_stats = await self._stats()
        except Exception as exc:
            logger.warning(
                "maintenance_stats_unavailable", error=str(exc), error_type=type(exc).__name__
            )

    async def _measure(self) -> DatabaseStats:
        """Default :data:`StatsProbe`: measure the real database."""
        return await gather_stats(self._database)

    # -------------------------------------------------------------- the jobs

    async def _run_quick_check(self) -> JobResult:
        """``PRAGMA quick_check``, retained and reported loudly on failure.

        Both failure shapes end in the same place. A database SQLite can still
        read returns rows describing the damage; one it cannot read raises. The
        outcome is retained either way, because on a corrupt database this
        record is the only description of the problem FlightSite has.
        """
        checked_ms = self._clock()
        try:
            rows = tuple(await self._database.quick_check())
        except Exception as exc:
            self._quick_check = QuickCheckOutcome(
                healthy=False, checked_ms=checked_ms, error=f"{type(exc).__name__}: {exc}"[:200]
            )
            logger.error(
                "maintenance_integrity_check_failed",
                db_path=str(self._database.path),
                error=str(exc),
                error_type=type(exc).__name__,
                remediation=CORRUPTION_REMEDIATION,
            )
            raise

        healthy = list(rows) == [QUICK_CHECK_OK]
        self._quick_check = QuickCheckOutcome(healthy=healthy, checked_ms=checked_ms, rows=rows)
        if healthy:
            return JobResult(JobOutcome.OK, {"result": QUICK_CHECK_OK})

        logger.error(
            "maintenance_integrity_check_failed",
            db_path=str(self._database.path),
            quick_check=list(rows),
            remediation=CORRUPTION_REMEDIATION,
        )
        return JobResult(
            JobOutcome.FAILED, {"problems": len(rows), "report": "; ".join(rows)[:200]}
        )

    async def _run_retention(self) -> JobResult:
        """Prune every registered prunable domain, each independently.

        A task that raises costs its own table this pass and nothing else: the
        others still run, and the job reports failed so the failure is counted
        and visible.
        """
        now_ms = self._clock()
        detail: dict[str, str | int | float] = {}
        pruned = 0
        failures = 0

        for task in self._retention:
            try:
                removed = await task.prune(now_ms=now_ms)
            except Exception as exc:
                failures += 1
                detail[f"{task.name}_error"] = type(exc).__name__
                logger.warning(
                    "maintenance_retention_task_failed",
                    task=task.name,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                continue
            detail[task.name] = removed
            pruned += removed

        detail["pruned"] = pruned
        if failures:
            detail["failed_tasks"] = failures
            return JobResult(JobOutcome.FAILED, detail)
        return JobResult(JobOutcome.OK, detail)

    async def _run_optimize(self) -> JobResult:
        """``PRAGMA optimize``: let SQLite refresh whatever statistics it wants.

        Cheap and almost always a no-op, which is exactly why it is run rather
        than reasoned about — SQLite's own guidance for a long-running
        application is to issue it periodically and let it decide.
        """
        async with self._database.maintenance_connection() as connection:
            await connection.exec_driver_sql("PRAGMA optimize")
        return JobResult(JobOutcome.OK)

    async def _run_checkpoint(self) -> JobResult:
        """Fold an oversized write-ahead log back into the database.

        Best-effort by construction: ``TRUNCATE`` cannot reset the log while a
        reader is still attached to it, and reports that as a busy indicator
        rather than an error. That is a skip, not a failure — the log is
        unchanged, no data is at risk, and the next cycle tries again.
        """
        before = await self._stats()
        if not should_checkpoint(before):
            return JobResult(
                JobOutcome.SKIPPED,
                {"wal_bytes": before.wal_bytes, "threshold_bytes": WAL_CHECKPOINT_THRESHOLD_BYTES},
            )

        async with self._database.maintenance_connection() as connection:
            row = (await connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")).fetchone()
        blocked = row is not None and int(row[0]) != 0

        after = await self._stats()
        detail: JobDetail = {
            "wal_bytes_before": before.wal_bytes,
            "wal_bytes_after": after.wal_bytes,
            "blocked": int(blocked),
        }
        if blocked:
            return JobResult(JobOutcome.SKIPPED, detail)
        logger.info(
            "maintenance_wal_checkpointed",
            wal_bytes_before=before.wal_bytes,
            wal_bytes_after=after.wal_bytes,
        )
        return JobResult(JobOutcome.OK, detail)

    async def _run_vacuum(self) -> JobResult:
        """Rewrite the database, but only if :mod:`.policy` says it is justified.

        The duration is logged because it is the one maintenance operation
        whose cost an operator can feel: it holds the writer lock for its whole
        run, so the persistence worker's next flush waits for it.
        """
        before = await self._stats()
        decision = vacuum_decision(before, under_pressure=self._under_pressure())
        detail: dict[str, str | int | float] = {
            "verdict": decision.verdict.value,
            "db_bytes": decision.db_bytes,
            "reclaimable_bytes": decision.reclaimable_bytes,
            "reclaimable_ratio": round(decision.reclaimable_ratio, 4),
        }
        if not decision.should_run:
            return JobResult(JobOutcome.SKIPPED, detail)

        started = time.monotonic()
        async with self._database.maintenance_connection() as connection:
            await connection.exec_driver_sql("VACUUM")
        duration_ms = int((time.monotonic() - started) * MS_PER_SECOND)

        after = await self._stats()
        logger.info(
            "maintenance_vacuum_completed",
            duration_ms=duration_ms,
            db_bytes_before=before.db_bytes,
            db_bytes_after=after.db_bytes,
            reclaimed_bytes=before.db_bytes - after.db_bytes,
        )
        detail["duration_ms"] = duration_ms
        detail["db_bytes_after"] = after.db_bytes
        return JobResult(JobOutcome.OK, detail)

    def _under_pressure(self) -> bool:
        """The cheap "is the receiver busy right now" heuristic (:mod:`.policy`).

        Two free signals, either of which vetoes: the writer lock being held at
        this instant, and a live set large enough that the persistence worker
        is about to be busy for a while.
        """
        if self._database.writer_busy:
            return True
        return self._live is not None and len(self._live) > VACUUM_MAX_LIVE_AIRCRAFT


__all__ = [
    "CHECKPOINT_INTERVAL_MS",
    "CORRUPTION_REMEDIATION",
    "DEFAULT_CYCLE_INTERVAL_S",
    "OPTIMIZE_INTERVAL_MS",
    "QUICK_CHECK_INTERVAL_MS",
    "RETENTION_INTERVAL_MS",
    "VACUUM_INTERVAL_MS",
    "EpochClock",
    "MaintenanceService",
    "Sleeper",
    "StatsProbe",
]
