"""The FlightSite-computed half of SPEC §60.

Simultaneous aircraft, positions/sec, messages/sec and range by bearing, taken
from the live set. Every test here drives the *real* live store — observations
in through :meth:`~flightsite.live.store.LiveStore.apply`, the same call the
decoder adapter makes — so what the sampler reads is what production hands it,
including the distance and bearing the live layer derived itself.
"""

from __future__ import annotations

import pytest

from flightsite.live import LiveStore
from flightsite.receiver_metrics.aggregate import MAX_RATE_GAP_MS
from flightsite.receiver_metrics.model import DecoderStats, bearing_bucket
from flightsite.receiver_metrics.sampler import MetricSampler, SampleResult
from tests.receiver_metrics.conftest import SimulatedTime, place

INTERVAL_S = 15.0


def take(
    sampler: MetricSampler,
    live: LiveStore,
    clock: SimulatedTime,
    *,
    stats: DecoderStats | None = None,
) -> SampleResult:
    """One sample at the current simulated instant."""
    return sampler.sample(ts_ms=clock.epoch_ms(), aircraft=live.snapshot(), stats=stats)


# ------------------------------------------------------------ aircraft counts


def test_simultaneous_aircraft_counts_the_whole_live_set(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """Including aircraft with no position: SPEC §20 makes those first-class."""
    place(live, clock, icao="a00001", bearing_deg=10.0)
    place(live, clock, icao="a00002", bearing_deg=200.0)
    place(live, clock, icao="a00003", bearing_deg=None)

    result = take(MetricSampler(), live, clock)

    assert result.sample.aircraft_visible == 3
    assert result.sample.aircraft_with_pos == 2


def test_an_empty_sky_samples_as_zero_aircraft_not_as_absence(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """Here zero *is* the measurement: nothing was overhead, and we know it."""
    result = take(MetricSampler(), live, clock)

    assert result.sample.aircraft_visible == 0
    assert result.sample.max_range_nm is None


# -------------------------------------------------------------------- range


def test_the_furthest_aircraft_in_each_sector_is_kept(
    live: LiveStore, clock: SimulatedTime
) -> None:
    place(live, clock, icao="a00001", bearing_deg=32.0, distance_nm=40.0)
    place(live, clock, icao="a00002", bearing_deg=33.0, distance_nm=120.0)
    place(live, clock, icao="a00003", bearing_deg=97.0, distance_nm=80.0)

    result = take(MetricSampler(), live, clock)

    by_sector = {record.bearing_bucket: record for record in result.ranges}
    assert set(by_sector) == {bearing_bucket(32.0), bearing_bucket(97.0)}
    assert by_sector[bearing_bucket(32.0)].max_range_nm == pytest.approx(120.0, abs=0.01)
    assert by_sector[bearing_bucket(32.0)].icao24 == "a00002"
    assert result.sample.max_range_nm == pytest.approx(120.0, abs=0.01)


def test_a_sector_records_which_aircraft_and_when(live: LiveStore, clock: SimulatedTime) -> None:
    """§6.3 keeps the attribution because a record with no owner is trivia."""
    place(live, clock, icao="ae1463", bearing_deg=182.0, distance_nm=201.0)

    result = take(MetricSampler(), live, clock)

    record = result.ranges[0]
    assert record.icao24 == "ae1463"
    assert record.at_ms == clock.epoch_ms()
    assert record.bearing_deg == pytest.approx(182.0, abs=0.01)


def test_sectors_are_five_degrees_and_cover_the_compass() -> None:
    assert bearing_bucket(0.0) == 0
    assert bearing_bucket(4.999) == 0
    assert bearing_bucket(5.0) == 1
    assert bearing_bucket(357.5) == 71
    # Total by construction, so no caller can produce an unstorable bucket.
    assert bearing_bucket(360.0) == 0
    assert bearing_bucket(-1.0) == 71
    assert bearing_bucket(725.0) == bearing_bucket(5.0)


def test_a_receiver_with_no_location_produces_no_range_at_all(
    clock: SimulatedTime,
) -> None:
    """Range from an unknown point is not a measurement (SPEC §39)."""
    live = LiveStore(receiver_location=None, clock=clock.monotonic)
    place(live, clock, icao="a00001", bearing_deg=45.0)

    result = take(MetricSampler(), live, clock)

    assert result.ranges == ()
    assert result.sample.max_range_nm is None
    assert result.sample.aircraft_visible == 1


# -------------------------------------------------------------------- rates


def test_the_first_sample_reports_no_rates(live: LiveStore, clock: SimulatedTime) -> None:
    """There is no earlier counter to difference against, so there is no rate."""
    sampler = MetricSampler()
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=100)

    result = take(sampler, live, clock, stats=DecoderStats(messages_total=1_000))

    assert result.sample.messages_per_sec is None
    assert result.sample.positions_per_sec is None
    assert sampler.has_baseline is True


def test_decoder_counters_give_the_rate_when_the_decoder_supplies_them(
    live: LiveStore, clock: SimulatedTime
) -> None:
    sampler = MetricSampler()
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=100)
    take(sampler, live, clock, stats=DecoderStats(messages_total=1_000, positions_total=200))

    clock.advance(INTERVAL_S)
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=140)
    result = take(
        sampler, live, clock, stats=DecoderStats(messages_total=7_000, positions_total=800)
    )

    assert result.sample.messages_per_sec == pytest.approx(6_000 / 15.0)
    assert result.sample.positions_per_sec == pytest.approx(600 / 15.0)


