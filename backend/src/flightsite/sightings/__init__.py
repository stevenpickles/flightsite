"""Aircraft and sighting persistence: the write-behind worker and its schema.

Module map:

========================================== =====================================
Module                                     Responsibility
========================================== =====================================
:mod:`~flightsite.sightings.vocabulary`    canonical closure/emergency values
:mod:`~flightsite.sightings.state`         per-sighting in-memory accumulator
:mod:`~flightsite.sightings.repository`    SQL for ``aircraft`` and ``sightings``
:mod:`~flightsite.sightings.worker`        the single-writer persistence worker
========================================== =====================================

This package is the *only* writer to the FlightSite database (ADR-0001,
ADR-0008) and is a pure consumer of the live event stream: nothing in
:mod:`flightsite.live` or :mod:`flightsite.ingest` depends on it, so a stalled
database cannot reach back and delay a decoder poll.

Track storage and reception statistics (``sightings/tracks.py``, slice 052) and
unclean-shutdown recovery (``sightings/recovery.py``, slice 053) extend this
package later; their columns already exist on the sighting row so that its
shape does not change again.
"""

from __future__ import annotations

from flightsite.sightings.repository import OpenSightingRow, SightingIds, SightingRepository
from flightsite.sightings.state import ActiveSighting, open_from
from flightsite.sightings.vocabulary import EMERGENCY_SQUAWKS, ClosureReason
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
    "ActiveSighting",
    "ClosureReason",
    "CycleResult",
    "EpochClock",
    "OpenSightingRow",
    "PersistenceWorker",
    "SightingIds",
    "SightingRepository",
    "open_from",
]
