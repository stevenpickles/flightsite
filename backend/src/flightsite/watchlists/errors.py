"""Domain errors the watchlists package raises.

One flat hierarchy, mirroring :class:`flightsite.config.loader.ConfigError`:
the internal API's job is to turn each into the right HTTP status
(``docs/API.md`` §5), and a single ``isinstance`` chain does that more simply
than a caller re-deriving "was this a 404 or a 409" from a message string.
"""

from __future__ import annotations


class WatchlistError(Exception):
    """Base class for every watchlist domain error."""


class WatchlistNotFoundError(WatchlistError):
    """Raised for an operation naming a watchlist id that does not exist."""


class DuplicateWatchlistNameError(WatchlistError):
    """Raised when a watchlist name is already taken (``UNIQUE(name)``)."""


class DuplicateEntryError(WatchlistError):
    """Raised when an entry already exists on the watchlist for its kind and value."""


__all__ = [
    "DuplicateEntryError",
    "DuplicateWatchlistNameError",
    "WatchlistError",
    "WatchlistNotFoundError",
]
