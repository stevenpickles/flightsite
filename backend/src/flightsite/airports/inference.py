"""The arrival/departure heuristic, as a pure function over gates.

SPEC §41 permits three things and forbids a fourth: FlightSite *may* show the
nearest airport, *may* say likely arriving, *may* say likely departing, must
label the last two as inferred — and must not infer a route. SPEC §23 adds the
condition that governs all of it: *"arrival/departure inference when confidence
is sufficient"*.

This module is where "sufficient" is decided, and it is deliberately the whole
decision in one place: no gate lives in the service, so the rules can be read,
argued with, and tested as a table rather than traced through a consumer loop.

The gates
---------

Each observation walks the gates in order and the first one that answers ends
the walk. Everything after gate 5 is about *phase*; gates 1 to 4 decide whether
FlightSite has anything to say at all.

1. **A position.** No position, no geometry, no context.
2. **A field within reach** (:data:`NEAREST_SEARCH_NM`). Beyond that, "nearest
   airport" stops being context and becomes trivia.
3. **Low, or on the ground** (:data:`CONTEXT_CEILING_FT` above the field). This
   is the gate cruise traffic fails: an airliner at FL350 passing over a field
   is not near it in any sense a reader would mean, and saying so once per poll
   for every aircraft in the sky would drown the field that matters.
4. Gates 1 to 3 passed: there is a nearest airport, and it is reported with its
   distance. **Provenance is ``heuristic`` for the block as a whole**
   (``docs/API.md`` §2.6) even though the distance itself is arithmetic,
   because which airport is *the* nearest one is the judgement being published.
5. **On the ground: no phase.** An aircraft parked at a field is neither
   arriving nor departing, and guessing which from a stationary snapshot is
   exactly the fabrication SPEC §39 forbids. The field is still reported — an
   aircraft on the ground within :data:`ON_GROUND_MAX_DISTANCE_NM` of a field
   is at that field, which is the most certain thing this module ever says.
6. **A vertical rate, and a decisive one** (:data:`MIN_VERTICAL_RATE_FPM`).
   Level flight below the ceiling is a transit, a hold, a circuit or a
   helicopter going somewhere — all readings this heuristic cannot separate, so
   it makes none.
7. **Low enough for the phase to be about *this* field**
   (:data:`PHASE_CEILING_AGL_FT`). Descending through 8 000 ft above a field is
   descending *over* it far more often than *into* it; the arrival ceiling is
   therefore well below the ceiling for reporting the field at all.
8. **Close enough** — :data:`ARRIVAL_MAX_DISTANCE_NM` for a descent,
   :data:`DEPARTURE_MAX_DISTANCE_NM` for a climb. The departure gate is tighter
   because a departure is a fact about where an aircraft *was*, and the further
   it has flown the weaker that gets.
9. **A trend, over the same field.** At least :data:`MIN_TREND_SAMPLES`
   observations inside :data:`TREND_WINDOW_MS`, all with the same nearest
   airport, moving at least :data:`MIN_TREND_DELTA_NM` in the right direction:
   *closing* for an arrival, *opening* for a departure. This is the gate that
   separates an aircraft approaching a field from one descending past it, and
   it is why a single observation never produces a phase however suggestive its
   numbers are.

Anything that reaches the end of the walk without matching gets no phase. That
asymmetry is the point: the cost of a missing inference is a blank field, and
the cost of a wrong one is FlightSite stating something untrue about an
aircraft (SPEC §39).

What the heuristic deliberately does not use
--------------------------------------------

Runway alignment, intercept angle and ground track were all considered and left
out. Each needs runway geometry OurAirports does not carry, and each would let
the heuristic claim more than it can support — SPEC §41 draws the line at *do
not infer a full route locally*, and a heuristic that reasoned about which
runway an aircraft was lined up for would be well past it.

Field elevation
---------------

Altitudes from a decoder are pressure altitudes above the standard datum, and
the gates above are about height *above the field*. Where OurAirports knows a
field's elevation it is subtracted; for the ~16% of rows it does not, the field
is treated as sea level. That errs toward *under*-stating height above ground
at a high-elevation field, which makes the gates slightly more willing to infer
there — so the trend gate, which knows nothing about elevation, is what carries
the weight in that case.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, NamedTuple

from flightsite.airports.index import NearestAirport
from flightsite.airports.model import InferredPhase

#: How far the index is searched for a nearest airport, in nautical miles.
#: Beyond this an aircraft is not "near" a field in any useful sense, and the
#: radius bounds the index walk (:mod:`flightsite.airports.index`).
NEAREST_SEARCH_NM: Final = 30.0

#: Height above the field, in feet, at or below which nearest-airport context
#: is produced at all. Ten thousand feet is roughly the top of an approach:
#: above it an aircraft's relationship to the field below is coincidence.
CONTEXT_CEILING_FT: Final = 10_000.0

#: Height above the field at or below which a *phase* may be inferred. Well
#: below :data:`CONTEXT_CEILING_FT`, because reporting a field and claiming an
#: aircraft is landing at it are very different assertions.
PHASE_CEILING_AGL_FT: Final = 6_000.0

#: Vertical rate magnitude, feet per minute, below which the aircraft counts as
#: level. Chosen above the noise a decoder's rate field carries in cruise and
#: below any real climb or descent profile.
MIN_VERTICAL_RATE_FPM: Final = 300.0

#: Distance gates, nautical miles. Arrivals get the wider one: an aircraft
#: fifteen miles out and descending toward a field is on approach to it, while
#: an aircraft fifteen miles from a field and climbing could have come from
#: anywhere.
ARRIVAL_MAX_DISTANCE_NM: Final = 15.0
DEPARTURE_MAX_DISTANCE_NM: Final = 10.0

#: An aircraft on the ground this close to a field is at that field. Three
#: miles covers the largest airports' own footprints without reaching a
#: neighbouring one.
ON_GROUND_MAX_DISTANCE_NM: Final = 3.0

#: Observations required before a trend counts, and how far back they may
#: reach. Two is the minimum that can have a direction at all; the window keeps
#: a stale sample from an earlier pass over the same field out of the answer.
MIN_TREND_SAMPLES: Final = 2
TREND_WINDOW_MS: Final = 120_000

#: How much the distance to the field must have moved across the trend window,
#: in nautical miles, before the direction is believed. Comfortably above ADS-B
#: position jitter, and an aircraft actually approaching or leaving covers it in
#: seconds.
MIN_TREND_DELTA_NM: Final = 0.3


class TrendSample(NamedTuple):
    """One remembered observation of an aircraft's range to a field."""

    ident: str
    distance_nm: float
    ts_ms: int


