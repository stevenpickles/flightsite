"""The five tables, through the repository: writes, upserts, records, pruning.

Two things are being asserted throughout. First that the *storage* semantics
match §6 — a sector record rises and never falls, a summary is replaced rather
than accumulated, a lifetime row is a read-modify-write. Second that pruning
removes **exactly** the expired rows and nothing else, which is the roadmap's
acceptance criterion and the half of retention a bug would silently destroy
data with.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.exc import IntegrityError

from flightsite.db import Database
from flightsite.receiver_metrics.lifetime import LifetimeDelta
from flightsite.receiver_metrics.model import (
    LIFETIME_MAX_RANGE_ICAO24,
    LIFETIME_MAX_RANGE_NM,
    LIFETIME_TOTAL_MESSAGES,
    MetricSample,
    MetricSummary,
    RangeRecord,
)
from flightsite.receiver_metrics.repository import MetricsRepository, group_by_day
from tests.receiver_metrics.conftest import BASE_EPOCH_MS, steady_samples

DAY = "2026-09-01"


def observation(
    nm: float, *, bucket: int = 8, at_ms: int = BASE_EPOCH_MS, icao: str = "ae1463"
) -> RangeRecord:
    """A range record in a chosen sector, for the record-merge tests."""
    return RangeRecord(bearing_deg=bucket * 5.0 + 1.0, max_range_nm=nm, at_ms=at_ms, icao24=icao)


# ------------------------------------------------------------- raw samples


async def test_samples_round_trip_with_their_absences_intact(
    repository: MetricsRepository,
) -> None:
    """A ``None`` must come back a ``None``, not a zero (SPEC §60)."""
    written = (
        MetricSample(ts_ms=BASE_EPOCH_MS, aircraft_visible=12, messages_per_sec=400.0),
        MetricSample(ts_ms=BASE_EPOCH_MS + 15_000, aircraft_visible=14),
    )

    await repository.record(written, {}, LifetimeDelta(), at_ms=BASE_EPOCH_MS)

    assert await repository.samples_between(BASE_EPOCH_MS, BASE_EPOCH_MS + 60_000) == written


async def test_a_repeated_timestamp_replaces_rather_than_failing(
    repository: MetricsRepository,
) -> None:
    """A retried flush must be idempotent, not an integrity error."""
    first = MetricSample(ts_ms=BASE_EPOCH_MS, aircraft_visible=12)
    second = MetricSample(ts_ms=BASE_EPOCH_MS, aircraft_visible=99)

    await repository.record((first,), {}, LifetimeDelta(), at_ms=BASE_EPOCH_MS)
    await repository.record((second,), {}, LifetimeDelta(), at_ms=BASE_EPOCH_MS)

    assert await repository.samples_between(BASE_EPOCH_MS, BASE_EPOCH_MS + 1) == (second,)


async def test_the_preceding_sample_is_the_one_immediately_before(
    repository: MetricsRepository,
) -> None:
    """What attributes a bucket's first interval of traffic."""
    samples = steady_samples(count=5)
    await repository.record(samples, {}, LifetimeDelta(), at_ms=BASE_EPOCH_MS)

    assert await repository.sample_before(samples[3].ts_ms) == samples[2]
    assert await repository.sample_before(samples[0].ts_ms) is None


async def test_the_raw_span_reports_the_retained_extremes(
    repository: MetricsRepository,
) -> None:
    assert await repository.raw_span() is None

    samples = steady_samples(count=10)
    await repository.record(samples, {}, LifetimeDelta(), at_ms=BASE_EPOCH_MS)

    assert await repository.raw_span() == (samples[0].ts_ms, samples[-1].ts_ms)


async def test_latest_sample_is_none_before_anything_is_recorded(
    repository: MetricsRepository,
) -> None:
    """Slice 034's scorecard reads this for "current" messages/positions per
    second; an install with no samples yet must answer "no data", not a 500."""
    assert await repository.latest_sample() is None


