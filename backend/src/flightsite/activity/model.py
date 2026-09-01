"""The activity vocabulary, its values, and the keys that make it exactly-once.

Two vocabularies, and which one wins
------------------------------------

``docs/API.md`` §3.9 and ``docs/DATA_MODEL.md`` §5 both enumerate event types,
and they do not agree word for word: §5's column comment says
``first_aircraft``/``metadata_update``/``alert``, §3.9 publishes
``first_ever_aircraft``/``metadata_updated``/``alert_triggered`` and attributes
the list to SPEC §55. :class:`ActivityEventType` spells §3.9's names, because
those are the strings a client sees and the ones the published OpenAPI document
has to match; §5's list is a comment on a column that deliberately carries no
``CHECK``, which is what "leave the vocabulary open" means in practice. The
enum therefore also carries the values *no producer in this slice emits* —
:attr:`ActivityEventType.ALERT_TRIGGERED` and
:attr:`ActivityEventType.EMERGENCY_SQUAWK` are phase 6's (roadmap slice 039),
and §5 reserves ``maintenance_issue`` and ``data_reset`` beyond them — so that
adding a producer later is a producer, not a schema change.

Milestones versus events
------------------------

§5 draws the line and this module keeps it:

* A **milestone** is something that can happen only once for this receiver —
  the first military aircraft ever, the first example of a type, the 1,000th
  unique airframe. It gets a ``milestones`` row whose primary key *is* the
  fire-once guarantee.
* A **rolling record** — the furthest detection ever, the busiest day, the
  highest simultaneous count, the longest sighting — can be beaten, so it has
  no natural key and lives in ``lifetime_stats`` (§6.4) or is re-derived from
  ``sightings``.

Both announce themselves as activity events, and both use the *specific* §3.9
word where one exists: a new type is announced as ``new_type`` and a new
furthest detection as ``range_record``, even though the first is also a
milestone row and the second is also a record. ``milestone`` is the word for
the achievements §3.9 gives no other name — the first military aircraft and
the unique-airframe thresholds.

Dedupe keys
-----------

:func:`dedupe_key` builds ``activity_events.dedupe_key``, and every builder
below derives it from **stored state** rather than from the moment a producer
happened to run. ``first_ever_aircraft:ae1463`` names an airframe;
``new_type:B738`` names a type; ``range_record:412.750`` names a distance;
``receiver_record:longest_sighting:9021`` names the sighting that holds the
record. Re-observing the same fact after a restart, during a catch-up scan or
on a replayed event therefore recomputes the same string, the ``UNIQUE`` index
rejects the second insert, and the roadmap's *"fixture scenarios emit exactly
the expected events (no duplicates on restart/replay)"* is a property of the
schema rather than of a producer remembering what it did.

Floats are formatted through :func:`_number` at fixed precision for exactly
that reason: ``repr(412.75)`` is stable in CPython, but a key that depended on
it would be depending on a formatting decision rather than on a value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

#: Round numbers of unique airframes worth a milestone (SPEC §54 names the
#: 1,000th; the smaller and larger ones are the same idea at the scales a real
#: install passes through). Ascending, and each fires exactly once because its
#: milestone key names the threshold.
UNIQUE_AIRCRAFT_THRESHOLDS: Final[tuple[int, ...]] = (
    100,
    500,
    1_000,
    2_500,
    5_000,
    10_000,
    25_000,
    50_000,
    100_000,
)

#: Milestone key for the first military airframe ever heard (SPEC §54).
MILESTONE_FIRST_MILITARY: Final = "first_military"

#: Prefix of the per-type milestone keys §5 names (``first_type_B52``).
MILESTONE_FIRST_TYPE_PREFIX: Final = "first_type_"

#: Prefix of the unique-airframe threshold keys (``unique_aircraft_1000``).
MILESTONE_UNIQUE_AIRCRAFT_PREFIX: Final = "unique_aircraft_"


class ActivityEventType(StrEnum):
    """``activity_events.type`` — the ``docs/API.md`` §3.9 / SPEC §55 list."""

    #: Phase 6 (roadmap slice 039). Declared here so the vocabulary is one list.
    ALERT_TRIGGERED = "alert_triggered"
    FIRST_EVER_AIRCRAFT = "first_ever_aircraft"
    NEW_TYPE = "new_type"
    RANGE_RECORD = "range_record"
    RECEIVER_RECORD = "receiver_record"
    #: Phase 6, alongside :attr:`ALERT_TRIGGERED`.
    EMERGENCY_SQUAWK = "emergency_squawk"
    RECEIVER_OFFLINE = "receiver_offline"
    RECEIVER_RESTORED = "receiver_restored"
    METADATA_UPDATED = "metadata_updated"
    MILESTONE = "milestone"


class Severity(StrEnum):
    """``docs/API.md`` §2.8's four-value ladder, shared with the alert tables."""

    INFO = "info"
    INTERESTING = "interesting"
    HIGH = "high"
    CRITICAL = "critical"