@dataclass(frozen=True, slots=True)
class Kinematics:
    """The live values one inference reads, decoupled from the live record.

    A plain value object rather than a :class:`~flightsite.live.aircraft.
    LiveAircraft` so the gate table can be tested directly, without building a
    live record and a track for every row of it.
    """

    altitude_ft: float | None
    vertical_rate_fpm: float | None
    on_ground: bool | None
    ts_ms: int


def height_above_field(altitude_ft: float | None, elevation_ft: int | None) -> float | None:
    """Height above the field in feet, or ``None`` if it cannot be computed.

    A missing field elevation is read as sea level rather than as a reason to
    skip the field — see the module docstring's "Field elevation".
    """
    if altitude_ft is None:
        return None
    return altitude_ft - float(elevation_ft or 0)


def in_context(nearest: NearestAirport, kinematics: Kinematics) -> bool:
    """Whether gates 2 and 3 pass: near a field, and low or on the ground.

    Split out from :func:`infer_phase` because the service needs the answer on
    its own — an aircraft that passes this gets a reported nearest airport
    whether or not any phase is inferable.
    """
    if nearest.distance_nm > NEAREST_SEARCH_NM:
        return False
    if kinematics.on_ground:
        return nearest.distance_nm <= ON_GROUND_MAX_DISTANCE_NM
    agl = height_above_field(kinematics.altitude_ft, nearest.airport.elevation_ft)
    # No altitude and no ground statement: the aircraft may be at circuit
    # height or at FL400, and there is no honest way to choose (§2.7).
    return agl is not None and agl <= CONTEXT_CEILING_FT


