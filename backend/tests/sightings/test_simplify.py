"""Douglas-Peucker simplification and checkpoint thinning.

The roadmap's acceptance criterion for slice 052 is that "simplification error
is bounded and tested (property tests)", so the bound is asserted the way it is
actually guaranteed rather than by eyeballing a few fixed tracks:

* over randomized plausible tracks (seeded, so a failure is reproducible),
* against the same metric the implementation uses
  (:func:`~flightsite.sightings.tracks.cross_track_deg`), so a test cannot pass
  by measuring something easier than what was minimized,
* separately per pass, where the bound is exact, and then on the combined
  result, where refining one pass's polyline with the other's vertices doubles
  it — see :func:`test_the_combined_passes_stay_within_twice_the_tolerance`.

The fixed-shape tests beside them pin the *behaviour* the tolerances were
chosen for: cruise collapses, turns survive, and a level-off on a dead-straight
ground track survives too.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from itertools import pairwise
from math import cos, hypot, inf, radians, sin

import pytest

from flightsite.sightings.tracks import (
    CHECKPOINT_ALTITUDE_FT,
    CHECKPOINT_EPSILON_DEG,
    SIMPLIFY_ALTITUDE_FT,
    SIMPLIFY_EPSILON_DEG,
    TrackSample,
    cross_track_deg,
    simplify,
    thin_for_checkpoint,
)

BASE_MS = 1_756_600_000_000
BASE_LAT = 47.45
BASE_LON = -122.31

#: Seeds for the randomized properties. Fixed, so every run explores the same
#: hundred tracks and a failure is reproducible from the report alone
#: (``docs/TEST_STRATEGY.md`` §3).
SEEDS = range(40)


def sample(
    *,
    at_ms: int,
    lat: float,
    lon: float,
    altitude_ft: int | None = 30_000,
    source: str = "adsb",
    ground_speed_kt: float | None = 420.0,
    track_deg: float | None = 90.0,
) -> TrackSample:
    """One sample, with plausible defaults so a test states only what it means."""
    return TrackSample(
        ts_ms=at_ms,
        latitude=lat,
        longitude=lon,
        position_source=source,  # type: ignore[arg-type]
        altitude_ft=altitude_ft,
        ground_speed_kt=ground_speed_kt,
        track_deg=track_deg,
    )


def straight_leg(count: int, *, altitude_ft: int | None = 30_000) -> tuple[TrackSample, ...]:
    """A dead-straight, level, evenly spaced leg — the cruise case."""
    return tuple(
        sample(
            at_ms=BASE_MS + index * 1_000,
            lat=BASE_LAT + index * 0.01,
            lon=BASE_LON,
            altitude_ft=altitude_ft,
        )
        for index in range(count)
    )


def random_track(rng: random.Random, count: int) -> tuple[TrackSample, ...]:
    """A plausible flown track: wandering heading, drifting altitude, ~1 Hz."""
    latitude, longitude = BASE_LAT, BASE_LON
    heading = rng.uniform(0.0, 360.0)
    altitude = rng.uniform(500.0, 38_000.0)
    at_ms = BASE_MS
    samples: list[TrackSample] = []
    for _ in range(count):
        at_ms += rng.randint(900, 1_400)
        heading += rng.gauss(0.0, 3.0)
        altitude = max(0.0, altitude + rng.gauss(0.0, 60.0))
        latitude += cos(radians(heading)) * 0.0015
        longitude += sin(radians(heading)) * 0.0015 / cos(radians(latitude))
        samples.append(
            sample(
                at_ms=at_ms,
                lat=latitude,
                lon=longitude,
                altitude_ft=round(altitude),
                ground_speed_kt=rng.uniform(90.0, 520.0),
                track_deg=heading % 360.0,
            )
        )
    return tuple(samples)


def bracketing(retained: Sequence[TrackSample], dropped: TrackSample) -> tuple[int, int]:
    """Indices of the retained points either side of ``dropped`` in time."""
    after = next(index for index, kept in enumerate(retained) if kept.ts_ms > dropped.ts_ms)
    return after - 1, after


def distance_to_path(retained: Sequence[TrackSample], point: TrackSample) -> float:
    """Distance from ``point`` to the nearest segment of the retained path."""
    return min(cross_track_deg(point, start, end) for start, end in pairwise(retained))


def interpolated_altitude(start: TrackSample, end: TrackSample, at_ms: int) -> float:
    span = end.ts_ms - start.ts_ms
    assert start.altitude_ft is not None and end.altitude_ft is not None
    if span <= 0:  # pragma: no cover - generated tracks always advance
        return float(start.altitude_ft)
    fraction = (at_ms - start.ts_ms) / span
    return start.altitude_ft + (end.altitude_ft - start.altitude_ft) * fraction


# --------------------------------------------------------------- properties


def test_the_endpoints_of_every_track_are_retained() -> None:
    # The stored path must span the same interval the sighting does, or a
    # sighting's first and last positions would be inventions of simplification.
    for seed in SEEDS:
        track = random_track(random.Random(seed), 200)

        retained = simplify(track)

        assert retained[0] == track[0]
        assert retained[-1] == track[-1]


def test_retained_points_are_the_original_points_in_order() -> None:
    # ADR-0005: points always remain real received fixes. Nothing is moved,
    # averaged or interpolated, and timestamps stay strictly increasing.
    for seed in SEEDS:
        track = random_track(random.Random(seed), 200)

        retained = simplify(track)

        assert set(retained) <= set(track)
        assert [point.ts_ms for point in retained] == sorted(point.ts_ms for point in retained)
        assert len(set(retained)) == len(retained)


def test_horizontal_simplification_bounds_every_dropped_point() -> None:
    """The exact Douglas-Peucker guarantee, on the pass that makes it.

    The vertical pass is disabled so the retained set is the horizontal pass's
    own: every dropped point must then lie within the tolerance of the segment
    joining the two retained points that bracket it.
    """
    for seed in SEEDS:
        track = random_track(random.Random(seed), 200)

        retained = simplify(track, altitude_epsilon_ft=inf)

        kept = set(retained)
        for point in track:
            if point in kept:
                continue
            before, after = bracketing(retained, point)
            error = cross_track_deg(point, retained[before], retained[after])
            assert error <= SIMPLIFY_EPSILON_DEG, f"seed {seed}: dropped point {error:.6f} away"


def test_vertical_simplification_bounds_every_dropped_altitude() -> None:
    """The same guarantee for the altitude profile, in feet against time."""
    for seed in SEEDS:
        track = random_track(random.Random(seed), 200)

        retained = simplify(track, epsilon_deg=inf)

        kept = set(retained)
        for point in track:
            if point in kept:
                continue
            before, after = bracketing(retained, point)
            expected = interpolated_altitude(retained[before], retained[after], point.ts_ms)
            assert point.altitude_ft is not None
            assert abs(point.altitude_ft - expected) <= SIMPLIFY_ALTITUDE_FT


def test_the_combined_passes_stay_within_twice_the_tolerance() -> None:
    """The honest bound when both passes run, and why it is twice.

    A point the horizontal pass dropped is within one tolerance of the coarse
    segment that replaced it. The vertical pass then puts extra vertices back
    onto that stretch — vertices the horizontal pass had itself dropped, so each
    is also within one tolerance of the same coarse segment. Both the point and
    the refined path therefore lie inside the same tolerance-wide slab, which
    puts them at most two tolerances apart.
    """
    for seed in SEEDS:
        track = random_track(random.Random(seed), 200)

        retained = simplify(track)

        kept = set(retained)
        for point in track:
            if point not in kept:
                assert distance_to_path(retained, point) <= 2 * SIMPLIFY_EPSILON_DEG


def test_a_coarser_tolerance_never_keeps_more_points() -> None:
    # Monotonicity is what makes the constant a tuning knob (DATA_MODEL §9):
    # raising it must trade fidelity for size, never the other way round.
    for seed in SEEDS:
        track = random_track(random.Random(seed), 150)

        counts = [
            len(simplify(track, epsilon_deg=epsilon, altitude_epsilon_ft=inf))
            for epsilon in (0.00005, 0.0002, 0.0005, 0.002, 0.01)
        ]

        assert counts == sorted(counts, reverse=True)


# ------------------------------------------------------------ fixed shapes


def test_a_straight_cruise_leg_collapses_to_its_endpoints() -> None:
    # The case that makes the storage budget work: an hour of level cruise is
    # two points, not thirty-six hundred.
    retained = simplify(straight_leg(400))

    assert len(retained) == 2


def test_a_turn_is_retained() -> None:
    # Douglas-Peucker spends points where the path bends (ADR-0005), so the
    # corner of a right-angle turn must survive.
    corner = sample(at_ms=BASE_MS + 50_000, lat=BASE_LAT + 0.5, lon=BASE_LON)
    track = (
        sample(at_ms=BASE_MS, lat=BASE_LAT, lon=BASE_LON),
        sample(at_ms=BASE_MS + 25_000, lat=BASE_LAT + 0.25, lon=BASE_LON),
        corner,
        sample(at_ms=BASE_MS + 75_000, lat=BASE_LAT + 0.5, lon=BASE_LON + 0.25),
        sample(at_ms=BASE_MS + 100_000, lat=BASE_LAT + 0.5, lon=BASE_LON + 0.5),
    )

    retained = simplify(track)

    assert corner in retained
    assert len(retained) == 3


def test_a_level_off_survives_a_dead_straight_ground_track() -> None:
    """The reason simplification is altitude-aware at all.

    A climb that levels off while tracking straight has no horizontal feature
    whatsoever — the horizontal pass alone would store two points and lose the
    entire vertical profile.
    """
    climb = [
        sample(
            at_ms=BASE_MS + index * 10_000,
            lat=BASE_LAT + index * 0.01,
            lon=BASE_LON,
            altitude_ft=1_000 + index * 1_000,
        )
        for index in range(10)
    ]
    level = [
        sample(
            at_ms=BASE_MS + (10 + index) * 10_000,
            lat=BASE_LAT + (10 + index) * 0.01,
            lon=BASE_LON,
            altitude_ft=10_000,
        )
        for index in range(10)
    ]
    track = tuple(climb + level)

    horizontal_only = simplify(track, altitude_epsilon_ft=inf)
    retained = simplify(track)

    assert len(horizontal_only) == 2
    level_off_ms = BASE_MS + 90_000
    assert any(point.altitude_ft == 10_000 and point.ts_ms == level_off_ms for point in retained)


def test_a_change_in_altitude_availability_is_retained() -> None:
    # An aircraft touching down stops reporting barometric altitude. That is a
    # transition, not a gap to be smoothed over.
    track = (
        *straight_leg(5),
        *[
            sample(
                at_ms=BASE_MS + (5 + index) * 1_000,
                lat=BASE_LAT + (5 + index) * 0.01,
                lon=BASE_LON,
                altitude_ft=None,
            )
            for index in range(5)
        ],
    )

    retained = simplify(track)

    assert any(point.altitude_ft is None for point in retained)
    assert any(point.altitude_ft is not None for point in retained)


def test_short_tracks_pass_straight_through() -> None:
    single = straight_leg(1)
    pair = straight_leg(2)

    assert simplify(single) == single
    assert simplify(pair) == pair
    assert simplify(()) == ()


def test_a_track_with_no_altitudes_at_all_still_simplifies() -> None:
    # Mode S with 2-D positions only: the vertical pass has nothing to say and
    # must not therefore retain every point.
    retained = simplify(straight_leg(200, altitude_ft=None))

    assert len(retained) == 2


# ------------------------------------------------------------ thinning


def test_thinning_drops_the_collinear_middle_of_a_cruise_batch() -> None:
    # ADR-0005's "collinear cruise points at unchanged altitude may be skipped".
    kept = thin_for_checkpoint(straight_leg(60))

    assert len(kept) == 2


def test_thinning_always_keeps_the_last_point_of_a_batch() -> None:
    # What a power cut costs is the points since the last batch. A batch that
    # ended short of its newest point would silently widen that window.
    for size in (1, 2, 5, 60):
        batch = straight_leg(size)

        kept = thin_for_checkpoint(batch)

        assert kept[-1] == batch[-1]


def test_thinning_is_continuous_across_batches() -> None:
    """The anchor is what stops every batch from re-keeping its own first point.

    Split a single cruise leg into batches and thin them in sequence: the
    result must be no larger than thinning the whole leg at once plus the one
    end-of-batch point each flush is obliged to keep.
    """
    leg = straight_leg(90)
    kept: list[TrackSample] = []
    anchor: TrackSample | None = None
    for start in range(0, 90, 30):
        batch = thin_for_checkpoint(leg[start : start + 30], previous=anchor)
        kept.extend(batch)
        anchor = batch[-1]

    assert [point.ts_ms for point in kept] == [
        leg[0].ts_ms,
        leg[29].ts_ms,
        leg[59].ts_ms,
        leg[89].ts_ms,
    ]


def test_thinning_keeps_a_position_source_change() -> None:
    # Position source is per-point provenance (DATA_MODEL §8): an aircraft
    # moving from MLAT to ADS-B mid-leg is telling the reader something.
    leg = list(straight_leg(9))
    leg[4] = sample(at_ms=leg[4].ts_ms, lat=leg[4].latitude, lon=leg[4].longitude, source="mlat")

    kept = thin_for_checkpoint(tuple(leg))

    assert leg[4] in kept


def test_thinning_keeps_an_altitude_step_on_a_straight_track() -> None:
    leg = list(straight_leg(9))
    leg[4] = sample(
        at_ms=leg[4].ts_ms, lat=leg[4].latitude, lon=leg[4].longitude, altitude_ft=31_000
    )

    kept = thin_for_checkpoint(tuple(leg))

    assert leg[4] in kept


def test_every_thinned_point_is_within_the_checkpoint_tolerance() -> None:
    """The bound that makes checkpoint thinning invisible in the archive.

    Thinning is a one-pass predicate rather than Douglas-Peucker, so what it
    guarantees is per-point: each dropped point was within the tolerance of the
    line between the point kept before it and the point that followed it.
    """
    for seed in SEEDS:
        track = random_track(random.Random(seed), 200)

        kept = thin_for_checkpoint(track)

        assert set(kept) <= set(track)
        assert distance_within(track, kept)


def distance_within(track: Sequence[TrackSample], kept: Sequence[TrackSample]) -> bool:
    """Whether every dropped point sits within the checkpoint tolerances."""
    retained = set(kept)
    anchor = None
    for index, point in enumerate(track):
        if point in retained:
            anchor = point
            continue
        assert anchor is not None, "the first point of a batch is always kept"
        following = track[index + 1]
        assert cross_track_deg(point, anchor, following) <= CHECKPOINT_EPSILON_DEG
        assert point.altitude_ft is not None
        expected = interpolated_altitude(anchor, following, point.ts_ms)
        assert abs(point.altitude_ft - expected) <= CHECKPOINT_ALTITUDE_FT
    return True


def test_checkpoint_thinning_is_tighter_than_simplification() -> None:
    """The ordering the two tolerances depend on (tracks.py, "Why two tolerances").

    Checkpoints must never be the reason a stored path loses fidelity, so
    thinning has to remove strictly less than simplification would.
    """
    assert CHECKPOINT_EPSILON_DEG < SIMPLIFY_EPSILON_DEG
    assert CHECKPOINT_ALTITUDE_FT < SIMPLIFY_ALTITUDE_FT

    for seed in SEEDS:
        track = random_track(random.Random(seed), 200)

        assert len(thin_for_checkpoint(track)) >= len(simplify(track))


def test_simplifying_a_thinned_track_matches_simplifying_the_raw_one() -> None:
    """The claim the close path rests on: what checkpoints dropped did not matter.

    The archived path is simplified from the checkpoint record, so the two
    routes through the pipeline have to agree to within the simplification
    tolerance itself — which is the whole reason thinning is a tenth of it.
    """
    for seed in SEEDS:
        track = random_track(random.Random(seed), 300)

        from_raw = simplify(track)
        from_thinned = simplify(thin_for_checkpoint(track))

        for point in from_thinned:
            assert distance_to_path(from_raw, point) <= 2 * SIMPLIFY_EPSILON_DEG
        assert abs(len(from_thinned) - len(from_raw)) <= max(2, len(from_raw) // 4)


def test_the_planar_metric_measures_distance_not_coordinates() -> None:
    """A degree of longitude at 47° N is not a degree of latitude.

    Without the cosine scaling the cross-track error of an east-west leg would
    be overstated by a third, and the tolerance would mean two different
    distances depending on which way the aircraft was flying.
    """
    start = sample(at_ms=BASE_MS, lat=BASE_LAT, lon=BASE_LON)
    east = sample(at_ms=BASE_MS + 1_000, lat=BASE_LAT, lon=BASE_LON + 0.01)
    north = sample(at_ms=BASE_MS + 1_000, lat=BASE_LAT + 0.01, lon=BASE_LON)

    east_offset = cross_track_deg(east, start, north)
    north_offset = cross_track_deg(north, start, east)

    assert east_offset == pytest.approx(0.01 * cos(radians(BASE_LAT)), rel=1e-4)
    assert north_offset == pytest.approx(0.01, rel=1e-9)
    assert east_offset < north_offset


def test_a_degenerate_segment_measures_straight_line_distance() -> None:
    # Two identical endpoints have no direction to project onto; the honest
    # answer is the distance to the point itself.
    start = sample(at_ms=BASE_MS, lat=BASE_LAT, lon=BASE_LON)
    duplicate = sample(at_ms=BASE_MS + 1_000, lat=BASE_LAT, lon=BASE_LON)
    away = sample(at_ms=BASE_MS + 500, lat=BASE_LAT + 0.02, lon=BASE_LON)

    assert cross_track_deg(away, start, duplicate) == pytest.approx(0.02, rel=1e-9)


def test_distance_beyond_a_segment_is_measured_to_its_end() -> None:
    # Distance to the segment, not to the infinite line: a point past the end
    # of a leg is as far away as the end of the leg, not as close as the line.
    start = sample(at_ms=BASE_MS, lat=BASE_LAT, lon=BASE_LON)
    end = sample(at_ms=BASE_MS + 1_000, lat=BASE_LAT + 0.01, lon=BASE_LON)
    beyond = sample(at_ms=BASE_MS + 2_000, lat=BASE_LAT + 0.03, lon=BASE_LON)

    assert cross_track_deg(beyond, start, end) == pytest.approx(hypot(0.0, 0.02), rel=1e-9)


def test_degenerate_timestamps_do_not_divide_by_zero() -> None:
    """Simplification tolerates a track that does not advance in time.

    The pipeline never produces one — the live track rejects a point that is
    not strictly newer, and the codec refuses to pack one — but the altitude
    profile is interpolated *against time*, and a zero-length span reaching
    that division would be a crash in the persistence worker rather than a
    wrong answer.
    """
    stalled = tuple(
        sample(at_ms=BASE_MS, lat=BASE_LAT + index * 0.01, lon=BASE_LON, altitude_ft=1_000 * index)
        for index in range(4)
    )

    retained = simplify(stalled)

    assert retained[0] == stalled[0]
    assert retained[-1] == stalled[-1]
