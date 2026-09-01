"""Aircraft and sighting persistence: the write-behind worker and its schema.

Module map:

========================================== =====================================
Module                                     Responsibility
========================================== =====================================
:mod:`~flightsite.sightings.vocabulary`    canonical closure/event/source values
:mod:`~flightsite.sightings.tracks`        track samples, thinning, simplifying
:mod:`~flightsite.sightings.track_codec`   the packed track encoding + decoder
:mod:`~flightsite.sightings.state`         per-sighting in-memory accumulator
:mod:`~flightsite.sightings.repository`    SQL for the sighting-owned tables
:mod:`~flightsite.sightings.worker`        the single-writer persistence worker
========================================== =====================================

This package is the *only* writer to the FlightSite database (ADR-0001,
ADR-0008) and is a pure consumer of the live event stream: nothing in
:mod:`flightsite.live` or :mod:`flightsite.ingest` depends on it, so a stalled
database cannot reach back and delay a decoder poll.

Unclean-shutdown recovery (``sightings/recovery.py``, slice 053) extends this
package later, on the checkpoint rows slice 052 writes: an open sighting's path
is already durable to within one flush interval, so recovery is a matter of
closing the sighting from what is on disk rather than of reconstructing it.
"""

from __future__ import annotations

from flightsite.sightings.repository import (
    ClosedTrack,
    OpenSightingRow,
    SightingIds,
    SightingRepository,
)
from flightsite.sightings.state import ActiveSighting, CheckpointBatch, PendingEvent, open_from
from flightsite.sightings.track_codec import (
    ENCODING_VERSION,
    PackedTrack,
    UnsupportedTrackEncoding,
    pack_track,
    unpack_track,
)
from flightsite.sightings.tracks import (
    SIMPLIFY_ALTITUDE_FT,
    SIMPLIFY_EPSILON_DEG,
    TrackSample,
    from_track_point,
    simplify,
    thin_for_checkpoint,
)
from flightsite.sightings.vocabulary import (
    EMERGENCY_SQUAWKS,
    ClosureReason,
    PositionSourceCode,
    SightingEventType,
)
from flightsite.sightings.worker import (
    DEFAULT_CLOSE_S,
    DEFAULT_FLUSH_INTERVAL_S,
    DEFAULT_TICK_INTERVAL_S,
    CycleResult,
    EpochClock,
    PersistenceWorker,
)

__all__ = [
    "DEFAULT_CLOSE_S",
    "DEFAULT_FLUSH_INTERVAL_S",
    "DEFAULT_TICK_INTERVAL_S",
    "EMERGENCY_SQUAWKS",
    "ENCODING_VERSION",
    "SIMPLIFY_ALTITUDE_FT",
    "SIMPLIFY_EPSILON_DEG",
    "ActiveSighting",
    "CheckpointBatch",
    "ClosedTrack",
    "ClosureReason",
    "CycleResult",
    "EpochClock",
    "OpenSightingRow",
    "PackedTrack",
    "PendingEvent",
    "PersistenceWorker",
    "PositionSourceCode",
    "SightingEventType",
    "SightingIds",
    "SightingRepository",
    "TrackSample",
    "UnsupportedTrackEncoding",
    "from_track_point",
    "open_from",
    "pack_track",
    "simplify",
    "thin_for_checkpoint",
    "unpack_track",
]
