"""Lifetime records: accumulation, comparison, and surviving retention.

ADR-0009's hardest promise is that *"downsampling/pruning can never lose a
record"*, and the roadmap restates it as an acceptance criterion. This file
tests it as arithmetic — the merge is pure, so "survives N cycles" is a
property that can be asserted directly — and ``test_service.py`` then tests the
same promise against a real database with real pruning.
"""

from __future__ import annotations

import pytest

from flightsite.receiver_metrics.aggregate import hourly
from flightsite.receiver_metrics.lifetime import (
    LifetimeAccumulator,
    LifetimeDelta,
    LifetimeValue,
    merged,
    merged_busiest_day,
)
from flightsite.receiver_metrics.model import (
    LIFETIME_BUSIEST_DAY,
    LIFETIME_BUSIEST_DAY_COUNT,
    LIFETIME_KEYS,
    LIFETIME_MAX_RANGE_AT_MS,
    LIFETIME_MAX_RANGE_BEARING,
    LIFETIME_MAX_RANGE_ICAO24,
    LIFETIME_MAX_RANGE_NM,
    LIFETIME_MAX_SIMULTANEOUS,
    LIFETIME_PEAK_MSG_RATE,
    LIFETIME_TOTAL_MESSAGES,
    LIFETIME_TOTAL_POSITIONS,
    MetricSample,
    RangeRecord,
)
from tests.receiver_metrics.conftest import BASE_EPOCH_MS


def record(
    nm: float, *, at_ms: int = BASE_EPOCH_MS, bearing: float = 42.0, icao: str = "ae1463"
) -> RangeRecord:
    """One range observation, for the merge tests."""
    return RangeRecord(bearing_deg=bearing, max_range_nm=nm, at_ms=at_ms, icao24=icao)


def apply(stored: dict[str, LifetimeValue], delta: LifetimeDelta) -> dict[str, LifetimeValue]:
    """Merge ``delta`` into ``stored`` the way the repository's transaction does."""
    return {**stored, **merged(stored, delta)}


# ------------------------------------------------------------ accumulation


def test_totals_accumulate_from_the_counts_each_sample_represents() -> None:
    """Never from a query over raw rows — that is what pruning would break."""
    accumulator = LifetimeAccumulator()
    previous = MetricSample(ts_ms=BASE_EPOCH_MS, messages_per_sec=400.0, positions_per_sec=40.0)
    for index in range(1, 5):
        current = MetricSample(
            ts_ms=BASE_EPOCH_MS + index * 15_000, messages_per_sec=400.0, positions_per_sec=40.0
        )
        accumulator.observe(current, previous=previous)
        previous = current

    delta = accumulator.drain()

    assert delta.messages == 4 * 6_000
    assert delta.positions == 4 * 600


def test_the_lifetime_total_and_the_hourly_totals_are_the_same_arithmetic() -> None:
    """They must agree: the scorecard and the chart describe one receiver.

    Both run through the same ``counter_delta``, so agreement is structural
    rather than a coincidence two implementations happen to share.
    """
    samples = [
        MetricSample(ts_ms=BASE_EPOCH_MS + n * 15_000, messages_per_sec=100.0 + n)
        for n in range(500)
    ]
    accumulator = LifetimeAccumulator()
    previous: MetricSample | None = None
    for current in samples:
        accumulator.observe(current, previous=previous)
        previous = current

    from_hourly = sum(summary.messages_total or 0 for summary in hourly(samples).values())

    assert accumulator.drain().messages == from_hourly


def test_draining_leaves_a_fresh_delta() -> None:
    accumulator = LifetimeAccumulator()
    accumulator.observe(
        MetricSample(ts_ms=BASE_EPOCH_MS, aircraft_visible=12), previous=None, ranges=[record(90.0)]
    )

    first = accumulator.drain()

    assert first.is_empty is False
    assert accumulator.drain().is_empty is True


def test_restoring_a_drained_delta_merges_it_with_whatever_arrived_since() -> None:
    """What a failed flush does. Losing either half would lose a total."""
    accumulator = LifetimeAccumulator()
    accumulator.observe(
        MetricSample(ts_ms=BASE_EPOCH_MS + 15_000, messages_per_sec=400.0, aircraft_visible=10),
        previous=MetricSample(ts_ms=BASE_EPOCH_MS),
        ranges=[record(90.0)],
    )
    failed = accumulator.drain()

    accumulator.observe(
        MetricSample(ts_ms=BASE_EPOCH_MS + 30_000, messages_per_sec=400.0, aircraft_visible=44),
        previous=MetricSample(ts_ms=BASE_EPOCH_MS + 15_000),
        ranges=[record(120.0)],
    )
    accumulator.restore(failed)

    combined = accumulator.drain()
    assert combined.messages == 12_000
    assert combined.max_simultaneous == 44
    assert combined.max_range is not None and combined.max_range.max_range_nm == 120.0