async def test_latest_sample_is_the_most_recently_retained_row(
    repository: MetricsRepository,
) -> None:
    samples = steady_samples(count=5)
    await repository.record(samples, {}, LifetimeDelta(), at_ms=BASE_EPOCH_MS)

    assert await repository.latest_sample() == samples[-1]

    # A later flush with an earlier ts_ms still leaves the highest ts_ms "latest".
    earlier = MetricSample(ts_ms=samples[0].ts_ms - 15_000, messages_per_sec=1.0)
    await repository.record((earlier,), {}, LifetimeDelta(), at_ms=BASE_EPOCH_MS)

    assert await repository.latest_sample() == samples[-1]


# --------------------------------------------------------- range by bearing


async def test_a_sector_record_rises(repository: MetricsRepository) -> None:
    await repository.record((), group_by_day([(DAY, observation(90.0))]), LifetimeDelta(), at_ms=1)
    await repository.record(
        (),
        group_by_day([(DAY, observation(180.0, icao="bbb222", at_ms=77))]),
        LifetimeDelta(),
        at_ms=2,
    )

    stored = await repository.ranges_for_day(DAY)

    assert stored[8].max_range_nm == 180.0
    assert stored[8].icao24 == "bbb222"
    assert stored[8].at_ms == 77


async def test_a_sector_record_does_not_fall(repository: MetricsRepository) -> None:
    """An aircraft closer in than today's best leaves the row exactly as it was."""
    await repository.record(
        (),
        group_by_day([(DAY, observation(180.0, icao="bbb222", at_ms=77))]),
        LifetimeDelta(),
        at_ms=1,
    )
    await repository.record(
        (),
        group_by_day([(DAY, observation(20.0, icao="ccc333", at_ms=900))]),
        LifetimeDelta(),
        at_ms=2,
    )

    stored = await repository.ranges_for_day(DAY)

    assert stored[8] == RangeRecord(
        bearing_deg=8 * 5.0 + 2.5, max_range_nm=180.0, at_ms=77, icao24="bbb222"
    )


async def test_sectors_and_days_are_independent(repository: MetricsRepository) -> None:
    await repository.record(
        (),
        group_by_day(
            [
                (DAY, observation(180.0, bucket=8)),
                (DAY, observation(40.0, bucket=9)),
                ("2026-09-02", observation(12.0, bucket=8)),
            ]
        ),
        LifetimeDelta(),
        at_ms=1,
    )

    assert set(await repository.ranges_for_day(DAY)) == {8, 9}
    assert (await repository.ranges_for_day("2026-09-02"))[8].max_range_nm == 12.0


async def test_a_day_with_no_observations_writes_no_row(
    repository: MetricsRepository,
) -> None:
    """A day the receiver saw nothing positioned on has no sectors to record."""
    await repository.record((), {DAY: []}, LifetimeDelta(), at_ms=1)

    assert await repository.ranges_for_day(DAY) == {}


async def test_ranges_all_returns_every_day_oldest_first(
    repository: MetricsRepository,
) -> None:
    """Slice 034's all-time polar plot reduces this via
    :func:`~flightsite.api.receiver_stats.ever_ranges`, which relies on
    oldest-day-first ordering to break a tie in favour of the earlier day."""
    await repository.record(
        (),
        group_by_day(
            [
                ("2026-09-02", observation(90.0, bucket=8, at_ms=2)),
                (DAY, observation(180.0, bucket=8, at_ms=1)),
                (DAY, observation(40.0, bucket=9, at_ms=1)),
            ]
        ),
        LifetimeDelta(),
        at_ms=1,
    )

    rows = await repository.ranges_all()

    assert [day for day, _record in rows] == [DAY, DAY, "2026-09-02"]
    by_bucket = {(day, record.bearing_bucket): record for day, record in rows}
    assert by_bucket[(DAY, 8)].max_range_nm == 180.0
    assert by_bucket[(DAY, 9)].max_range_nm == 40.0
    assert by_bucket[("2026-09-02", 8)].max_range_nm == 90.0


async def test_ranges_all_is_empty_before_anything_is_recorded(
    repository: MetricsRepository,
) -> None:
    assert await repository.ranges_all() == ()


# ----------------------------------------------------------------- lifetime


async def test_lifetime_totals_accumulate_across_flushes(
    repository: MetricsRepository,
) -> None:
    for _ in range(3):
        await repository.record((), {}, LifetimeDelta(messages=1_000), at_ms=BASE_EPOCH_MS)

    assert (await repository.lifetime())[LIFETIME_TOTAL_MESSAGES].value_num == 3_000.0


