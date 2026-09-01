"""The service end to end: cadence, retention, and every way it degrades.

Everything here runs against a hand-driven clock and a real database
(``docs/TEST_STRATEGY.md`` §3), so a fortnight of retention is a few
milliseconds and every timestamp is exact. The tests drive
:meth:`~flightsite.receiver_metrics.service.ReceiverMetricsService.sample_once`
and :meth:`~flightsite.receiver_metrics.service.ReceiverMetricsService.run_maintenance`
directly rather than starting the tasks, so nothing happens at an instant the
test did not choose.

The centrepiece is
:func:`test_summaries_and_records_survive_a_fortnight_of_rolling_retention`:
a simulated month of sampling with real downsampling and real pruning, checked
against a brute-force recomputation over the samples that were *originally*
taken — including the ones the window has since discarded.
"""

from __future__ import annotations

import asyncio
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.receiver_metrics.aggregate import (
    hour_start_ms,
    hourly,
    local_day,
    local_day_start_ms,
)
from flightsite.receiver_metrics.model import (
    LIFETIME_MAX_RANGE_ICAO24,
    LIFETIME_MAX_RANGE_NM,
    LIFETIME_MAX_SIMULTANEOUS,
    LIFETIME_TOTAL_MESSAGES,
    MetricSample,
)
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.service import (
    MAX_PENDING_SAMPLES,
    POLL_FAILURES_COUNTER,
    MaintenanceResult,
    ReceiverMetricsService,
)
from flightsite.receiver_metrics.statsjson import StatsJsonPoller
from tests.receiver_metrics.conftest import (
    MS_PER_DAY,
    MS_PER_HOUR,
    SimulatedTime,
    dump1090fa_stats,
    place,
    readsb_stats,
    stats_poller,
    status_poller,
)

SAMPLE_INTERVAL_S = 15.0
UTC_ZONE = ZoneInfo("UTC")


def build(
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
    *,
    poller: StatsJsonPoller | None = None,
    high_res_days: int = 14,
    flush_interval_s: float = 60.0,
    timezone: str = "UTC",
    counters: CounterRegistry | None = None,
) -> ReceiverMetricsService:
    """An unstarted service on the simulated clock."""
    return ReceiverMetricsService(
        database=database,
        live=live,
        poller=poller,
        timezone=timezone,
        high_res_days=high_res_days,
        sample_interval_s=SAMPLE_INTERVAL_S,
        flush_interval_s=flush_interval_s,
        clock=clock.epoch_ms,
        counters=counters if counters is not None else CounterRegistry(),
    )


async def sample_for(
    service: ReceiverMetricsService, clock: SimulatedTime, *, ticks: int
) -> list[MetricSample]:
    """Advance the clock one interval per tick, sampling each time."""
    taken = []
    for _ in range(ticks):
        clock.advance(SAMPLE_INTERVAL_S)
        taken.append(await service.sample_once())
    return taken


