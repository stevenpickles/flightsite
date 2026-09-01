"""The packed binary encoding of a closed sighting's track (ADR-0005).

One ``sighting_tracks`` row holds a whole flown path. That is the decision
DATA_MODEL §9 rests its multi-year storage budget on: at the SPEC §5 load
envelope a row per retained point costs more than 25 GB a year, and the same
points packed into one blob per sighting cost around 8. This module is that
pack/unpack layer, and per ADR-0005 it ships *with* the data — a stored track
is only as playback-capable as the decoder that comes with it, so encoder and
decoder live in one file and are round-trip tested together.

Layout, version 1
-----------------

Little-endian throughout, no padding (every ``struct`` format is prefixed
``<``). A five-byte header::

    uint8   encoding_version   always 1 here
    uint32  point_count

followed by ``point_count`` fixed-width 21-byte records::

    int32   dt_ms     milliseconds since the previous point
    int32   dlat      scaled latitude, delta from the previous point
    int32   dlon      scaled longitude, delta from the previous point
    int32   alt_ft    whole feet, or NO_ALTITUDE
    uint16  gs        ground speed in tenths of a knot, or NO_VALUE_16
    uint16  track     track in hundredths of a degree, or NO_VALUE_16
    uint8   source    position-source code (vocabulary.PositionSourceCode)

The first record's deltas are taken against the base — ``started_ms`` from the
row, and zero for the coordinates — so every record has the same shape and the
decoder needs no special case for the first point.

Why fixed width rather than varints
-----------------------------------

A variable-length integer encoding would save perhaps a third of the bytes, and
it would put a parser with a loop and a shift into the layer that has to decode
years of archived history correctly. Twenty-one bytes a point already meets the
budget DATA_MODEL §9 sizes (a ~60-point track is ~1.3 KB, and the roadmap's
2 KB ceiling for a typical sighting holds to ~95 points), so the compression is
not worth the class of bug. ``struct`` does the whole job, and a corrupt or
truncated blob is caught by an arithmetic length check rather than by running
off the end of a parse loop.

Quantization, and what a round trip promises
--------------------------------------------

============ =============================== ===========================
Field        Stored as                       Worst-case round-trip error
============ =============================== ===========================
time         exact milliseconds              none
latitude     int32, 1e-5°                    5e-6° (~0.6 m)
longitude    int32, 1e-5°                    5e-6° (~0.4 m at 50° N)
altitude     int32, whole feet               none (input is whole feet)
ground speed uint16, 0.1 kt, up to 6553.4 kt 0.05 kt
track        uint16, 0.01°, up to 359.99°    0.005°
source       uint8 code                      none
============ =============================== ===========================

Coordinate resolution is deliberately an order of magnitude finer than the
~56 m simplification tolerance the points have already survived
(:data:`~flightsite.sightings.tracks.SIMPLIFY_EPSILON_DEG`): quantization must
never be the dominant error in a stored path, or the two effects would compound
into something no test could bound.

Values outside a field's range are clamped rather than rejected — a decoder
reporting 9 000 kt is wrong, and refusing to store the whole sighting because
of one absurd speed would lose real data over a field nothing depends on.
``None`` stays ``None`` through the round trip: every optional field has a
reserved sentinel, so "the decoder did not report this" is preserved rather
than flattened to zero.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from typing import Final, NamedTuple

from flightsite.ingest import PositionSource
from flightsite.sightings.tracks import TrackSample
from flightsite.sightings.vocabulary import position_source_code, position_source_name

#: The format version written today. A stored track keeps the version it was
#: written with; format changes bump this and teach :func:`unpack_track` the
#: new layout, which makes evolution additive (DATA_MODEL §2.4).
ENCODING_VERSION: Final = 1

#: Versions this build can decode.
SUPPORTED_VERSIONS: Final[frozenset[int]] = frozenset({ENCODING_VERSION})

_HEADER: Final = struct.Struct("<BI")
_POINT: Final = struct.Struct("<iiiiHHB")

#: Degrees per stored coordinate unit: coordinates are scaled by 1e5.
COORD_SCALE: Final = 100_000
#: Ground speed is stored in tenths of a knot.
SPEED_SCALE: Final = 10
#: Track angle is stored in hundredths of a degree.
TRACK_SCALE: Final = 100

#: Sentinel for "the decoder reported no altitude" — the int32 minimum, which
#: no real altitude in feet can collide with.
NO_ALTITUDE: Final = -(2**31)
#: Sentinel for an absent ground speed or track angle.
NO_VALUE_16: Final = 0xFFFF

_MAX_UINT16: Final = 0xFFFE
_MIN_INT32: Final = -(2**31) + 1
_MAX_INT32: Final = 2**31 - 1


class UnsupportedTrackEncoding(ValueError):
    """A packed track carries a version (or a code) this build cannot decode.

    Raised rather than best-effort decoded: a track read with the wrong layout
    would not fail, it would produce a plausible wrong path, and a wrong flown
    route is worse than a missing one.
    """


class PackedTrack(NamedTuple):
    """A packed track, in the shape the ``sighting_tracks`` row stores it."""

    encoding_version: int
    point_count: int
    started_ms: int
    points_blob: bytes


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def pack_track(samples: Sequence[TrackSample]) -> PackedTrack:
    """Pack ordered samples into one row's worth of bytes.

    Args:
        samples: the retained points, oldest first, with strictly increasing
            ``ts_ms``.

    Raises:
        ValueError: if ``samples`` is empty, or if its timestamps do not
            strictly increase. Both are programming errors upstream — the
            encoding's time deltas are non-negative by construction, and a
            silently reordered track would be indistinguishable from a real
            one once written.
    """
    if not samples:
        raise ValueError("refusing to pack an empty track")

    base_ms = samples[0].ts_ms
    buffer = bytearray(_HEADER.pack(ENCODING_VERSION, len(samples)))
    previous_ms = base_ms
    previous_lat = 0
    previous_lon = 0

    for index, sample in enumerate(samples):
        if index and sample.ts_ms <= previous_ms:
            raise ValueError(
                f"track timestamps must strictly increase: {sample.ts_ms} follows {previous_ms}"
            )
        latitude = round(sample.latitude * COORD_SCALE)
        longitude = round(sample.longitude * COORD_SCALE)
        buffer += _POINT.pack(
            _clamp(sample.ts_ms - previous_ms, 0, _MAX_INT32),
            latitude - previous_lat,
            longitude - previous_lon,
            NO_ALTITUDE
            if sample.altitude_ft is None
            else _clamp(sample.altitude_ft, _MIN_INT32, _MAX_INT32),
            _encode_scaled(sample.ground_speed_kt, SPEED_SCALE),
            _encode_scaled(sample.track_deg, TRACK_SCALE),
            position_source_code(sample.position_source),
        )
        previous_ms = sample.ts_ms
        previous_lat = latitude
        previous_lon = longitude

    return PackedTrack(
        encoding_version=ENCODING_VERSION,
        point_count=len(samples),
        started_ms=base_ms,
        points_blob=bytes(buffer),
    )


def unpack_track(packed: PackedTrack) -> tuple[TrackSample, ...]:
    """Decode a packed track back into samples, oldest first.

    ``packed.started_ms`` supplies the absolute base the time deltas are
    measured from; ``encoding_version`` and ``point_count`` in the row are
    cross-checked against the blob's own header, so a row whose columns and
    blob disagree is reported rather than trusted.

    Raises:
        UnsupportedTrackEncoding: on an unknown version, a truncated or
            over-long blob, a header that contradicts the row, or a
            position-source code this build does not know.
    """
    blob = packed.points_blob
    if len(blob) < _HEADER.size:
        raise UnsupportedTrackEncoding(
            f"packed track is {len(blob)} bytes, shorter than its {_HEADER.size}-byte header"
        )

    version, point_count = _HEADER.unpack_from(blob, 0)
    if version not in SUPPORTED_VERSIONS:
        raise UnsupportedTrackEncoding(
            f"packed track encoding version {version} is not one of {sorted(SUPPORTED_VERSIONS)}"
        )
    if version != packed.encoding_version or point_count != packed.point_count:
        raise UnsupportedTrackEncoding(
            f"packed track header (v{version}, {point_count} points) contradicts its row "
            f"(v{packed.encoding_version}, {packed.point_count} points)"
        )
    expected = _HEADER.size + point_count * _POINT.size
    if len(blob) != expected:
        raise UnsupportedTrackEncoding(
            f"packed track of {point_count} points should be {expected} bytes, got {len(blob)}"
        )

    samples: list[TrackSample] = []
    ts_ms = packed.started_ms
    latitude = 0
    longitude = 0
    for index in range(point_count):
        delta_ms, delta_lat, delta_lon, altitude, speed, track, source = _POINT.unpack_from(
            blob, _HEADER.size + index * _POINT.size
        )
        ts_ms += delta_ms
        latitude += delta_lat
        longitude += delta_lon
        samples.append(
            TrackSample(
                ts_ms=ts_ms,
                latitude=latitude / COORD_SCALE,
                longitude=longitude / COORD_SCALE,
                position_source=_decode_source(source),
                altitude_ft=None if altitude == NO_ALTITUDE else altitude,
                ground_speed_kt=_decode_scaled(speed, SPEED_SCALE),
                track_deg=_decode_scaled(track, TRACK_SCALE),
            )
        )
    return tuple(samples)


def _encode_scaled(value: float | None, scale: int) -> int:
    if value is None:
        return NO_VALUE_16
    return _clamp(round(value * scale), 0, _MAX_UINT16)


def _decode_scaled(stored: int, scale: int) -> float | None:
    return None if stored == NO_VALUE_16 else stored / scale


def _decode_source(code: int) -> PositionSource:
    try:
        return position_source_name(code)
    except ValueError as error:
        raise UnsupportedTrackEncoding(str(error)) from error


__all__ = [
    "COORD_SCALE",
    "ENCODING_VERSION",
    "NO_ALTITUDE",
    "NO_VALUE_16",
    "SPEED_SCALE",
    "SUPPORTED_VERSIONS",
    "TRACK_SCALE",
    "PackedTrack",
    "UnsupportedTrackEncoding",
    "pack_track",
    "unpack_track",
]
