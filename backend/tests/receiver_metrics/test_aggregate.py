"""Downsampling correctness, against a brute-force recomputation.

The roadmap's acceptance criterion is *"downsampling produces correct hourly/
daily aggregates (property-tested)"*, and ``docs/TEST_STRATEGY.md`` §2 names
retention as a critical-coverage domain wanting *exhaustive branch/edge
coverage of the decision logic*. So the shape of this file is:

* a **brute-force implementation** written independently of the one under
  test, in the obvious way, with no bucketing machinery — that is the oracle;
* **generated fixtures** covering the awkward shapes: absent metrics, gaps,
  restarts, irregular spacing, DST days;
* and properties asserted over both.

The oracle is deliberately naive and deliberately duplicated. It is not
sharing helpers with :mod:`flightsite.receiver_metrics.aggregate`, because a
test that reuses the implementation's own arithmetic proves only that the code
equals itself.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from flightsite.receiver_metrics.aggregate import (
    MAX_RATE_GAP_MS,
    MS_PER_HOUR,
    counter_delta,
    daily,
    hour_start_ms,
    hourly,
    local_day,
    local_day_start_ms,
    summarize,
)
from flightsite.receiver_metrics.model import MetricSample, MetricSummary
from tests.receiver_metrics.conftest import BASE_EPOCH_MS, MS_PER_DAY, steady_samples

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
KOLKATA = ZoneInfo("Asia/Kolkata")
CHATHAM = ZoneInfo("Pacific/Chatham")


# ------------------------------------------------------------ the oracle


def brute_force(
    samples: Sequence[MetricSample], previous: MetricSample | None = None
) -> MetricSummary:
    """The obvious summary of a bucket, written without any shared machinery."""
    messages = 0
    positions = 0
    saw_messages = False
    saw_positions = False
    before = previous
    for current in samples:
        if before is not None:
            gap = current.ts_ms - before.ts_ms
            if 0 < gap <= MAX_RATE_GAP_MS:
                if current.messages_per_sec is not None:
                    messages += round(current.messages_per_sec * gap / 1000)
                    saw_messages = True
                if current.positions_per_sec is not None:
                    positions += round(current.positions_per_sec * gap / 1000)
                    saw_positions = True
        before = current

    def kept(name: str) -> list[float]:
        return [
            float(value) for value in (getattr(item, name) for item in samples) if value is not None
        ]

    def average(name: str) -> float | None:
        values = kept(name)
        return sum(values) / len(values) if values else None

    def peak(name: str) -> float | None:
        values = kept(name)
        return max(values) if values else None

    aircraft_peak = peak("aircraft_visible")
    return MetricSummary(
        sample_count=len(samples),
        messages_total=messages if saw_messages else None,
        positions_total=positions if saw_positions else None,
        msgs_per_sec_avg=average("messages_per_sec"),
        msgs_per_sec_max=peak("messages_per_sec"),
        pos_per_sec_avg=average("positions_per_sec"),
        pos_per_sec_max=peak("positions_per_sec"),
        aircraft_avg=average("aircraft_visible"),
        aircraft_max=None if aircraft_peak is None else int(aircraft_peak),
        max_range_nm=peak("max_range_nm"),
        rssi_avg_db=average("rssi_avg_db"),
        rssi_peak_db=peak("rssi_peak_db"),
    )


def brute_force_by(
    samples: Sequence[MetricSample],
    key: Callable[[MetricSample], object],
    previous: MetricSample | None = None,
) -> dict[object, MetricSummary]:
    """Every bucket's brute-force summary, grouped the obvious way."""
    groups: dict[object, list[MetricSample]] = {}
    for item in samples:
        groups.setdefault(key(item), []).append(item)

    result: dict[object, MetricSummary] = {}
    before = previous
    for bucket, members in groups.items():
        result[bucket] = brute_force(members, before)
        before = members[-1]
    return result


