"""Plausibility bounds and type coercion for decoder input.

A decoder is an untrusted input source. It can be an old build, a fork, a
proxy, a half-written file, or a device with a broken clock, and FlightSite
must never crash or store nonsense because of it (roadmap slice 007:
"malformed-input hardening"). This module is the single place where "is this
number believable?" is decided, so the answer is uniform across every adapter
and every bound is a named constant rather than a magic number buried in a
parser.

Two rules govern the whole module:

* **Coercion is strict.** A field of the wrong JSON type is treated as absent,
  never guessed at. In particular numeric strings are rejected: a decoder that
  sends ``"350"`` for an altitude is malfunctioning, and quietly accepting it
  would hide that. ``bool`` is rejected where a number is expected, because
  Python would otherwise happily read ``True`` as ``1``.
* **An implausible field is dropped, not the aircraft.** One absurd altitude
  should not erase an aircraft that is otherwise reporting perfectly good
  position and callsign. Only a broken *identity* (see
  :mod:`flightsite.ingest.readsb`) disqualifies a whole entry.

The bounds are deliberately generous: they exist to reject impossible values
(a latitude of 91, an altitude of 200,000 ft, a negative ground speed), not to
second-guess unusual but real traffic such as a U-2 at FL700 or Concorde-class
ground speeds.
"""

from __future__ import annotations

import math
from typing import Final

#: Latitude/longitude limits: anything outside is not a point on Earth.
MIN_LATITUDE_DEG: Final = -90.0
MAX_LATITUDE_DEG: Final = 90.0
MIN_LONGITUDE_DEG: Final = -180.0
MAX_LONGITUDE_DEG: Final = 180.0

#: Barometric altitude can legitimately read below sea level (low QNH, or an
#: airfield below it — Bar Yehuda is ~1,240 ft down), and the ADS-B altitude
#: encoding itself starts at -1,000 ft. The upper bound sits above the
#: armstrong-limit traffic FlightSite might plausibly hear; balloon payloads
#: and re-entry vehicles are out of scope.
MIN_ALTITUDE_FT: Final = -2_000.0
MAX_ALTITUDE_FT: Final = 100_000.0

#: Ground speed. The upper bound clears any crewed airframe (SR-71 territory)
#: while rejecting the four- and five-digit garbage a corrupt field produces.
MIN_GROUND_SPEED_KT: Final = 0.0
MAX_GROUND_SPEED_KT: Final = 2_500.0

#: Vertical rate. Fighter climb rates reach ~60,000 fpm; beyond that the value
#: is noise.
MAX_ABS_VERTICAL_RATE_FPM: Final = 60_000.0

#: Track over ground, degrees true. 360 is accepted and folded onto 0.
MIN_TRACK_DEG: Final = 0.0
MAX_TRACK_DEG: Final = 360.0

#: Signal level in dBFS. Both supported decoders report a negative dBFS figure
#: (0 dBFS being a full-scale sample); the window here spans the noise floor of
#: a very deaf receiver up to a slightly positive reading from a clipping one.
MIN_RSSI_DB: Final = -60.0
MAX_RSSI_DB: Final = 10.0

#: Message counters are cumulative per aircraft and only ever grow; a negative
#: value means the field is not what we think it is.
MIN_MESSAGE_COUNT: Final = 0

#: "Seconds since last heard". A decoder drops aircraft long before a day has
#: passed, so a larger value indicates a broken clock rather than a stale
#: aircraft.
MIN_AGE_S: Final = 0.0
MAX_AGE_S: Final = 86_400.0

#: Sanity window for a decoder's own wall clock, as Unix seconds. Below the
#: lower bound the clock is unset (a Pi with no RTC reports 1970); above the
#: upper bound it is nonsense. Roughly 2001-09-09 .. 2286-11-20.
MIN_UNIX_TIME_S: Final = 1_000_000_000.0
MAX_UNIX_TIME_S: Final = 10_000_000_000.0


def as_float(value: object) -> float | None:
    """Return ``value`` as a finite float, or ``None`` if it is not a number.

    Booleans are rejected (``True`` is not a measurement) and NaN/±inf are
    rejected, since they would poison every downstream comparison.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return result


def as_int(value: object) -> int | None:
    """Return ``value`` as an int, or ``None`` if it is not a whole number.

    Floats that are exactly integral are accepted, because JSON encoders
    occasionally render a counter as ``1234.0``.
    """
    number = as_float(value)
    if number is None or number != int(number):
        return None
    return int(number)


def as_text(value: object) -> str | None:
    """Return ``value`` as a stripped, non-empty string, else ``None``.

    Decoders pad fixed-width fields — a callsign arrives as ``"BAW117  "`` and
    an absent one as ``"        "``.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def as_bool(value: object) -> bool | None:
    """Return ``value`` if it is a real boolean, else ``None``."""
    return value if isinstance(value, bool) else None


def bounded(value: object, low: float, high: float) -> float | None:
    """Return ``value`` as a float when it lies within ``[low, high]``.

    Out-of-range and wrong-typed values both yield ``None`` — the field is
    dropped, and the rest of the aircraft's report is kept.
    """
    number = as_float(value)
    if number is None or not (low <= number <= high):
        return None
    return number


def bounded_int(value: object, low: int, high: int | None = None) -> int | None:
    """Integer counterpart of :func:`bounded`, with an optional upper bound."""
    number = as_int(value)
    if number is None or number < low:
        return None
    if high is not None and number > high:
        return None
    return number


def latitude(value: object) -> float | None:
    """Return a plausible latitude in degrees, else ``None``."""
    return bounded(value, MIN_LATITUDE_DEG, MAX_LATITUDE_DEG)


def longitude(value: object) -> float | None:
    """Return a plausible longitude in degrees, else ``None``."""
    return bounded(value, MIN_LONGITUDE_DEG, MAX_LONGITUDE_DEG)


def altitude_ft(value: object) -> float | None:
    """Return a plausible altitude in feet, else ``None``."""
    return bounded(value, MIN_ALTITUDE_FT, MAX_ALTITUDE_FT)


def ground_speed_kt(value: object) -> float | None:
    """Return a plausible ground speed in knots, else ``None``."""
    return bounded(value, MIN_GROUND_SPEED_KT, MAX_GROUND_SPEED_KT)


def vertical_rate_fpm(value: object) -> float | None:
    """Return a plausible vertical rate in feet/minute, else ``None``."""
    return bounded(value, -MAX_ABS_VERTICAL_RATE_FPM, MAX_ABS_VERTICAL_RATE_FPM)


def track_deg(value: object) -> float | None:
    """Return a plausible track in degrees true, with 360 folded onto 0."""
    number = bounded(value, MIN_TRACK_DEG, MAX_TRACK_DEG)
    if number is None:
        return None
    return 0.0 if number == MAX_TRACK_DEG else number


def rssi_db(value: object) -> float | None:
    """Return a plausible signal level in dBFS, else ``None``."""
    return bounded(value, MIN_RSSI_DB, MAX_RSSI_DB)


def age_s(value: object) -> float | None:
    """Return a plausible "seconds since last heard" value, else ``None``."""
    return bounded(value, MIN_AGE_S, MAX_AGE_S)


def message_count(value: object) -> int | None:
    """Return a plausible cumulative message count, else ``None``."""
    return bounded_int(value, MIN_MESSAGE_COUNT)


def unix_time_s(value: object) -> float | None:
    """Return a plausible Unix timestamp in seconds, else ``None``."""
    return bounded(value, MIN_UNIX_TIME_S, MAX_UNIX_TIME_S)
