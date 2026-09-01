"""Data reset actions (SPEC §73, roadmap slice 045).

Settings offers two destructive, explicitly-confirmed actions
(``docs/API.md`` §5, ``POST /api/internal/reset/...``):

``Clear Metadata Cache``
    :func:`~flightsite.reset.service.clear_metadata_cache` — deletes every
    imported aircraft-metadata row, the derived resolution/classification/
    operator tables, the route cache and the airports table, then
    invalidates the in-memory caches built from them. History (aircraft,
    sightings, analytics, activity) is untouched.

``Reset FlightSite Data``
    :func:`~flightsite.reset.marker.write_reset_marker` /
    :func:`~flightsite.reset.marker.apply_pending_reset` — mark-and-restart
    semantics. See :mod:`flightsite.reset.marker` for why a live re-init was
    rejected in favor of the same "stop first" posture
    ``docs/BACKUP.md`` gives restore.
"""

from __future__ import annotations

from flightsite.reset.marker import (
    RESET_MARKER_FILENAME,
    apply_pending_reset,
    marker_path,
    reset_pending,
    write_reset_marker,
)
from flightsite.reset.service import ClearMetadataResult, clear_metadata_cache

__all__ = [
    "RESET_MARKER_FILENAME",
    "ClearMetadataResult",
    "apply_pending_reset",
    "clear_metadata_cache",
    "marker_path",
    "reset_pending",
    "write_reset_marker",
]
