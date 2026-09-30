"""Closest position fix to the receiver within a time window (roadmap slice 090).

"What was that?" — issue #233, ``docs/design/080-feature-program.md`` §4 —
asks which aircraft passed closest to the receiver around a chosen moment.
This module is the part of that answer that needs no database: given one
sighting's stored points, which of them is the closest *stored* fix inside
the window, and how far away was it. :mod:`flightsite.api.overhead` finds the
candidate sightings and feeds their points through here.

Stored points only, never interpolated
--------------------------------------

The answer is always one of the points the sighting actually stored — a
closed sighting's Douglas-Peucker-simplified packed track (ADR-0005), or an
open one's checkpointed tail — with that point's own timestamp, altitude and
position source. Nothing is interpolated between two stored points, and
nothing is extrapolated beyond the first or last one. That is SPEC §79's line
between a single-moment lookup and the animated historical playback it keeps
out of scope, and it is also simply what the data supports: a simplified
track promises its points are within ~56 m of the flown path
(:data:`~flightsite.sightings.tracks.SIMPLIFY_EPSILON_DEG`), not that a
position computed between them was ever reported.

The price is stated rather than hidden: a long straight leg that
simplification collapsed to its two endpoints can pass directly overhead with
neither endpoint inside the window, and then the sighting has no fix to offer
for it. Such a sighting is left out rather than represented by a position it
never reported.

Distance
--------

``ground_distance_nm`` is the great-circle distance from the receiver to the
fix, from :mod:`flightsite.live.geo` — the same haversine every other
receiver-relative figure uses, so this number and the sighting's
``closest_approach_nm`` are measured the same way. When the fix carries an
altitude, ``distance_nm`` is the **slant** (line-of-sight) distance: the
ground distance and the height of the aircraft above the antenna, combined
as the two legs of a right triangle. Height above the antenna is the fix's
reported altitude minus the configured ``antenna_height_ft`` (``location``
settings, an elevation above mean sea level — its -1 400 ft floor is the Dead
Sea shore), or the altitude itself when no antenna height is configured. The
triangle is flat: across the tens of miles that matter for "overhead", Earth
curvature changes the result by well under a percent. The reported altitude
is barometric, so the height is approximate in the same way every altitude
on the map is.

A fix with no altitude (on the ground, or a decoder that reported none) is
ranked by its ground distance and says so (``distance_kind="ground"``): a
missing altitude is unknown, not zero (``docs/API.md`` §2.7), and inventing
one would put a taxiing aircraft and a cruising one on the same footing.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

from flightsite.ingest import Position, PositionSource
from flightsite.live.geo import bearing_deg, distance_nm
from flightsite.sightings.tracks import TrackSample

#: Feet in one international nautical mile (exactly 1 852 m / 0.3048 m).
FEET_PER_NM: Final = 1_852.0 / 0.3048

#: How the ranked distance was measured — see the module docstring.
DistanceKind = Literal["slant", "ground"]


@dataclass(frozen=True, slots=True)
class ClosestFix:
    """One sighting's closest stored position fix inside a window.

    Every field describes a point the sighting actually stored; none is
    derived by interpolation. ``distance_nm`` is what results are ranked by.
    """

    ts_ms: int
    latitude: float
    longitude: float
    altitude_ft: int | None
    position_source: PositionSource
    ground_distance_nm: float
    distance_nm: float
    distance_kind: DistanceKind
    bearing_deg: float


def slant_distance_nm(ground_nm: float, height_ft: float) -> float:
    """Line-of-sight distance from a ground distance and a height difference.

    A flat right triangle — see the module docstring for why curvature is
    ignored. The height may be negative (an aircraft below a hilltop
    antenna); only its magnitude matters.
    """
    return math.hypot(ground_nm, height_ft / FEET_PER_NM)


def fix_distance(
    sample: TrackSample, receiver: Position, *, antenna_height_ft: float | None
) -> ClosestFix:
    """Measure one stored point from the receiver."""
    target = Position(latitude=sample.latitude, longitude=sample.longitude)
    ground = distance_nm(receiver, target)
    kind: DistanceKind
    if sample.altitude_ft is None:
        ranked, kind = ground, "ground"
    else:
        height = sample.altitude_ft - (antenna_height_ft or 0.0)
        ranked, kind = slant_distance_nm(ground, height), "slant"
    return ClosestFix(
        ts_ms=sample.ts_ms,
        latitude=sample.latitude,
        longitude=sample.longitude,
        altitude_ft=sample.altitude_ft,
        position_source=sample.position_source,
        ground_distance_nm=ground,
        distance_nm=ranked,
        distance_kind=kind,
        bearing_deg=bearing_deg(receiver, target),
    )


def closest_fix(
    samples: Iterable[TrackSample],
    receiver: Position,
    *,
    from_ms: int,
    to_ms: int,
    antenna_height_ft: float | None = None,
) -> ClosestFix | None:
    """The stored point inside ``[from_ms, to_ms]`` closest to the receiver.

    Both bounds are inclusive. Points outside the window are skipped, never
    used as the end of an interpolated segment (module docstring). On a tie
    the earlier point wins, so the answer does not depend on anything but the
    points themselves. ``None`` when no stored point falls inside the window.
    """
    best: ClosestFix | None = None
    for sample in samples:
        if sample.ts_ms < from_ms or sample.ts_ms > to_ms:
            continue
        candidate = fix_distance(sample, receiver, antenna_height_ft=antenna_height_ft)
        if best is None or candidate.distance_nm < best.distance_nm:
            best = candidate
    return best


__all__ = [
    "FEET_PER_NM",
    "ClosestFix",
    "DistanceKind",
    "closest_fix",
    "fix_distance",
    "slant_distance_nm",
]