# ------------------------------------------------------------ construction


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sample_interval_s": 0.0}, "sample_interval_s"),
        ({"flush_interval_s": -1.0}, "flush_interval_s"),
        ({"maintenance_interval_s": 0.0}, "maintenance_interval_s"),
        ({"high_res_days": 0}, "high_res_days"),
    ],
)
async def test_nonsensical_timings_are_refused(
    database: Database, live: LiveStore, kwargs: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ReceiverMetricsService(database=database, live=live, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------- sampling


async def test_a_sample_is_taken_every_interval_on_the_injected_clock(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """Cadence with an injected clock, and the §6.1 spacing it produces."""
    service = build(database, live, clock, flush_interval_s=1.0)
    place(live, clock, icao="a00001", bearing_deg=10.0)

    taken = await sample_for(service, clock, ticks=5)
    await service.flush()

    stored = await repository.samples_between(0, clock.epoch_ms() + 1)
    assert [row.ts_ms for row in stored] == [row.ts_ms for row in taken]
    spacings = {b.ts_ms - a.ts_ms for a, b in pairwise(stored)}
    assert spacings == {int(SAMPLE_INTERVAL_S * 1000)}


async def test_samples_are_buffered_and_written_in_one_transaction(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """Four samples a transaction, not four transactions (SD-card wear)."""
    service = build(database, live, clock, flush_interval_s=60.0)

    await sample_for(service, clock, ticks=3)
    assert await repository.raw_count() == 0
    assert service.pending_samples == 3

    await sample_for(service, clock, ticks=2)

    assert await repository.raw_count() == 5
    assert service.pending_samples == 0


async def test_the_range_records_of_a_sample_reach_the_right_day(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    service = build(database, live, clock, flush_interval_s=1.0)
    place(live, clock, icao="ae1463", bearing_deg=182.0, distance_nm=201.0)

    await sample_for(service, clock, ticks=1)
    await service.flush()

    day = local_day(clock.epoch_ms(), UTC_ZONE)
    stored = await repository.ranges_for_day(day)
    assert stored[36].max_range_nm == pytest.approx(201.0, abs=0.01)
    assert stored[36].icao24 == "ae1463"


# ------------------------------------------------------------- decoder half


async def test_decoder_statistics_are_recorded_alongside_the_computed_ones(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    poller = stats_poller(
        documents=[readsb_stats(messages=1_000_000), readsb_stats(messages=1_006_000)]
    )
    service = build(database, live, clock, poller=poller, flush_interval_s=1.0)
    place(live, clock, icao="a00001", bearing_deg=10.0)

    await sample_for(service, clock, ticks=2)
    await service.flush()
    await service.stop()

    stored = await repository.samples_between(0, clock.epoch_ms() + 1)
    assert stored[0].messages_per_sec is None  # no baseline yet
    assert stored[1].messages_per_sec == pytest.approx(6_000 / 15.0)
    assert stored[1].rssi_avg_db == -14.2
    assert service.stats_supported is True
    assert service.latest_stats is not None
    assert service.latest_stats.uptime_s == 24_800.0


async def test_a_decoder_without_a_statistics_endpoint_degrades_gracefully(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """The roadmap's third acceptance criterion, end to end.

    Metrics are simply absent — not zero, and not a failure — and everything
    FlightSite computes itself is recorded exactly as it would have been.
    """
    counters = CounterRegistry()
    service = build(
        database, live, clock, poller=status_poller(404), flush_interval_s=1.0, counters=counters
    )
    place(live, clock, icao="a00001", bearing_deg=10.0, distance_nm=64.0, messages=100)

    await sample_for(service, clock, ticks=1)
    clock.advance(SAMPLE_INTERVAL_S)
    place(live, clock, icao="a00001", bearing_deg=10.0, distance_nm=64.0, messages=190)
    await service.sample_once()
    await service.flush()
    await service.stop()

    stored = await repository.samples_between(0, clock.epoch_ms() + 1)
    assert [row.rssi_avg_db for row in stored] == [None, None]
    assert [row.rssi_peak_db for row in stored] == [None, None]
    assert stored[1].aircraft_visible == 1
    assert stored[1].max_range_nm == pytest.approx(64.0, abs=0.01)
    # The live set still supplies a real message rate.
    assert stored[1].messages_per_sec == pytest.approx(90 / 15.0)
    # And a supported configuration is not an ingestion error.
    assert counters.snapshot()[POLL_FAILURES_COUNTER] == 0
    assert service.stats_supported is False


async def test_a_smaller_decoder_leaves_only_its_missing_columns_null(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """dump1090-fa: signal average yes, peak no, and nothing invented."""
    poller = stats_poller(documents=[dump1090fa_stats()])
    service = build(database, live, clock, poller=poller, flush_interval_s=1.0)

    await sample_for(service, clock, ticks=1)
    await service.flush()
    await service.stop()

    stored = await repository.samples_between(0, clock.epoch_ms() + 1)
    assert stored[0].rssi_avg_db == -18.7
    assert stored[0].rssi_peak_db is None


async def test_a_failing_statistics_poll_is_counted_and_the_sample_still_taken(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    counters = CounterRegistry()
    service = build(
        database, live, clock, poller=status_poller(500), flush_interval_s=1.0, counters=counters
    )
    place(live, clock, icao="a00001", bearing_deg=10.0)

    await sample_for(service, clock, ticks=2)
    await service.flush()
    await service.stop()

    assert counters.snapshot()[POLL_FAILURES_COUNTER] == 2
    assert await repository.raw_count() == 2


async def test_no_poller_at_all_still_records_the_computed_metrics(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """A first-run install, or demo mode: no decoder endpoint is configured."""
    service = build(database, live, clock, poller=None, flush_interval_s=1.0)
    place(live, clock, icao="a00001", bearing_deg=10.0, distance_nm=33.0)

    await sample_for(service, clock, ticks=1)
    await service.flush()

    stored = await repository.samples_between(0, clock.epoch_ms() + 1)
    assert stored[0].aircraft_visible == 1
    assert stored[0].max_range_nm == pytest.approx(33.0, abs=0.01)
    assert service.stats_supported is None


# ------------------------------------------------------------- degradation


async def test_a_failed_flush_keeps_everything_for_the_next_one(
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
    repository: MetricsRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient write failure must not cost a sample or a lifetime total.

    The failing flush is followed by a succeeding one, and the succeeding one
    must land *everything* — the samples it still holds and the lifetime
    increments the first attempt drained and put back.
    """
    counters = CounterRegistry()
    service = build(database, live, clock, flush_interval_s=10**9, counters=counters)
    place(live, clock, icao="a00001", bearing_deg=10.0, distance_nm=99.0, messages=100)
    await sample_for(service, clock, ticks=3)

    failing = MetricsRepository.record

    async def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("disk I/O error")

    monkeypatch.setattr(MetricsRepository, "record", refuse)
    assert await service.flush() is False
    assert counters.snapshot()["db_errors"] == 1
    assert service.pending_samples == 3
    assert await repository.raw_count() == 0

    monkeypatch.setattr(MetricsRepository, "record", failing)
    assert await service.flush() is True

    assert service.pending_samples == 0
    assert await repository.raw_count() == 3
    lifetime = await repository.lifetime()
    assert lifetime[LIFETIME_MAX_RANGE_NM].value_num == pytest.approx(99.0, abs=0.01)
    assert lifetime[LIFETIME_MAX_SIMULTANEOUS].value_num == 1.0


async def test_a_sustained_write_outage_sheds_raw_detail_but_not_records(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """ADR-0009's priority, under the one pressure that could violate it.

    The buffer is bounded, so a permanent write failure cannot grow the
    process without limit — but what it sheds is *raw samples*, whose lifetime
    contribution was folded into the accumulator before they were buffered.
    """
    service = build(database, live, clock, flush_interval_s=10**9)
    place(live, clock, icao="a00001", bearing_deg=10.0, distance_nm=250.0)

    await sample_for(service, clock, ticks=MAX_PENDING_SAMPLES + 20)

    assert service.pending_samples == MAX_PENDING_SAMPLES
    assert service.shed_samples == 20
    pending = service._accumulator.pending
    assert pending.max_range is not None
    assert pending.max_range.max_range_nm == pytest.approx(250.0, abs=0.01)
    assert pending.max_simultaneous == 1


# ------------------------------------------------------------- maintenance


async def test_maintenance_on_an_empty_database_does_nothing(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """An install that has never sampled has nothing to summarize or prune."""
    service = build(database, live, clock)

    assert await service.run_maintenance() == MaintenanceResult()


async def test_downsampling_writes_the_hourly_and_daily_rows(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    service = build(database, live, clock, flush_interval_s=1.0)
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=100)
    taken = await sample_for(service, clock, ticks=4 * 60 * 2)  # two hours
    await service.flush()

    result = await service.run_maintenance()

    assert result.hours_written >= 2
    expected = hourly(taken)
    stored = await repository.hourly_between(0, clock.epoch_ms() + 1)
    assert set(stored) == set(expected)
    for hour, summary in expected.items():
        assert stored[hour].sample_count == summary.sample_count
        assert stored[hour].aircraft_max == summary.aircraft_max


async def test_running_maintenance_twice_changes_nothing(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """ADR-0009: idempotent, so an interrupted pass is safe to repeat."""
    service = build(database, live, clock, flush_interval_s=1.0)
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=100)
    await sample_for(service, clock, ticks=200)
    await service.flush()

    await service.run_maintenance()
    first = await repository.hourly_between(0, clock.epoch_ms() + 1)
    await service.run_maintenance()
    second = await repository.hourly_between(0, clock.epoch_ms() + 1)

    assert first == second


async def test_pruning_only_starts_once_the_window_has_rolled(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    service = build(database, live, clock, flush_interval_s=1.0, high_res_days=14)
    await sample_for(service, clock, ticks=20)
    await service.flush()

    assert (await service.run_maintenance()).pruned == 0
    assert await repository.raw_count() == 20


async def test_a_summary_is_always_written_before_its_samples_are_pruned(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """The ordering ADR-0009's whole structure depends on."""
    service = build(database, live, clock, flush_interval_s=1.0, high_res_days=7)
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=100)
    taken = await sample_for(service, clock, ticks=240)  # one hour
    await service.flush()

    clock.advance(8 * 24 * 3600)  # the whole hour is now beyond the window
    result = await service.run_maintenance()

    assert result.pruned == len(taken)
    assert await repository.raw_count() == 0
    stored = await repository.hourly_between(0, taken[-1].ts_ms + MS_PER_HOUR)
    assert sum(row.sample_count for row in stored.values()) == len(taken)


async def test_a_frozen_summary_is_not_rewritten_after_its_samples_are_gone(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """The invariant that keeps the hourly tier stable for years.

    Once a bucket's raw rows are outside the window, recomputing it would read
    an empty or truncated bucket. It is never recomputed, so the row a later
    pass leaves is the row the full data produced.
    """
    service = build(database, live, clock, flush_interval_s=1.0, high_res_days=7)
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=100)
    taken = await sample_for(service, clock, ticks=240)
    await service.flush()
    await service.run_maintenance()

    original = await repository.hourly_between(0, taken[-1].ts_ms + MS_PER_HOUR)
    assert original

    clock.advance(8 * 24 * 3600)
    await service.run_maintenance()
    await service.run_maintenance()

    assert await repository.raw_count() == 0
    assert await repository.hourly_between(0, taken[-1].ts_ms + MS_PER_HOUR) == original


# --------------------------------------------------------------- the promise


async def test_summaries_and_records_survive_a_fortnight_of_rolling_retention(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """The slice's central claim, over a simulated month.

    Sampling runs for thirty simulated days with a seven-day window, so every
    row spends time in the high-resolution tier and is then pruned — twenty-
    three days' worth of raw data is destroyed during the run. Afterwards:

    * every hourly bucket still matches a brute-force recomputation over the
      samples *as they were taken*, including the pruned ones;
    * the lifetime record still names the furthest aircraft ever seen, which
      flew on day two and whose sample no longer exists;
    * and the raw tier holds only the window.

    Sampling is at four-minute intervals rather than fifteen seconds to keep
    the fixture to ~11k rows; the retention logic cannot see the difference,
    and the ~15 s production cadence is asserted separately above.
    """
    interval_s = 240.0
    service = ReceiverMetricsService(
        database=database,
        live=live,
        timezone="UTC",
        high_res_days=7,
        sample_interval_s=interval_s,
        # An hour's samples per transaction. Deliberately inside
        # MAX_PENDING_SAMPLES: a longer interval would shed the front of every
        # day, which is correct behaviour under write pressure but is not what
        # this test is about (see the shedding test above).
        flush_interval_s=3_600.0,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )

    taken: list[MetricSample] = []
    ticks_per_day = int(24 * 3600 / interval_s)
    for day in range(30):
        for tick in range(ticks_per_day):
            clock.advance(interval_s)
            # Sweep first, so each tick's aircraft has genuinely left the live
            # set before the next arrives: the record-setter below is therefore
            # observed exactly once in thirty days, and the lifetime record can
            # only survive by having been remembered rather than re-seen.
            live.sweep()
            # A record-setting aircraft on day two, and nothing further out
            # ever again.
            far = day == 2 and tick == 5
            place(
                live,
                clock,
                icao="ae1463" if far else "a00001",
                bearing_deg=182.0,
                distance_nm=243.5 if far else 40.0,
                messages=100 + tick,
            )
            taken.append(await service.sample_once())
        await service.flush()
        await service.run_maintenance()

    expected = hourly(taken)
    stored = await repository.hourly_between(0, clock.epoch_ms() + MS_PER_HOUR)

    assert set(stored) == set(expected)
    for hour, summary in expected.items():
        assert stored[hour].sample_count == summary.sample_count, f"hour {hour} lost samples"
        assert stored[hour].aircraft_max == summary.aircraft_max
        assert stored[hour].max_range_nm == pytest.approx(summary.max_range_nm)

    lifetime = await repository.lifetime()
    assert lifetime[LIFETIME_MAX_RANGE_NM].value_num == pytest.approx(243.5, abs=0.01)
    assert lifetime[LIFETIME_MAX_RANGE_ICAO24].value_text == "ae1463"
    assert lifetime[LIFETIME_MAX_SIMULTANEOUS].value_num == 1.0
    assert lifetime[LIFETIME_TOTAL_MESSAGES].value_num is not None

    # The raw tier holds the window and nothing older.
    span = await repository.raw_span()
    assert span is not None
    assert span[0] >= hour_start_ms(clock.epoch_ms() - 7 * MS_PER_DAY)
    assert await repository.raw_count() < len(taken)

    # And the daily tier covers every local day that was sampled — thirty-one
    # of them, because thirty days that start mid-morning end mid-morning.
    assert set(await repository.daily_all()) == {local_day(item.ts_ms, UTC_ZONE) for item in taken}


async def test_the_lifetime_total_matches_the_sum_of_the_surviving_summaries(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """Two views of one receiver: the scorecard and the daily message chart."""
    poller = stats_poller(
        documents=[readsb_stats(messages=1_000_000 + n * 6_000) for n in range(60)]
    )
    service = build(database, live, clock, poller=poller, flush_interval_s=1.0)
    place(live, clock, icao="a00001", bearing_deg=10.0)

    await sample_for(service, clock, ticks=50)
    await service.flush()
    await service.run_maintenance()
    await service.stop()

    lifetime = await repository.lifetime()
    from_summaries = sum(
        row.messages_total or 0
        for row in (await repository.hourly_between(0, clock.epoch_ms() + MS_PER_HOUR)).values()
    )

    assert lifetime[LIFETIME_TOTAL_MESSAGES].value_num == float(from_summaries)


# ------------------------------------------------------------ dst bucketing


async def test_a_dst_day_is_bucketed_by_the_receivers_calendar(
    database: Database, live: LiveStore, repository: MetricsRepository
) -> None:
    """A 23-hour local day rolls up as one day, not as one-and-a-bit."""
    london = ZoneInfo("Europe/London")
    # One interval before local midnight, because the loop advances the clock
    # before each sample: the first sample then lands exactly on the boundary.
    clock = SimulatedTime(base_ms=local_day_start_ms("2026-03-29", london) - 900_000)
    service = ReceiverMetricsService(
        database=database,
        live=live,
        timezone="Europe/London",
        sample_interval_s=900.0,
        flush_interval_s=900.0,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )

    for _ in range(24 * 4):  # 24 hours of elapsed time on a 23-hour day
        clock.advance(900.0)
        await service.sample_once()
    await service.flush()
    await service.run_maintenance()

    stored = await repository.daily_all()

    assert stored["2026-03-29"].sample_count == 23 * 4
    assert stored["2026-03-30"].sample_count == 4


# -------------------------------------------------------------- the tasks


async def test_starting_and_stopping_runs_a_final_flush(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """A clean shutdown must not drop the interval it is holding."""
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        # Record the cadence each loop asks for, then park: the test drives
        # the sampling itself, so no tick happens at an unchosen instant.
        slept.append(seconds)
        await asyncio.Event().wait()

    service = ReceiverMetricsService(
        database=database,
        live=live,
        sample_interval_s=SAMPLE_INTERVAL_S,
        flush_interval_s=10**9,
        clock=clock.epoch_ms,
        sleep=sleep,
        counters=CounterRegistry(),
    )
    await service.start()
    assert service.running is True
    await sample_for(service, clock, ticks=2)
    assert await repository.raw_count() == 0

    await service.stop()

    assert service.running is False
    assert await repository.raw_count() == 2
    assert slept  # both loops actually parked on the injected sleeper


async def test_starting_twice_is_idempotent(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    async def sleep(seconds: float) -> None:
        await asyncio.Event().wait()

    service = ReceiverMetricsService(
        database=database, live=live, clock=clock.epoch_ms, sleep=sleep
    )
    try:
        await service.start()
        first = service._sample_task
        await service.start()
        assert service._sample_task is first
    finally:
        await service.stop()


async def test_stopping_before_starting_is_safe(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    service = build(database, live, clock)

    await service.stop()
    await service.stop()


# --------------------------------------------------------- the loops themselves


class Ticker:
    """A sleeper that runs one loop a fixed number of times, then parks.

    Cadence without wall-clock time: the loop's own ``await sleep(interval)``
    is what advances the simulated clock, so the task runs exactly the number
    of iterations the test asked for and then stops, deterministically.

    Both of the service's loops share one sleeper, so the ticker is keyed on
    the interval of the loop under test; the other loop parks on its first
    sleep and never runs a body.
    """

    def __init__(self, clock: SimulatedTime, *, interval_s: float, ticks: int) -> None:
        self.clock = clock
        self.interval_s = interval_s
        self.remaining = ticks
        self.intervals: list[float] = []
        self.exhausted = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.intervals.append(seconds)
        if seconds != self.interval_s or self.remaining <= 0:
            if seconds == self.interval_s:
                self.exhausted.set()
            await asyncio.Event().wait()
        self.remaining -= 1
        self.clock.advance(seconds)
        await asyncio.sleep(0)


async def test_the_sampling_task_samples_on_its_own_cadence(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """The loop, not just the method the other tests call directly."""
    ticker = Ticker(clock, interval_s=SAMPLE_INTERVAL_S, ticks=4)
    service = ReceiverMetricsService(
        database=database,
        live=live,
        sample_interval_s=SAMPLE_INTERVAL_S,
        flush_interval_s=1.0,
        maintenance_interval_s=10**9,
        clock=clock.epoch_ms,
        sleep=ticker,
        counters=CounterRegistry(),
    )
    place(live, clock, icao="a00001", bearing_deg=10.0)

    await service.start()
    try:
        await asyncio.wait_for(ticker.exhausted.wait(), timeout=5.0)
    finally:
        await service.stop()

    assert SAMPLE_INTERVAL_S in ticker.intervals
    assert await repository.raw_count() >= 3


async def test_starting_opens_the_statistics_pollers_client(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """The poller is started with the service, and stopped with it."""
    ticker = Ticker(clock, interval_s=SAMPLE_INTERVAL_S, ticks=2)
    poller = stats_poller(documents=[readsb_stats()])
    service = ReceiverMetricsService(
        database=database,
        live=live,
        poller=poller,
        sample_interval_s=SAMPLE_INTERVAL_S,
        flush_interval_s=1.0,
        maintenance_interval_s=10**9,
        clock=clock.epoch_ms,
        sleep=ticker,
        counters=CounterRegistry(),
    )

    await service.start()
    try:
        await asyncio.wait_for(ticker.exhausted.wait(), timeout=5.0)
    finally:
        await service.stop()

    assert service.stats_supported is True
    assert await repository.raw_count() >= 1


async def test_the_maintenance_task_runs_on_its_own_cadence(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """A second loop on a second interval, downsampling what sampling wrote."""
    service = build(database, live, clock, flush_interval_s=1.0)
    place(live, clock, icao="a00001", bearing_deg=10.0)
    await sample_for(service, clock, ticks=10)
    await service.flush()

    ticker = Ticker(clock, interval_s=60.0, ticks=2)
    running = ReceiverMetricsService(
        database=database,
        live=live,
        sample_interval_s=10**9,
        maintenance_interval_s=60.0,
        clock=clock.epoch_ms,
        sleep=ticker,
        counters=CounterRegistry(),
    )
    await running.start()
    try:
        await asyncio.wait_for(ticker.exhausted.wait(), timeout=5.0)
    finally:
        await running.stop()

    assert 60.0 in ticker.intervals
    assert await repository.hourly_between(0, clock.epoch_ms() + MS_PER_HOUR) != {}


async def test_a_tick_that_raises_does_not_kill_the_loop(
    database: Database, live: LiveStore, clock: SimulatedTime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead sampler would freeze the receiver page with no indication why."""
    ticker = Ticker(clock, interval_s=SAMPLE_INTERVAL_S, ticks=3)
    service = ReceiverMetricsService(
        database=database,
        live=live,
        sample_interval_s=SAMPLE_INTERVAL_S,
        maintenance_interval_s=10**9,
        clock=clock.epoch_ms,
        sleep=ticker,
        counters=CounterRegistry(),
    )
    attempts = 0

    async def explode(self: ReceiverMetricsService) -> MetricSample:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("a bug in a later slice")

    monkeypatch.setattr(ReceiverMetricsService, "sample_once", explode)

    await service.start()
    try:
        await asyncio.wait_for(ticker.exhausted.wait(), timeout=5.0)
        assert service.running is True
    finally:
        await service.stop()

    assert attempts >= 3


async def test_a_maintenance_pass_that_raises_does_not_kill_its_loop(
    database: Database, live: LiveStore, clock: SimulatedTime, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticker = Ticker(clock, interval_s=60.0, ticks=2)
    service = ReceiverMetricsService(
        database=database,
        live=live,
        sample_interval_s=10**9,
        maintenance_interval_s=60.0,
        clock=clock.epoch_ms,
        sleep=ticker,
        counters=CounterRegistry(),
    )
    attempts = 0

    async def explode(self: ReceiverMetricsService) -> MaintenanceResult:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("a bug in a later slice")

    monkeypatch.setattr(ReceiverMetricsService, "run_maintenance", explode)

    await service.start()
    try:
        await asyncio.wait_for(ticker.exhausted.wait(), timeout=5.0)
    finally:
        await service.stop()

    assert attempts >= 2


# --------------------------------------------------- maintenance under failure


async def test_a_failed_downsample_prunes_nothing(
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
    repository: MetricsRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one ordering ADR-0009 forbids: discarding an unsummarized row."""
    counters = CounterRegistry()
    service = build(database, live, clock, flush_interval_s=1.0, high_res_days=7, counters=counters)
    await sample_for(service, clock, ticks=20)
    await service.flush()
    clock.advance(8 * 24 * 3600)

    async def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("disk I/O error")

    monkeypatch.setattr(MetricsRepository, "write_summaries", refuse)
    result = await service.run_maintenance()

    assert result.failed is True
    assert result.pruned == 0
    assert await repository.raw_count() == 20
    assert counters.snapshot()["db_errors"] == 1


async def test_a_failed_prune_keeps_the_summaries_it_already_wrote(
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
    repository: MetricsRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downsampling succeeded, so its rows stay; the prune retries next pass."""
    counters = CounterRegistry()
    service = build(database, live, clock, flush_interval_s=1.0, high_res_days=7, counters=counters)
    await sample_for(service, clock, ticks=20)
    await service.flush()
    clock.advance(8 * 24 * 3600)

    async def refuse(*args: object, **kwargs: object) -> int:
        raise OSError("disk I/O error")

    monkeypatch.setattr(MetricsRepository, "prune_raw", refuse)
    result = await service.run_maintenance()

    assert result.failed is True
    assert result.hours_written >= 1
    assert await repository.hourly_between(0, clock.epoch_ms()) != {}
    assert counters.snapshot()["db_errors"] == 1


async def test_a_clock_that_stepped_backwards_summarizes_nothing_rather_than_guessing(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    """A Pi with no RTC boots wrong and jumps when NTP lands.

    Samples then sit in the *future* relative to the corrected clock. There is
    nothing in the range a pass would summarize, and inventing buckets for
    instants that have not happened would be worse than waiting for the samples
    the corrected clock will produce.
    """
    service = build(database, live, clock, flush_interval_s=1.0)
    await sample_for(service, clock, ticks=5)
    await service.flush()

    clock.elapsed_s -= 2 * 24 * 3600
    result = await service.run_maintenance()

    assert result == MaintenanceResult()
    assert await repository.hourly_between(0, clock.epoch_ms() + 10**9) == {}
    assert await repository.raw_count() == 5
