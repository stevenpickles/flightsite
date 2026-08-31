"""Live aircraft state: the in-memory answer to "what is up there now".

Module map:

========================================== =====================================
Module                                     Responsibility
========================================== =====================================
:mod:`~flightsite.live.geo`                great-circle distance and bearing
:mod:`~flightsite.live.track`              capped per-aircraft current track
:mod:`~flightsite.live.aircraft`           the live record, merge and provenance
:mod:`~flightsite.live.events`             domain events + bounded dispatcher
:mod:`~flightsite.live.store`              the registry and its lifecycle sweep
========================================== =====================================

Nothing in this package touches the database. The live path is memory-only
(``docs/ARCHITECTURE.md`` §3.1); persistence, sighting lifecycle and alerting
are *consumers* of :class:`~flightsite.live.events.EventDispatcher`, added by
later slices.
"""

from __future__ import annotations

from flightsite.live.aircraft import (
    AIRBORNE_INFERENCE_ALTITUDE_FT,
    CHANGE_TRACKED_FIELDS,
    GroundState,
    LiveAircraft,
    LiveState,
    Provenance,
    appear,
    mark_stale,
    merge,
)
from flightsite.live.events import (
    DEFAULT_QUEUE_SIZE,
    AircraftAppeared,
    AircraftRemoved,
    AircraftStale,
    AircraftUpdated,
    EventDispatcher,
    EventSubscription,
    LiveEvent,
)
from flightsite.live.geo import EARTH_RADIUS_NM, bearing_deg, distance_and_bearing, distance_nm
from flightsite.live.store import (
    DEFAULT_REMOVE_S,
    DEFAULT_STALE_S,
    DEFAULT_SWEEP_INTERVAL_S,
    LiveCounts,
    LiveStore,
    MonotonicClock,
)
from flightsite.live.track import DEFAULT_TRACK_CAPACITY, CurrentTrack, TrackPoint

__all__ = [
    "AIRBORNE_INFERENCE_ALTITUDE_FT",
    "CHANGE_TRACKED_FIELDS",
    "DEFAULT_QUEUE_SIZE",
    "DEFAULT_REMOVE_S",
    "DEFAULT_STALE_S",
    "DEFAULT_SWEEP_INTERVAL_S",
    "DEFAULT_TRACK_CAPACITY",
    "EARTH_RADIUS_NM",
    "AircraftAppeared",
    "AircraftRemoved",
    "AircraftStale",
    "AircraftUpdated",
    "CurrentTrack",
    "EventDispatcher",
    "EventSubscription",
    "GroundState",
    "LiveAircraft",
    "LiveCounts",
    "LiveEvent",
    "LiveState",
    "LiveStore",
    "MonotonicClock",
    "Provenance",
    "TrackPoint",
    "appear",
    "bearing_deg",
    "distance_and_bearing",
    "distance_nm",
    "mark_stale",
    "merge",
]
