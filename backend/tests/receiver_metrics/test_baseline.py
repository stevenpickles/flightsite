"""The hour-of-week message-rate baseline (slice 088).

Pure-function tests over hand-built hourly rows, plus one round trip through
the real ``receiver_metrics_hourly`` table and one through the sampler's
listener seam the self-alert monitor rides.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from flightsite.db import Database
from flightsite.db.clock import to_epoch_ms
from flightsite.live import LiveStore
from flightsite.receiver_metrics.baseline import (
    MIN_BUCKET_SAMPLES,
    MS_PER_WEEK,
    BaselineState,
    hour_of_week,
    load_rate_baseline,
    rate_baseline,
)
from flightsite.receiver_metrics.model import MetricSample, MetricSummary
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.service import ReceiverMetricsService
from tests.receiver_metrics.conftest import MS_PER_HOUR, SimulatedTime

UTC_ZONE = ZoneInfo("UTC")

#: Tuesday 2026-09-01 03:10 UTC — a quiet night hour.
NIGHT_MS = to_epoch_ms(datetime(2026, 9, 1, 3, 10, tzinfo=UTC))
NIGHT_HOUR_MS = NIGHT_MS - NIGHT_MS % MS_PER_HOUR


def summary(rate: float | None, samples: int = 240) -> MetricSummary:
    return MetricSummary(sample_count=samples, msgs_per_sec_avg=rate)


def weekly(rates: list[float], *, hour_ms: int = NIGHT_HOUR_MS) -> dict[int, MetricSummary]:
    """One row per past week at the same hour, newest last."""
    return {
        hour_ms - (len(rates) - index) * MS_PER_WEEK: summary(rate)
        for index, rate in enumerate(rates)
    }


def test_hour_of_week_counts_from_monday_midnight_in_the_receivers_zone() -> None:
    monday = to_epoch_ms(datetime(2026, 8, 31, 0, 30, tzinfo=UTC))
    assert hour_of_week(monday, UTC_ZONE) == 0
    assert hour_of_week(NIGHT_MS, UTC_ZONE) == 24 + 3
    # Tuesday 03:10 UTC is Monday 20:10 in Los Angeles (UTC-7 in September).
    assert hour_of_week(NIGHT_MS, ZoneInfo("America/Los_Angeles")) == 20


def test_the_median_of_the_same_hour_in_earlier_weeks_is_the_baseline() -> None:
    rows = weekly([10.0, 30.0, 12.0])
    # Other hours of the same weeks must not leak in.
    rows[NIGHT_HOUR_MS - MS_PER_HOUR] = summary(500.0)
    rows[NIGHT_HOUR_MS - 3 * MS_PER_HOUR - MS_PER_WEEK] = summary(500.0)

    baseline = rate_baseline(rows, at_ms=NIGHT_MS, zone=UTC_ZONE)

    assert baseline.state is BaselineState.READY
    assert baseline.msgs_per_sec == 12.0
    assert baseline.weeks == 3
    assert baseline.hour_of_week == 27


def test_one_outage_week_does_not_drag_the_median() -> None:
    baseline = rate_baseline(weekly([40.0, 0.0, 42.0, 41.0]), at_ms=NIGHT_MS, zone=UTC_ZONE)
    assert baseline.msgs_per_sec == 40.5


def test_fewer_than_two_weeks_is_still_learning() -> None:
    assert rate_baseline({}, at_ms=NIGHT_MS, zone=UTC_ZONE).state is BaselineState.LEARNING
    one = rate_baseline(weekly([25.0]), at_ms=NIGHT_MS, zone=UTC_ZONE)
    assert one.state is BaselineState.LEARNING
    assert one.msgs_per_sec == 25.0
    assert not one.ready


def test_the_minimum_week_count_is_a_parameter() -> None:
    rows = weekly([25.0, 26.0])
    assert rate_baseline(rows, at_ms=NIGHT_MS, zone=UTC_ZONE, min_weeks=3).state is (
        BaselineState.LEARNING
    )
    assert rate_baseline(rows, at_ms=NIGHT_MS, zone=UTC_ZONE, min_weeks=2).ready


def test_thinly_sampled_or_rateless_hours_do_not_count() -> None:
    rows = weekly([20.0, 22.0])
    rows[NIGHT_HOUR_MS - 3 * MS_PER_WEEK] = summary(1.0, samples=MIN_BUCKET_SAMPLES - 1)
    rows[NIGHT_HOUR_MS - 4 * MS_PER_WEEK] = summary(None)

    baseline = rate_baseline(rows, at_ms=NIGHT_MS, zone=UTC_ZONE)
    assert baseline.weeks == 2
    assert baseline.msgs_per_sec == 21.0


def test_the_current_hour_itself_is_never_part_of_its_own_baseline() -> None:
    rows = weekly([20.0, 22.0])
    rows[NIGHT_HOUR_MS] = summary(0.0)
    assert rate_baseline(rows, at_ms=NIGHT_MS, zone=UTC_ZONE).msgs_per_sec == 21.0


def test_an_almost_empty_hour_is_quiet_rather_than_judged() -> None:
    baseline = rate_baseline(weekly([0.4, 0.6, 0.5]), at_ms=NIGHT_MS, zone=UTC_ZONE)
    assert baseline.state is BaselineState.QUIET
    assert not baseline.ready


async def test_the_baseline_is_read_from_the_hourly_table(database: Database) -> None:
    repository = MetricsRepository(database)
    rows = weekly([18.0, 20.0, 22.0])
    # Older than the eight-week window: ignored.
    rows[NIGHT_HOUR_MS - 9 * MS_PER_WEEK] = summary(900.0)
    await repository.write_summaries(rows, {}, at_ms=NIGHT_MS)

    baseline = await load_rate_baseline(repository, at_ms=NIGHT_MS, zone=UTC_ZONE)

    assert baseline.ready
    assert baseline.weeks == 3
    assert baseline.msgs_per_sec == 20.0


# ------------------------------------------------------- the sampler's seam


async def test_every_sample_is_handed_to_the_listeners(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    service = ReceiverMetricsService(database=database, live=live, clock=clock.epoch_ms)
    seen: list[MetricSample] = []

    async def listener(sample: MetricSample) -> None:
        seen.append(sample)

    service.subscribe_samples(listener)
    service.subscribe_samples(listener)  # idempotent
    first = await service.sample_once()
    clock.advance(15)
    second = await service.sample_once()

    assert seen == [first, second]
    service.unsubscribe_samples(listener)
    clock.advance(15)
    await service.sample_once()
    assert len(seen) == 2


async def test_a_listener_that_raises_costs_nothing(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    service = ReceiverMetricsService(database=database, live=live, clock=clock.epoch_ms)
    seen: list[int] = []

    async def broken(_sample: MetricSample) -> None:
        raise RuntimeError("boom")

    async def healthy(sample: MetricSample) -> None:
        seen.append(sample.ts_ms)

    service.subscribe_samples(broken)
    service.subscribe_samples(healthy)
    sample = await service.sample_once()

    assert seen == [sample.ts_ms]
    assert service.pending_samples == 1


@pytest.mark.parametrize("zone", ["UTC", "Asia/Kolkata"])
def test_a_sample_and_its_hourly_row_share_an_hour_of_week(zone: str) -> None:
    """Classified by the UTC hour start, so half-hour zones agree too."""
    tz = ZoneInfo(zone)
    for offset_min in (0, 10, 29, 31, 59):
        ts = NIGHT_HOUR_MS + offset_min * 60_000
        assert hour_of_week(ts, tz) == hour_of_week(NIGHT_HOUR_MS, tz)