class RecordKind(StrEnum):
    """Which rolling receiver record a ``receiver_record`` event describes.

    ``range_record`` has its own §3.9 event type and so is deliberately absent:
    a furthest-detection record is announced as
    :attr:`ActivityEventType.RANGE_RECORD`, not as a ``receiver_record`` with a
    kind. These three are the records §3.9 gives no separate word to.
    """

    MAX_SIMULTANEOUS = "max_simultaneous"
    BUSIEST_DAY = "busiest_day"
    LONGEST_SIGHTING = "longest_sighting"


def first_type_milestone_key(type_code: str) -> str:
    """Milestone key for the first example of ``type_code`` (``first_type_B52``)."""
    return f"{MILESTONE_FIRST_TYPE_PREFIX}{type_code}"


def unique_aircraft_milestone_key(threshold: int) -> str:
    """Milestone key for the ``threshold``-th unique airframe."""
    return f"{MILESTONE_UNIQUE_AIRCRAFT_PREFIX}{threshold}"


def crossed_threshold(rank: int) -> int | None:
    """The unique-airframe threshold an airframe of rank ``rank`` reaches.

    Exact equality rather than a range, because every airframe's first sighting
    is examined exactly once: the service's catch-up scan walks ``sightings``
    by id, so no rank is ever skipped, however long the service was stopped
    for. The milestone key names the threshold, so even a rank observed twice
    fires once.
    """
    return rank if rank in UNIQUE_AIRCRAFT_THRESHOLDS else None


def _number(value: float) -> str:
    """Format a float for a dedupe key at fixed precision.

    Pinning the precision is what makes the key depend on the *value* rather
    than on a repr, which is the whole point of deriving it from stored state.

    Three decimals — for the one float-keyed record, the furthest detection,
    about two metres — is deliberately coarser than the stored value. A record
    beaten by less than that reads as the same record and is not announced
    again, which is the right answer twice over: two metres is inside the noise
    of a position report, and a feed that reported it would be reporting
    rounding.
    """
    return f"{value:.3f}"


def dedupe_key(*parts: object) -> str:
    """Join ``parts`` into a ``dedupe_key``, formatting floats stably."""
    return ":".join(_number(part) if isinstance(part, float) else str(part) for part in parts)


@dataclass(frozen=True, slots=True)
class NewActivityEvent:
    """One event a producer wants recorded, before it has an id.

    ``dedupe_key`` is mandatory here even though the column is nullable: every
    producer in this slice has a natural key, and making it a required argument
    is what stops a future one from quietly acquiring at-least-once semantics.
    """

    type: ActivityEventType
    ts_ms: int
    dedupe_key: str
    severity: Severity = Severity.INFO
    aircraft_id: int | None = None
    sighting_id: int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NewMilestone:
    """One milestone a producer wants recorded, keyed by its natural key."""

    key: str
    achieved_ms: int
    aircraft_id: int | None = None
    value_num: float | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActivityBatch:
    """What one detection pass concluded: events to record, milestones to claim.

    Producers return these and the service merges them, so the pure detection
    layer never has to know that two producers can both want to write in the
    same transaction.
    """

    events: tuple[NewActivityEvent, ...] = ()
    milestones: tuple[NewMilestone, ...] = ()

    @property
    def empty(self) -> bool:
        """True when there is nothing to write."""
        return not self.events and not self.milestones


@dataclass(frozen=True, slots=True)
class StoredActivityEvent:
    """One recorded event, as the feed and the WebSocket frame report it.

    ``icao24`` is joined from ``aircraft`` rather than duplicated into the
    payload: it is the identity a client links on, and reading it from the
    airframe row means a metadata correction can never leave the feed naming an
    address the aircraft page does not know.
    """

    id: int
    ts_ms: int
    type: str
    severity: str
    aircraft_id: int | None = None
    icao24: str | None = None
    sighting_id: int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "MILESTONE_FIRST_MILITARY",
    "MILESTONE_FIRST_TYPE_PREFIX",
    "MILESTONE_UNIQUE_AIRCRAFT_PREFIX",
    "UNIQUE_AIRCRAFT_THRESHOLDS",
    "ActivityBatch",
    "ActivityEventType",
    "NewActivityEvent",
    "NewMilestone",
    "RecordKind",
    "Severity",
    "StoredActivityEvent",
    "crossed_threshold",
    "dedupe_key",
    "first_type_milestone_key",
    "unique_aircraft_milestone_key",
]
