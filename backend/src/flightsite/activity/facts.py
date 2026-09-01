"""What a detection pass observed, as values the producers can reason about.

Everything in :mod:`flightsite.activity.producers` is a pure function of these
records, and :mod:`flightsite.activity.repository` is what fills them from
SQLite. That split is the point: "this fixture emits exactly these events and
no more" — the roadmap's acceptance criterion for this slice — becomes an
assertion about a function, checked in microseconds, instead of a drill against
a database.

The records are deliberately *conclusions* rather than raw rows.
:attr:`SightingObservation.first_ever` is the answer to "is this the airframe's
first sighting", not the minimum sighting id the caller must compare for
itself, because deciding it needs an indexed query and deciding it twice — once
to build the fact and once to use it — is how two callers come to disagree.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SightingObservation:
    """One committed sighting, with everything a producer needs to judge it.

    Built for the sightings a pass is looking at — the ones a committed worker
    cycle just opened or closed, plus whatever a catch-up scan found — never
    for history at large.
    """

    sighting_id: int
    aircraft_id: int
    icao24: str
    started_ms: int
    #: ``None`` while the sighting is still open.
    ended_ms: int | None = None
    duration_ms: int | None = None

    #: True when this row is the airframe's earliest sighting: the airframe was
    #: heard here for the first time ever.
    first_ever: bool = False
    #: 1-based position of this airframe among every airframe ever heard, in
    #: first-heard order. Meaningful only when :attr:`first_ever` is true.
    rank: int | None = None

    registration: str | None = None
    type_code: str | None = None
    model: str | None = None
    operator: str | None = None

    #: True when this airframe is the earliest-heard airframe of its type *and*
    #: this is its first sighting: the first example of a new type (SPEC §54).
    first_of_type: bool = False
    #: True when the airframe is classified military (SPEC §39).
    military: bool = False


@dataclass(frozen=True, slots=True)
class MilitaryFirst:
    """The earliest sighting of a military-classified airframe, if there is one.

    Queried rather than taken from the batch because classification arrives
    with a metadata import, which lands hours or days after the sighting it
    describes: the first military aircraft this receiver ever heard is very
    often one it heard before it knew what it was.
    """

    sighting_id: int
    aircraft_id: int
    icao24: str
    started_ms: int
    registration: str | None = None
    type_code: str | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True)
class ReceiverRecords:
    """The rolling receiver records, as ``lifetime_stats`` holds them (§6.4).

    Slice 033 owns and maintains every one of these values; this slice only
    watches them change. Reading them rather than recomputing them is what
    makes a record announcement agree with the Receiver page by construction.
    """

    max_range_nm: float | None = None
    max_range_at_ms: int | None = None
    max_range_icao24: str | None = None
    max_range_bearing_deg: float | None = None
    busiest_day: str | None = None
    busiest_day_count: float | None = None
    max_simultaneous: float | None = None


@dataclass(frozen=True, slots=True)
class LongestSighting:
    """The longest closed sighting ever — a rolling record, held in memory.

    SPEC §54 asks for the longest sighting, and ``docs/DATA_MODEL.md`` §5 gives
    it nowhere to live: the ``milestones`` table is for achievements that cannot
    be beaten, and ``lifetime_stats`` is slice 033's, maintained from receiver
    samples rather than from sightings. So this record is *derived* — one
    ``MAX`` over ``sightings`` at startup seeds it, and every sighting closed
    afterwards is compared against the value carried forward in memory.

    That is a deliberate trade. The scan happens once per boot rather than once
    per pass (``sightings`` has no index on ``duration_ms``, and a multi-year
    install must not scan it every few seconds), and the cost of it is that a
    record set while the service was stopped is adopted silently instead of
    announced. The record itself is never wrong, because the seed reads ground
    truth.
    """

    sighting_id: int
    duration_ms: int
    #: When the record-holding sighting ended, which is when the record was set.
    ended_ms: int


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """One source's result from a completed metadata import run (SPEC §27).

    Flattened out of :class:`~flightsite.metadata.importer.ImportRun` at the
    moment the listener fires, so the pass that writes the events does not have
    to hold a reference to a run object whose meaning is another package's.
    """

    source: str
    ok: bool
    finished_ms: int
    rows_imported: int = 0
    rows_rejected: int = 0
    dataset_version: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AlertMatchFact:
    """One alert match that was actually recorded (slice 038, SPEC §55).

    Handed to this service by :class:`flightsite.alerts.engine.AlertEngine`
    after its own transaction has committed, for exactly the rows that
    transaction *created* — the alert tables' unique indexes are what decide
    that, so a re-proposed match produces no fact and therefore no feed event.
    The dependency runs one way: ``alerts`` consumes this package, and nothing
    here knows what a rule is beyond its id, its name and the severity it
    fired at.

    The identity and position fields are carried rather than re-queried
    because SPEC §48 wants a notification to say *"callsign/tail, aircraft
    type, classification, altitude, distance, match reason"*, and the alert
    engine had every one of them in memory at the instant it matched. Reading
    them back later would be a second opinion about a moment that has passed.
    """

    match_id: int
    matched_ms: int
    severity: str
    reason: str
    aircraft_id: int
    sighting_id: int
    icao24: str
    #: ``None`` for a built-in match, which has no rule (SPEC §47).
    rule_id: int | None = None
    rule_name: str | None = None
    #: ``None`` for a rule match; a built-in detector's key otherwise.
    builtin_key: str | None = None
    #: The squawk that triggered a built-in emergency match, if any.
    squawk: str | None = None
    callsign: str | None = None
    registration: str | None = None
    type_code: str | None = None
    model: str | None = None
    operator: str | None = None
    distance_nm: float | None = None
    altitude_ft: float | None = None
    military: bool = False
    government: bool = False
    law_enforcement: bool = False

    @property
    def emergency(self) -> bool:
        """True when this match came from a built-in rather than a rule.

        The two get different event types: SPEC §55 lists ``alert triggered``
        and ``emergency squawk`` separately, and SPEC §47 wants the emergency
        prominent rather than one entry among the alerts.
        """
        return self.builtin_key is not None


@dataclass(frozen=True, slots=True)
class HealthEpisode:
    """A decoder connection transition that has survived the debounce window.

    ``offline`` is the *announced* state, not the adapter's instantaneous one:
    :class:`~flightsite.ingest.health.HealthState.DEGRADED` is explicitly "polls
    are failing but not often enough to call the decoder gone", so it never
    produces an episode of its own — it simply leaves the announced state where
    it was until the tracker commits to ``connected`` or ``down``.
    """

    offline: bool
    #: When the state this episode announces was *first* observed — the moment
    #: the decoder actually went away, not the moment the debounce expired.
    at_ms: int
    #: How long the previous state lasted, for a restore's "back after N".
    previous_duration_ms: int | None = None
    #: Short reason from the adapter, for an outage. Never a secret: decoder
    #: endpoints carry no credentials (:mod:`flightsite.ingest.health`).
    error: str | None = None


__all__ = [
    "AlertMatchFact",
    "HealthEpisode",
    "ImportOutcome",
    "LongestSighting",
    "MilitaryFirst",
    "ReceiverRecords",
    "SightingObservation",
]
