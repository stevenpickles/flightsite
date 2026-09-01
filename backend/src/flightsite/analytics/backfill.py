"""The backfill: rebuild any day's rollups from sighting ground truth.

Two callers, one operation. :class:`AnalyticsBackfill` rebuilds a named set of
receiver-local days by reading the sightings that started in each day and
replacing that day's rows with the fold of them. The incremental maintainer
(:mod:`flightsite.analytics.service`) calls it for the handful of days a
sighting has just touched; startup calls it for whatever the previous process
left missing or stale.

That is the whole of the convergence guarantee. There is no second code path
that "adds one sighting to a running total": an incremental update *is* a
rebuild of the day that sighting fell in. Whether a day's row was produced by
one rebuild after a year of quiet or by four hundred rebuilds as the day
happened, the row is the fold of the same set of sightings — so incremental
maintenance and a from-scratch backfill cannot disagree, and a crash at any
point costs at most a stale day that the next pass repairs.

The cost of that choice is honest and bounded: maintaining today's rollup
re-reads today's sightings on each pass. That is a range scan over
``ix_sightings_started`` of one day's rows — a few hundred to a couple of
thousand on the receiver ``docs/DATA_MODEL.md`` §6.5 sizes for — every flush
interval, on a background task that nothing waits on. The alternative, a
long-lived in-memory accumulator, would buy that back and pay for it with a
second implementation of every figure, a restart path that has to reconstruct
it, and no way to notice that a metadata import has just given a month-old
airframe its type. Slice 031 is the slice whose acceptance criterion is
*correctness against brute force*; this is the design that makes that criterion
true by construction rather than by test.

What "missing or stale" means at startup
-----------------------------------------

Two sources, and each covers what the other cannot:

* **The watermark** (``meta`` key
  :data:`~flightsite.analytics.repository.META_KEY_ROLLUP_THROUGH_DAY`) names
  the last day the rollups are known complete through. Every day after it, up
  to today, is rebuilt. On an install upgrading into this slice the key is
  absent and the floor becomes the first day this receiver ever recorded a
  sighting, so the whole history is built once.
* **Today and yesterday are always rebuilt**, watermark or not. They are the
  two days a process can have been interrupted in the middle of, and rebuilding
  them is a few milliseconds.

The pass is bounded by :data:`DEFAULT_MAX_BACKFILL_DAYS`. A history longer than
that is rebuilt oldest-first across successive boots, because the watermark
advances contiguously — a partial pass leaves a *correct* watermark for what it
did, never a claim about days it has not reached.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from zoneinfo import ZoneInfo

import structlog

from flightsite.analytics.bucketing import (
    day_bounds_ms,
    days_in_range,
    local_day,
    next_day,
    previous_day,
    shift_days,
)
from flightsite.analytics.model import DayRollup
from flightsite.analytics.repository import META_KEY_ROLLUP_THROUGH_DAY, AnalyticsRepository
from flightsite.analytics.rollup import fold_day
from flightsite.db.meta import MetaRepository

logger = structlog.get_logger(__name__)

#: Days one startup pass will rebuild. Ten years of history in a single boot,
#: which no install reaches; the bound exists so that a corrupt or absurd
#: watermark cannot turn startup into an unbounded scan.
DEFAULT_MAX_BACKFILL_DAYS: Final = 3_650


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """What one backfill pass rebuilt."""

    days: tuple[str, ...] = ()
    sightings: int = 0
    #: The watermark this pass left behind, or ``None`` if it advanced none.
    through_day: str | None = None
    #: True when the pass stopped at :data:`DEFAULT_MAX_BACKFILL_DAYS` and a
    #: later boot has more to do.
    truncated: bool = False

    @property
    def rebuilt(self) -> int:
        """How many days were rebuilt."""
        return len(self.days)


class AnalyticsBackfill:
    """Rebuilds receiver-local days of rollup from ``sightings``.

    Args:
        repository: the rollup repository; every read and write goes through it.
        meta: the ``meta`` key/value store holding the watermark.
        zone: the receiver's IANA zone (``docs/DATA_MODEL.md`` §10).
        max_days: bound on one :meth:`run_startup_repair` pass.
    """

    __slots__ = ("_max_days", "_meta", "_repository", "_zone")

    def __init__(
        self,
        *,
        repository: AnalyticsRepository,
        meta: MetaRepository,
        zone: ZoneInfo,
        max_days: int = DEFAULT_MAX_BACKFILL_DAYS,
    ) -> None:
        if max_days < 1:
            raise ValueError("max_days must be at least one")
        self._repository = repository
        self._meta = meta
        self._zone = zone
        self._max_days = max_days

    # -------------------------------------------------------------- one day

    async def rebuild_day(self, day: str, *, now_ms: int) -> DayRollup:
        """Rebuild one local day from ground truth and write it.

        Idempotent full-day replacement: reading the same sightings twice
        writes the same rows twice. The day counts as *closed* — and therefore
        gets its ``busiest_hour`` written, per §6.5 — exactly when its local
        end boundary is at or before ``now_ms``.
        """
        start_ms, end_ms = day_bounds_ms(day, self._zone)
        facts = await self._repository.facts_between(start_ms, end_ms)
        rollup = fold_day(day, facts, zone=self._zone, closed=end_ms <= now_ms)
        await self._repository.replace_day(rollup)
        return rollup

    async def rebuild_days(self, days: Sequence[str], *, now_ms: int) -> BackfillResult:
        """Rebuild each of ``days``, one transaction each, in calendar order."""
        rebuilt: list[str] = []
        sightings = 0
        for day in sorted(set(days)):
            rollup = await self.rebuild_day(day, now_ms=now_ms)
            rebuilt.append(day)
            sightings += rollup.sightings
        return BackfillResult(days=tuple(rebuilt), sightings=sightings)

    # -------------------------------------------------------- the whole job

    async def refresh_type_stats(self) -> int:
        """Re-derive ``type_stats`` in full; returns the row count written."""
        return await self._repository.replace_type_stats(await self._repository.derive_type_stats())

    async def plan_startup_repair(self, *, now_ms: int) -> list[str]:
        """The days a startup pass should rebuild, oldest first.

        Empty when this install has never persisted a sighting: there is no
        history to repair and no day to write a zero row for.
        """
        span = await self._repository.sighting_span_ms()
        if span is None:
            return []

        today = local_day(now_ms, self._zone)
        watermark = await self.watermark()
        floor = next_day(watermark) if watermark is not None else local_day(span[0], self._zone)
        # A watermark ahead of today is not a state this process can produce;
        # it means the clock moved backwards or the timezone changed. Repairing
        # from today is the conservative reading — never rebuild *less* than the
        # two days a restart can have interrupted.
        floor = min(floor, shift_days(today, -1))

        # Bounded before enumeration, not after: a corrupt watermark could name
        # a day in 1970, and building that list to slice it would be the
        # unbounded allocation the bound exists to prevent. Oldest-first, so a
        # truncated pass leaves a contiguous prefix behind a correct watermark
        # and the next boot continues from it.
        ceiling = min(today, shift_days(floor, self._max_days - 1))
        planned = days_in_range(floor, ceiling)
        if ceiling < today:
            logger.warning(
                "analytics_backfill_truncated",
                planned=len(planned),
                through_day=ceiling,
                max_days=self._max_days,
            )
        return planned

    async def run_startup_repair(self, *, now_ms: int) -> BackfillResult:
        """Rebuild whatever the previous process left missing or stale.

        Runs the plan, advances the watermark to the last *closed* day it
        covered, and re-derives ``type_stats``. The watermark deliberately
        stops short of today: today is still accumulating sightings, so
        claiming it complete would keep the next boot from rebuilding it.
        """
        planned = await self.plan_startup_repair(now_ms=now_ms)
        if not planned:
            await self.refresh_type_stats()
            return BackfillResult()

        result = await self.rebuild_days(planned, now_ms=now_ms)
        await self.refresh_type_stats()

        # The plan always reaches back to at least yesterday (see
        # :meth:`plan_startup_repair`), so there is always a closed day to
        # advance the watermark to — and today is always excluded from it,
        # because a day still accumulating sightings is not complete.
        today = local_day(now_ms, self._zone)
        through = [day for day in result.days if day < today][-1]
        await self.set_watermark(through)
        logger.info(
            "analytics_backfill_complete",
            days=result.rebuilt,
            sightings=result.sightings,
            through_day=through,
        )
        return BackfillResult(
            days=result.days,
            sightings=result.sightings,
            through_day=through,
            truncated=len(planned) == self._max_days,
        )

    # --------------------------------------------------------- the watermark

    async def watermark(self) -> str | None:
        """The last day the rollups are known complete through, if any.

        A stored value that is not a calendar date is treated as absent rather
        than raised on: the watermark is an optimization over a rebuild that is
        always correct, so a corrupt one must cost a slower boot, never a
        failed one.
        """
        raw = await self._meta.get(META_KEY_ROLLUP_THROUGH_DAY)
        if raw is None:
            return None
        try:
            previous_day(raw)
        except ValueError:
            logger.warning("analytics_watermark_unreadable", value=raw)
            return None
        return raw

    async def set_watermark(self, day: str) -> None:
        """Record ``day`` as the last day the rollups are complete through."""
        await self._meta.set(META_KEY_ROLLUP_THROUGH_DAY, day)


__all__ = ["DEFAULT_MAX_BACKFILL_DAYS", "AnalyticsBackfill", "BackfillResult"]
