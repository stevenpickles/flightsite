"""The packed track encoding: round trips, tolerances, and refusals.

ADR-0005 makes the decoder part of the data: a `sighting_tracks` row is only
worth keeping for years if what comes back out of it is what went in. These
tests hold the encoder to the tolerance table in
:mod:`flightsite.sightings.track_codec` — over randomized tracks, so the
guarantee is a property rather than a handful of examples — and hold the
decoder to refusing anything it cannot decode *correctly*, since a track
decoded with the wrong layout would not fail, it would draw a wrong route.
"""

from __future__ import annotations

import random
import struct

import pytest

from flightsite.sightings.track_codec import (
    COORD_SCALE,
    ENCODING_VERSION,
    SPEED_SCALE,
    TRACK_SCALE,
    PackedTrack,
    UnsupportedTrackEncoding,
    pack_track,
    unpack_track,
)
from flightsite.sightings.tracks import TrackSample

from .test_simplify import BASE_MS, random_track, sample, straight_leg

HEADER_BYTES = 5
POINT_BYTES = 21

#: Half a stored unit, which is the worst a round trip through a scaled
#: integer can cost.
COORD_TOLERANCE = 0.5 / COORD_SCALE
SPEED_TOLERANCE = 0.5 / SPEED_SCALE
TRACK_TOLERANCE = 0.5 / TRACK_SCALE

SEEDS = range(30)


def assert_round_trips(track: tuple[TrackSample, ...]) -> None:
    """Every field survives a pack/unpack within its documented tolerance."""
    decoded = unpack_track(pack_track(track))

    assert len(decoded) == len(track)
    for original, restored in zip(track, decoded, strict=True):
        assert restored.ts_ms == original.ts_ms
        assert restored.position_source == original.position_source
        assert restored.altitude_ft == original.altitude_ft
        assert abs(restored.latitude - original.latitude) <= COORD_TOLERANCE
        assert abs(restored.longitude - original.longitude) <= COORD_TOLERANCE
        assert (restored.ground_speed_kt is None) == (original.ground_speed_kt is None)
        if original.ground_speed_kt is not None and restored.ground_speed_kt is not None:
            assert abs(restored.ground_speed_kt - original.ground_speed_kt) <= SPEED_TOLERANCE
        assert (restored.track_deg is None) == (original.track_deg is None)
        if original.track_deg is not None and restored.track_deg is not None:
            assert abs(restored.track_deg - original.track_deg) <= TRACK_TOLERANCE


# ------------------------------------------------------------- round trips


def test_random_tracks_round_trip_within_the_documented_tolerances() -> None:
    for seed in SEEDS:
        assert_round_trips(random_track(random.Random(seed), 120))


def test_a_single_point_track_round_trips() -> None:
    # The shortest real track: an aircraft heard once, with one position.
    assert_round_trips(straight_leg(1))


def test_absent_optional_fields_stay_absent() -> None:
    # "The decoder did not report this" is a fact worth keeping (SPEC §39);
    # flattening it to zero would invent a stationary aircraft at sea level.
    track = (
        sample(at_ms=BASE_MS, lat=47.4, lon=-122.3, altitude_ft=None),
        sample(at_ms=BASE_MS + 1_000, lat=47.5, lon=-122.2, ground_speed_kt=None),
        sample(at_ms=BASE_MS + 2_000, lat=47.6, lon=-122.1, track_deg=None),
    )

    decoded = unpack_track(pack_track(track))

    assert decoded[0].altitude_ft is None
    assert decoded[1].ground_speed_kt is None
    assert decoded[2].track_deg is None
    assert_round_trips(track)


def test_every_position_source_round_trips() -> None:
    for index, source in enumerate(("adsb", "mlat", "none", "other")):
        track = (sample(at_ms=BASE_MS + index, lat=47.4, lon=-122.3, source=source),)

        assert unpack_track(pack_track(track))[0].position_source == source


def test_negative_altitudes_and_southern_hemisphere_positions_round_trip() -> None:
    # Below-sea-level fields exist, and so does the other side of both the
    # equator and the prime meridian; the deltas are signed for a reason.
    track = (
        sample(at_ms=BASE_MS, lat=-33.94, lon=151.18, altitude_ft=-150),
        sample(at_ms=BASE_MS + 5_000, lat=-33.80, lon=151.30, altitude_ft=-1_200),
    )

    assert_round_trips(track)


def test_a_track_spanning_hours_round_trips() -> None:
    # Time deltas are int32 milliseconds, which covers gaps far longer than a
    # sighting: a four-hour loiter with sparse fixes must survive intact.
    track = tuple(
        sample(at_ms=BASE_MS + index * 900_000, lat=47.4 + index * 0.1, lon=-122.3)
        for index in range(16)
    )

    assert_round_trips(track)


def test_the_base_is_the_first_point_and_its_delta_is_zero() -> None:
    track = straight_leg(4)

    packed = pack_track(track)

    assert packed.started_ms == track[0].ts_ms
    assert packed.encoding_version == ENCODING_VERSION
    assert packed.point_count == 4
    assert unpack_track(packed)[0].ts_ms == track[0].ts_ms


# ------------------------------------------------------------------- size


def test_the_encoding_costs_a_fixed_twenty_one_bytes_a_point() -> None:
    # The budget DATA_MODEL §9 sizes the multi-year database with.
    for count in (1, 10, 60, 200):
        packed = pack_track(straight_leg(count))

        assert len(packed.points_blob) == HEADER_BYTES + count * POINT_BYTES


