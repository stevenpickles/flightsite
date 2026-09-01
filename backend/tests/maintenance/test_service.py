"""The scheduler: cadences, independence, outcomes, and the retained report.

Cadence is asserted against an injected epoch clock and an injected sleeper, so
a full simulated week of maintenance runs in milliseconds and nothing here can
flake on a loaded machine (``docs/TEST_STRATEGY.md`` §3).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import Delete, Insert, delete, insert

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.db.engine import QUICK_CHECK_OK
from flightsite.db.models import Meta
from flightsite.enrichment.cache import RouteCacheRepository
from flightsite.enrichment.model import RouteInfo
from flightsite.live import LiveStore
from flightsite.maintenance.model import (
    CHECKPOINT_JOB,
    JOB_NAMES,
    OPTIMIZE_JOB,
    QUICK_CHECK_JOB,
    RETENTION_JOB,
    VACUUM_JOB,
    DatabaseStats,
    JobOutcome,
)
from flightsite.maintenance.policy import (
    VACUUM_MAX_LIVE_AIRCRAFT,
    VACUUM_MIN_DB_BYTES,
    VACUUM_MIN_RECLAIMABLE_RATIO,
    WAL_CHECKPOINT_THRESHOLD_BYTES,
    VacuumVerdict,
)
from flightsite.maintenance.retention import RetentionTask, RouteCachePruner
from flightsite.maintenance.service import (
    DEFAULT_CYCLE_INTERVAL_S,
    MaintenanceService,
    StatsProbe,
)
from flightsite.maintenance.stats import gather_stats, wal_path
from tests.maintenance.conftest import ManualClock, make_stats, observations

#: Statistics that satisfy every ``VACUUM`` condition, so a test about the
#: *service* running one is not silently a test of the guard declining it.
VACUUM_READY = make_stats(
    db_bytes=4 * VACUUM_MIN_DB_BYTES, reclaimable_ratio=VACUUM_MIN_RECLAIMABLE_RATIO + 0.1
)

#: Statistics of a healthy install: nothing to checkpoint, nothing to reclaim.
QUIET = make_stats()


class CountingTask:
    """A retention task recording its calls, optionally failing."""

    def __init__(self, *, name: str = "counted", removes: int = 0, fails: bool = False) -> None:
        self._name = name
        self._removes = removes
        self._fails = fails
        self.calls: list[int] = []

    @property
    def name(self) -> str:
        return self._name

    async def prune(self, *, now_ms: int) -> int:
        self.calls.append(now_ms)
        if self._fails:
            raise RuntimeError("simulated prune failure")
        return self._removes


def build(
    database: Database,
    clock: ManualClock,
    counters: CounterRegistry,
    *,
    retention: Sequence[RetentionTask] = (),
    live: LiveStore | None = None,
    stats: StatsProbe | None = None,
) -> MaintenanceService:
    """A service wired for a test: hand-driven clock, private counters."""
    return MaintenanceService(
        database=database,
        retention=retention,
        live=live,
        clock=clock,
        counters=counters,
        stats=stats,
    )


# --------------------------------------------------------------- scheduling


async def test_the_first_cycle_runs_every_job(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = build(database, clock, counters, stats=_fixed(QUIET))

    report = await service.run_cycle()

    assert set(report.jobs) == set(JOB_NAMES)
    assert report.cycles == 1
    assert report.last_cycle_ms == clock.now_ms
    assert all(job.started_ms == clock.now_ms for job in report.jobs.values())


async def test_hourly_jobs_run_again_while_daily_ones_wait(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """Each job keeps its own cadence; sharing a cycle is not sharing a schedule."""
    task = CountingTask()
    service = build(database, clock, counters, retention=[task], stats=_fixed(QUIET))
    first = await service.run_cycle()

    clock.advance_hours(1)
    second = await service.run_cycle()

    for hourly in (RETENTION_JOB, CHECKPOINT_JOB):
        assert second.jobs[hourly].started_ms == clock.now_ms
    for daily in (QUICK_CHECK_JOB, OPTIMIZE_JOB, VACUUM_JOB):
        assert second.jobs[daily].started_ms == first.jobs[daily].started_ms
    assert len(task.calls) == 2


async def test_a_cycle_inside_the_hour_runs_nothing_at_all(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    task = CountingTask()
    service = build(database, clock, counters, retention=[task], stats=_fixed(QUIET))
    first = await service.run_cycle()

    clock.advance_ms(60_000)
    second = await service.run_cycle()

    assert len(task.calls) == 1
    assert {name: job.started_ms for name, job in second.jobs.items()} == {
        name: job.started_ms for name, job in first.jobs.items()
    }
    # The cycle still counted: "nothing was due" is not "nothing happened".
    assert second.cycles == 2


async def test_daily_jobs_run_again_a_day_later(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = build(database, clock, counters, stats=_fixed(QUIET))
    await service.run_cycle()

    clock.advance_days(1)
    report = await service.run_cycle()

    for daily in (QUICK_CHECK_JOB, OPTIMIZE_JOB, VACUUM_JOB):
        assert report.jobs[daily].started_ms == clock.now_ms


async def test_a_week_of_cycles_runs_the_daily_jobs_seven_times(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """The cadence holds over time rather than only across one boundary."""
    task = CountingTask(name="hourly")
    service = build(database, clock, counters, retention=[task], stats=_fixed(QUIET))
    checks: list[int] = []

    for _ in range(7 * 24):
        report = await service.run_cycle()
        check = report.jobs[QUICK_CHECK_JOB].started_ms
        if check not in checks:
            checks.append(check)
        clock.advance_hours(1)

    assert len(checks) == 7
    assert len(task.calls) == 7 * 24


# -------------------------------------------------------------- independence


async def test_a_failing_retention_task_does_not_stop_the_other_jobs(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = build(
        database, clock, counters, retention=[CountingTask(fails=True)], stats=_fixed(QUIET)
    )

    report = await service.run_cycle()

    assert report.jobs[RETENTION_JOB].outcome is JobOutcome.FAILED
    assert report.jobs[QUICK_CHECK_JOB].outcome is JobOutcome.OK
    assert report.jobs[OPTIMIZE_JOB].outcome is JobOutcome.OK
    assert counters.snapshot()["db_errors"] == 1
    assert report.healthy is False


async def test_one_failing_retention_task_does_not_stop_its_siblings(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """Independence holds inside the retention job as well as between jobs."""
    broken = CountingTask(name="broken", fails=True)
    working = CountingTask(name="working", removes=3)
    service = build(database, clock, counters, retention=[broken, working], stats=_fixed(QUIET))

    report = await service.run_cycle()

    assert working.calls, "a failing sibling stopped the task after it"
    detail = report.jobs[RETENTION_JOB].detail
    assert detail["working"] == 3
    assert detail["broken_error"] == "RuntimeError"
    assert detail["pruned"] == 3


async def test_a_raising_job_is_recorded_counted_and_survived(
    database: Database,
    clock: ManualClock,
    counters: CounterRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job body that raises must not escape the cycle it is running in."""

    async def explode(self: Database) -> Sequence[str]:
        raise RuntimeError("simulated integrity failure")

    monkeypatch.setattr(Database, "quick_check", explode)
    service = build(database, clock, counters, stats=_fixed(QUIET))

    report = await service.run_cycle()

    failed = report.jobs[QUICK_CHECK_JOB]
    assert failed.outcome is JobOutcome.FAILED
    assert failed.detail["error_type"] == "RuntimeError"
    assert counters.snapshot()["db_errors"] == 1
    assert report.jobs[CHECKPOINT_JOB].outcome is JobOutcome.SKIPPED


