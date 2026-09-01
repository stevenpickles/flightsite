"""The capped, ordered current track."""

from __future__ import annotations

from datetime import timedelta

import pytest

from flightsite.live.track import DEFAULT_TRACK_CAPACITY, CurrentTrack, TrackPoint

from .conftest import BASE_TIME


def point(offset_s: float, latitude: float, longitude: float = -122.0) -> TrackPoint:
    return TrackPoint(
        timestamp=BASE_TIME + timedelta(seconds=offset_s),
        latitude=latitude,
        longitude=longitude,
        position_source="adsb",
        altitude_ft=25_000.0,
    )


def test_the_default_capacity_is_four_hours_at_one_hertz() -> None:
    # The documented bound; changing it is a memory-budget decision, not an
    # incidental tweak.
    assert DEFAULT_TRACK_CAPACITY == 4 * 60 * 60


def test_points_are_kept_in_arrival_order() -> None:
    track = CurrentTrack()
    for index in range(5):
        track.append(point(index, 47.0 + index))

    assert [p.latitude for p in track.points()] == [47.0, 48.0, 49.0, 50.0, 51.0]
    assert len(track) == 5


def test_a_repeated_position_is_not_appended() -> None:
    # A decoder re-serves the last known position on every poll; a parked
    # aircraft must not consume its whole capacity standing still.
    track = CurrentTrack()
    track.append(point(0, 47.0))

    appended = track.append(point(1, 47.0))

    assert appended is False
    assert len(track) == 1


def test_a_moved_aircraft_appends_again_after_a_repeat() -> None:
    track = CurrentTrack()
    track.append(point(0, 47.0))
    track.append(point(1, 47.0))

    assert track.append(point(2, 47.1)) is True
    assert len(track) == 2


def test_an_out_of_order_point_is_rejected() -> None:
    track = CurrentTrack()
    track.append(point(10, 47.0))

    assert track.append(point(5, 48.0)) is False
    assert track.latest is not None
    assert track.latest.latitude == 47.0


def test_the_cap_evicts_the_oldest_and_counts_what_it_dropped() -> None:
    track = CurrentTrack(capacity=3)
    for index in range(5):
        track.append(point(index, 47.0 + index))

    assert [p.latitude for p in track.points()] == [49.0, 50.0, 51.0]
    assert track.dropped == 2
    assert track.capacity == 3


def test_nothing_is_dropped_before_the_cap_is_reached() -> None:
    track = CurrentTrack(capacity=3)
    track.append(point(0, 47.0))

    assert track.dropped == 0


def test_points_returns_a_stable_copy() -> None:
    track = CurrentTrack()
    track.append(point(0, 47.0))
    snapshot = track.points()

    track.append(point(1, 48.0))

    assert len(snapshot) == 1
    assert len(track.points()) == 2


def test_a_track_iterates_oldest_first() -> None:
    track = CurrentTrack()
    track.append(point(0, 47.0))
    track.append(point(1, 47.1))

    assert [round(p.latitude, 1) for p in track] == [47.0, 47.1]


def test_an_empty_track_has_no_latest_point() -> None:
    assert CurrentTrack().latest is None


def test_a_zero_capacity_track_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1 point"):
        CurrentTrack(capacity=0)


def test_points_since_returns_only_what_is_newer() -> None:
    # The tail query sighting checkpointing polls once per observation across
    # the whole live set: it must answer "what have I not seen" and nothing more.
    track = CurrentTrack()
    for index in range(5):
        track.append(point(index, 47.0 + index))

    tail = track.points_since(BASE_TIME + timedelta(seconds=2))

    assert [p.latitude for p in tail] == [50.0, 51.0]


def test_points_since_none_returns_the_whole_track() -> None:
    # The first harvest of a sighting has no high-water mark yet.
    track = CurrentTrack()
    track.append(point(0, 47.0))
    track.append(point(1, 48.0))

    assert len(track.points_since(None)) == 2


def test_points_since_the_newest_point_returns_nothing() -> None:
    # Strictly newer: the boundary point has already been taken.
    track = CurrentTrack()
    track.append(point(0, 47.0))

    assert track.points_since(BASE_TIME) == ()


def test_points_since_an_instant_after_the_track_returns_nothing() -> None:
    track = CurrentTrack()
    track.append(point(0, 47.0))

    assert track.points_since(BASE_TIME + timedelta(hours=1)) == ()


def test_points_since_is_oldest_first_like_every_other_view() -> None:
    track = CurrentTrack()
    for index in range(4):
        track.append(point(index, 47.0 + index))

    tail = track.points_since(BASE_TIME - timedelta(seconds=1))

    assert [p.timestamp for p in tail] == sorted(p.timestamp for p in tail)
    assert tail == track.points()