def test_a_typical_simplified_track_fits_the_two_kilobyte_ceiling() -> None:
    # The roadmap's acceptance criterion, stated against the point count
    # DATA_MODEL §2.4 predicts for a typical transit (40-80 points).
    packed = pack_track(straight_leg(80))

    assert len(packed.points_blob) <= 2_048


# -------------------------------------------------------------- refusals


def test_an_unknown_encoding_version_is_refused() -> None:
    # The forward-compatibility contract: a track written by a newer FlightSite
    # is reported, never decoded by guessing at its layout.
    packed = pack_track(straight_leg(3))
    future = bytearray(packed.points_blob)
    future[0] = 2

    with pytest.raises(UnsupportedTrackEncoding, match="version 2"):
        unpack_track(packed._replace(encoding_version=2, points_blob=bytes(future)))


def test_a_row_that_contradicts_its_own_blob_is_refused() -> None:
    packed = pack_track(straight_leg(3))

    with pytest.raises(UnsupportedTrackEncoding, match="contradicts its row"):
        unpack_track(packed._replace(point_count=4))


def test_a_truncated_blob_is_refused() -> None:
    packed = pack_track(straight_leg(3))

    with pytest.raises(UnsupportedTrackEncoding, match="should be"):
        unpack_track(packed._replace(points_blob=packed.points_blob[:-4]))


def test_a_blob_shorter_than_its_header_is_refused() -> None:
    with pytest.raises(UnsupportedTrackEncoding, match="shorter than"):
        unpack_track(
            PackedTrack(
                encoding_version=ENCODING_VERSION,
                point_count=0,
                started_ms=BASE_MS,
                points_blob=b"\x01",
            )
        )


def test_an_unknown_position_source_code_is_refused() -> None:
    # Codes are appended, never renumbered, so an unrecognized one means the
    # blob came from a build this one does not understand.
    packed = pack_track(straight_leg(1))
    tampered = bytearray(packed.points_blob)
    tampered[-1] = 9

    with pytest.raises(UnsupportedTrackEncoding, match="position source code"):
        unpack_track(packed._replace(points_blob=bytes(tampered)))


def test_packing_an_empty_track_is_refused() -> None:
    # A sighting with no points stores no row at all; an empty blob would be a
    # row asserting a path that does not exist.
    with pytest.raises(ValueError, match="empty track"):
        pack_track(())


def test_packing_out_of_order_timestamps_is_refused() -> None:
    track = (
        sample(at_ms=BASE_MS + 1_000, lat=47.4, lon=-122.3),
        sample(at_ms=BASE_MS, lat=47.5, lon=-122.2),
    )

    with pytest.raises(ValueError, match="strictly increase"):
        pack_track(track)


def test_packing_duplicate_timestamps_is_refused() -> None:
    track = (
        sample(at_ms=BASE_MS, lat=47.4, lon=-122.3),
        sample(at_ms=BASE_MS, lat=47.5, lon=-122.2),
    )

    with pytest.raises(ValueError, match="strictly increase"):
        pack_track(track)


# -------------------------------------------------------------- clamping


def test_an_absurd_ground_speed_is_clamped_rather_than_rejected() -> None:
    # A decoder reporting nine thousand knots is wrong; losing the whole
    # sighting's path over it would be worse.
    track = (sample(at_ms=BASE_MS, lat=47.4, lon=-122.3, ground_speed_kt=9_000.0),)

    restored = unpack_track(pack_track(track))[0]

    assert restored.ground_speed_kt is not None
    assert restored.ground_speed_kt == pytest.approx(6_553.4, rel=1e-6)


def test_a_negative_ground_speed_is_clamped_to_zero() -> None:
    track = (sample(at_ms=BASE_MS, lat=47.4, lon=-122.3, ground_speed_kt=-5.0),)

    assert unpack_track(pack_track(track))[0].ground_speed_kt == 0.0


def test_the_layout_is_the_documented_one() -> None:
    """A byte-level check, so the on-disk format cannot drift unnoticed.

    Everything else here is a round trip, which a matching pair of encoder and
    decoder bugs would pass. This reads the bytes the way a future version — or
    a forensic tool — would have to.
    """
    track = (
        sample(at_ms=BASE_MS, lat=47.5, lon=-122.25, altitude_ft=31_000, source="mlat"),
        sample(at_ms=BASE_MS + 2_500, lat=47.51, lon=-122.25, altitude_ft=None),
    )

    blob = pack_track(track).points_blob

    version, count = struct.unpack_from("<BI", blob, 0)
    first = struct.unpack_from("<iiiiHHB", blob, HEADER_BYTES)
    second = struct.unpack_from("<iiiiHHB", blob, HEADER_BYTES + POINT_BYTES)

    assert (version, count) == (1, 2)
    assert first[0] == 0  # the first point's delta is against the row's base
    assert first[1] == round(47.5 * COORD_SCALE)
    assert first[2] == round(-122.25 * COORD_SCALE)
    assert first[3] == 31_000
    assert first[5] == round(90.0 * TRACK_SCALE)
    assert first[6] == 1  # mlat
    assert second[0] == 2_500
    assert second[1] == round(0.01 * COORD_SCALE)
    assert second[2] == 0  # unchanged longitude costs a zero delta
    assert second[3] == -(2**31)  # the no-altitude sentinel
