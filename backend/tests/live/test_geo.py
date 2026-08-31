"""Great-circle distance and bearing against known geodesic fixtures.

The cases are chosen so the expected answer is knowable independently of the
implementation: degrees along the equator and along a meridian have an exact
arc length on a sphere, the cardinal bearings are exact, and the London-to-New
York pair is a distance published in every navigation reference.
"""

from __future__ import annotations

import math

import pytest

from flightsite.ingest import Position
from flightsite.live.geo import EARTH_RADIUS_NM, bearing_deg, distance_and_bearing, distance_nm

ORIGIN = Position(latitude=0.0, longitude=0.0)

#: One degree of arc on the mean-radius sphere, in nautical miles. A nautical
#: mile is one minute of arc by definition, so this is 60 nm to within the
#: 0.07 % by which the international nautical mile (1 852 m exactly) differs
#: from a minute of the IUGG mean radius.
ONE_DEGREE_NM = math.radians(1.0) * EARTH_RADIUS_NM


def test_one_degree_of_arc_is_sixty_nautical_miles() -> None:
    assert pytest.approx(60.0, abs=0.05) == ONE_DEGREE_NM


def test_distance_along_the_equator() -> None:
    east = Position(latitude=0.0, longitude=1.0)

    assert distance_nm(ORIGIN, east) == pytest.approx(ONE_DEGREE_NM, abs=1e-6)


def test_distance_along_a_meridian() -> None:
    north = Position(latitude=1.0, longitude=0.0)

    assert distance_nm(ORIGIN, north) == pytest.approx(ONE_DEGREE_NM, abs=1e-6)


def test_distance_is_symmetric() -> None:
    north = Position(latitude=1.0, longitude=0.0)

    assert distance_nm(ORIGIN, north) == pytest.approx(distance_nm(north, ORIGIN))


@pytest.mark.parametrize(
    ("target", "expected_bearing"),
    [
        (Position(latitude=1.0, longitude=0.0), 0.0),
        (Position(latitude=0.0, longitude=1.0), 90.0),
        (Position(latitude=-1.0, longitude=0.0), 180.0),
        (Position(latitude=0.0, longitude=-1.0), 270.0),
    ],
)
def test_cardinal_bearings_from_the_origin(target: Position, expected_bearing: float) -> None:
    assert bearing_deg(ORIGIN, target) == pytest.approx(expected_bearing, abs=1e-9)


def test_bearing_is_normalized_to_a_positive_compass_range() -> None:
    # South-west: the raw atan2 result is negative before normalization.
    south_west = Position(latitude=-1.0, longitude=-1.0)

    assert 180.0 < bearing_deg(ORIGIN, south_west) < 270.0


def test_a_real_world_pair_matches_published_figures() -> None:
    # Heathrow to JFK: 5 540 km / 2 991 nm great circle, initial track ~288°.
    heathrow = Position(latitude=51.4700, longitude=-0.4543)
    jfk = Position(latitude=40.6413, longitude=-73.7781)

    distance, bearing = distance_and_bearing(heathrow, jfk)

    assert distance == pytest.approx(2991.4, abs=1.0)
    assert bearing == pytest.approx(287.94, abs=0.05)


def test_the_reverse_bearing_is_not_the_reciprocal_on_a_great_circle() -> None:
    # The forward azimuth changes along a long great-circle path; JFK->LHR
    # departs on 051°, not the 108° a rhumb-line reciprocal would suggest.
    heathrow = Position(latitude=51.4700, longitude=-0.4543)
    jfk = Position(latitude=40.6413, longitude=-73.7781)

    assert bearing_deg(jfk, heathrow) == pytest.approx(51.35, abs=0.05)


def test_identical_points_are_zero_range() -> None:
    same = Position(latitude=47.4502, longitude=-122.3088)

    assert distance_nm(same, same) == 0.0
    assert bearing_deg(same, same) == 0.0


def test_antipodal_points_do_not_overflow_the_arcsine() -> None:
    # Floating-point drift can push the haversine term just above 1.0 here;
    # unclamped, that raises instead of returning half the circumference.
    antipode = Position(latitude=0.0, longitude=180.0)

    assert distance_nm(ORIGIN, antipode) == pytest.approx(math.pi * EARTH_RADIUS_NM, rel=1e-9)