def close_enough(left: MetricSummary, right: MetricSummary) -> bool:
    """Summaries equal to floating-point tolerance on the averaged fields."""
    if (left.sample_count, left.messages_total, left.positions_total) != (
        right.sample_count,
        right.messages_total,
        right.positions_total,
    ):
        return False
    if (left.aircraft_max, left.rssi_peak_db) != (right.aircraft_max, right.rssi_peak_db):
        return False
    for name in (
        "msgs_per_sec_avg",
        "msgs_per_sec_max",
        "pos_per_sec_avg",
        "pos_per_sec_max",
        "aircraft_avg",
        "max_range_nm",
        "rssi_avg_db",
    ):
        a, b = getattr(left, name), getattr(right, name)
        if (a is None) != (b is None):
            return False
        if a is not None and b is not None and abs(a - b) > 1e-9:
            return False
    return True


# -------------------------------------------------------- fixture generation


def random_samples(seed: int, *, count: int, start_ms: int = BASE_EPOCH_MS) -> list[MetricSample]:
    """A deliberately awkward run: absent metrics, gaps, restarts, jitter.

    Seeded, so a failure is reproducible from the parameter id alone
    (``docs/TEST_STRATEGY.md`` §3: determinism is not optional).
    """
    rng = random.Random(seed)
    samples: list[MetricSample] = []
    ts = start_ms
    for _ in range(count):
        # Jitter and the occasional outage, so bucket boundaries fall in
        # different places relative to the samples on every seed.
        ts += rng.choice([15_000, 15_000, 15_000, 14_000, 16_000, 900_000])
        has_decoder = rng.random() > 0.25
        samples.append(
            MetricSample(
                ts_ms=ts,
                messages_per_sec=round(rng.uniform(0.0, 900.0), 3) if rng.random() > 0.1 else None,
                positions_per_sec=round(rng.uniform(0.0, 90.0), 3) if rng.random() > 0.1 else None,
                aircraft_visible=rng.randint(0, 300),
                aircraft_with_pos=rng.randint(0, 200),
                max_range_nm=round(rng.uniform(1.0, 260.0), 2) if rng.random() > 0.2 else None,
                rssi_avg_db=round(rng.uniform(-30.0, -3.0), 2) if has_decoder else None,
                rssi_peak_db=round(rng.uniform(-10.0, -0.5), 2) if has_decoder else None,
            )
        )
    return samples


SEEDS = [1, 2, 3, 7, 11, 42, 1_337, 20_260_901]


# ------------------------------------------------------------- the properties


@pytest.mark.parametrize("seed", SEEDS)
def test_hourly_aggregates_equal_brute_force_over_the_raw_samples(seed: int) -> None:
    """The acceptance criterion, over eight hours of awkward fixture data."""
    samples = random_samples(seed, count=400)

    produced = hourly(samples)
    expected = brute_force_by(samples, lambda s: hour_start_ms(s.ts_ms))

    assert set(produced) == set(expected)
    for bucket, summary in produced.items():
        assert close_enough(summary, expected[bucket]), f"hour {bucket} disagrees"


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("zone", [LONDON, NEW_YORK, KOLKATA, CHATHAM], ids=str)
def test_daily_aggregates_equal_brute_force_over_the_raw_samples(seed: int, zone: ZoneInfo) -> None:
    """The same property for the daily tier, in four zones.

    Kolkata (+05:30) and Chatham (+12:45) are in the list because a local day
    is not a whole number of UTC hours there: a daily row folded from *hourly*
    rows would split a bucket in the wrong place, which is why the daily tier
    is folded from raw samples instead.
    """
    samples = random_samples(seed, count=900)

    produced = daily(samples, zone)
    expected = brute_force_by(samples, lambda s: local_day(s.ts_ms, zone))

    assert set(produced) == set(expected)
    for bucket, summary in produced.items():
        assert close_enough(summary, expected[bucket]), f"day {bucket} disagrees"