async def test_a_lifetime_record_and_its_attribution_move_together(
    repository: MetricsRepository,
) -> None:
    await repository.record(
        (), {}, LifetimeDelta(max_range=observation(100.0, icao="aaa111")), at_ms=1
    )
    await repository.record(
        (), {}, LifetimeDelta(max_range=observation(243.5, icao="ae1463")), at_ms=2
    )

    stored = await repository.lifetime()

    assert stored[LIFETIME_MAX_RANGE_NM].value_num == 243.5
    assert stored[LIFETIME_MAX_RANGE_ICAO24].value_text == "ae1463"


async def test_an_empty_flush_writes_nothing(repository: MetricsRepository) -> None:
    await repository.record((), {}, LifetimeDelta(), at_ms=BASE_EPOCH_MS)

    assert await repository.raw_count() == 0
    assert await repository.lifetime() == {}


async def test_a_failing_flush_leaves_no_partial_state(
    repository: MetricsRepository, database: Database
) -> None:
    """One transaction: a lifetime total counting traffic whose rows are absent
    is exactly the drift ADR-0009 is about, in the other direction.

    The write is failed at its *second* statement — the sector record, whose
    ``max_range_nm`` is ``NOT NULL`` — so the samples of the first statement
    have already been issued when the transaction rolls back. If they survived,
    the flush would not be atomic.
    """
    unstorable = RangeRecord(
        bearing_deg=40.0,
        max_range_nm=None,  # type: ignore[arg-type]
        at_ms=BASE_EPOCH_MS,
    )

    with pytest.raises(IntegrityError):
        await repository.record(
            (MetricSample(ts_ms=BASE_EPOCH_MS),),
            group_by_day([(DAY, unstorable)]),
            LifetimeDelta(messages=500),
            at_ms=1,
        )

    assert await repository.raw_count() == 0
    assert await repository.lifetime() == {}
    assert await repository.ranges_for_day(DAY) == {}


# ---------------------------------------------------------------- summaries


async def test_summaries_are_replaced_not_accumulated(
    repository: MetricsRepository,
) -> None:
    """ADR-0009's idempotence, at the storage layer."""
    summary = MetricSummary(sample_count=240, messages_total=1_000)

    for _ in range(3):
        await repository.write_summaries({BASE_EPOCH_MS: summary}, {}, at_ms=1)

    stored = await repository.hourly_between(BASE_EPOCH_MS, BASE_EPOCH_MS + 3_600_000)
    assert stored == {BASE_EPOCH_MS: summary}


async def test_writing_daily_rows_updates_the_busiest_day_in_the_same_pass(
    repository: MetricsRepository,
) -> None:
    await repository.write_summaries(
        {},
        {
            "2026-08-31": MetricSummary(sample_count=5_760, messages_total=100),
            "2026-09-01": MetricSummary(sample_count=5_760, messages_total=900),
        },
        at_ms=1,
    )

    stored = await repository.lifetime()

    assert stored["busiest_day"].value_text == "2026-09-01"
    assert stored["busiest_day_count"].value_num == 900.0


async def test_existing_buckets_are_reported_for_the_recompute_decision(
    repository: MetricsRepository,
) -> None:
    await repository.write_summaries(
        {BASE_EPOCH_MS: MetricSummary(sample_count=1)},
        {DAY: MetricSummary(sample_count=1)},
        at_ms=1,
    )

    assert await repository.existing_hours(BASE_EPOCH_MS) == {BASE_EPOCH_MS}
    assert await repository.existing_hours(BASE_EPOCH_MS + 1) == set()
    assert await repository.existing_days("2026-01-01") == {DAY}
    assert await repository.existing_days("2026-09-02") == set()


async def test_writing_no_summaries_at_all_is_a_no_op(
    repository: MetricsRepository,
) -> None:
    await repository.write_summaries({}, {}, at_ms=1)

    assert await repository.daily_all() == {}


