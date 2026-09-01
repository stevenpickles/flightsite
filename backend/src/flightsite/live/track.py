"""The in-memory current track of a live aircraft.

While an aircraft is in the live set, every position it reports is appended to
an ordered, full-resolution track. This is the raw material for three later
consumers: the map trail (slice 013), sighting track checkpointing (slice 052)
and the Douglas-Peucker simplification that packs a closed sighting's path
into one row ([ADR-0005](../../../../docs/adr/0005-track-checkpointing-and-simplification.md)).
Nothing here touches the database — the live path is memory-only
(``docs/ARCHITECTURE.md`` §3.1) — and the track is discarded when the aircraft
leaves the live set. Persisting it before that happens is slice 009's job,
which is why :class:`~flightsite.live.events.AircraftRemoved` carries the
aircraft (and therefore its track) rather than just an ICAO address.

Memory bound
------------

:data:`DEFAULT_TRACK_CAPACITY` caps a single aircraft's track at 14 400 points
— four hours at the 1 Hz position rate a decoder sustains for a strong ADS-B
target. The reasoning:

* **Why a cap at all.** Without one, a single aircraft parked in view (or a
  decoder emitting a stuck trackfile) grows without limit, and the <1 GB
  process budget (``docs/ARCHITECTURE.md`` §9) has no floor.
* **Why four hours.** An aircraft crossing a 250 nm display radius at 450 kt is
  in view for about 70 minutes end to end; four hours covers loitering
  traffic (survey, patrol, training circuits) with a wide margin, so the cap
  is a safety valve rather than a routine truncation.
* **What it costs.** A :class:`TrackPoint` and the objects it references come
  to roughly 250 bytes, so a track at the cap is about 3.5 MB. Typical live
  tracks are one to two orders of magnitude shorter than that. The *aggregate*
  bound across a large live set is not this cap's job: slice 009/052
  checkpoint track points to SQLite and truncate what they have persisted,
  which is what keeps a busy receiver's total resident track memory small.

The capacity is a constructor argument, so a deployment or a later slice can
tune it without editing this module. Eviction is FIFO — the oldest point goes
— and :attr:`CurrentTrack.dropped` counts what was evicted so a consumer can
tell "this is the whole track" from "this is the tail of the track".
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from flightsite.ingest import PositionSource

#: Maximum points retained per live aircraft: 4 h at 1 Hz. See module docstring.
DEFAULT_TRACK_CAPACITY: Final = 14_400


@dataclass(frozen=True, slots=True)
class TrackPoint:
    """One positioned observation, at the resolution the decoder reported it.

    ``timestamp`` is the decoder's own UTC clock for the observation, not
    FlightSite's wall clock: the decoder is the authority on when a position
    was received, and on a Pi with no RTC the two can differ substantially.

    ``position_source`` rides along per point because a single flight can move
    between ``adsb`` and ``mlat`` mid-track, and the distinction is
    safety-relevant display state that must survive into the persisted track
    (``docs/DATA_MODEL.md`` §8).
    """

    timestamp: datetime
    latitude: float
    longitude: float
    position_source: PositionSource
    altitude_ft: float | None = None
    ground_speed_kt: float | None = None
    track_deg: float | None = None


class CurrentTrack:
    """An ordered, capped, append-only track for one live aircraft.

    Ordering is enforced on append rather than assumed: a point is accepted
    only when it is strictly newer than the last one held. Decoders re-serve
    the same position on consecutive polls — the reported position simply ages
    rather than disappearing — and a restarted decoder can briefly hand back an
    older timestamp, so accepting everything would produce a track that is
    neither monotonic nor a record of movement.

    A point whose latitude and longitude are identical to the previous point's
    is also rejected. That is what keeps a parked or holding aircraft from
    consuming its whole capacity on a single stationary position, and it makes
    the track a record of *movement* — which is what the map trail draws and
    what simplification consumes.
    """

    __slots__ = ("_capacity", "_dropped", "_points")

    def __init__(self, capacity: int = DEFAULT_TRACK_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("track capacity must be at least 1 point")
        self._capacity = capacity
        self._points: deque[TrackPoint] = deque(maxlen=capacity)
        self._dropped = 0

    @property
    def capacity(self) -> int:
        """Maximum points retained before the oldest is evicted."""
        return self._capacity

    @property
    def dropped(self) -> int:
        """Points evicted by the capacity cap since this track was created."""
        return self._dropped

    @property
    def latest(self) -> TrackPoint | None:
        """The most recent point, or ``None`` while the track is empty."""
        return self._points[-1] if self._points else None

    def append(self, point: TrackPoint) -> bool:
        """Append ``point`` if it advances the track; report whether it did.

        Returns ``False`` for a point that is not strictly newer than the last
        one, or that repeats the last one's exact position — see the class
        docstring for why both are rejected.
        """
        last = self.latest
        if last is not None and (
            point.timestamp <= last.timestamp
            or (point.latitude == last.latitude and point.longitude == last.longitude)
        ):
            return False
        if len(self._points) == self._capacity:
            self._dropped += 1
        self._points.append(point)
        return True

    def points_since(self, moment: datetime | None) -> tuple[TrackPoint, ...]:
        """Points strictly newer than ``moment``, oldest first.

        ``None`` returns the whole track. A reverse scan, so a consumer polling
        for what it has not seen yet pays for the size of that tail rather than
        the size of the track: sighting checkpointing (slice 052) asks this
        question once per observation across the whole live set, and a copy of
        every point each time would put an O(track) cost on a 1 Hz path.
        """
        if moment is None:
            return tuple(self._points)
        tail: list[TrackPoint] = []
        for point in reversed(self._points):
            if point.timestamp <= moment:
                break
            tail.append(point)
        tail.reverse()
        return tuple(tail)

    def points(self) -> tuple[TrackPoint, ...]:
        """An immutable, oldest-first copy of the track.

        A copy rather than a view: the live track keeps growing underneath a
        reader, and a consumer serializing it (REST, WebSocket, a checkpoint
        batch) needs a stable sequence.
        """
        return tuple(self._points)

    def __len__(self) -> int:
        return len(self._points)

    def __iter__(self) -> Iterator[TrackPoint]:
        return iter(self._points)


__all__ = ["DEFAULT_TRACK_CAPACITY", "CurrentTrack", "TrackPoint"]
