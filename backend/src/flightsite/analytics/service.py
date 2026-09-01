"""The analytics service: incremental rollup maintenance and its repair pass.

Where this runs, and why
------------------------

``docs/DATA_MODEL.md`` §6.5 puts rollup maintenance on *"the persistence worker
at sighting close / day boundary, with a backfill job for correctness repair"*,
and the roadmap says the same from the other end: *"maintained incrementally by
the persistence worker + backfill job"*. This module honours both halves the
way slice 033 does — by taking the **seam** rather than the cycle.

* **Incremental, driven by the persistence worker.** The service subscribes to
  :meth:`~flightsite.sightings.worker.PersistenceWorker.subscribe_lifecycle`,
  the seam that publishes what each committed cycle opened and closed. Every
  notification marks the receiver-local day those sightings started in as
  *dirty*, in memory, with no ``await`` and no allocation beyond a set entry.
* **Written on this service's own task and in its own transaction.** A flush
  pass rebuilds the dirty days and writes them through
  :meth:`~flightsite.db.engine.Database.writer_session`, the process's one
  serialized writer (ADR-0001, ADR-0008). That is the single-writer guarantee
  the roadmap's "runs in the persistence worker" exists to secure, without
  giving a rollup bug the ability to fail a sighting transaction — the same
  trade, for the same reason, that
  :mod:`flightsite.receiver_metrics.service` documents.
* **Repaired at startup by the backfill job**, which is also what makes the
  seam allowed to be lossy: a crash between a committed cycle and the flush
  that would have rebuilt its day costs a stale day, and the next boot rebuilds
  it (:mod:`flightsite.analytics.backfill`).

What "incremental" means here
-----------------------------

It is incremental in *days*, not in counters: a pass rebuilds only the days
that changed, and rebuilds each of those from ground truth. The reasoning —
and the honest accounting of what that costs — is in
:mod:`flightsite.analytics.backfill`. The consequence worth stating here is
that the incremental path and the backfill path are the same code, so
"incremental maintenance agrees with a from-scratch rebuild" is true by
construction and the convergence test is a regression guard rather than a
proof obligation.

Day rollover
------------

``daily_stats.busiest_hour`` is §6.5's finalized **closed-day** value, and a
day is not closed until its local midnight has passed. The flush pass therefore
watches the local date: when it changes, the day that just ended is marked
dirty one last time, rebuilt with its ``busiest_hour`` written, and the
watermark advances to it. The in-progress day's busiest hour is *not* this
slice's to serve — §6.5 sends that question to slice 033's
``receiver_metrics_hourly``, and :mod:`flightsite.analytics.queries` asks it
there.

Degradation
-----------

Every failure mode ends in rollups being staler, and none of them ends anywhere
else:

* A flush that fails — counted into ``db_errors``, the dirty days are kept and
  the next pass rebuilds them. Nothing is marked clean that was not written.
* A startup repair that fails — logged and counted; the watermark is not
  advanced, so the next boot covers this boot's range as well as its own, and
  the periodic flush still maintains today.
* A listener notification that arrives while the service is stopped — recorded
  as dirty anyway. The set is plain memory; a service that is started again
  flushes it, and one that is not is in a process that is going away.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final
from zoneinfo import ZoneInfo

import structlog

from flightsite.analytics.backfill import AnalyticsBackfill, BackfillResult
from flightsite.analytics.bucketing import days_in_range, local_day, previous_day, shift_days
from flightsite.analytics.repository import AnalyticsRepository
from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.clock import utc_now_ms
from flightsite.db.engine import Database
from flightsite.db.meta import MetaRepository
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.sightings.worker import PersistenceWorker, SightingLifecycle

logger = structlog.get_logger(__name__)

#: How often dirty days are rebuilt. Thirty seconds keeps the in-progress day —
#: the one "Today at a Glance" reads — within a flush of the truth, while
#: keeping a busy sky at two transactions a minute rather than one per sighting.
#: It is the same interval the sighting worker uses for the same reason.
DEFAULT_FLUSH_INTERVAL_S: Final = 30.0

#: Most days one flush pass will finalize after a rollover. A month, which no
#: ordinary suspension approaches; the cap exists so a clock that jumps years
#: forward cannot turn a single pass into an unbounded rebuild.
MAX_ROLLOVER_DAYS: Final = 31

#: A source of UTC epoch milliseconds, injected so day-rollover and cadence
#: tests run against a hand-driven clock rather than ``asyncio.sleep``.
EpochClock = Callable[[], int]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class FlushResult:
    """What one flush pass rebuilt."""

    days: tuple[str, ...] = ()
    sightings: int = 0
    #: True when the pass crossed a receiver-local midnight and finalized the
    #: day that ended.
    day_closed: bool = False
    failed: bool = False

    @property
    def rebuilt(self) -> int:
        """How many days were rebuilt."""
        return len(self.days)


class AnalyticsService:
    """Keeps the §6.5 rollups current, and repairs them at startup.

    Args:
        database: the application database; writes take its single writer lock.
        persistence: the sighting worker whose lifecycle seam drives the dirty
            set. ``None`` is supported and means "nothing marks days dirty" —
            the periodic pass still maintains today, which is what a test or a
            read-only process wants.
        timezone: IANA zone the day buckets are keyed in (``docs/DATA_MODEL.md``
            §10). Read once at construction, matching §10's rule that a changed
            timezone applies to new rollups only.
        flush_interval_s: how often dirty days are rebuilt.
        max_backfill_days: bound on one startup repair pass.
        clock: UTC epoch-millisecond source.
        sleep: awaited between passes; injected so tests drive the cadence.
        counters: registry receiving write failures.
    """

    __slots__ = (
        "_backfill",
        "_clock",
        "_counters",
        "_current_day",
        "_dirty",
        "_flush_interval_s",
        "_persistence",
        "_repository",
        "_sleep",
        "_startup",
        "_task",
        "_zone",
    )

    def __init__(
        self,
        *,
        database: Database,
        persistence: PersistenceWorker | None = None,
        timezone: str = "UTC",
        flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
        max_backfill_days: int | None = None,
        clock: EpochClock = utc_now_ms,
        sleep: Sleeper = asyncio.sleep,
        counters: CounterRegistry = default_counters,
    ) -> None:
        if flush_interval_s <= 0.0:
            raise ValueError("flush_interval_s must be greater than zero")

        self._repository = AnalyticsRepository(database)
        self._zone = ZoneInfo(timezone)
        self._backfill = AnalyticsBackfill(
            repository=self._repository,
            meta=MetaRepository(database),
            zone=self._zone,
            **({} if max_backfill_days is None else {"max_days": max_backfill_days}),
        )
        self._persistence = persistence
        self._flush_interval_s = flush_interval_s
        self._clock = clock
        self._sleep = sleep
        self._counters = counters

        self._dirty: set[str] = set()
        self._current_day: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._startup = BackfillResult()

    # ------------------------------------------------------------ inspection

    @property
    def running(self) -> bool:
        """True while the flush task is alive."""
        return self._task is not None and not self._task.done()

    @property
    def dirty_days(self) -> frozenset[str]:
        """Receiver-local days awaiting a rebuild."""
        return frozenset(self._dirty)

    @property
    def startup_repair(self) -> BackfillResult:
        """What the startup backfill rebuilt at this service's last start.

        All-zero before :meth:`start` and after a boot that found nothing to
        repair, which is the ordinary case on a running install. Kept so the
        diagnostics surface (slice 042) can report the last boot's repair
        without re-deriving it.
        """
        return self._startup

    @property
    def repository(self) -> AnalyticsRepository:
        """The rollup repository, for the API's read path and for tests."""
        return self._repository

    @property
    def backfill(self) -> AnalyticsBackfill:
        """The backfill job, callable directly by tests and later by slice 044."""
        return self._backfill

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Repair, subscribe, and start the flush task. Idempotent.

        The repair runs *before* the subscription so a day the previous process
        left half-rolled-up is rebuilt from ground truth rather than from
        whatever this process happens to observe next — and it runs inline
        rather than in the background because everything after it, up to and
        including the first API request, reads rows it may be about to fix.
        """
        if self.running:
            return

        self._dirty.clear()
        now_ms = self._clock()
        self._current_day = local_day(now_ms, self._zone)
        self._startup = await self._repair(now_ms)

        if self._persistence is not None:
            self._persistence.subscribe_lifecycle(self._on_lifecycle)
        self._task = asyncio.create_task(self._loop(), name="flightsite-analytics")
        logger.info(
            "analytics_started",
            timezone=str(self._zone),
            flush_interval_s=self._flush_interval_s,
            repaired_days=self._startup.rebuilt,
            through_day=self._startup.through_day,
        )

    async def stop(self) -> None:
        """Unsubscribe, stop the task and flush what is dirty. Idempotent.

        The final flush is not optional in the same sense slice 033's is — no
        rollup figure is unrecoverable, since every one of them is derivable
        from ``sightings``. It is done anyway because it is cheap and because
        it means a clean shutdown leaves the rollups current, so the next boot's
        repair has nothing to do.
        """
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        if self._persistence is not None:
            self._persistence.unsubscribe_lifecycle(self._on_lifecycle)

        result = await self.flush()
        logger.info("analytics_stopped", flushed=result.rebuilt, pending=len(self._dirty))

    async def _loop(self) -> None:
        while True:
            await self._sleep(self._flush_interval_s)
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                # The loop outliving a bad pass matters more than the pass: a
                # dead maintainer would leave the analytics page frozen at
                # whatever the last successful flush wrote, with no indication
                # why.
                logger.warning(
                    "analytics_flush_error", error=str(exc), error_type=type(exc).__name__
                )

    # -------------------------------------------------------------- the seam

    def _on_lifecycle(self, event: SightingLifecycle) -> None:
        """Mark the days a committed cycle touched as needing a rebuild.

        Synchronous, allocation-light and never raising: it runs inside the
        persistence worker's cycle (see
        :data:`~flightsite.sightings.worker.SightingLifecycleListener`).

        The day marked is the one the sighting *started* in, for both opens and
        closes, because that is the bucket §6.5's rollups use
        (:mod:`flightsite.analytics.rollup` says why). A close therefore
        re-dirties the day the sighting opened on, which is what carries its
        final ``max_range_nm`` into that day's row even when the aircraft was
        overhead across midnight.
        """
        for reference in (*event.opened, *event.closed):
            self._dirty.add(local_day(reference.started_ms, self._zone))

    def mark_dirty(self, day: str) -> None:
        """Queue ``day`` for the next rebuild. For tests and later slices."""
        self._dirty.add(day)

    # ------------------------------------------------------------ the passes

    async def _repair(self, now_ms: int) -> BackfillResult:
        """One startup repair pass, never raising."""
        try:
            return await self._backfill.run_startup_repair(now_ms=now_ms)
        except Exception as exc:
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning(
                "analytics_backfill_failed", error=str(exc), error_type=type(exc).__name__
            )
            return BackfillResult()

    async def flush(self) -> FlushResult:
        """Rebuild every dirty day, plus any day that has just closed.

        Split out from the loop so tests drive it one pass at a time against a
        hand-driven clock, with no sleeping and no background task. Never
        raises: a write failure is an analytics problem and must not propagate
        into the task that took it.

        The dirty set is drained *before* the rebuild and restored on failure,
        so a day marked dirty by a cycle that commits mid-pass is rebuilt by the
        next pass rather than being lost to this one.
        """
        now_ms = self._clock()
        today = local_day(now_ms, self._zone)
        closed, complete = self._rollover(today)

        due = self._dirty | set(closed)
        # Today is rebuilt whenever anything at all is due, because a sighting
        # that closed just after midnight dirties yesterday while today's row
        # is the one a client is looking at.
        if due:
            due.add(today)
        if not due:
            return FlushResult()

        self._dirty -= due
        try:
            result = await self._backfill.rebuild_days(sorted(due), now_ms=now_ms)
            if closed:
                await self._backfill.refresh_type_stats()
                # Only when the rebuilt run reaches back to where the last pass
                # left off: a truncated run has unfinalized days behind it, and
                # a watermark past them would stop the next boot's repair from
                # ever reaching them.
                if complete:
                    await self._backfill.set_watermark(closed[-1])
        except Exception as exc:
            self._dirty |= due
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning(
                "analytics_flush_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                days=len(due),
            )
            return FlushResult(failed=True)

        if closed:
            logger.info("analytics_days_closed", days=list(closed), complete=complete)
        return FlushResult(
            days=result.days,
            sightings=result.sightings,
            day_closed=bool(closed),
        )

    def _rollover(self, today: str) -> tuple[tuple[str, ...], bool]:
        """Every day that ended since the last pass, and whether that is all of them.

        A pass usually crosses at most one midnight, but a process that was
        suspended — a Pi asleep, a laptop lid closed, a long ``VACUUM`` — can
        wake up several days later, and *every* day in between needs its
        ``busiest_hour`` finalized, not just the most recent one.

        The run is capped at :data:`MAX_ROLLOVER_DAYS` so that a clock jumping
        years forward cannot turn one flush into an unbounded rebuild. The
        second element of the return says whether the cap bit: when it did, the
        watermark is deliberately left where it was, and the next boot's repair
        walks the whole gap from there.
        """
        previous, self._current_day = self._current_day, today
        if previous is None or previous >= today:
            return (), True
        floor = max(previous, shift_days(today, -MAX_ROLLOVER_DAYS))
        return tuple(days_in_range(floor, previous_day(today))), floor == previous


__all__ = [
    "DEFAULT_FLUSH_INTERVAL_S",
    "MAX_ROLLOVER_DAYS",
    "AnalyticsService",
    "EpochClock",
    "FlushResult",
]
