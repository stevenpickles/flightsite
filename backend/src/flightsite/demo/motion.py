"""Closed-form, deterministic motion for demo-mode aircraft.

Every position the demo scenario ever reports is computed directly from
*elapsed seconds since spawn* — never by iterating a simulation step by step
and accumulating state. That is what keeps
:func:`~flightsite.demo.scenario.state_at` a pure function of
``(seed, tick_index)``: two adapters built from the same seed produce bit-
identical output for tick 400 without ever having computed ticks 0-399.

Constant-turn-rate flight model
--------------------------------

An aircraft flies at constant true airspeed ``speed_kt`` on a heading that
turns at a constant rate ``turn_rate_deg_s`` (``0`` for a straight leg, a
small value for a gentle en-route drift, a larger value for a loitering
orbit). That is a textbook constant-radius turn, which has an exact closed
form in local East/North coordinates:

.. math::

    E(t) - E_0 = \\frac{v}{\\omega} \\left( \\cos\\theta_0 - \\cos\\theta(t) \\right)

    N(t) - N_0 = \\frac{v}{\\omega} \\left( \\sin\\theta(t) - \\sin\\theta_0 \\right)

with :math:`\\theta(t) = \\theta_0 + \\omega t`, :math:`v` the speed and
:math:`\\omega` the turn rate in radians/second. As :math:`\\omega \\to 0`
this reduces to the straight-line case, which is computed directly to avoid
a division by (near) zero.

Local coordinates are converted to latitude/longitude with a flat-earth
approximation (nautical miles / 60 = degrees latitude; longitude scaled by
``cos(latitude)``). Demo positions are for visualization, not measurement —
``flightsite.live.geo`` remains the only geodesy the rest of the system
relies on — so the small distortion this introduces at long range is an
acceptable trade for a simple, exact, continuous function of time.
"""

from __future__ import annotations

import math
from typing import Final

from flightsite.ingest.types import Position

#: Nautical miles per degree of latitude (and, at the equator, of longitude).
NM_PER_DEGREE_LATITUDE: Final = 60.0

#: Below this angular rate a turn is treated as a straight line: the exact
#: formula's ``v/omega`` term would otherwise blow up for no visible benefit
#: (a radius that many thousands of nautical miles is indistinguishable from
#: straight over any demo aircraft's active window).
STRAIGHT_LINE_THRESHOLD_DEG_S: Final = 1e-6


def _clamp_latitude(latitude: float) -> float:
    return max(-90.0, min(90.0, latitude))


def _wrap_longitude(longitude: float) -> float:
    return ((longitude + 180.0) % 360.0) - 180.0


def offset_position(origin: Position, *, distance_nm: float, bearing_deg: float) -> Position:
    """Return the point ``distance_nm`` from ``origin`` on ``bearing_deg``.

    A flat-earth approximation, deliberately: this builds scenario geometry
    (start points, orbit centers), not a distance a user will read off the
    UI. It is the exact inverse of the East/North displacement
    :func:`position_at` integrates, which keeps the whole module internally
    consistent.
    """
    bearing_rad = math.radians(bearing_deg)
    north_nm = distance_nm * math.cos(bearing_rad)
    east_nm = distance_nm * math.sin(bearing_rad)
    return _displace(origin, east_nm=east_nm, north_nm=north_nm)


def _displace(origin: Position, *, east_nm: float, north_nm: float) -> Position:
    latitude = origin.latitude + north_nm / NM_PER_DEGREE_LATITUDE
    cos_lat = math.cos(math.radians(origin.latitude))
    # A demo center within a few hundred nm of a pole is not a scenario this
    # module needs to support; guard only against literal division by zero.
    divisor = cos_lat if abs(cos_lat) > 1e-9 else 1e-9
    longitude = origin.longitude + east_nm / (NM_PER_DEGREE_LATITUDE * divisor)
    return Position(latitude=_clamp_latitude(latitude), longitude=_wrap_longitude(longitude))


def position_at(
    start: Position,
    *,
    heading_deg: float,
    speed_kt: float,
    turn_rate_deg_s: float,
    age_s: float,
) -> tuple[Position, float]:
    """Return ``(position, heading_deg)`` after ``age_s`` seconds of flight.

    ``age_s`` is seconds since the aircraft started this leg (its spawn tick)
    — the sole time-varying input, which is what makes the result a pure
    function of elapsed time for a fixed profile.
    """
    speed_nm_s = speed_kt / 3600.0
    heading0_rad = math.radians(heading_deg)
    omega = math.radians(turn_rate_deg_s)

    if abs(turn_rate_deg_s) < STRAIGHT_LINE_THRESHOLD_DEG_S:
        east_nm = speed_nm_s * age_s * math.sin(heading0_rad)
        north_nm = speed_nm_s * age_s * math.cos(heading0_rad)
        heading_now = heading_deg % 360.0
    else:
        heading_now_rad = heading0_rad + omega * age_s
        radius = speed_nm_s / omega
        east_nm = radius * (math.cos(heading0_rad) - math.cos(heading_now_rad))
        north_nm = radius * (math.sin(heading_now_rad) - math.sin(heading0_rad))
        heading_now = math.degrees(heading_now_rad) % 360.0

    return _displace(start, east_nm=east_nm, north_nm=north_nm), heading_now


def altitude_at(
    *,
    base_altitude_ft: float,
    climb_fpm: float,
    age_s: float,
    min_altitude_ft: float,
    max_altitude_ft: float,
) -> tuple[float, float]:
    """Return ``(altitude_ft, vertical_rate_fpm)`` after ``age_s`` seconds.

    A linear climb/descent from ``base_altitude_ft`` at ``climb_fpm``,
    clamped to ``[min_altitude_ft, max_altitude_ft]``. Once clamped the
    reported vertical rate drops to ``0.0`` — the aircraft has leveled off,
    which is the truthful reading at that instant, not a discontinuity in the
    underlying model.
    """
    altitude = base_altitude_ft + (climb_fpm / 60.0) * age_s
    if altitude >= max_altitude_ft:
        return max_altitude_ft, 0.0
    if altitude <= min_altitude_ft:
        return min_altitude_ft, 0.0
    return altitude, climb_fpm


__all__ = [
    "NM_PER_DEGREE_LATITUDE",
    "STRAIGHT_LINE_THRESHOLD_DEG_S",
    "altitude_at",
    "offset_position",
    "position_at",
]