def test_an_empty_delta_is_recognised_as_nothing_to_write() -> None:
    """A silent receiver should not produce a transaction every minute."""
    accumulator = LifetimeAccumulator()
    accumulator.observe(MetricSample(ts_ms=BASE_EPOCH_MS), previous=None)

    assert accumulator.drain().is_empty is True


# ---------------------------------------------------------------- the merge


def test_totals_add_to_what_is_stored() -> None:
    stored = {LIFETIME_TOTAL_MESSAGES: LifetimeValue(value_num=1_000.0)}

    updates = merged(stored, LifetimeDelta(messages=250, positions=40))

    assert updates[LIFETIME_TOTAL_MESSAGES].value_num == 1_250.0
    assert updates[LIFETIME_TOTAL_POSITIONS].value_num == 40.0


def test_a_greater_range_replaces_the_whole_record_together() -> None:
    """A range with somebody else's timestamp on it is a record of nothing."""
    stored = apply({}, LifetimeDelta(max_range=record(100.0, at_ms=1, icao="aaa111", bearing=10.0)))

    updates = merged(
        stored, LifetimeDelta(max_range=record(240.0, at_ms=999, icao="bbb222", bearing=310.0))
    )

    assert updates[LIFETIME_MAX_RANGE_NM].value_num == 240.0
    assert updates[LIFETIME_MAX_RANGE_AT_MS].value_num == 999.0
    assert updates[LIFETIME_MAX_RANGE_ICAO24].value_text == "bbb222"
    assert updates[LIFETIME_MAX_RANGE_BEARING].value_num == 310.0


def test_a_lesser_range_changes_nothing_at_all() -> None:
    stored = apply({}, LifetimeDelta(max_range=record(240.0, at_ms=999, icao="bbb222")))

    updates = merged(stored, LifetimeDelta(max_range=record(100.0, at_ms=1_000, icao="ccc333")))

    assert LIFETIME_MAX_RANGE_NM not in updates
    assert LIFETIME_MAX_RANGE_ICAO24 not in updates


def test_an_equal_range_does_not_displace_the_first_time_it_happened() -> None:
    """ "When did the receiver first reach this far" should stay answerable."""
    stored = apply({}, LifetimeDelta(max_range=record(240.0, at_ms=100, icao="bbb222")))

    updates = merged(stored, LifetimeDelta(max_range=record(240.0, at_ms=900, icao="ccc333")))

    assert updates == {}


def test_maxima_only_move_upwards() -> None:
    stored = apply(
        {}, LifetimeDelta(max_simultaneous=310, peak_msg_rate=980.0, peak_pos_rate=110.0)
    )

    updates = merged(stored, LifetimeDelta(max_simultaneous=12, peak_msg_rate=4.0))

    assert updates == {}


def test_only_changed_keys_are_written() -> None:
    """A quiet flush should be one or two rows, not eleven."""
    stored = apply({}, LifetimeDelta(messages=10, max_simultaneous=50))

    updates = merged(stored, LifetimeDelta(messages=5))

    assert set(updates) == {LIFETIME_TOTAL_MESSAGES}


def test_the_declared_key_set_is_exactly_what_the_merge_can_produce() -> None:
    """Guards slice 034 against a key it reads never actually being written."""
    stored = apply(
        {},
        LifetimeDelta(
            messages=1,
            positions=1,
            max_range=record(10.0),
            max_simultaneous=1,
            peak_msg_rate=1.0,
            peak_pos_rate=1.0,
        ),
    )
    stored.update(merged_busiest_day(stored, {"2026-09-01": 5_000}))

    assert set(stored) == set(LIFETIME_KEYS)


# ------------------------------------------------------------- busiest day


def test_the_busiest_day_is_the_day_with_the_most_messages() -> None:
    updates = merged_busiest_day({}, {"2026-08-30": 100, "2026-08-31": 900, "2026-09-01": 400})

    assert updates[LIFETIME_BUSIEST_DAY].value_text == "2026-08-31"
    assert updates[LIFETIME_BUSIEST_DAY_COUNT].value_num == 900.0