def infer_phase(
    nearest: NearestAirport,
    kinematics: Kinematics,
    trail: Sequence[TrendSample],
) -> InferredPhase | None:
    """The phase gates 5 through 9 allow, or ``None``.

    Args:
        nearest: the field this inference is about, and the current range to it.
        kinematics: the current observation's altitude, vertical rate and
            ground state.
        trail: this aircraft's recent range samples, oldest first. The caller
            owns the trail; this function only reads it, and reads only the
            part of it inside :data:`TREND_WINDOW_MS`.

    Returns ``None`` for every ambiguous case, which is most of them.
    """
    if kinematics.on_ground:
        return None
    rate = kinematics.vertical_rate_fpm
    if rate is None or abs(rate) < MIN_VERTICAL_RATE_FPM:
        return None

    agl = height_above_field(kinematics.altitude_ft, nearest.airport.elevation_ft)
    if agl is None or agl > PHASE_CEILING_AGL_FT:
        return None

    delta = _closing_delta(nearest, trail, kinematics.ts_ms)
    if delta is None:
        return None

    if rate <= -MIN_VERTICAL_RATE_FPM:
        if nearest.distance_nm > ARRIVAL_MAX_DISTANCE_NM:
            return None
        return InferredPhase.ARRIVING if delta >= MIN_TREND_DELTA_NM else None

    if nearest.distance_nm > DEPARTURE_MAX_DISTANCE_NM:
        return None
    return InferredPhase.DEPARTING if -delta >= MIN_TREND_DELTA_NM else None


def _closing_delta(
    nearest: NearestAirport,
    trail: Sequence[TrendSample],
    now_ms: int,
) -> float | None:
    """How much closer the aircraft has come, or ``None`` if there is no trend.

    Positive means closing on the field, negative means leaving it. ``None``
    means the trail cannot support either reading: too few samples inside the
    window, or samples taken against a *different* field, which happens when an
    aircraft crosses from one field's neighbourhood into another's and means the
    two ends of the trend are not measuring the same thing.
    """
    ident = nearest.airport.ident
    window = [
        sample
        for sample in trail
        if sample.ident == ident and now_ms - sample.ts_ms <= TREND_WINDOW_MS
    ]
    if len(window) < MIN_TREND_SAMPLES:
        return None
    # A sample whose ident differs anywhere inside the window disqualifies the
    # trend rather than merely being skipped: the aircraft was nearer something
    # else in the middle of it, so neither end describes an approach to *this*
    # field.
    if any(sample.ident != ident for sample in trail if now_ms - sample.ts_ms <= TREND_WINDOW_MS):
        return None
    oldest = min(window, key=lambda sample: sample.ts_ms)
    return oldest.distance_nm - nearest.distance_nm


def trail_window_start(now_ms: int) -> int:
    """The oldest timestamp a trail sample may carry and still count.

    Exposed so the service can prune with the same bound the gates apply,
    rather than keeping its own copy of the window.
    """
    return now_ms - TREND_WINDOW_MS


__all__ = [
    "ARRIVAL_MAX_DISTANCE_NM",
    "CONTEXT_CEILING_FT",
    "DEPARTURE_MAX_DISTANCE_NM",
    "MIN_TREND_DELTA_NM",
    "MIN_TREND_SAMPLES",
    "MIN_VERTICAL_RATE_FPM",
    "NEAREST_SEARCH_NM",
    "ON_GROUND_MAX_DISTANCE_NM",
    "PHASE_CEILING_AGL_FT",
    "TREND_WINDOW_MS",
    "Kinematics",
    "TrendSample",
    "height_above_field",
    "in_context",
    "infer_phase",
    "trail_window_start",
]
