"""The traffic model: rhythm, population reuse, and track length.

These are the three properties :mod:`.traffic`'s docstring claims make the
dataset realistic rather than merely large, so each gets a test. The last one
matters most: the generator assumes simplification retains about one point per
fifteen seconds, and the entire growth model is built on the track sizes that
assumption produces. It is checked here against the *production* simplifier
rather than taken on trust.
"""

from __future__ import annotations

import math
import random
from collections import Counter

import pytest

from flightsite.perf.storage_qualification.traffic import (
    HOURLY_WEIGHTS,
    MAX_TRACK_POINTS,
    MIN_TRACK_POINTS,
    SECONDS_PER_RETAINED_POINT,
    WEEKDAY_WEIGHTS,
    AircraftPool,
    SyntheticSighting,
    TrackPool,
    sightings_for_day,
    sightings_on,
)
from flightsite.sightings.track_codec import unpack_track
from flightsite.sightings.tracks import (
    SIMPLIFY_ALTITUDE_FT,
    SIMPLIFY_EPSILON_DEG,
    TrackSample,
    simplify,
)

DAY_START_MS = 1_787_356_800_000


def one_day(seed: int = 7, *, sightings: int = 2_000) -> list[SyntheticSighting]:
    rng = random.Random(seed)
    pool = AircraftPool(400, rng=rng)
    airframes = pool.draw_day(unique_today=400, new_today=400)
    return sightings_for_day(
        rng,
        day_start_ms=DAY_START_MS,
        airframes=airframes,
        sightings_today=sightings,
        alert_share=0.06,
    )


def test_the_diurnal_curve_covers_every_hour() -> None:
    """Twenty-four weights, all positive: a receiver hears something at 03:00."""
    assert len(HOURLY_WEIGHTS) == 24
    assert all(weight > 0 for weight in HOURLY_WEIGHTS)
    assert len(WEEKDAY_WEIGHTS) == 7


