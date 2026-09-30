"""Closest stored fix and its distance — :mod:`flightsite.sightings.overhead` (slice 090).

The geometry (slant versus ground distance, antenna height, bearing) and the
selection rule: the closest *stored* point inside an inclusive window, with
nothing interpolated between or beyond stored points.
"""

from __future__ import annotations

import math

import pytest

from flightsite.ingest import Position
from flightsite.live.geo import distance_nm
from flightsite.sightings.overhead import (
    FEET_PER_NM,
    closest_fix,
    fix_distance,
    slant_distance_nm,
)
from flightsite.sightings.tracks import TrackSample

RECEIVER = Position(latitude=47.0, longitude=-122.0)

#: One minute of arc of latitude is one nautical mile on the haversine sphere
#: to within a fraction of a percent — close enough to build fixtures with.
NM_IN_DEG = 1.0 / 60.0

MINUTE_MS = 60_000


def sample(
    ts_ms: int,
    *,
    north_nm: float = 0.0,
    east_nm: float = 0.0,
    altitude_ft: int | None = None,
) -> TrackSample:
    """A point ``north_nm``/``east_nm`` from the receiver."""
    return TrackSample(
        ts_ms=ts_ms,
        latitude=RECEIVER.latitude + north_nm * NM_IN_DEG,
        longitude=RECEIVER.longitude
        + east_nm * NM_IN_DEG / math.cos(math.radians(RECEIVER.latitude)),
        position_source="adsb",
        altitude_ft=altitude_ft,
    )


# ------------------------------------------------------------------ geometry


def test_slant_distance_is_the_hypotenuse_of_ground_and_height() -> None:
    assert slant_distance_nm(3.0, 4.0 * FEET_PER_NM) == pytest.approx(5.0)


def test_slant_distance_uses_the_magnitude_of_a_negative_height() -> None:
    assert slant_distance_nm(3.0, -4.0 * FEET_PER_NM) == pytest.approx(5.0)


def test_a_fix_with_altitude_is_ranked_by_slant_distance() -> None:
    fix = fix_distance(
        sample(0, north_nm=3.0, altitude_ft=round(4 * FEET_PER_NM)),
        RECEIVER,
        antenna_height_ft=None,
    )

    assert fix.distance_kind == "slant"
    assert fix.ground_distance_nm == pytest.approx(3.0, rel=5e-3)
    assert fix.distance_nm == pytest.approx(5.0, rel=5e-3)


def test_a_fix_without_altitude_is_ranked_by_ground_distance() -> None:
    fix = fix_distance(sample(0, north_nm=3.0), RECEIVER, antenna_height_ft=None)

    assert fix.distance_kind == "ground"
    assert fix.altitude_ft is None
    assert fix.distance_nm == fix.ground_distance_nm


def test_the_antenna_height_is_subtracted_from_the_altitude() -> None:
    at_antenna = fix_distance(
        sample(0, north_nm=2.0, altitude_ft=1_200), RECEIVER, antenna_height_ft=1_200.0
    )
    at_sea_level = fix_distance(
        sample(0, north_nm=2.0, altitude_ft=1_200), RECEIVER, antenna_height_ft=None
    )

    assert at_antenna.distance_nm == pytest.approx(at_antenna.ground_distance_nm)
    assert at_sea_level.distance_nm > at_antenna.distance_nm


def test_ground_distance_is_the_live_stores_haversine() -> None:
    point = sample(0, north_nm=4.0, east_nm=3.0)
    fix = fix_distance(point, RECEIVER, antenna_height_ft=None)

    assert fix.ground_distance_nm == distance_nm(
        RECEIVER, Position(latitude=point.latitude, longitude=point.longitude)
    )


@pytest.mark.parametrize(
    ("north_nm", "east_nm", "bearing"),
    [(5.0, 0.0, 0.0), (0.0, 5.0, 90.0), (-5.0, 0.0, 180.0), (0.0, -5.0, 270.0)],
)
def test_bearing_is_degrees_true_from_the_receiver(
    north_nm: float, east_nm: float, bearing: float
) -> None:
    fix = fix_distance(
        sample(0, north_nm=north_nm, east_nm=east_nm), RECEIVER, antenna_height_ft=None
    )

    assert fix.bearing_deg == pytest.approx(bearing, abs=0.1)