@pytest.mark.parametrize("seed", SEEDS[:4])
def test_a_bucket_boundary_does_not_lose_the_traffic_that_crossed_it(seed: int) -> None:
    """Every attributable interval belongs to exactly one bucket, and to one.

    The sum over hourly buckets must equal the sum over the whole run: a delta
    dropped at a boundary is data silently lost by downsampling, and one
    counted twice is ADR-0009's double-count.
    """
    samples = random_samples(seed, count=400)

    per_bucket = sum(summary.messages_total or 0 for summary in hourly(samples).values())
    whole_run = brute_force(samples).messages_total or 0

    assert per_bucket == whole_run


@pytest.mark.parametrize("seed", SEEDS[:4])
def test_downsampling_the_same_samples_twice_gives_the_same_answer(seed: int) -> None:
    """ADR-0009: idempotent, so a crash or restart cannot double-count."""
    samples = random_samples(seed, count=300)

    assert hourly(samples) == hourly(samples)
    assert daily(samples, LONDON) == daily(samples, LONDON)


# ------------------------------------------------------------- counts vs rates


def test_a_rate_multiplied_back_by_its_interval_recovers_the_exact_count() -> None:
    """The premise the whole totals tier rests on."""
    for delta in (1, 7, 4_211, 999_983):
        rate = delta / 15.0
        first = MetricSample(ts_ms=BASE_EPOCH_MS)
        second = MetricSample(ts_ms=BASE_EPOCH_MS + 15_000, messages_per_sec=rate)

        assert counter_delta(second, first, rate) == delta


def test_the_first_sample_of_a_run_contributes_no_count() -> None:
    """There is no interval before it, so no traffic is attributable to it."""
    samples = [
        MetricSample(ts_ms=BASE_EPOCH_MS, messages_per_sec=400.0),
        MetricSample(ts_ms=BASE_EPOCH_MS + 15_000, messages_per_sec=400.0),
    ]

    assert summarize(samples).messages_total == 6_000  # one interval, not two


def test_a_preceding_sample_attributes_the_first_interval() -> None:
    """What the repository fetches a predecessor row for."""
    before = MetricSample(ts_ms=BASE_EPOCH_MS - 15_000, messages_per_sec=400.0)
    samples = [
        MetricSample(ts_ms=BASE_EPOCH_MS, messages_per_sec=400.0),
        MetricSample(ts_ms=BASE_EPOCH_MS + 15_000, messages_per_sec=400.0),
    ]

    assert summarize(samples, before).messages_total == 12_000


def test_a_gap_longer_than_the_trust_window_attributes_nothing() -> None:
    """An outage is not an hour of traffic at the rate on the far side of it."""
    before = MetricSample(ts_ms=BASE_EPOCH_MS - MAX_RATE_GAP_MS - 1, messages_per_sec=400.0)
    samples = [MetricSample(ts_ms=BASE_EPOCH_MS, messages_per_sec=400.0)]

    assert summarize(samples, before).messages_total is None


def test_a_rateless_sample_contributes_nothing_but_still_counts_as_a_sample() -> None:
    """It is a real observation of the sky, with no measurable traffic in it."""
    samples = [
        MetricSample(ts_ms=BASE_EPOCH_MS, aircraft_visible=12),
        MetricSample(ts_ms=BASE_EPOCH_MS + 15_000, aircraft_visible=14),
    ]

    summary = summarize(samples)

    assert summary.sample_count == 2
    assert summary.messages_total is None
    assert summary.aircraft_max == 14


# ------------------------------------------------------------------- absence


def test_an_absent_metric_is_absent_in_the_summary_rather_than_zero() -> None:
    """SPEC §60/§39, carried through the aggregate: no invented measurements."""
    summary = summarize(steady_samples(count=4, messages_per_sec=None))

    assert summary.messages_total is None
    assert summary.msgs_per_sec_avg is None
    assert summary.msgs_per_sec_max is None
    # The metrics that *are* present are unaffected.
    assert summary.pos_per_sec_avg == 40.0
    assert summary.aircraft_max is not None


