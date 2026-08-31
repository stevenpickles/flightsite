"""Storage-time helpers.

Every instant FlightSite stores is a UTC Unix-epoch value in **milliseconds**
held in an ``INTEGER`` column whose name ends in ``_ms``
(``docs/DATA_MODEL.md`` §Conventions, SPEC §15). SQLite has no datetime type,
so this convention — rather than a text encoding — is what makes stored
instants compact, indexable, sortable, and free of timezone ambiguity.

Local-time presentation (receiver-local day bucketing, UI rendering) is always
a conversion applied *after* reading, never a storage format.
"""

from __future__ import annotations

from datetime import UTC, datetime

MS_PER_SECOND = 1000


def utc_now_ms() -> int:
    """Current UTC time as integer Unix epoch milliseconds."""
    return int(datetime.now(UTC).timestamp() * MS_PER_SECOND)


def to_epoch_ms(moment: datetime) -> int:
    """Convert an aware :class:`datetime` to integer Unix epoch milliseconds.

    Raises:
        ValueError: if ``moment`` is naive. Storing a naive datetime would
            silently adopt the host's local zone, which is exactly the
            ambiguity the epoch-ms convention exists to remove.
    """
    if moment.tzinfo is None:
        raise ValueError("refusing to store a naive datetime; timestamps must be timezone-aware")
    return int(moment.timestamp() * MS_PER_SECOND)


def from_epoch_ms(epoch_ms: int) -> datetime:
    """Convert integer Unix epoch milliseconds to an aware UTC :class:`datetime`."""
    return datetime.fromtimestamp(epoch_ms / MS_PER_SECOND, tz=UTC)
