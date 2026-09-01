"""Track points, checkpoint thinning, and Douglas-Peucker simplification.

Three things live here, and they are the three shapes a sighting's path takes
between the receiver and the database (ADR-0005):

1. :class:`TrackSample` — one point, as storage sees it. The live layer's
   :class:`~flightsite.live.track.TrackPoint` carries a ``datetime`` and float
   altitudes; storage wants epoch milliseconds and whole feet, and the
   conversion belongs on this side of the seam rather than in the live path.
2. :func:`thin_for_checkpoint` — the *light* thinning ADR-0005 allows on
   checkpoint batches. Checkpoints are a crash-recovery record; dropping a
   point that sits on the straight line between its neighbours at unchanged
   altitude costs no recoverable information and keeps the busiest table in the
   schema small while sightings are open.
3. :func:`simplify` — the Douglas-Peucker pass run once, at close, before the
   path is packed into a single row and kept forever.

Why two tolerances
------------------

:data:`CHECKPOINT_EPSILON_DEG` is a tenth of :data:`SIMPLIFY_EPSILON_DEG`. That
ordering is deliberate and is what makes the close path's error bound
meaningful: a point thinning removes lies within ~5 m of the line its
neighbours draw, so simplification of the thinned path stays within the same
~55 m envelope as simplification of the raw path would. Checkpoint thinning is
therefore invisible in the archived result, while still removing the great
majority of cruise points from the open-sighting table.

Both tolerances are *cross-track* distances measured in the planar frame
:func:`cross_track_deg` builds, and both are ordinary constants: ADR-0005 asks
for the values to be chosen and property-tested in this slice rather than left
as configuration, since changing them changes what history means.

Geometry
--------

Great-circle geometry is not used for simplification. Over the few nautical
miles that separate consecutive points of a track, a local planar
approximation — latitude in degrees, longitude scaled by the cosine of the
track's mean latitude — differs from the true cross-track distance by far less
than the tolerance itself, and it makes the tolerance readable: 0.0005° of
latitude is 55.6 m anywhere on Earth. Great-circle distance stays where it
matters, in :mod:`flightsite.live.geo`, which computes the receiver-relative
ranges that become records.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import cos, hypot, inf, radians
from typing import Final

from flightsite.db.clock import to_epoch_ms
from flightsite.ingest import PositionSource
from flightsite.live import TrackPoint

#: Metres per degree of latitude, for stating tolerances in human units.
METRES_PER_DEGREE: Final = 111_320.0

#: Douglas-Peucker cross-track tolerance at sighting close, in degrees of
#: latitude — 0.0005° ≈ 56 m.
#:
#: Chosen against what the retained path is *for*: drawing a flown route on a
#: map and, later, playing it back (SPEC §19). Fifty-odd metres is well inside
#: the position error of the surveillance data itself and a fraction of a pixel
#: at any zoom that shows a whole flight, while being coarse enough to collapse
#: the long straight legs that dominate a track. Measured against the
#: DATA_MODEL §2.4 target it lands where that document predicts: a typical
#: transit keeps a few dozen points, and a manoeuvring aircraft keeps more —
#: Douglas-Peucker spends points where the path actually bends.
SIMPLIFY_EPSILON_DEG: Final = 0.0005

#: Altitude tolerance for the vertical pass, in feet.
#:
#: Simplification runs on the lat/lon/alt polyline (DATA_MODEL §2.4), so a
#: level-off, a step climb or the start of a descent has to survive even when
#: it happens on a dead-straight ground track. One hundred feet is half the
#: 200 ft altitude quantum a Mode C-only report carries and well below any
#: vertical manoeuvre worth seeing on a profile.
SIMPLIFY_ALTITUDE_FT: Final = 100.0

#: Cross-track tolerance for checkpoint thinning — 0.00005° ≈ 5.6 m, a tenth
#: of :data:`SIMPLIFY_EPSILON_DEG`. See "Why two tolerances" above.
CHECKPOINT_EPSILON_DEG: Final = 0.00005

#: Altitude tolerance for checkpoint thinning, in feet. Twenty-five feet is the
#: finest altitude quantum ADS-B reports, so a thinned checkpoint never hides a
#: reported altitude change.
CHECKPOINT_ALTITUDE_FT: Final = 25.0


@dataclass(frozen=True, slots=True)
class TrackSample:
    """One track point in storage's units: epoch milliseconds and whole feet.

    Immutable, because the same sample is handed to thinning, to
    simplification, to the codec and to tests, and none of them owns it.

    ``altitude_ft`` is ``None`` on the ground or where the decoder reported no
    barometric altitude — a real and common answer that the encoding carries as
    such rather than substituting a zero.
    """

    ts_ms: int
    latitude: float
    longitude: float
    position_source: PositionSource
    altitude_ft: int | None = None
    ground_speed_kt: float | None = None
    track_deg: float | None = None


def from_track_point(point: TrackPoint) -> TrackSample:
    """Convert a live track point into a storage sample.

    Altitude is rounded to whole feet here rather than at encode time: it is
    the value that gets compared against the previous point's during thinning,
    and comparing pre-rounding values would let a 0.4 ft wobble defeat the
    "unchanged altitude" test.
    """
    return TrackSample(
        ts_ms=to_epoch_ms(point.timestamp),
        latitude=point.latitude,
        longitude=point.longitude,
        position_source=point.position_source,
        altitude_ft=None if point.altitude_ft is None else round(point.altitude_ft),
        ground_speed_kt=point.ground_speed_kt,
        track_deg=point.track_deg,
    )


def cross_track_deg(sample: TrackSample, start: TrackSample, end: TrackSample) -> float:
    """Distance from ``sample`` to the segment ``start``-``end``, in degrees.

    Distance to the *segment*, not to the infinite line through it: the bound
    every caller wants is "how far is the discarded point from the path that
    was kept", and beyond a segment's ends the path is somewhere else entirely.
    Longitude is scaled by the cosine of the mean latitude so that a degree
    means the same distance on both axes.
    """
    scale = cos(radians((start.latitude + end.latitude) / 2.0))
    origin_x = start.longitude * scale
    origin_y = start.latitude
    point_x = sample.longitude * scale - origin_x
    point_y = sample.latitude - origin_y
    end_x = end.longitude * scale - origin_x
    end_y = end.latitude - origin_y

    span = end_x * end_x + end_y * end_y
    if span == 0.0:
        return hypot(point_x, point_y)
    # Projection of the point onto the segment, clamped to its ends.
    position = max(0.0, min(1.0, (point_x * end_x + point_y * end_y) / span))
    return hypot(point_x - position * end_x, point_y - position * end_y)


def _altitude_deviation_ft(sample: TrackSample, start: TrackSample, end: TrackSample) -> float:
    """How far ``sample``'s altitude sits from the profile ``start``-``end``.

    Availability is part of the profile: a point that reports an altitude
    between two that do not (or the reverse) is a transition, not a deviation,
    and is always kept. Where nothing in the trio has an altitude there is
    nothing to say and the deviation is zero.
    """
    altitude = sample.altitude_ft
    first, last = start.altitude_ft, end.altitude_ft
    if altitude is None:
        return 0.0 if first is None and last is None else inf
    if first is None or last is None:
        return inf

    span_ms = end.ts_ms - start.ts_ms
    if span_ms <= 0:
        return abs(altitude - first)
    expected = first + (last - first) * (sample.ts_ms - start.ts_ms) / span_ms
    return abs(altitude - expected)


def _simplify_indices(
    count: int, distance: Callable[[int, int, int], float], epsilon: float
) -> set[int]:
    """Douglas-Peucker over ``count`` points, as a set of retained indices.

    Iterative rather than recursive: a four-hour track is 14 400 points and a
    pathological input would recurse as deep as it is long, which on a Pi is a
    ``RecursionError`` in the persistence worker rather than a slow close.

    ``distance(index, first, last)`` is supplied by the caller so the same
    routine drives both the horizontal pass and the altitude-profile pass.
    """
    keep = {0, count - 1}
    stack = [(0, count - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        # Strictly greater than epsilon: every *dropped* point is therefore
        # within epsilon of the segment that replaced it, which is the bound
        # the property tests assert.
        worst, worst_distance = -1, epsilon
        for index in range(first + 1, last):
            candidate = distance(index, first, last)
            if candidate > worst_distance:
                worst, worst_distance = index, candidate
        if worst >= 0:
            keep.add(worst)
            stack.append((first, worst))
            stack.append((worst, last))
    return keep


def simplify(
    samples: Sequence[TrackSample],
    *,
    epsilon_deg: float = SIMPLIFY_EPSILON_DEG,
    altitude_epsilon_ft: float = SIMPLIFY_ALTITUDE_FT,
) -> tuple[TrackSample, ...]:
    """Simplify a sighting's path for permanent storage (ADR-0005).

    Two Douglas-Peucker passes over the same point sequence — one on the ground
    track, one on the altitude profile against time — and the union of what
    they retain. Running them separately rather than on a single 3-D polyline
    is what lets each carry its own unit: a tolerance in degrees and one in
    feet, both meaningful, instead of an arbitrary exchange rate between
    horizontal and vertical error.

    Guarantees, all property-tested:

    * the first and last points are always retained, so the stored path spans
      the same interval the sighting does;
    * every dropped point lies within ``epsilon_deg`` of the retained segment
      that spans it **and** within ``altitude_epsilon_ft`` of that segment's
      altitude profile;
    * order and timestamps are the input's — no point is moved, invented or
      interpolated (ADR-0005: points always remain real received fixes).
    """
    count = len(samples)
    if count <= 2:
        return tuple(samples)

    def horizontal(index: int, first: int, last: int) -> float:
        return cross_track_deg(samples[index], samples[first], samples[last])

    def vertical(index: int, first: int, last: int) -> float:
        return _altitude_deviation_ft(samples[index], samples[first], samples[last])

    keep = _simplify_indices(count, horizontal, epsilon_deg)
    keep |= _simplify_indices(count, vertical, altitude_epsilon_ft)
    return tuple(samples[index] for index in sorted(keep))


def thin_for_checkpoint(
    samples: Sequence[TrackSample],
    *,
    previous: TrackSample | None = None,
    epsilon_deg: float = CHECKPOINT_EPSILON_DEG,
    altitude_epsilon_ft: float = CHECKPOINT_ALTITUDE_FT,
) -> tuple[TrackSample, ...]:
    """Thin one checkpoint batch, keeping what a crash would need.

    A point is dropped only when all three of the following hold against the
    last point kept and the point that follows it: it is within
    ``epsilon_deg`` of the line between them, its altitude is within
    ``altitude_epsilon_ft`` of both, and its ``position_source`` has not
    changed. The last condition is not decoration — a track that moves from
    MLAT to ADS-B mid-flight is telling the reader something about the
    observation, and DATA_MODEL §8 makes position source per-point provenance.

    The final sample of every batch is always kept, so the checkpoint record
    ends at the newest point the sighting has: what a power cut costs is the
    points since the last batch, never a stale tail.

    ``previous`` is the last sample already checkpointed, which makes the
    decision continuous across batches instead of restarting the run at every
    flush.
    """
    kept: list[TrackSample] = []
    anchor = previous
    last_index = len(samples) - 1
    for index, sample in enumerate(samples):
        following = None if index == last_index else samples[index + 1]
        if (
            anchor is not None
            and following is not None
            and sample.position_source == anchor.position_source
            and cross_track_deg(sample, anchor, following) <= epsilon_deg
            and _altitude_deviation_ft(sample, anchor, following) <= altitude_epsilon_ft
        ):
            continue
        kept.append(sample)
        anchor = sample
    return tuple(kept)


__all__ = [
    "CHECKPOINT_ALTITUDE_FT",
    "CHECKPOINT_EPSILON_DEG",
    "METRES_PER_DEGREE",
    "SIMPLIFY_ALTITUDE_FT",
    "SIMPLIFY_EPSILON_DEG",
    "TrackSample",
    "cross_track_deg",
    "from_track_point",
    "simplify",
    "thin_for_checkpoint",
]