async def test_a_failed_job_waits_its_own_cadence_before_retrying(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """A broken job must not turn one problem into an hourly log flood."""
    task = CountingTask(fails=True)
    service = build(database, clock, counters, retention=[task], stats=_fixed(QUIET))

    await service.run_cycle()
    clock.advance_ms(60_000)
    await service.run_cycle()

    assert len(task.calls) == 1


async def test_a_failing_stats_probe_does_not_fail_the_cycle(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """Diagnostics must stay reachable on exactly the database that broke."""

    async def broken() -> DatabaseStats:
        raise RuntimeError("cannot measure")

    service = build(database, clock, counters, stats=broken)

    report = await service.run_cycle()

    assert report.cycles == 1
    assert report.stats is None
    # The two jobs that read statistics failed; the three that do not, did not.
    assert report.jobs[CHECKPOINT_JOB].outcome is JobOutcome.FAILED
    assert report.jobs[VACUUM_JOB].outcome is JobOutcome.FAILED
    assert report.jobs[QUICK_CHECK_JOB].outcome is JobOutcome.OK
    assert report.jobs[OPTIMIZE_JOB].outcome is JobOutcome.OK
    assert report.jobs[RETENTION_JOB].outcome is JobOutcome.OK
    assert counters.snapshot()["db_errors"] == 2


# ------------------------------------------------------------- integrity job


async def test_a_healthy_database_passes_the_integrity_check(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = build(database, clock, counters, stats=_fixed(QUIET))

    report = await service.run_cycle()

    assert report.jobs[QUICK_CHECK_JOB].outcome is JobOutcome.OK
    assert report.quick_check is not None
    assert report.quick_check.healthy is True
    assert report.quick_check.rows == (QUICK_CHECK_OK,)
    assert report.quick_check.checked_ms == clock.now_ms
    assert counters.snapshot()["db_errors"] == 0


async def test_reported_problems_are_retained_verbatim(
    database: Database,
    clock: ManualClock,
    counters: CounterRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``quick_check`` can *return* problems rather than raise; both must land."""
    problems = ["*** in database main ***", "Page 3 is never used"]

    async def failing(self: Database) -> Sequence[str]:
        return problems

    monkeypatch.setattr(Database, "quick_check", failing)
    service = build(database, clock, counters, stats=_fixed(QUIET))

    report = await service.run_cycle()

    assert report.jobs[QUICK_CHECK_JOB].outcome is JobOutcome.FAILED
    assert report.quick_check is not None
    assert report.quick_check.healthy is False
    assert report.quick_check.rows == tuple(problems)
    assert report.quick_check.error is None


# ------------------------------------------------------------ checkpoint job


async def test_a_small_wal_is_left_alone(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = build(database, clock, counters, stats=_fixed(QUIET))

    report = await service.run_cycle()

    checkpoint = report.jobs[CHECKPOINT_JOB]
    assert checkpoint.outcome is JobOutcome.SKIPPED
    assert checkpoint.detail["threshold_bytes"] == WAL_CHECKPOINT_THRESHOLD_BYTES


async def test_an_oversized_wal_is_truncated_for_real(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """The trigger is faked; the checkpoint that follows is not.

    Growing a real 16 MB write-ahead log would take longer than the rest of the
    suite, so the *first* measurement of the cycle reports an oversized log and
    every later one tells the truth. What follows is a genuine
    ``PRAGMA wal_checkpoint(TRUNCATE)`` against a real database with a real
    ``-wal``, and the assertion is on the file that is left behind.
    """
    async with database.writer_session() as session:
        await session.execute(_meta_insert())
    assert wal_path(database.path).stat().st_size > 0

    probe = _oversized_wal_once(database)
    service = build(database, clock, counters, stats=probe)

    report = await service.run_cycle()

    checkpoint = report.jobs[CHECKPOINT_JOB]
    assert checkpoint.outcome is JobOutcome.OK
    assert checkpoint.detail["wal_bytes_before"] == WAL_CHECKPOINT_THRESHOLD_BYTES + 1
    assert checkpoint.detail["blocked"] == 0
    assert wal_path(database.path).stat().st_size == 0


async def test_a_checkpoint_a_reader_blocks_is_a_skip_not_a_failure(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """``TRUNCATE`` cannot reset a log another reader is still attached to.

    SQLite reports that as a busy indicator rather than an error, and it is not
    one: the log is untouched, no data is at risk, and the next cycle tries
    again. Counting it as a failure would put a ``db_errors`` increment on
    every hour a long read happened to overlap the checkpoint.

    The reader is a second connection holding an open read transaction, which
    is the real condition rather than a simulation of it — so this test pays
    the connection's ``busy_timeout`` (a few seconds) once.
    """
    async with database.writer_session() as session:
        await session.execute(_meta_insert(rows=200))

    reader = sqlite3.connect(database.path)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM meta").fetchall()
    service = build(database, clock, counters, stats=_oversized_wal_once(database))

    try:
        checkpoint = (await service.run_cycle()).jobs[CHECKPOINT_JOB]
    finally:
        reader.close()

    assert checkpoint.outcome is JobOutcome.SKIPPED
    assert checkpoint.detail["blocked"] == 1
    assert counters.snapshot()["db_errors"] == 0
    assert wal_path(database.path).stat().st_size > 0


# ---------------------------------------------------------------- vacuum job


async def test_a_healthy_database_is_never_vacuumed(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = build(database, clock, counters, stats=_fixed(QUIET))

    vacuum = (await service.run_cycle()).jobs[VACUUM_JOB]

    assert vacuum.outcome is JobOutcome.SKIPPED
    assert vacuum.detail["verdict"] == VacuumVerdict.BELOW_SIZE_FLOOR.value


async def test_a_justified_vacuum_runs_and_reports_its_duration(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """The guard says yes; a real ``VACUUM`` follows, through the writer lock."""
    service = build(database, clock, counters, stats=_fixed(VACUUM_READY))

    vacuum = (await service.run_cycle()).jobs[VACUUM_JOB]

    assert vacuum.outcome is JobOutcome.OK
    assert vacuum.detail["verdict"] == VacuumVerdict.RUN.value
    assert isinstance(vacuum.detail["duration_ms"], int)
    assert "db_bytes_after" in vacuum.detail


async def test_a_busy_live_set_defers_a_justified_vacuum(
    database: Database, clock: ManualClock, counters: CounterRegistry, live: LiveStore
) -> None:
    """The cheap pressure heuristic, half one: traffic the writer is about to see."""
    live.apply_updates(observations(VACUUM_MAX_LIVE_AIRCRAFT + 1))
    service = build(database, clock, counters, live=live, stats=_fixed(VACUUM_READY))

    vacuum = (await service.run_cycle()).jobs[VACUUM_JOB]

    assert vacuum.outcome is JobOutcome.SKIPPED
    assert vacuum.detail["verdict"] == VacuumVerdict.INGESTION_PRESSURE.value


async def test_a_quiet_live_set_does_not_defer_a_vacuum(
    database: Database, clock: ManualClock, counters: CounterRegistry, live: LiveStore
) -> None:
    live.apply_updates(observations(VACUUM_MAX_LIVE_AIRCRAFT))
    service = build(database, clock, counters, live=live, stats=_fixed(VACUUM_READY))

    assert (await service.run_cycle()).jobs[VACUUM_JOB].outcome is JobOutcome.OK


async def test_observed_writer_contention_defers_a_justified_vacuum(
    db_path: Path, clock: ManualClock, counters: CounterRegistry
) -> None:
    """The cheap pressure heuristic, half two: the writer lock held right now.

    The signal is faked rather than produced by parking a real writer, because
    a real one would also block the two *other* jobs in the cycle that take the
    same lock — this test would then be about the lock, not about the guard.
    That :attr:`~flightsite.db.engine.Database.writer_busy` really is true while
    a writer session is open is asserted in ``tests/db/test_writer_discipline``.
    """

    class ContendedDatabase(Database):
        @property
        def writer_busy(self) -> bool:
            return True

    database = ContendedDatabase(db_path)
    await database.upgrade_to("head")
    service = build(database, clock, counters, stats=_fixed(VACUUM_READY))
    try:
        vacuum = (await service.run_cycle()).jobs[VACUUM_JOB]
    finally:
        await database.dispose()

    assert vacuum.outcome is JobOutcome.SKIPPED
    assert vacuum.detail["verdict"] == VacuumVerdict.INGESTION_PRESSURE.value


async def test_a_real_vacuum_reclaims_the_space_the_guard_measured(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """End to end on a real file: dead pages measured, then actually returned."""
    async with database.writer_session() as session:
        await session.execute(_meta_insert(rows=800))
    async with database.writer_session() as session:
        await session.execute(_meta_delete())
    before = await gather_stats(database)
    assert before.freelist_count > 0

    service = build(database, clock, counters, stats=_fixed(VACUUM_READY))
    assert (await service.run_cycle()).jobs[VACUUM_JOB].outcome is JobOutcome.OK

    after = await gather_stats(database)
    assert after.freelist_count == 0
    assert after.page_count < before.page_count


# ------------------------------------------------------------------ the task


async def test_the_task_runs_cycles_on_its_own_cadence(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """Cadence without wall-clock time: the loop's own sleep drives the clock."""
    cycles = asyncio.Event()
    intervals: list[float] = []

    async def sleep(seconds: float) -> None:
        intervals.append(seconds)
        if len(intervals) > 1:
            cycles.set()
            await asyncio.Event().wait()
        clock.advance_hours(1)
        await asyncio.sleep(0)

    task = CountingTask()
    service = MaintenanceService(
        database=database,
        retention=[task],
        clock=clock,
        sleep=sleep,
        counters=counters,
        stats=_fixed(QUIET),
    )

    await service.start()
    assert service.running is True
    try:
        await asyncio.wait_for(cycles.wait(), timeout=5.0)
    finally:
        await service.stop()

    assert intervals[0] == DEFAULT_CYCLE_INTERVAL_S
    assert task.calls, "the loop never ran a cycle"
    assert service.running is False


async def test_starting_twice_starts_one_task(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    parked: list[float] = []

    async def sleep(seconds: float) -> None:
        parked.append(seconds)
        await asyncio.Event().wait()

    service = MaintenanceService(
        database=database, clock=clock, sleep=sleep, counters=counters, stats=_fixed(QUIET)
    )
    await service.start()
    first = service._task
    await service.start()
    await asyncio.sleep(0)

    try:
        assert service._task is first
    finally:
        await service.stop()
    await service.stop()  # idempotent

    assert service.running is False
    # One task, therefore one sleeper waiting: a second would have parked too.
    assert parked == [DEFAULT_CYCLE_INTERVAL_S]


async def test_nothing_runs_before_the_first_interval_elapses(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """Startup is the busiest minute of the process's life; maintenance waits."""
    task = CountingTask()

    async def sleep(seconds: float) -> None:
        await asyncio.Event().wait()

    service = MaintenanceService(
        database=database,
        retention=[task],
        clock=clock,
        sleep=sleep,
        counters=counters,
        stats=_fixed(QUIET),
    )
    await service.start()
    await asyncio.sleep(0)
    await service.stop()

    assert task.calls == []
    assert service.report.cycles == 0


async def test_stopping_mid_cycle_cancels_without_inventing_a_failure(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """Shutdown cancels a cycle in flight; a cancelled job is not a failed one.

    Recording one as failed would put a ``db_errors`` increment and an error
    log into every clean shutdown that happened to land mid-cycle.
    """
    started = asyncio.Event()
    gate = asyncio.Event()

    class BlockingTask:
        name = "blocking"

        async def prune(self, *, now_ms: int) -> int:
            started.set()
            await gate.wait()
            return 0

    ticks = 0

    async def sleep(seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks > 1:  # pragma: no cover - the cycle never returns to sleep
            await asyncio.Event().wait()

    service = MaintenanceService(
        database=database,
        retention=[BlockingTask()],
        clock=clock,
        sleep=sleep,
        counters=counters,
        stats=_fixed(QUIET),
    )
    await service.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=5.0)
    finally:
        await service.stop()

    assert service.running is False
    assert RETENTION_JOB not in service.report.jobs
    assert counters.snapshot()["db_errors"] == 0


def test_a_non_positive_cycle_interval_is_rejected(database: Database) -> None:
    with pytest.raises(ValueError, match="cycle_interval_s"):
        MaintenanceService(database=database, cycle_interval_s=0.0)


# -------------------------------------------------------------- the report


async def test_the_report_is_a_copy_not_the_service_s_state(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """Slice 042 reads this; it must not be able to edit the service through it."""
    service = build(database, clock, counters, stats=_fixed(QUIET))
    await service.run_cycle()

    report = service.report
    assert service.report.jobs is not report.jobs

    clock.advance_days(1)
    await service.run_cycle()

    # The value handed out earlier still describes the cycle it was taken from.
    assert report.cycles == 1
    assert service.report.cycles == 2


async def test_a_service_that_has_never_run_reports_nothing_wrong(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    report = build(database, clock, counters).report

    assert report.cycles == 0
    assert report.last_cycle_ms is None
    assert report.jobs == {}
    assert report.quick_check is None
    assert report.stats is None
    assert report.healthy is True


async def test_the_report_carries_the_measurements_diagnostics_needs(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    service = build(database, clock, counters, retention=[CountingTask(removes=4)])

    report = await service.run_cycle()

    assert report.stats is not None
    assert report.stats.page_count > 0
    assert report.jobs[RETENTION_JOB].detail["pruned"] == 4
    assert report.healthy is True


async def test_the_real_route_cache_pruner_is_driven_by_the_cycle(
    database: Database,
    clock: ManualClock,
    counters: CounterRegistry,
    route_cache: RouteCacheRepository,
) -> None:
    """The wiring the app uses, exercised end to end rather than with a double."""
    await route_cache.store_not_found("XXX999-2026-08-31", now_ms=clock.now_ms - 10_000_000)
    await route_cache.store_route(
        "BAW117-2026-08-31",
        RouteInfo(origin_ident="EGLL", destination_ident="KJFK"),
        now_ms=clock.now_ms,
    )
    service = build(database, clock, counters, retention=[RouteCachePruner(route_cache)])

    report = await service.run_cycle()

    assert report.jobs[RETENTION_JOB].detail["route_cache"] == 1
    assert await route_cache.size() == 1


# ------------------------------------------------------------------ helpers


def _fixed(stats: DatabaseStats) -> StatsProbe:
    async def probe() -> DatabaseStats:
        return stats

    return probe


def _oversized_wal_once(database: Database) -> StatsProbe:
    """Real statistics, except the first reading claims an oversized log."""
    calls = 0

    async def probe() -> DatabaseStats:
        nonlocal calls
        calls += 1
        stats = await gather_stats(database)
        if calls == 1:
            return replace(stats, wal_bytes=WAL_CHECKPOINT_THRESHOLD_BYTES + 1)
        return stats

    return probe


def _meta_insert(rows: int = 1) -> Insert:
    """Filler ``meta`` rows: enough bytes to make a real WAL and real pages."""
    return insert(Meta).values(
        [
            {"key": f"filler-{index:04d}", "value": "x" * 400, "updated_ms": 1}
            for index in range(rows)
        ]
    )


def _meta_delete() -> Delete:
    return delete(Meta).where(Meta.key.like("filler-%"))