def test_the_fix_carries_the_stored_points_own_fields() -> None:
    point = TrackSample(
        ts_ms=1_234,
        latitude=47.01,
        longitude=-122.02,
        position_source="mlat",
        altitude_ft=3_500,
    )

    fix = fix_distance(point, RECEIVER, antenna_height_ft=None)

    assert (fix.ts_ms, fix.latitude, fix.longitude, fix.altitude_ft, fix.position_source) == (
        1_234,
        47.01,
        -122.02,
        3_500,
        "mlat",
    )


# ----------------------------------------------------------------- selection


def test_the_closest_point_inside_the_window_wins() -> None:
    points = [
        sample(1 * MINUTE_MS, north_nm=8.0),
        sample(2 * MINUTE_MS, north_nm=2.0),
        sample(3 * MINUTE_MS, north_nm=5.0),
    ]

    fix = closest_fix(points, RECEIVER, from_ms=0, to_ms=10 * MINUTE_MS)

    assert fix is not None
    assert fix.ts_ms == 2 * MINUTE_MS


def test_a_closer_point_outside_the_window_is_ignored() -> None:
    points = [
        sample(0, north_nm=0.5),
        sample(5 * MINUTE_MS, north_nm=6.0),
        sample(20 * MINUTE_MS, north_nm=0.1),
    ]

    fix = closest_fix(points, RECEIVER, from_ms=MINUTE_MS, to_ms=10 * MINUTE_MS)

    assert fix is not None
    assert fix.ts_ms == 5 * MINUTE_MS


def test_both_window_bounds_are_inclusive() -> None:
    start = closest_fix(
        [sample(MINUTE_MS, north_nm=1.0)], RECEIVER, from_ms=MINUTE_MS, to_ms=2 * MINUTE_MS
    )
    end = closest_fix(
        [sample(2 * MINUTE_MS, north_nm=1.0)], RECEIVER, from_ms=MINUTE_MS, to_ms=2 * MINUTE_MS
    )

    assert start is not None
    assert end is not None


def test_no_stored_point_in_the_window_means_no_fix_never_an_interpolated_one() -> None:
    """Two points straddling the window pass right over the receiver between them.

    The straight line between them crosses the antenna mid-window, and it is
    still not an answer: no stored point lies in the window, so there is no
    fix to report (the module docstring's stated limit).
    """
    points = [
        sample(0, east_nm=-10.0, altitude_ft=3_000),
        sample(20 * MINUTE_MS, east_nm=10.0, altitude_ft=3_000),
    ]

    assert closest_fix(points, RECEIVER, from_ms=5 * MINUTE_MS, to_ms=15 * MINUTE_MS) is None


def test_an_empty_path_has_no_fix() -> None:
    assert closest_fix([], RECEIVER, from_ms=0, to_ms=MINUTE_MS) is None


def test_a_tie_goes_to_the_earlier_point() -> None:
    points = [sample(2 * MINUTE_MS, north_nm=3.0), sample(4 * MINUTE_MS, north_nm=-3.0)]

    fix = closest_fix(points, RECEIVER, from_ms=0, to_ms=10 * MINUTE_MS)

    assert fix is not None
    assert fix.ts_ms == 2 * MINUTE_MS


def test_altitude_can_make_the_nearer_ground_point_the_farther_fix() -> None:
    """A jet at FL350 overhead is farther than a light aircraft two miles off at 1,000 ft."""
    points = [
        sample(MINUTE_MS, north_nm=0.0, altitude_ft=35_000),
        sample(2 * MINUTE_MS, north_nm=2.0, altitude_ft=1_000),
    ]

    fix = closest_fix(points, RECEIVER, from_ms=0, to_ms=10 * MINUTE_MS)

    assert fix is not None
    assert fix.ts_ms == 2 * MINUTE_MS
