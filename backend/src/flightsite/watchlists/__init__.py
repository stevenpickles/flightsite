"""User-defined watchlists: CRUD, storage, and live matching (SPEC §42, roadmap slice 037).

Reading order:

* :mod:`~flightsite.watchlists.vocabulary` — the five entry kinds, and the
  normalization/validation rule each one's ``value`` is held to.
* :mod:`~flightsite.watchlists.model` — the plain domain records that cross
  this package's boundary.
* :mod:`~flightsite.watchlists.errors` — the domain errors CRUD operations raise.
* :mod:`~flightsite.watchlists.repository` — every SQL statement.
* :mod:`~flightsite.watchlists.matcher` — the in-memory match index that keeps
  SQLite off the live aircraft path; see its module docstring for the design
  (piggy-backing on :class:`~flightsite.metadata.cache.MetadataCache`'s own
  population pipeline rather than a second live-event subscription).
* :mod:`~flightsite.watchlists.service` — the one object the application
  wires up: CRUD plus the index rebuild that keeps it current.
* :mod:`~flightsite.watchlists.schemas` — the internal API's request bodies.

Out of scope for this slice (SPEC §42, roadmap slice 037's ``out_of_scope``):
alert rules that *act* on a match (roadmap slice 038, which reads
:class:`~flightsite.watchlists.matcher.WatchlistMatcher` the same way this
slice's own aircraft payload does) and free-form aircraft notes/metadata
overrides (a distinct, not-yet-scheduled feature).
"""

from __future__ import annotations

from flightsite.watchlists.errors import (
    DuplicateEntryError,
    DuplicateWatchlistNameError,
    WatchlistError,
    WatchlistNotFoundError,
)
from flightsite.watchlists.matcher import WatchlistIndex, WatchlistMatcher
from flightsite.watchlists.model import WatchlistEntryRecord, WatchlistRecord
from flightsite.watchlists.repository import WatchlistRepository
from flightsite.watchlists.schemas import (
    WatchlistCreateRequest,
    WatchlistEntryCreateRequest,
    WatchlistUpdateRequest,
)
from flightsite.watchlists.service import ClockFn, WatchlistService
from flightsite.watchlists.vocabulary import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_VALUE_LENGTH,
    VALID_CATEGORY_VALUES,
    WatchlistEntryKind,
    WatchlistValueError,
)

__all__ = [
    "MAX_DESCRIPTION_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_NOTE_LENGTH",
    "MAX_VALUE_LENGTH",
    "VALID_CATEGORY_VALUES",
    "ClockFn",
    "DuplicateEntryError",
    "DuplicateWatchlistNameError",
    "WatchlistCreateRequest",
    "WatchlistEntryCreateRequest",
    "WatchlistEntryKind",
    "WatchlistEntryRecord",
    "WatchlistError",
    "WatchlistIndex",
    "WatchlistMatcher",
    "WatchlistNotFoundError",
    "WatchlistRecord",
    "WatchlistRepository",
    "WatchlistService",
    "WatchlistUpdateRequest",
    "WatchlistValueError",
]
