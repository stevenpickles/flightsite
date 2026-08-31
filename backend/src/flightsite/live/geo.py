"""Spherical geodesy for receiver-relative derived fields.

Distance and bearing from the receiver to an aircraft are the two derived
values the live store computes on every positioned update (SPEC §22:
``derived``, never presented as decoder-reported). Both are great-circle
figures on a sphere of the Earth's mean radius.

Why a sphere and not an ellipsoid
---------------------------------

FlightSite reports ranges in whole-tenths of a nautical mile over distances of
a few hundred nautical miles. Across that span the spherical haversine differs
from a WGS-84 geodesic (Vincenty/Karney) by roughly 0.3 % worst case — under
1 nm at 250 nm, and far below the position error of the ADS-B reports being
measured. A sphere buys that accuracy for two trigonometric calls per
positioned aircraft per poll, with no iteration and no convergence failure
near antipodal points, which is what keeps the 500-aircraft batch budget
(``docs/ARCHITECTURE.md`` §3.3) comfortable. Range rings, closest-approach
records and per-bearing range statistics all consume these numbers, so the
choice is documented here once rather than re-argued per consumer.

Units follow ``docs/API.md`` §2.3: nautical miles and degrees true.
"""

from __future__ import annotations

import math
from typing import Final

from flightsite.ingest import Position

#: Mean Earth radius in nautical miles: the IUGG mean radius 6 371.0088 km
#: converted at the international nautical mile of exactly 1 852 m.
EARTH_RADIUS_NM: Final = 6371.0088 / 1.852


def distance_nm(origin: Position, target: Position) -> float:
    """Great-circle distance from ``origin`` to ``target`` in nautical miles.

    Uses the haversine formulation, which stays numerically well-conditioned
    for the short distances that dominate here (the spherical law of cosines
    loses precision below a mile or so).
    """
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(target.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(target.longitude - origin.longitude)

    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    # Clamp against floating-point drift above 1.0 for near-antipodal pairs,
    # which would otherwise make asin raise.
    return 2.0 * EARTH_RADIUS_NM * math.asin(math.sqrt(min(1.0, a)))


def bearing_deg(origin: Position, target: Position) -> float:
    """Initial great-circle bearing from ``origin`` to ``target``, degrees true.

    This is the *forward azimuth* at the origin, normalized to ``[0, 360)``.
    On a great circle the bearing changes along the path, so the value is only
    meaningful as "the direction to look from the receiver" — which is exactly
    what it is used for (range rings, per-bearing range statistics, the
    aircraft detail panel).

    Two identical points have no defined bearing; ``0.0`` is returned, which is
    the value the formula yields anyway and which no consumer distinguishes
    from north at zero range.
    """
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(target.latitude)
    delta_lon = math.radians(target.longitude - origin.longitude)

    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return math.degrees(math.atan2(y, x)) % 360.0


def distance_and_bearing(origin: Position, target: Position) -> tuple[float, float]:
    """Return ``(distance_nm, bearing_deg)`` in one call.

    The live store always wants both, and computing them together keeps the
    hot path to a single helper call per positioned aircraft.
    """
    return distance_nm(origin, target), bearing_deg(origin, target)


__all__ = ["EARTH_RADIUS_NM", "bearing_deg", "distance_and_bearing", "distance_nm"]