def test_a_partially_absent_metric_averages_over_what_was_measured() -> None:
    """Three readings of -14 dB and one silence average -14, not -10.5."""
    samples = [
        MetricSample(ts_ms=BASE_EPOCH_MS + n * 15_000, rssi_avg_db=-14.0 if n < 3 else None)
        for n in range(4)
    ]

    assert summarize(samples).rssi_avg_db == pytest.approx(-14.0)


def test_summarizing_an_empty_bucket_is_refused() -> None:
    """A row claiming the receiver was up and heard nothing would be a lie."""
    with pytest.raises(ValueError, match="empty bucket"):
        summarize([])


# -------------------------------------------------------------- day bucketing


def test_hour_buckets_are_utc_hour_starts() -> None:
    ts = int(datetime(2026, 9, 1, 13, 47, 3, tzinfo=UTC).timestamp() * 1000)

    assert hour_start_ms(ts) == int(datetime(2026, 9, 1, 13, 0, tzinfo=UTC).timestamp() * 1000)


def test_a_local_day_is_the_receivers_day_not_utcs() -> None:
    """23:30 in New York is already tomorrow in UTC, and is not tomorrow here."""
    ts = int(datetime(2026, 9, 1, 3, 30, tzinfo=UTC).timestamp() * 1000)

    assert local_day(ts, NEW_YORK) == "2026-08-31"
    assert local_day(ts, ZoneInfo("UTC")) == "2026-09-01"


def test_a_spring_forward_day_rolls_up_as_twenty_three_hours() -> None:
    """29 March 2026, when Europe/London loses an hour (``docs/DATA_MODEL.md`` §10)."""
    start = local_day_start_ms("2026-03-29", LONDON)
    samples = steady_samples(start_ms=start, count=24 * 4, interval_ms=MS_PER_HOUR // 4)

    buckets = daily(samples, LONDON)

    assert local_day_start_ms("2026-03-30", LONDON) - start == 23 * MS_PER_HOUR
    # Twenty-three hours of samples land on the short day; the twenty-fourth
    # hour of elapsed time is already the next day.
    assert buckets["2026-03-29"].sample_count == 23 * 4
    assert buckets["2026-03-30"].sample_count == 4


def test_an_autumn_back_day_rolls_up_as_twenty_five_hours() -> None:
    """25 October 2026, when Europe/London repeats an hour."""
    start = local_day_start_ms("2026-10-25", LONDON)
    samples = steady_samples(start_ms=start, count=26 * 4, interval_ms=MS_PER_HOUR // 4)

    buckets = daily(samples, LONDON)

    assert local_day_start_ms("2026-10-26", LONDON) - start == 25 * MS_PER_HOUR
    assert buckets["2026-10-25"].sample_count == 25 * 4
    assert buckets["2026-10-26"].sample_count == 4


def test_the_repeated_local_hour_is_two_distinct_utc_hours() -> None:
    """01:30 happens twice on a fall-back day; both belong to the same local day.

    The reason day bucketing converts through :mod:`zoneinfo` rather than
    through a fixed offset: an offset would put the second 01:30 on the wrong
    side of the boundary.
    """
    start = local_day_start_ms("2026-10-25", LONDON)
    first_0130 = start + 90 * 60_000
    second_0130 = first_0130 + MS_PER_HOUR

    assert local_day(first_0130, LONDON) == "2026-10-25"
    assert local_day(second_0130, LONDON) == "2026-10-25"
    assert hour_start_ms(first_0130) != hour_start_ms(second_0130)


@pytest.mark.parametrize("zone", [LONDON, NEW_YORK, KOLKATA, CHATHAM], ids=str)
def test_consecutive_local_days_tile_time_without_gap_or_overlap(zone: ZoneInfo) -> None:
    """Every instant of a fortnight belongs to exactly one local day."""
    start = local_day_start_ms("2026-03-01", zone)
    ts = start
    while ts < start + 14 * MS_PER_DAY:
        day = local_day(ts, zone)
        assert local_day_start_ms(day, zone) <= ts
        following = local_day(ts + MS_PER_DAY, zone)
        assert local_day_start_ms(following, zone) > ts
        ts += MS_PER_HOUR
