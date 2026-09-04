"""The receiver-metrics service: a stats poller and a maintenance scheduler.

Where this runs, and why
------------------------

``docs/ARCHITECTURE.md`` §3.3 lists the asyncio tasks this process runs, and
the last of them is *"Stats poller / maintenance scheduler — low-frequency
background tasks"*. That is this module: two tasks, one sampling the receiver
every ~15 s and one downsampling and pruning every few minutes.

The roadmap states the same requirement from the other end — *"runs in
persistence worker; never blocks ingestion"* — and both halves of that hold
here. **Never blocks ingestion** is structural: nothing on the decoder poll
path, the live store's ``apply`` path or any API path can reach this service.
It reads :meth:`~flightsite.live.store.LiveStore.snapshot`, which is an
immutable tuple, and it makes its own HTTP request to a different endpoint on
its own task. **Runs in the persistence worker** is honoured as what it is
there to guarantee — the single-writer discipline: every write goes through
:meth:`~flightsite.db.engine.Database.writer_session`, the process's one
serialized writer (ADR-0001, ADR-0008), in batched short transactions on a
periodic flush.

What it is *not* is a passenger on
:class:`~flightsite.sightings.worker.PersistenceWorker`'s cycle, and that is
deliberate. That worker's cycle exists to keep one accumulator per open
sighting consistent with one row per sighting; enrichment and airport context
ride it because they write *into those same rows*. Receiver metrics share no
row, no accumulator and no failure mode with it — they are five tables nothing
else touches — so folding them in would add a way for a metrics bug to fail a
sighting transaction, in exchange for a serialization the writer lock already
provides.

The two cadences
----------------

* **Sampling** every :data:`~flightsite.receiver_metrics.sampler.DEFAULT_SAMPLE_INTERVAL_S`
  — the raw row spacing ``docs/DATA_MODEL.md`` §6.1 states. Each tick polls the
  decoder's ``stats.json`` (if it serves one), takes one sample of the live
  set, and buffers it. Samples are written out every
  :data:`DEFAULT_FLUSH_INTERVAL_S` in one transaction rather than one
  transaction per sample, for the same reason the sighting worker batches: a
  few rows are not worth a commit each on an SD card.
* **Maintenance** every :data:`DEFAULT_MAINTENANCE_INTERVAL_S`: recompute the
  hourly and daily summaries, then prune the expired high-resolution rows.
  Always in that order — a row must be summarized before it can be discarded,
  and ADR-0009's whole structure depends on it.

Degradation
-----------

Every failure mode ends in metrics being less complete, and none of them ends
anywhere else:

* No decoder configured, or no ``stats.json`` — FlightSite computes what it
  can from the live set and leaves the decoder columns ``NULL`` (SPEC §60).
* A statistics poll that genuinely fails — counted into ``ingestion_failures``,
  the sample is taken anyway with its decoder half absent.
* A flush that fails — counted into ``db_errors``, the buffer is kept and the
  next flush carries it. The lifetime delta is put back rather than dropped, so
  a transient write failure cannot cost a lifetime total.
* A buffer that grows past :data:`MAX_PENDING_SAMPLES` because writes keep
  failing — the *oldest raw samples* are shed, and only those. The lifetime
  totals and records they contributed to are already in the accumulator, so
  what a sustained write outage costs is high-resolution detail, never a
  record (ADR-0009).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Final
from zoneinfo import ZoneInfo

import structlog

from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.clock import MS_PER_SECOND, utc_now_ms
from flightsite.db.engine import Database
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.live.store import LiveStore
from flightsite.receiver_metrics.aggregate import (
    MS_PER_HOUR,
    daily,
    hour_start_ms,
    hourly,
    local_day,
    local_day_start_ms,
)
from flightsite.receiver_metrics.lifetime import LifetimeAccumulator
from flightsite.receiver_metrics.model import (
    DecoderStats,
    MetricSample,
    MetricSummary,
    RangeRecord,
    better_range,
)
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.sampler import DEFAULT_SAMPLE_INTERVAL_S, MetricSampler
from flightsite.receiver_metrics.statsjson import StatsJsonPoller

logger = structlog.get_logger(__name__)

#: Counter a genuinely failed statistics poll increments.
#:
#: Deliberately the decoder's existing counter rather than a new one: this is a
#: failed request to the decoder, which is exactly what ``ingestion_failures``
#: already means to the health payload and to the diagnostics surface
#: (SPEC §67's *"recent ingestion errors"*). A decoder that simply serves no
#: statistics document is *not* counted here — see
#: :mod:`flightsite.receiver_metrics.statsjson`.
POLL_FAILURES_COUNTER: Final = "ingestion_failures"

#: How often buffered samples are written. Four samples a transaction at the
#: default cadence, which bounds what an unclean shutdown costs the raw tier to
#: one interval — the same bound ADR-0005 puts on track checkpoints.
DEFAULT_FLUSH_INTERVAL_S: Final = 60.0

#: How often summaries are recomputed and expired rows pruned. Frequent enough
#: that the in-progress hour and day are never far behind, rare enough that the
#: work is invisible: ADR-0009 asks for maintenance "sized to run without
#: ingestion impact".
DEFAULT_MAINTENANCE_INTERVAL_S: Final = 300.0

#: Days of high-resolution samples retained by default (ADR-0009, SPEC §64).
DEFAULT_HIGH_RES_DAYS: Final = 14

#: Buffered samples before the oldest are shed. An hour of them at the default
#: cadence: long enough that no plausible transient write failure loses a row,
#: bounded so a permanent one cannot grow the process without limit.
MAX_PENDING_SAMPLES: Final = 240

MS_PER_DAY: Final = 24 * MS_PER_HOUR

#: Margin above the prune boundary within which a summary is *not* recomputed.
#:
#: One hour, because a bucket is only recomputable while the sample immediately
#: *before* it survives — that is what attributes the bucket's first interval
#: of traffic. A bucket starting exactly at the prune boundary has lost its
#: predecessor, so recomputing it would silently drop one interval from a row
#: that was already final and correct. Above the margin every predecessor is
#: retained, so every recomputation reproduces the same row.
RECOMPUTE_MARGIN_MS: Final = MS_PER_HOUR

#: A source of UTC epoch milliseconds, injected so cadence and retention tests
#: run against a hand-driven clock rather than ``asyncio.sleep``.
EpochClock = Callable[[], int]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    """What one downsample-and-prune pass did."""

    hours_written: int = 0
    days_written: int = 0
    pruned: int = 0
    failed: bool = False


class ReceiverMetricsService:
    """Samples the receiver, stores the samples, and enforces ADR-0009's tiers.

    Args:
        database: the application database; writes take its single writer lock.
        live: the live store sampled for aircraft counts and range.
        poller: the decoder statistics poller, or ``None`` when no decoder is
            configured (a first-run install, or demo mode). ``None`` is a fully
            supported state: every FlightSite-computed metric is still recorded.
        timezone: IANA zone the daily buckets are keyed in (``docs/DATA_MODEL.md``
            §10). Read once at construction, matching §10's rule that a changed
            timezone applies to new rollups only.
        high_res_days: the ADR-0009 window, 7 to 30 days.
        sample_interval_s: raw sample spacing.
        flush_interval_s: how often buffered samples are written.
        maintenance_interval_s: how often summaries and pruning run.
        clock: UTC epoch-millisecond source.
        sleep: awaited between ticks; injected so tests drive the cadence.
        counters: registry receiving poll and write failures.
    """

    __slots__ = (
        "_accumulator",
        "_clock",
        "_counters",
        "_flush_interval_ms",
        "_last_flush_ms",
        "_latest_stats",
        "_live",
        "_maintenance_interval_s",
        "_maintenance_task",
        "_pending",
        "_pending_ranges",
        "_poller",
        "_previous_sample",
        "_repository",
        "_sample_interval_s",
        "_sample_task",
        "_sampler",
        "_shed",
        "_sleep",
        "_stats_supported",
        "_summary_floor_ms",
        "_window_ms",
        "_zone",
    )

    def __init__(
        self,
        *,
        database: Database,
        live: LiveStore,
        poller: StatsJsonPoller | None = None,
        timezone: str = "UTC",
        high_res_days: int = DEFAULT_HIGH_RES_DAYS,
        sample_interval_s: float = DEFAULT_SAMPLE_INTERVAL_S,
        flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
        maintenance_interval_s: float = DEFAULT_MAINTENANCE_INTERVAL_S,
        clock: EpochClock = utc_now_ms,
        sleep: Sleeper = asyncio.sleep,
        counters: CounterRegistry = default_counters,
    ) -> None:
        if sample_interval_s <= 0.0:
            raise ValueError("sample_interval_s must be greater than zero")
        if flush_interval_s <= 0.0:
            raise ValueError("flush_interval_s must be greater than zero")
        if maintenance_interval_s <= 0.0:
            raise ValueError("maintenance_interval_s must be greater than zero")
        if high_res_days < 1:
            raise ValueError("high_res_days must be at least one")

        self._repository = MetricsRepository(database)
        self._live = live
        self._poller = poller
        self._zone = ZoneInfo(timezone)
        self._window_ms = high_res_days * MS_PER_DAY
        self._sample_interval_s = sample_interval_s
        self._flush_interval_ms = int(flush_interval_s * MS_PER_SECOND)
        self._maintenance_interval_s = maintenance_interval_s
        self._clock = clock
        self._sleep = sleep
        self._counters = counters

        self._sampler = MetricSampler()
        self._accumulator = LifetimeAccumulator()
        self._pending: list[MetricSample] = []
        self._pending_ranges: dict[str, dict[int, RangeRecord]] = {}
        self._previous_sample: MetricSample | None = None
        self._last_flush_ms: int | None = None
        self._summary_floor_ms: int | None = None
        self._latest_stats: DecoderStats | None = None
        self._stats_supported: bool | None = None
        self._shed = 0
        self._sample_task: asyncio.Task[None] | None = None
        self._maintenance_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ inspection

    @property
    def running(self) -> bool:
        """True while the sampling task is alive."""
        return self._sample_task is not None and not self._sample_task.done()

    @property
    def pending_samples(self) -> int:
        """Samples buffered but not yet written."""
        return len(self._pending)

    @property
    def shed_samples(self) -> int:
        """Raw samples dropped because writes could not keep up.

        Never anything but raw detail: what they contributed to the lifetime
        totals and records was folded in before they were buffered.
        """
        return self._shed

    @property
    def latest_stats(self) -> DecoderStats | None:
        """The most recent decoder statistics, or ``None`` if there are none.

        The live half of the receiver scorecard (SPEC §61) — decoder uptime in
        particular, which has no stored column because it is a statement about
        right now. Slice 034's API reads this.
        """
        return self._latest_stats

    @property
    def stats_supported(self) -> bool | None:
        """Whether this decoder serves usable statistics.

        ``None`` before the first poll; ``False`` for a decoder with no
        statistics document, which is a supported configuration rather than a
        fault (SPEC §60).
        """
        return self._stats_supported

    # ------------------------------------------------------------- lifecycle

    async def attach_poller(self, poller: StatsJsonPoller) -> None:
        """Give a service built without a decoder the poller it can now use.

        The first-run case, and only it (issue #129). The service is
        constructed before the install has a receiver, so it is built with
        ``poller=None`` and records every FlightSite-computed metric with the
        decoder columns ``NULL``. The save that ends the first-run state is the
        moment a decoder exists — and until this method existed there was no
        way to tell an already-running service so, which left the
        decoder-supplied columns ``NULL`` until the backend was restarted. It
        is the metrics half of the hot-start
        :mod:`flightsite.api.ingestion` performs for the aircraft stream.

        A service that already has a poller **keeps it**: this logs and
        returns, rather than replacing it. Replacing would mean stopping an
        in-flight poll and discarding the availability state and latest reading
        that belong to the old endpoint, and changing the endpoint of a running
        poller is restart-required for exactly the same reason it is for the
        ingestion adapter.

        Before :meth:`start`, the poller is simply held and started there. On a
        running service it is opened here, because the sampling loop is already
        ticking and the next tick must find an open client. Either way
        :meth:`stop` closes it. A failure to open propagates to the caller and
        leaves nothing half-attached: :meth:`StatsJsonPoller.poll` opens the
        client itself if it is still closed, so the next sample recovers.
        """
        if self._poller is not None:
            logger.info("receiver_stats_poller_already_attached", url=self._poller.url)
            return
        self._poller = poller
        # A poller that has never been asked has told us nothing: no
        # availability verdict, no reading. Stated rather than assumed, so the
        # bookkeeping cannot outlive the poller it describes.
        self._stats_supported = None
        self._latest_stats = None
        if self.running:
            await poller.start()
        logger.info("receiver_stats_poller_attached", url=poller.url, running=self.running)

    async def start(self) -> None:
        """Start sampling and maintenance. Idempotent.

        The sampler's baseline is cleared first: the counters it would
        otherwise difference against were read before whatever gap the restart
        represents, so the first sample after a start reports no rates at all
        rather than an invented one (SPEC §39).
        """
        if self.running:
            return
        self._sampler.reset()
        self._previous_sample = None
        self._summary_floor_ms = None
        if self._poller is not None:
            await self._poller.start()
        self._sample_task = asyncio.create_task(self._sample_loop(), name="flightsite-stats-poller")
        self._maintenance_task = asyncio.create_task(
            self._maintenance_loop(), name="flightsite-metrics-maintenance"
        )
        logger.info(
            "receiver_metrics_started",
            sample_interval_s=self._sample_interval_s,
            high_res_days=self._window_ms // MS_PER_DAY,
            timezone=str(self._zone),
            decoder_stats=self._poller is not None,
        )

    async def stop(self) -> None:
        """Stop both tasks and flush what is buffered. Idempotent.

        The final flush is not optional: an interval's worth of samples and,
        more importantly, the lifetime increments they carry are in memory at
        this point, and a clean shutdown that dropped them would lose totals a
        restart cannot rebuild.
        """
        for attribute in ("_sample_task", "_maintenance_task"):
            task: asyncio.Task[None] | None = getattr(self, attribute)
            setattr(self, attribute, None)
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        await self.flush()
        if self._poller is not None:
            await self._poller.stop()
        logger.info("receiver_metrics_stopped", pending=len(self._pending), shed=self._shed)

    async def _sample_loop(self) -> None:
        while True:
            await self._sleep(self._sample_interval_s)
            try:
                await self.sample_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                # The loop outliving a bad tick matters more than the tick: a
                # dead sampler would leave the receiver page frozen with no
                # indication why.
                logger.warning(
                    "receiver_metrics_sample_error", error=str(exc), error_type=type(exc).__name__
                )

    async def _maintenance_loop(self) -> None:
        while True:
            await self._sleep(self._maintenance_interval_s)
            try:
                await self.run_maintenance()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "receiver_metrics_maintenance_error",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

    # ---------------------------------------------------------- one sampling

    async def sample_once(self) -> MetricSample:
        """Poll, sample, buffer, and flush if the flush interval has elapsed.

        Split out from the loop so tests drive it one tick at a time against a
        hand-driven clock, with no sleeping and no background task.
        """
        stats = await self._poll_stats()
        ts_ms = self._clock()
        result = self._sampler.sample(ts_ms=ts_ms, aircraft=self._live.snapshot(), stats=stats)

        self._accumulator.observe(
            result.sample, previous=self._previous_sample, ranges=result.ranges
        )
        self._previous_sample = result.sample
        self._buffer(result.sample)
        self._remember_ranges(local_day(ts_ms, self._zone), result.ranges)

        if self._flush_due(ts_ms):
            await self.flush()
        return result.sample

    async def _poll_stats(self) -> DecoderStats | None:
        """One statistics poll, reduced to "usable statistics, or not"."""
        if self._poller is None:
            return None

        poll = await self._poller.poll()
        if poll.failed:
            self._counters.increment(POLL_FAILURES_COUNTER)
            logger.debug("receiver_stats_poll_failed", url=self._poller.url, error=poll.error)
            return None

        supported = poll.stats is not None
        if supported != self._stats_supported:
            # Once per transition, not once per poll: a decoder with no
            # statistics document is polled every fifteen seconds forever, and
            # saying so every time would be a log flood describing a supported
            # configuration.
            logger.info(
                "receiver_stats_availability_changed",
                url=self._poller.url,
                supported=supported,
            )
        self._stats_supported = supported
        self._latest_stats = poll.stats
        return poll.stats

    def _buffer(self, sample: MetricSample) -> None:
        self._pending.append(sample)
        while len(self._pending) > MAX_PENDING_SAMPLES:
            self._pending.pop(0)
            self._shed += 1

    def _remember_ranges(self, day: str, ranges: tuple[RangeRecord, ...]) -> None:
        if not ranges:
            return
        sectors = self._pending_ranges.setdefault(day, {})
        for record in ranges:
            bucket = record.bearing_bucket
            sectors[bucket] = better_range(sectors.get(bucket), record)

    def _flush_due(self, now_ms: int) -> bool:
        if self._last_flush_ms is None:
            self._last_flush_ms = now_ms
            return False
        return now_ms - self._last_flush_ms >= self._flush_interval_ms

    # -------------------------------------------------------------- flushing

    async def flush(self) -> bool:
        """Write buffered samples, range records and lifetime increments.

        One transaction. Returns ``False`` when there was nothing to write or
        when the write failed — in the failure case nothing in memory is
        cleared, so the next flush carries the same batch. Never raises: a
        write failure is a metrics problem and must not propagate into the task
        that took the samples.
        """
        samples = tuple(self._pending)
        ranges: Mapping[str, list[RangeRecord]] = {
            day: [sectors[bucket] for bucket in sorted(sectors)]
            for day, sectors in self._pending_ranges.items()
        }
        delta = self._accumulator.drain()
        if not samples and not ranges and delta.is_empty:
            return False

        now_ms = self._clock()
        try:
            await self._repository.record(samples, ranges, delta, at_ms=now_ms)
        except Exception as exc:
            self._accumulator.restore(delta)
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning(
                "receiver_metrics_flush_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                samples=len(samples),
            )
            return False

        del self._pending[: len(samples)]
        self._pending_ranges.clear()
        self._last_flush_ms = now_ms
        return True

    # ----------------------------------------------------------- maintenance

    async def run_maintenance(self) -> MaintenanceResult:
        """Recompute the summaries, then prune what has expired. In that order.

        The order is ADR-0009's structure expressed as two statements in one
        method: a high-resolution row is summarized before it can be
        discarded, so the fortnight the raw tier keeps is the only thing the
        prune costs.

        Recomputation is a full replacement of each bucket from its raw rows,
        so running this twice over the same data writes the same rows twice —
        which is the idempotence ADR-0009 requires of a pass that a crash may
        have interrupted.
        """
        now_ms = self._clock()
        span = await self._repository.raw_span()
        if span is None:
            return MaintenanceResult()

        prune_before_ms = hour_start_ms(now_ms - self._window_ms)
        frozen_before_ms = prune_before_ms + RECOMPUTE_MARGIN_MS
        start_ms = self._reprocess_from(span[0], now_ms)

        try:
            hours, days = await self._recompute(start_ms, now_ms, frozen_before_ms)
            await self._repository.write_summaries(hours, days, at_ms=now_ms)
        except Exception as exc:
            # The watermark is not advanced, so the next pass covers this
            # pass's range as well as its own — and nothing is pruned, because
            # pruning a row whose summary failed to land is the one ordering
            # ADR-0009 forbids.
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning(
                "receiver_metrics_downsample_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return MaintenanceResult(failed=True)

        self._summary_floor_ms = self._recent_floor(now_ms)

        try:
            pruned = await self._repository.prune_raw(prune_before_ms)
        except Exception as exc:
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning(
                "receiver_metrics_prune_failed", error=str(exc), error_type=type(exc).__name__
            )
            return MaintenanceResult(hours_written=len(hours), days_written=len(days), failed=True)

        if pruned:
            logger.info("receiver_metrics_pruned", rows=pruned, before_ms=prune_before_ms)
        return MaintenanceResult(hours_written=len(hours), days_written=len(days), pruned=pruned)

    def _recent_floor(self, now_ms: int) -> int:
        """Local midnight opening the day before ``now_ms``.

        The steady-state reprocessing floor. Yesterday rather than today so
        that a pass just after midnight still finalizes the day that has just
        ended, and a whole local day rather than a few hours so that a daily
        bucket is always folded from the whole of the day it names — which is
        what keeps the daily tier exact in zones whose offset is not a whole
        number of hours.
        """
        return local_day_start_ms(local_day(now_ms - MS_PER_DAY, self._zone), self._zone)

    def _reprocess_from(self, earliest_ms: int, now_ms: int) -> int:
        """The instant this pass recomputes from.

        The first pass of a process covers everything still retained, because
        it is the only moment that can repair whatever an unclean shutdown left
        unsummarized. Every pass after it covers yesterday and today, which is
        all that can still be changing.
        """
        floor = self._summary_floor_ms
        if floor is None:
            return earliest_ms
        return max(earliest_ms, min(floor, self._recent_floor(now_ms)))

    async def _recompute(
        self, start_ms: int, now_ms: int, frozen_before_ms: int
    ) -> tuple[dict[int, MetricSummary], dict[str, MetricSummary]]:
        """Summaries for every bucket in range that may still be written."""
        samples = await self._repository.samples_between(start_ms, now_ms + 1)
        if not samples:
            return {}, {}
        previous = await self._repository.sample_before(start_ms)

        existing_hours = await self._repository.existing_hours(hour_start_ms(start_ms))
        existing_days = await self._repository.existing_days(local_day(start_ms, self._zone))

        hours = {
            hour: summary
            for hour, summary in hourly(samples, previous=previous).items()
            if hour >= frozen_before_ms or hour not in existing_hours
        }
        days = {
            day: summary
            for day, summary in daily(samples, self._zone, previous=previous).items()
            if local_day_start_ms(day, self._zone) >= frozen_before_ms or day not in existing_days
        }
        return hours, days


__all__ = [
    "DEFAULT_FLUSH_INTERVAL_S",
    "DEFAULT_HIGH_RES_DAYS",
    "DEFAULT_MAINTENANCE_INTERVAL_S",
    "MAX_PENDING_SAMPLES",
    "MS_PER_DAY",
    "POLL_FAILURES_COUNTER",
    "RECOMPUTE_MARGIN_MS",
    "EpochClock",
    "MaintenanceResult",
    "ReceiverMetricsService",
]