async def test_daily_between_is_bounded_like_hourly_between(
    repository: MetricsRepository,
) -> None:
    """Slice 034's time-series endpoint reads this for ``resolution=daily`` —
    the daily counterpart of :meth:`~MetricsRepository.hourly_between`."""
    await repository.write_summaries(
        {},
        {
            "2026-08-30": MetricSummary(sample_count=1, messages_total=10),
            "2026-08-31": MetricSummary(sample_count=1, messages_total=20),
            "2026-09-01": MetricSummary(sample_count=1, messages_total=30),
        },
        at_ms=1,
    )

    stored = await repository.daily_between("2026-08-31", "2026-09-01")

    assert set(stored) == {"2026-08-31"}
    assert stored["2026-08-31"].messages_total == 20


# ------------------------------------------------------------------ pruning


async def test_pruning_removes_exactly_the_expired_rows(
    repository: MetricsRepository,
) -> None:
    """The acceptance criterion. The boundary is exclusive: a sample stamped
    exactly at it is inside the window and stays."""
    samples = steady_samples(count=20)
    await repository.record(samples, {}, LifetimeDelta(), at_ms=1)
    boundary = samples[7].ts_ms

    removed = await repository.prune_raw(boundary)

    assert removed == 7
    remaining = await repository.samples_between(0, BASE_EPOCH_MS + 10**9)
    assert remaining == samples[7:]


async def test_pruning_touches_nothing_but_the_raw_table(
    repository: MetricsRepository,
) -> None:
    """ADR-0009: hourly, daily, sector records and lifetime rows are permanent."""
    await repository.record(
        steady_samples(count=10),
        group_by_day([(DAY, observation(180.0))]),
        LifetimeDelta(messages=5_000, max_range=observation(243.5)),
        at_ms=1,
    )
    await repository.write_summaries(
        {BASE_EPOCH_MS: MetricSummary(sample_count=10, messages_total=5_000)},
        {DAY: MetricSummary(sample_count=10, messages_total=5_000)},
        at_ms=1,
    )

    await repository.prune_raw(BASE_EPOCH_MS + 10**9)

    assert await repository.raw_count() == 0
    assert await repository.hourly_between(0, BASE_EPOCH_MS + 10**9) != {}
    assert await repository.daily_all() != {}
    assert await repository.ranges_for_day(DAY) != {}
    assert (await repository.lifetime())[LIFETIME_MAX_RANGE_NM].value_num == 243.5


async def test_pruning_nothing_expired_removes_nothing(
    repository: MetricsRepository,
) -> None:
    samples = steady_samples(count=5)
    await repository.record(samples, {}, LifetimeDelta(), at_ms=1)

    assert await repository.prune_raw(samples[0].ts_ms) == 0
    assert await repository.raw_count() == 5


async def test_pruning_is_chunked_across_transactions(
    repository: MetricsRepository,
) -> None:
    """A catch-up prune must not hold the single writer lock for its whole run.

    Asserted through behaviour rather than instrumentation: with a chunk size
    of three, a 10-row prune still removes exactly ten.
    """
    await repository.record(steady_samples(count=10), {}, LifetimeDelta(), at_ms=1)

    removed = await repository.prune_raw(BASE_EPOCH_MS + 10**9, chunk_rows=3)

    assert removed == 10
    assert await repository.raw_count() == 0


async def test_a_nonsensical_chunk_size_is_refused(repository: MetricsRepository) -> None:
    with pytest.raises(ValueError, match="chunk_rows"):
        await repository.prune_raw(BASE_EPOCH_MS, chunk_rows=0)


async def test_metrics_writes_take_the_shared_single_writer_lock(
    repository: MetricsRepository, database: Database
) -> None:
    """ADR-0001/ADR-0008: one serialized writer, whoever the caller is.

    Held from the outside, the metrics write must wait rather than opening a
    second writer — which is what makes "the persistence worker is not stalled
    by this, only queued behind it" true in both directions.
    """
    async with database.writer_session():
        write = asyncio.create_task(
            repository.record((MetricSample(ts_ms=BASE_EPOCH_MS),), {}, LifetimeDelta(), at_ms=1)
        )
        await asyncio.sleep(0)
        assert not write.done()
        assert await repository.raw_count() == 0

    await write
    assert await repository.raw_count() == 1