def test_traffic_actually_follows_the_diurnal_curve() -> None:
    """Daytime is busier than the small hours, by a wide margin.

    Asserted as a ratio between aggregate bands rather than per hour, because
    the hour-by-hour counts are a sample and would make this test flap. What
    must hold is the shape: an afternoon that is not busier than 02:00-04:00
    means the curve is not being applied at all.
    """
    day = one_day()
    hours = Counter((sighting.started_ms - DAY_START_MS) // 3_600_000 for sighting in day)
    quiet = sum(hours[hour] for hour in (1, 2, 3, 4))
    busy = sum(hours[hour] for hour in (12, 13, 14, 15))
    assert busy > quiet * 3, f"daytime {busy} against night {quiet}: the curve is not applied"
    assert set(hours) <= set(range(24))


def test_the_weekend_carries_less_traffic_than_the_week() -> None:
    """The day-of-week factor changes how many sightings a day holds.

    It deliberately does not reshape the diurnal curve: scaling all 24 hourly
    weights by one constant is a no-op once ``random.choices`` normalizes them,
    so a weekday effect applied there would look like a model and do nothing.
    """
    monday = sightings_on(0, daily_average=1_500)
    saturday = sightings_on(5, daily_average=1_500)
    sunday = sightings_on(6, daily_average=1_500)
    assert saturday < monday
    assert sunday < monday


def test_a_week_still_averages_the_scenarios_daily_traffic() -> None:
    """Normalizing by the mean weight is what keeps growth figures honest.

    If the weekday factors did not average to one, every measured
    bytes-per-sighting and GB-per-year would carry that bias.
    """
    week = sum(sightings_on(weekday, daily_average=1_500) for weekday in range(7))
    assert week == pytest.approx(7 * 1_500, rel=0.01)


def test_the_population_is_reused_rather_than_replaced() -> None:
    """A receiver meets the same airframes again; a pool that never repeats is
    not modelling a receiver."""
    rng = random.Random(3)
    pool = AircraftPool(100, rng=rng)
    seen: Counter[int] = Counter()
    for _ in range(40):
        for index in pool.draw_day(unique_today=100, new_today=5):
            seen[index] += 1

    assert pool.size < 40 * 100, "every day drew an entirely new population"
    assert max(seen.values()) > 5, "no airframe was seen repeatedly"
    assert sum(1 for count in seen.values() if count == 1) > 0, "no airframe was seen only once"


def test_the_pool_grows_at_the_rate_it_is_asked_to() -> None:
    """New airframes per day is what drives the ``aircraft`` table's growth."""
    rng = random.Random(5)
    pool = AircraftPool(50, rng=rng)
    pool.draw_day(unique_today=50, new_today=50)
    after_first = pool.size
    for _ in range(10):
        pool.draw_day(unique_today=50, new_today=4)
    assert pool.size == after_first + 40


def test_a_day_is_ordered_and_bounded() -> None:
    """Sightings come out in receiver order and inside their own day."""
    day = one_day()
    starts = [sighting.started_ms for sighting in day]
    assert starts == sorted(starts)
    assert all(DAY_START_MS <= start < DAY_START_MS + 86_400_000 for start in starts)


def test_mode_s_sightings_carry_no_track() -> None:
    """The no-position case must actually occur, or the growth model is untested."""
    day = one_day(sightings=3_000)
    silent = [sighting for sighting in day if not sighting.any_position]
    assert silent, "no Mode S-only sightings were generated"
    assert all(sighting.track_points == 0 for sighting in silent)
    assert all(sighting.pos_count == 0 for sighting in silent)


def test_track_lengths_centre_on_the_documented_sixty_points() -> None:
    """``docs/DATA_MODEL.md`` §9 sizes the packed track at ~60 points."""
    day = one_day(sightings=4_000)
    points = [sighting.track_points for sighting in day if sighting.any_position]
    mean = sum(points) / len(points)
    assert 50 <= mean <= 70, f"mean retained points is {mean:.1f}, not §9's ~60"
    assert min(points) >= MIN_TRACK_POINTS
    assert max(points) <= MAX_TRACK_POINTS


def test_the_track_pool_produces_real_decodable_packed_rows() -> None:
    """Pooled blobs are genuine codec output at the exact size ADR-0005 states."""
    pool = TrackPool(rng=random.Random(1))
    for points in (2, 17, 60, 120):
        packed = pool.blob_for(points)
        assert packed.point_count == points
        assert len(packed.points_blob) == 5 + 21 * points
        samples = unpack_track(packed)
        assert len(samples) == points
        assert [sample.ts_ms for sample in samples] == sorted({sample.ts_ms for sample in samples})


def test_the_track_pool_offers_more_than_one_path_per_length() -> None:
    """A page of sighting details should not decode the same path every time."""
    pool = TrackPool(rng=random.Random(2))
    blobs = {pool.blob_for(40).points_blob for _ in range(60)}
    assert len(blobs) > 1


def test_a_pooled_track_is_too_short_to_be_a_path() -> None:
    """One point is not a track; the codec would accept it, the model should not."""
    pool = TrackPool(rng=random.Random(4))
    with pytest.raises(ValueError, match="at least"):
        pool.blob_for(1)


def test_production_simplification_retains_points_at_about_the_assumed_rate() -> None:
    """The assumption the whole growth model rests on, checked against real code.

    The generator does not run Douglas-Peucker per sighting — that would cost
    hours over a multi-year dataset and change nothing about what is stored —
    so it assumes a retention rate of one point per
    :data:`SECONDS_PER_RETAINED_POINT`. Here a dense 1 Hz transit with the
    gentle turn and climb of real cruise traffic is put through the *production*
    :func:`~flightsite.sightings.tracks.simplify`, at the production epsilons,
    and the retained count is compared against what the generator would have
    assumed for a sighting of the same length.

    The bound is deliberately an order-of-magnitude band rather than a tight
    one. Douglas-Peucker's output depends on the path's curvature, and pinning
    it here would be re-testing slice 052's simplifier against a synthetic
    path. What this catches is the assumption being wrong in kind — a rate that
    retains every point, or two.
    """
    duration_s = 900
    latitude, longitude, heading, altitude = 51.5, -0.45, 70.0, 30_000.0
    samples: list[TrackSample] = []
    for second in range(duration_s):
        heading += 0.02
        altitude += 4.0
        latitude += 450.0 / 3_600.0 / 60.0 * math.cos(math.radians(heading))
        longitude += (450.0 / 3_600.0 / 60.0 * math.sin(math.radians(heading))) / math.cos(
            math.radians(latitude)
        )
        samples.append(
            TrackSample(
                ts_ms=second * 1_000,
                latitude=latitude,
                longitude=longitude,
                position_source="adsb",
                altitude_ft=int(altitude),
                ground_speed_kt=450.0,
                track_deg=heading % 360.0,
            )
        )

    retained = simplify(
        tuple(samples),
        epsilon_deg=SIMPLIFY_EPSILON_DEG,
        altitude_epsilon_ft=SIMPLIFY_ALTITUDE_FT,
    )
    assumed = duration_s / SECONDS_PER_RETAINED_POINT

    assert 2 < len(retained) < duration_s, "simplification neither collapsed nor kept everything"
    assert assumed / 8 <= len(retained) <= assumed * 8, (
        f"production simplification retained {len(retained)} points from a {duration_s}s "
        f"1 Hz track, against the generator's assumed {assumed:.0f}; the modelled retention "
        "rate is wrong in kind, not merely in detail"
    )