def test_a_quieter_day_does_not_displace_the_record() -> None:
    stored = {
        LIFETIME_BUSIEST_DAY: LifetimeValue(value_text="2026-08-31"),
        LIFETIME_BUSIEST_DAY_COUNT: LifetimeValue(value_num=900.0),
    }

    assert merged_busiest_day(stored, {"2026-09-02": 400}) == {}


def test_recomputing_the_record_holding_day_corrects_its_count() -> None:
    """A day in progress is rewritten on every pass; the record follows it."""
    stored = {
        LIFETIME_BUSIEST_DAY: LifetimeValue(value_text="2026-09-01"),
        LIFETIME_BUSIEST_DAY_COUNT: LifetimeValue(value_num=400.0),
    }

    updates = merged_busiest_day(stored, {"2026-09-01": 950})

    assert updates[LIFETIME_BUSIEST_DAY].value_text == "2026-09-01"
    assert updates[LIFETIME_BUSIEST_DAY_COUNT].value_num == 950.0


def test_a_day_with_no_message_total_is_not_a_candidate() -> None:
    """SPEC §60's graceful absence: an unmeasurable day cannot be the busiest."""
    assert merged_busiest_day({}, {"2026-09-01": None}) == {}


def test_a_day_that_becomes_unmeasurable_gives_the_record_to_someone_else() -> None:
    stored = {
        LIFETIME_BUSIEST_DAY: LifetimeValue(value_text="2026-09-01"),
        LIFETIME_BUSIEST_DAY_COUNT: LifetimeValue(value_num=400.0),
    }

    updates = merged_busiest_day(stored, {"2026-09-01": None, "2026-09-02": 12})

    assert updates[LIFETIME_BUSIEST_DAY].value_text == "2026-09-02"


def test_rewriting_the_record_day_with_the_same_total_writes_nothing() -> None:
    stored = {
        LIFETIME_BUSIEST_DAY: LifetimeValue(value_text="2026-09-01"),
        LIFETIME_BUSIEST_DAY_COUNT: LifetimeValue(value_num=400.0),
    }

    assert merged_busiest_day(stored, {"2026-09-01": 400}) == {}


# --------------------------------------------------------------- the promise


@pytest.mark.parametrize("cycles", [1, 3, 10, 50])
def test_records_survive_any_number_of_downsample_and_prune_cycles(cycles: int) -> None:
    """ADR-0009's invariant as arithmetic.

    Each "cycle" is a flush of ordinary traffic followed by everything a
    retention pass could do. Nothing a pass does reaches these values —
    downsampling reads raw rows and writes summaries, pruning deletes raw rows
    — so the peak set here must be exactly what was ever observed, however
    many times the window has rolled over.
    """
    stored = apply({}, LifetimeDelta(max_range=record(243.5, at_ms=77, icao="ae1463")))
    for cycle in range(cycles):
        stored = apply(
            stored,
            LifetimeDelta(
                messages=1_000,
                positions=100,
                max_range=record(10.0 + cycle, at_ms=1_000 + cycle, icao="zzz999"),
                max_simultaneous=20,
                peak_msg_rate=50.0,
            ),
        )

    assert stored[LIFETIME_MAX_RANGE_NM].value_num == 243.5
    assert stored[LIFETIME_MAX_RANGE_ICAO24].value_text == "ae1463"
    assert stored[LIFETIME_MAX_RANGE_AT_MS].value_num == 77.0
    assert stored[LIFETIME_TOTAL_MESSAGES].value_num == 1_000.0 * cycles
    assert stored[LIFETIME_MAX_SIMULTANEOUS].value_num == 20.0
    assert stored[LIFETIME_PEAK_MSG_RATE].value_num == 50.0


def test_a_total_is_never_a_maximum_and_a_maximum_is_never_a_total() -> None:
    """The type keeps them apart; this asserts the merge honours the split."""
    stored = apply({}, LifetimeDelta(messages=100, max_simultaneous=40))
    stored = apply(stored, LifetimeDelta(messages=100, max_simultaneous=40))

    assert stored[LIFETIME_TOTAL_MESSAGES].value_num == 200.0
    assert stored[LIFETIME_MAX_SIMULTANEOUS].value_num == 40.0