def test_the_live_set_supplies_the_rate_when_the_decoder_does_not(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """dump1090-fa with no statistics endpoint still gets real rates.

    Two aircraft, each gaining 30 messages and 1 position report over fifteen
    seconds: 60 messages and 2 positions, from the live records alone.
    """
    sampler = MetricSampler()
    for icao in ("a00001", "a00002"):
        place(live, clock, icao=icao, bearing_deg=10.0, messages=100)
    take(sampler, live, clock)

    clock.advance(INTERVAL_S)
    for icao in ("a00001", "a00002"):
        place(live, clock, icao=icao, bearing_deg=11.0, messages=130)
    result = take(sampler, live, clock)

    assert result.sample.messages_per_sec == pytest.approx(60 / 15.0)
    assert result.sample.positions_per_sec == pytest.approx(2 / 15.0)


def test_an_aircraft_that_appeared_mid_interval_does_not_spike_the_fallback(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """Its message count is a fact about before it came into range.

    Counting it would report a burst of 50 000 messages because one distant
    aircraft the decoder had been tracking finally reached the live set.
    """
    sampler = MetricSampler()
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=100)
    take(sampler, live, clock)

    clock.advance(INTERVAL_S)
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=130)
    place(live, clock, icao="b00002", bearing_deg=10.0, messages=50_000)
    result = take(sampler, live, clock)

    assert result.sample.messages_per_sec == pytest.approx(30 / 15.0)


def test_a_decoder_counter_that_went_backwards_falls_back_rather_than_going_negative(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """A restarted decoder has not delivered minus four million messages."""
    sampler = MetricSampler()
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=100)
    take(sampler, live, clock, stats=DecoderStats(messages_total=4_000_000))

    clock.advance(INTERVAL_S)
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=115)
    result = take(sampler, live, clock, stats=DecoderStats(messages_total=12))

    # The live set still saw fifteen messages arrive, so that is what is reported.
    assert result.sample.messages_per_sec == pytest.approx(15 / 15.0)


def test_an_aircraft_whose_own_counter_reset_contributes_nothing_negative(
    live: LiveStore, clock: SimulatedTime
) -> None:
    sampler = MetricSampler()
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=5_000)
    take(sampler, live, clock)

    clock.advance(INTERVAL_S)
    place(live, clock, icao="a00001", bearing_deg=10.0, messages=3)
    result = take(sampler, live, clock)

    assert result.sample.messages_per_sec == 0.0


def test_a_gap_longer_than_the_trust_window_reports_no_rate(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """An outage is not an interval, however large the counter difference is."""
    sampler = MetricSampler()
    take(sampler, live, clock, stats=DecoderStats(messages_total=1_000))

    clock.advance(MAX_RATE_GAP_MS / 1000 + 1)
    result = take(sampler, live, clock, stats=DecoderStats(messages_total=9_000_000))

    assert result.sample.messages_per_sec is None
    assert result.sample.positions_per_sec is None


def test_resetting_the_baseline_makes_the_next_sample_rateless(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """What a restart does: the counters on either side are not comparable."""
    sampler = MetricSampler()
    take(sampler, live, clock, stats=DecoderStats(messages_total=1_000))
    sampler.reset()

    clock.advance(INTERVAL_S)
    result = take(sampler, live, clock, stats=DecoderStats(messages_total=7_000))

    assert sampler.has_baseline is False or result.sample.messages_per_sec is None
    assert result.sample.messages_per_sec is None


def test_two_samples_at_the_same_instant_report_no_rate(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """A clock that did not advance cannot be divided by."""
    sampler = MetricSampler()
    take(sampler, live, clock, stats=DecoderStats(messages_total=1_000))
    result = take(sampler, live, clock, stats=DecoderStats(messages_total=2_000))

    assert result.sample.messages_per_sec is None


# ------------------------------------------------------------ decoder fields


def test_signal_levels_come_straight_from_the_decoder(
    live: LiveStore, clock: SimulatedTime
) -> None:
    result = take(
        MetricSampler(), live, clock, stats=DecoderStats(rssi_avg_db=-14.2, rssi_peak_db=-2.1)
    )

    assert result.sample.rssi_avg_db == -14.2
    assert result.sample.rssi_peak_db == -2.1


def test_no_decoder_statistics_leaves_the_decoder_columns_absent(
    live: LiveStore, clock: SimulatedTime
) -> None:
    """SPEC §60: unsupported metrics are hidden, and the rest still records."""
    place(live, clock, icao="a00001", bearing_deg=10.0, distance_nm=77.0)

    result = take(MetricSampler(), live, clock, stats=None)

    assert result.sample.rssi_avg_db is None
    assert result.sample.rssi_peak_db is None
    assert result.sample.aircraft_visible == 1
    assert result.sample.max_range_nm == pytest.approx(77.0, abs=0.01)


def test_a_negative_gap_window_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="max_gap_ms"):
        MetricSampler(max_gap_ms=0)
