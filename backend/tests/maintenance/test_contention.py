"""Maintenance runs unattended without blocking ingestion (slice 044 AC #1).

The invariant is structural — nothing on the decoder poll path or in
:meth:`~flightsite.live.store.LiveStore.apply_updates` touches SQLite at all
(``docs/ARCHITECTURE.md`` §3.1) — but "structural" is a claim, and this slice
adds the process's first deliberately *long* database operation. So it is
measured, the same way slice 009's stalled-writer test and slice 033's stalled
-metrics-write test measure it: time the live-apply path while the database is
busy, and compare against a baseline taken while it is idle.

Two shapes, because there are two ways maintenance can be in the way. It can be
*running* — holding the writer lock through a real ``VACUUM`` — or it can be
*queued*, waiting behind somebody else's writer transaction. Ingestion must not
notice either.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import delete, insert

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.db.models import Meta
from flightsite.live import LiveStore
from flightsite.maintenance.model import VACUUM_JOB, DatabaseStats, JobOutcome
from flightsite.maintenance.policy import VACUUM_MIN_DB_BYTES, VACUUM_MIN_RECLAIMABLE_RATIO
from flightsite.maintenance.service import MaintenanceService, StatsProbe
from tests.maintenance.conftest import ManualClock, make_stats, observations

#: Aircraft applied per timed batch. A realistic busy-receiver batch, and
#: enough work that the measurement is not dominated by loop overhead.
FLEET = 100

#: Timed batches per phase.
SAMPLES = 40

#: ``docs/ARCHITECTURE.md`` §3.3's absolute ceiling: a 500-aircraft batch must
#: apply well inside one polling interval. A hundred aircraft has far more room
#: than this, so the budget is deliberately generous and still decisive.
APPLY_BUDGET_S = 0.1

#: How much slower than its own baseline the apply path may get.
SLOWDOWN_ALLOWANCE = 4.0

#: Floor under the allowance, so a microsecond baseline is not hypersensitive.
MINIMUM_ALLOWANCE_S = 0.005

#: Filler rows written and then deleted, to give ``VACUUM`` real work to do.
FILLER_ROWS = 4_000

VACUUM_READY = make_stats(
    db_bytes=4 * VACUUM_MIN_DB_BYTES, reclaimable_ratio=VACUUM_MIN_RECLAIMABLE_RATIO + 0.1
)


def _fixed(stats: DatabaseStats) -> StatsProbe:
    async def probe() -> DatabaseStats:
        return stats

    return probe


def _apply_once(live: LiveStore, offset_s: float) -> float:
    """Apply one batch of observations and return how long it took."""
    batch = observations(FLEET, offset_s=offset_s)
    started = time.perf_counter()
    live.apply_updates(batch)
    return time.perf_counter() - started


async def _median_apply_time(live: LiveStore, *, samples: int = SAMPLES) -> float:
    """Median of ``samples`` timed batches, yielding the loop between each.

    A median rather than a maximum: a single scheduler hiccup on a shared CI
    runner is noise, while a systematic delay moves the middle of the
    distribution. The yield matters — without it nothing else on the loop would
    get to run, and the comparison would be against an idle database either way.
    """
    timings: list[float] = []
    for index in range(samples):
        timings.append(_apply_once(live, offset_s=float(index)))
        await asyncio.sleep(0)
    timings.sort()
    return timings[len(timings) // 2]


async def _seed_reclaimable_space(database: Database) -> None:
    """Write and then delete enough rows that a ``VACUUM`` has work to do."""
    async with database.writer_session() as session:
        await session.execute(
            insert(Meta).values(
                [
                    {"key": f"filler-{index:05d}", "value": "x" * 400, "updated_ms": 1}
                    for index in range(FILLER_ROWS)
                ]
            )
        )
    async with database.writer_session() as session:
        await session.execute(delete(Meta).where(Meta.key.like("filler-%")))


@pytest.mark.perf
async def test_the_live_picture_is_unaffected_while_a_maintenance_cycle_runs(
    database: Database, clock: ManualClock, counters: CounterRegistry, live: LiveStore
) -> None:
    """A full cycle — integrity check, prune, optimize, checkpoint, VACUUM.

    Every one of those runs inside aiosqlite's worker thread, so the event loop
    stays free and the apply path never waits on any of them. The applies here
    run for the *whole* duration of the cycle rather than for a fixed window,
    so there is no way for the measurement to miss the expensive part.
    """
    await _seed_reclaimable_space(database)
    baseline_s = await _median_apply_time(live)

    service = MaintenanceService(
        database=database, clock=clock, counters=counters, stats=_fixed(VACUUM_READY)
    )
    cycle = asyncio.create_task(service.run_cycle())

    timings: list[float] = []
    while not cycle.done() or len(timings) < SAMPLES:
        timings.append(_apply_once(live, offset_s=float(len(timings))))
        await asyncio.sleep(0)
    report = await cycle

    # The cycle really did the expensive thing; otherwise this proves nothing.
    assert report.jobs[VACUUM_JOB].outcome is JobOutcome.OK

    timings.sort()
    during_s = timings[len(timings) // 2]
    worst_s = timings[-1]
    allowance_s = max(baseline_s * SLOWDOWN_ALLOWANCE, MINIMUM_ALLOWANCE_S)
    assert during_s <= allowance_s, (
        f"applying {FLEET} aircraft took {during_s * 1000:.3f} ms during a "
        f"maintenance cycle against a {baseline_s * 1000:.3f} ms baseline"
    )
    assert worst_s < APPLY_BUDGET_S


async def test_the_live_picture_is_unaffected_while_maintenance_waits_for_the_writer(
    database: Database, clock: ManualClock, counters: CounterRegistry, live: LiveStore
) -> None:
    """The other direction: maintenance queued behind somebody else's writer.

    Deterministic rather than timed-on-average — the held lock is released only
    when this test says so, so the cycle is provably still blocked while every
    measurement is taken.
    """
    release = asyncio.Event()

    async def hold_the_writer() -> None:
        async with database.writer_session():
            await release.wait()

    holder = asyncio.create_task(hold_the_writer())
    await asyncio.sleep(0)

    service = MaintenanceService(
        database=database, clock=clock, counters=counters, stats=_fixed(make_stats())
    )
    cycle = asyncio.create_task(service.run_cycle())
    await asyncio.sleep(0)

    try:
        worst_s = 0.0
        for index in range(SAMPLES):
            worst_s = max(worst_s, _apply_once(live, offset_s=float(index)))
            await asyncio.sleep(0)
        assert not cycle.done(), "maintenance should still be queued behind the writer"
    finally:
        release.set()
        await holder
        await cycle

    assert worst_s < APPLY_BUDGET_S
    assert len(live) == FLEET
