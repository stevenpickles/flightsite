"""Storage-time helpers.

Every instant FlightSite stores is a UTC Unix-epoch value in **milliseconds**
held in an ``INTEGER`` column whose name ends in ``_ms``
(``docs/DATA_MODEL.md`` §Conventions, SPEC §15). SQLite has no datetime type,
so this convention — rather than a text encoding — is what makes stored
instants compact, indexable, sortable, and free of timezone ambiguity.

Local-time presentation (receiver-local day bucketing, UI rendering) is always
a conversion applied *after* reading, never a storage format.

Which zone that conversion uses
-------------------------------

The receiver's zone is a *setting*, and ``PUT /api/internal/config`` replaces
``app.state.settings`` on a running app — so a component that captured
``ZoneInfo(settings.timezone)`` at construction keeps bucketing days in a zone
the user has since changed. That is not a theoretical hazard: on a fresh
install the setup wizard writes the timezone a minute *after* the backend has
booted, so everything that captured it holds the ``UTC`` default for the life
of the process while every read resolves the live value (issue #205, findings
R1-02 / R3-01).

:data:`TimezoneSource` and :func:`resolve_zone` are the seam that removes the
hazard: a component is handed *where to get the zone* rather than a zone, and
resolves it at the moment it needs one. A plain name or :class:`ZoneInfo` is
still accepted, because a test that wants one fixed zone should not have to
write a closure to say so.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

MS_PER_SECOND = 1000

#: Where a component gets the receiver's IANA zone. Either the zone itself —
#: a tz database name or a :class:`~zoneinfo.ZoneInfo` — or a probe that reads
#: it late, which is what a long-lived service takes so a timezone change
#: applies without a restart (``flightsite.app._receiver_timezone``).
TimezoneSource = str | ZoneInfo | Callable[[], str | ZoneInfo]


def resolve_zone(source: TimezoneSource) -> ZoneInfo:
    """The receiver's zone as of *now*, from whichever form ``source`` takes.

    Cheap enough to call on every bucketing pass: :class:`~zoneinfo.ZoneInfo`
    interns its instances by key, so resolving a name that has not changed
    costs a dictionary lookup rather than a tz database read.

    The zone name is validated where it enters the process
    (``flightsite.config.models.Settings._known_timezone``), so a probe over
    live settings cannot hand this an unknown name — the same assumption the
    read path makes in :class:`~flightsite.api.context.LiveApiContext`.
    """
    zone = source() if callable(source) else source
    return zone if isinstance(zone, ZoneInfo) else ZoneInfo(zone)


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
