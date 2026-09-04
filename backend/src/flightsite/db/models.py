"""SQLAlchemy 2.0 typed ORM models.

:class:`Base` is the single declarative base every FlightSite table hangs off,
and therefore the metadata Alembic autogenerate compares against. Adding a
model here without a matching migration (or vice versa) fails the drift test in
``backend/tests/db/test_migrations.py``.

Tables land slice by slice per ``docs/DATA_MODEL.md`` §12: :class:`Meta` in
slice 005, :class:`Aircraft` and :class:`Sighting` in slice 009,
:class:`SightingTrackCheckpoint`, :class:`SightingTrack` and
:class:`SightingEvent` in slice 052, and the metadata group
(:class:`MetadataSource`, :class:`AircraftMetadata`,
:class:`AircraftMetadataStaging`, :class:`AircraftMetadataResolved`,
:class:`OperatorGroup`, :class:`Operator`) in slice 021,
:class:`AircraftClassification` in slice 024, :class:`RouteCache` in slice 026,
:class:`Airport` in slice 027, and the receiver-metric group
(:class:`ReceiverMetricRaw`, :class:`ReceiverMetricHourly`,
:class:`ReceiverMetricDaily`, :class:`RangeByBearingDaily`,
:class:`LifetimeStat`) in slice 033, and the analytics rollup group
(:class:`DailyStats`, :class:`DailyTypeStats`, :class:`DailyOperatorStats`,
:class:`TypeStats`) in slice 031, and the activity group
(:class:`ActivityEvent`, :class:`Milestone`) in slice 035, and the alert group
(:class:`AlertRule`, :class:`AlertMatch`) in slice 038.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import (
    REAL,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: ``meta`` key holding T0 — the moment the first observation was persisted
#: (SPEC §16). Written exactly once, by the persistence worker (slice 009).
META_KEY_T0: Final[str] = "t0_ms"

#: The canonical ``closure_reason`` vocabulary (``docs/API.md`` §2.8), spelled
#: as the SQL ``CHECK`` predicate ``docs/DATA_MODEL.md`` §2.3 defines.
#:
#: The runtime enum is
#: :class:`flightsite.sightings.vocabulary.ClosureReason`; it cannot be
#: imported here (``sightings`` depends on ``db``, not the reverse), so a test
#: asserts the two agree rather than letting them drift silently.
CLOSURE_REASON_CHECK: Final[str] = (
    "closure_reason IN ('gap_timeout', 'shutdown_recovery', 'data_reset')"
)

#: ``route_source`` vocabulary — AeroDataBox is the only route provider v1
#: ships (ADR-0006); populated by slice 026.
ROUTE_SOURCE_CHECK: Final[str] = "route_source IN ('aerodatabox')"

#: Local arrival/departure inference, kept distinct from enriched route data
#: (SPEC §28, §41); populated by slice 027.
INFERRED_PHASE_CHECK: Final[str] = "inferred_phase IN ('arriving', 'departing')"

#: Alert severity ladder (``docs/API.md`` §2.8); populated by slice 038.
ALERT_SEVERITY_CHECK: Final[str] = (
    "max_alert_severity IN ('info', 'interesting', 'high', 'critical')"
)

#: The same §2.8 ladder on ``activity_events.severity`` (``docs/DATA_MODEL.md``
#: §5), where the column is named ``severity`` rather than
#: ``max_alert_severity``. Constrained — unlike ``activity_events.type``,
#: which stays open — because the ladder is fixed and shared.
ACTIVITY_SEVERITY_CHECK: Final[str] = "severity IN ('info', 'interesting', 'high', 'critical')"

#: The same §2.8 ladder again, on ``alert_rules.severity`` and
#: ``alert_matches.severity`` (``docs/DATA_MODEL.md`` §4.2/§4.3, slice 038).
#:
#: Spelled out rather than aliased to :data:`ACTIVITY_SEVERITY_CHECK`, whose
#: text it happens to equal: each constraint belongs to the document that owns
#: its table, and a migration copies the predicate it was written against
#: rather than whatever a shared name later points at. A test asserts every
#: spelling of the ladder — these two, :data:`ALERT_SEVERITY_CHECK` and
#: :class:`flightsite.alerts.vocabulary.AlertSeverity` — stays one ladder.
ALERT_ROW_SEVERITY_CHECK: Final[str] = "severity IN ('info', 'interesting', 'high', 'critical')"

#: Every ``alert_matches`` row attributes itself to *something* that matched
#: (``docs/DATA_MODEL.md`` §4.3): a user rule, or one of the built-in
#: emergency-squawk detectors, which have no rule row to point at (SPEC §47).
ALERT_MATCH_ORIGIN_CHECK: Final[str] = "rule_id IS NOT NULL OR builtin_key IS NOT NULL"

#: SPEC §39's mission/use categories, spelled as ``docs/DATA_MODEL.md`` §3.4's
#: ``CHECK`` predicate.
#:
#: Spelled out rather than generated from
#: :class:`flightsite.classification.vocabulary.MissionCategory`, for the same
#: reason as :data:`CLOSURE_REASON_CHECK` above: ``classification`` depends on
#: ``db`` and not the reverse. A test asserts the two lists agree.
MISSION_CATEGORY_CHECK: Final[str] = (
    "mission_category IN ('commercial_passenger', 'cargo', 'general_aviation', "
    "'business_aviation', 'military', 'government', 'law_enforcement', 'medical', "
    "'firefighting', 'training', 'helicopter', 'unknown')"
)

#: The ``sighting_events.type`` vocabulary of ``docs/DATA_MODEL.md`` §2.5,
#: spelled as the SQL ``CHECK`` predicate.
#:
#: All eight values are constrained from birth even though slice 052 emits only
#: the first four: the enum is a storage contract, and widening a SQLite
#: ``CHECK`` later means rebuilding the table. The runtime enum is
#: :class:`flightsite.sightings.vocabulary.SightingEventType` — as with
#: :data:`CLOSURE_REASON_CHECK` it cannot be imported here, so a test asserts
#: the two agree rather than letting them drift silently.
SIGHTING_EVENT_TYPE_CHECK: Final[str] = (
    "type IN ('callsign_change', 'squawk_change', 'emergency_start', 'emergency_end', "
    "'route_enriched', 'classification_available', 'alert_matched', "
    "'alert_severity_upgraded')"
)

#: The ``metadata_sources.status`` vocabulary of ``docs/DATA_MODEL.md`` §3.1,
#: spelled as the SQL ``CHECK`` predicate.
#:
#: Three terminal values, deliberately: a run that is *in flight* is process
#: state, not stored state — a crash mid-import must not leave a row claiming
#: to be running forever. In-flight progress is
#: :class:`flightsite.metadata.registry.SourceRunState`, held in memory and
#: read by the slice-025 status endpoint; the row here records only what the
#: last completed attempt did. The runtime enum is
#: :class:`flightsite.metadata.registry.SourceStatus`; as with
#: :data:`CLOSURE_REASON_CHECK` it cannot be imported here (``metadata``
#: depends on ``db``, not the reverse), so a test asserts the two agree.
METADATA_SOURCE_STATUS_CHECK: Final[str] = "status IN ('never_run', 'ok', 'failed')"

#: The ``route_cache.status`` vocabulary of ``docs/DATA_MODEL.md`` §7, spelled
#: as the SQL ``CHECK`` predicate.
#:
#: Every value is constrained from birth. Slice 026 wrote ``ok`` and
#: ``not_found``, and slice 070 added ``restricted``: what none of them records
#: is a *provider unavailability* — a timeout, a 429, a 5xx, an open circuit —
#: because those say nothing about the callsign and caching them would turn one
#: bad minute into hours of false "no route". ``restricted`` is the opposite
#: case and belongs here for exactly that reason: an HTTP 451 is the provider
#: answering, definitively, that this flight is legally withheld (issue #165),
#: so it is cached like any other answer. ``error`` remains the shape reserved
#: for a provider answering definitively and unusably for a particular key, the
#: same way :data:`CLOSURE_REASON_CHECK` carried values before the code that
#: writes them existed. The runtime enum is
#: :class:`flightsite.enrichment.model.RouteCacheStatus`; as with
#: :data:`CLOSURE_REASON_CHECK` it cannot be imported here (``enrichment``
#: depends on ``db``, not the reverse), so a test asserts the two agree.
ROUTE_CACHE_STATUS_CHECK: Final[str] = "status IN ('ok', 'not_found', 'restricted', 'error')"

#: The ``watchlist_entries.kind`` vocabulary of ``docs/DATA_MODEL.md`` §4.1 /
#: SPEC §42, spelled as the SQL ``CHECK`` predicate.
#:
#: The runtime enum is
#: :class:`flightsite.watchlists.vocabulary.WatchlistEntryKind`; it cannot be
#: imported here (``watchlists`` depends on ``db``, not the reverse), so a
#: test asserts the two agree rather than letting them drift silently.
WATCHLIST_ENTRY_KIND_CHECK: Final[str] = (
    "kind IN ('icao24', 'registration', 'type_code', 'operator', 'category')"
)


class Base(DeclarativeBase):
    """Declarative base for all FlightSite ORM models."""


class Meta(Base):
    """Application-level key/value state (``docs/DATA_MODEL.md`` §2.1).

    ``WITHOUT ROWID`` because the table is a handful of rows always addressed
    by their text primary key: the clustered b-tree is both smaller and one
    lookup cheaper than the rowid indirection.
    """

    __tablename__ = "meta"
    # Tuple form (dialect kwargs last) rather than a bare dict: SQLAlchemy
    # declares __table_args__ as an instance variable, so a ClassVar annotation
    # is rejected, and an unannotated mutable class attribute is a lint error.
    __table_args__ = ({"sqlite_with_rowid": False},)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Meta(key={self.key!r}, value={self.value!r}, updated_ms={self.updated_ms!r})"


class Aircraft(Base):
    """One physical airframe ever observed (``docs/DATA_MODEL.md`` §2.2).

    Permanent identity plus the *receiver-relative* lifetime records of SPEC
    §53, denormalized onto the row so "how often, how close, how high" is one
    indexed read rather than an aggregate over every sighting. The persistence
    worker maintains them transactionally as sightings flush and close.

    The primary key is a surrogate integer rather than ``icao24`` so that the
    high-volume child tables carry a compact foreign key, and so a future ICAO
    reassignment is a data problem rather than an identity one (ADR-0004).
    Each record column carries its own ``_ms`` moment: the UI shows *when* a
    record was set, which a bare value could not answer.

    Flight-context fields (callsign, squawk, route) never appear here — they
    belong to the sighting (SPEC §17).
    """

    __tablename__ = "aircraft"
    __table_args__ = (
        Index("ix_aircraft_first_seen", "first_seen_ms"),
        Index("ix_aircraft_last_seen", "last_seen_ms"),
        # Rarity ("seen fewer than N times", SPEC §44) reads this directly.
        Index("ix_aircraft_sightings", "sighting_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    icao24: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    first_seen_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    last_seen_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    sighting_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    total_observed_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    closest_approach_nm: Mapped[float | None] = mapped_column(REAL)
    closest_approach_ms: Mapped[int | None] = mapped_column(Integer)
    #: Lifetime farthest detection (``max_range_nm``, ``docs/API.md`` §2.8).
    max_range_nm: Mapped[float | None] = mapped_column(REAL)
    max_range_ms: Mapped[int | None] = mapped_column(Integer)
    lowest_alt_ft: Mapped[int | None] = mapped_column(Integer)
    lowest_alt_ms: Mapped[int | None] = mapped_column(Integer)
    highest_alt_ft: Mapped[int | None] = mapped_column(Integer)
    highest_alt_ms: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Aircraft(id={self.id!r}, icao24={self.icao24!r})"


class Sighting(Base):
    """One continuous observation period of one aircraft (§2.3).

    Opens on the first observation of an aircraft that is not currently
    sighted and closes after the configured absence gap; a new sighting for the
    same airframe begins only once the previous one is closed (SPEC §18). While
    a sighting is open ``ended_ms`` is ``NULL``, which the partial index
    ``ix_sightings_open`` makes a cheap lookup — that index is what the
    no-reopen-before-close rule and startup recovery both stand on.

    Column groups, and who fills them:

    * **times / closure** — the persistence worker (slice 009).
    * **flight context** — ``callsign_*``, ``squawk_last`` and
      ``had_emergency`` from the live stream (slice 009); ``origin_ident``,
      ``destination_ident`` and ``route_source`` from route enrichment (026);
      ``inferred_airport_ident`` / ``inferred_phase`` from the local
      arrival/departure heuristic (027), deliberately kept distinct from
      enriched truth (SPEC §28, §41).
    * **position character** — slice 009.
    * **reception statistics** — slice 052, from the live stream's per-update
      ``rssi_db``, message counts and position reports.
    * **per-sighting extremes** — slice 009; these feed the lifetime records on
      :class:`Aircraft`.
    * ``max_alert_severity`` — slice 038's denormalized outcome for the
      sightings list; ``alert_matches`` remains the source of truth.
    """

    __tablename__ = "sightings"
    __table_args__ = (
        CheckConstraint(CLOSURE_REASON_CHECK, name="ck_sightings_closure_reason"),
        CheckConstraint(ROUTE_SOURCE_CHECK, name="ck_sightings_route_source"),
        CheckConstraint(INFERRED_PHASE_CHECK, name="ck_sightings_inferred_phase"),
        CheckConstraint(ALERT_SEVERITY_CHECK, name="ck_sightings_max_alert_severity"),
        Index("ix_sightings_aircraft", "aircraft_id", "started_ms"),
        Index("ix_sightings_started", "started_ms"),
        # Partial: the open set is a handful of rows against a multi-year
        # history, so indexing only them keeps "is this aircraft already
        # sighted?" and startup recovery independent of table size.
        Index("ix_sightings_open", "ended_ms", sqlite_where=text("ended_ms IS NULL")),
        # `docs/API.md` §3.6's `sort=max_range_nm`, which was a full scan and
        # sort until rev 0013 — 8.0 s over 1.64M sightings. `id` rides along as
        # the list endpoint's pagination tiebreaker. `closest_approach_nm` is
        # deliberately *not* given a sibling: every index here is rewritten on
        # each 30-second flush of an open sighting, and a second one measured
        # ~2.6x the baseline per-sighting write cost again (issue #115).
        Index("ix_sightings_max_range", "max_range_nm", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aircraft_id: Mapped[int] = mapped_column(Integer, ForeignKey("aircraft.id"), nullable=False)

    started_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    #: ``NULL`` while the sighting is open.
    ended_ms: Mapped[int | None] = mapped_column(Integer)
    #: Set at close, so history needs no arithmetic to sort by duration.
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    closure_reason: Mapped[str | None] = mapped_column(Text)

    callsign_first: Mapped[str | None] = mapped_column(Text)
    #: Changes within a sighting are also recorded as ``sighting_events`` (052).
    callsign_last: Mapped[str | None] = mapped_column(Text)
    squawk_last: Mapped[str | None] = mapped_column(Text)
    had_emergency: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    origin_ident: Mapped[str | None] = mapped_column(Text)
    destination_ident: Mapped[str | None] = mapped_column(Text)
    route_source: Mapped[str | None] = mapped_column(Text)
    inferred_airport_ident: Mapped[str | None] = mapped_column(Text)
    inferred_phase: Mapped[str | None] = mapped_column(Text)

    any_position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    mlat_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    ground_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    msg_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    pos_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rssi_peak_db: Mapped[float | None] = mapped_column(REAL)
    rssi_avg_db: Mapped[float | None] = mapped_column(REAL)
    rssi_min_db: Mapped[float | None] = mapped_column(REAL)
    #: Percentage of the sighting spent with a valid position.
    pos_time_pct: Mapped[float | None] = mapped_column(REAL)

    closest_approach_nm: Mapped[float | None] = mapped_column(REAL)
    max_range_nm: Mapped[float | None] = mapped_column(REAL)
    lowest_alt_ft: Mapped[int | None] = mapped_column(Integer)
    highest_alt_ft: Mapped[int | None] = mapped_column(Integer)

    max_alert_severity: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Sighting(id={self.id!r}, aircraft_id={self.aircraft_id!r})"


class SightingTrackCheckpoint(Base):
    """One checkpointed track point of an *open* sighting (§2.4, ADR-0005).

    This table is a crash-recovery record, not an archival one. While a
    sighting is open its full-resolution track lives in memory; the persistence
    worker appends lightly thinned batches here on its flush cadence so an
    unclean shutdown loses at most one interval of path. Every row is deleted
    in the transaction that packs the sighting's :class:`SightingTrack`, which
    is why the table's steady-state size is bounded by concurrent traffic
    rather than by history (``docs/DATA_MODEL.md`` §9).

    ``pos_source`` is an **integer** code rather than the ``TEXT`` enum the
    low-volume tables use: this is the highest-volume table in the schema, and
    §Conventions puts integer codes on exactly these. The mapping is
    :class:`flightsite.sightings.vocabulary.PositionSourceCode`.

    ``WITHOUT ROWID`` with ``(sighting_id, seq)`` as the primary key clusters a
    sighting's points together in insertion order, which is how they are always
    read — the whole path for one sighting, never a point-level query — and is
    the reason no separate index over ``sighting_id`` is declared.
    """

    __tablename__ = "sighting_track_checkpoints"
    __table_args__ = ({"sqlite_with_rowid": False},)

    sighting_id: Mapped[int] = mapped_column(Integer, ForeignKey("sightings.id"), primary_key=True)
    #: Ordering within the sighting, dense and monotonic across batches.
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    lat: Mapped[float] = mapped_column(REAL, nullable=False)
    lon: Mapped[float] = mapped_column(REAL, nullable=False)
    #: ``NULL`` on the ground or where the decoder reported no altitude.
    alt_ft: Mapped[int | None] = mapped_column(Integer)
    gs_kt: Mapped[float | None] = mapped_column(REAL)
    track_deg: Mapped[float | None] = mapped_column(REAL)
    pos_source: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"SightingTrackCheckpoint(sighting_id={self.sighting_id!r}, seq={self.seq!r})"


class SightingTrack(Base):
    """The packed, simplified path of one *closed* sighting (§2.4, ADR-0005).

    One row per sighting, holding every retained point of the Douglas-Peucker
    simplified track as a compact binary blob — roughly 21 bytes per point
    against the hundreds a b-tree row apiece would cost. That ratio is what
    makes retaining tracks indefinitely (SPEC §65) fit a Pi 4's storage budget
    at the SPEC §5 load envelope; ``docs/DATA_MODEL.md`` §9 carries the
    arithmetic.

    The blob is opaque to SQL on purpose: every read is "the whole path for
    sighting N", served by
    :mod:`flightsite.sightings.track_codec` as points-in/points-out. A future
    feature needing per-point ``WHERE`` clauses would need a superseding ADR.

    ``started_ms`` is the absolute base the per-point time deltas are measured
    from, and ``encoding_version`` makes a future format change an additive
    migration rather than a rewrite — the decoder refuses versions it does not
    know rather than guessing at their layout.
    """

    __tablename__ = "sighting_tracks"
    __table_args__ = ({"sqlite_with_rowid": False},)

    sighting_id: Mapped[int] = mapped_column(Integer, ForeignKey("sightings.id"), primary_key=True)
    encoding_version: Mapped[int] = mapped_column(Integer, nullable=False)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    started_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    points_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"SightingTrack(sighting_id={self.sighting_id!r}, points={self.point_count!r})"


class SightingEvent(Base):
    """A meaningful change within a sighting (§2.5, SPEC §52).

    Deliberately *not* one row per decoder snapshot: a row appears only when
    something a person would want to read about changed — the flight took a new
    callsign, the squawk changed, an emergency code appeared or cleared. Slice
    052 emits those four from the live stream; the enrichment, classification
    and alert values in the ``CHECK`` belong to later slices and are constrained
    from birth so the vocabulary never has to be widened in place.

    The index is ``(sighting_id, ts_ms)`` because the only query is "this
    sighting's timeline, in order" — the sighting detail view today and
    historical playback later (``docs/DATA_MODEL.md`` §11).
    """

    __tablename__ = "sighting_events"
    __table_args__ = (
        CheckConstraint(SIGHTING_EVENT_TYPE_CHECK, name="ck_sighting_events_type"),
        Index("ix_sevents_sighting", "sighting_id", "ts_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sighting_id: Mapped[int] = mapped_column(Integer, ForeignKey("sightings.id"), nullable=False)
    ts_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    #: Pydantic-free by design: the payloads are two or three scalar fields
    #: (``{"from": "7000", "to": "7700"}``) written and read in one module.
    payload_json: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"SightingEvent(id={self.id!r}, sighting_id={self.sighting_id!r}, type={self.type!r})"
        )


class MetadataSource(Base):
    """Per-source import status (``docs/DATA_MODEL.md`` §3.1, SPEC §27).

    One row per configured metadata source, and the only place "when did this
    source last work, and what did it fail with" is recorded. SPEC §27 requires
    each source to succeed or fail *independently*, so nothing here is shared
    between sources: an import writes exactly its own row.

    ``last_attempt_ms`` moves on every attempt while ``last_success_ms``,
    ``dataset_version`` and ``row_count`` describe the dataset currently in
    ``aircraft_metadata`` — after a failed import those still describe the
    previous, still-intact dataset, which is precisely what "preserves the
    previous working dataset" means to a user reading the status.
    """

    __tablename__ = "metadata_sources"
    __table_args__ = (
        CheckConstraint(METADATA_SOURCE_STATUS_CHECK, name="ck_metadata_sources_status"),
        {"sqlite_with_rowid": False},
    )

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    last_attempt_ms: Mapped[int | None] = mapped_column(Integer)
    last_success_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="never_run", server_default=text("'never_run'")
    )
    #: Upstream version string or content hash — whatever identifies the
    #: snapshot that produced the current rows.
    dataset_version: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"MetadataSource(source={self.source!r}, status={self.status!r})"


class _AircraftMetadataColumns:
    """The per-source metadata column set, shared by the live and staging tables.

    A declarative mixin rather than two hand-written copies: the staging table
    exists only to receive a full source snapshot before it is promoted, so any
    divergence between the two shapes would be a bug, and the ``INSERT ...
    SELECT`` that promotes one into the other assumes they match column for
    column.
    """

    icao24: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)

    registration: Mapped[str | None] = mapped_column(Text)
    #: ICAO type designator, e.g. ``B738``.
    type_code: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    manufacture_year: Mapped[int | None] = mapped_column(Integer)
    operator_name: Mapped[str | None] = mapped_column(Text)
    #: FAA owner where released; ``NULL`` when withheld — SPEC §26 prefers
    #: ``Unknown`` in the UI to speculation here.
    owner: Mapped[str | None] = mapped_column(Text)
    #: Upstream military flag, normalized to 0/1 by the provider.
    military_flag: Mapped[int | None] = mapped_column(Integer)
    #: Remaining source-specific flags, opaque to SQL; slice 024 reads them.
    flags_json: Mapped[str | None] = mapped_column(Text)
    updated_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class AircraftMetadata(_AircraftMetadataColumns, Base):
    """One row per ``(icao24, source)`` (``docs/DATA_MODEL.md`` §3.2).

    Sources never overwrite each other: an import replaces only its own rows,
    so a failed FAA import cannot damage Mictronics data and the field-level
    precedence in :class:`AircraftMetadataResolved` always has every source's
    unmerged claim available to re-derive from.

    ``WITHOUT ROWID`` with ``(icao24, source)`` as the primary key clusters an
    airframe's per-source rows together, which is how resolution reads them —
    one airframe's claims at a time, in ``icao24`` order.
    """

    __tablename__ = "aircraft_metadata"
    __table_args__ = (
        # Declared here rather than on the shared mixin: the staging table
        # takes the same columns but must not take this constraint.
        ForeignKeyConstraint(["source"], ["metadata_sources.source"]),
        {"sqlite_with_rowid": False},
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AircraftMetadata(icao24={self.icao24!r}, source={self.source!r})"


class AircraftMetadataStaging(_AircraftMetadataColumns, Base):
    """Landing area for one source's snapshot before it is promoted (§3.2).

    ``docs/DATA_MODEL.md`` §3.2 spells the import as *staging table → validate
    → swap inside one transaction*. Loading a multi-hundred-thousand-row
    snapshot straight into :class:`AircraftMetadata` inside a single
    transaction would hold the process's one writer (ADR-0008) for the whole
    download-sized write, stalling sighting persistence; loading it here in
    short batched transactions and promoting it with one small
    ``DELETE``/``INSERT ... SELECT`` keeps the writer available throughout and
    makes the visible swap atomic.

    Rows here are scratch: they are deleted when their run promotes or fails,
    and any left behind by a crash are cleared before the next run of that
    source, so they can never leak into a later import. Deliberately **no**
    foreign key to ``metadata_sources`` — this is not integrity-bearing data
    and the per-row check would be paid once per staged row for nothing.
    """

    __tablename__ = "aircraft_metadata_staging"
    __table_args__ = ({"sqlite_with_rowid": False},)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AircraftMetadataStaging(icao24={self.icao24!r}, source={self.source!r})"


class AircraftMetadataResolved(Base):
    """Field-level precedence, materialized (``docs/DATA_MODEL.md`` §3.3).

    One row per airframe, each field carrying the name of the source that won
    it. Resolution happens at import time rather than at read time because the
    Aircraft page sorts and filters on resolved type and operator in SQL; a
    per-field EAV provenance table was rejected as slow and unqueryable at this
    scale (§3.3, §8).

    The ``_src`` value is non-``NULL`` exactly when its field is non-``NULL``:
    provenance describes a value, so a field nobody supplied has no source.
    """

    __tablename__ = "aircraft_metadata_resolved"
    __table_args__ = (
        Index("ix_amr_registration", "registration"),
        Index("ix_amr_type", "type_code"),
        Index("ix_amr_opgroup", "operator_group_id"),
        {"sqlite_with_rowid": False},
    )

    icao24: Mapped[str] = mapped_column(Text, primary_key=True)

    registration: Mapped[str | None] = mapped_column(Text)
    registration_src: Mapped[str | None] = mapped_column(Text)
    type_code: Mapped[str | None] = mapped_column(Text)
    type_code_src: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    model_src: Mapped[str | None] = mapped_column(Text)
    manufacture_year: Mapped[int | None] = mapped_column(Integer)
    year_src: Mapped[str | None] = mapped_column(Text)
    operator_name: Mapped[str | None] = mapped_column(Text)
    operator_src: Mapped[str | None] = mapped_column(Text)
    #: Curated grouping, filled once slice 024 populates ``operators``. The
    #: exact operator string above is always preserved beside it (SPEC §38).
    operator_group_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("operator_groups.id"))
    owner: Mapped[str | None] = mapped_column(Text)
    owner_src: Mapped[str | None] = mapped_column(Text)
    updated_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AircraftMetadataResolved(icao24={self.icao24!r}, type_code={self.type_code!r})"


class OperatorGroup(Base):
    """A curated operator grouping (``docs/DATA_MODEL.md`` §3.5).

    Created empty by slice 021 and populated by slice 024. It exists this early
    because :class:`AircraftMetadataResolved` references it and ADR-0001 runs
    with ``foreign_keys=ON``: the referenced table has to exist at the moment
    the referencing one is created, so splitting the two across migrations
    would make the first metadata migration fail.
    """

    __tablename__ = "operator_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"OperatorGroup(id={self.id!r}, slug={self.slug!r})"


class Operator(Base):
    """An exact operator string mapped to its group (§3.5).

    Created empty by slice 021, populated by slice 024. Grouping is additive:
    the exact operator string stays on the metadata rows regardless of whether
    a group claims it (SPEC §38).
    """

    __tablename__ = "operators"
    __table_args__ = ({"sqlite_with_rowid": False},)

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("operator_groups.id"), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Operator(name={self.name!r}, group_id={self.group_id!r})"


class AircraftClassification(Base):
    """Computed classification with per-claim provenance (§3.4, SPEC §39).

    One row per airframe, rebuilt inside the metadata import transaction beside
    :class:`AircraftMetadataResolved`. Keyed by ``icao24`` rather than by a
    sighting or an ``aircraft`` row, so an airframe is classified whether or
    not the receiver has ever heard it — which is what lets the Aircraft page
    filter by classification over the whole metadata database.

    Every claim gets three columns, not one: the answer, the source that
    supports it, and a confidence. A ``NULL`` ``*_src``/``*_conf`` pair beside a
    ``0`` flag is the shape of "nothing asserts this", and the pair is non-``NULL``
    exactly when the flag is set — the same rule the resolved table follows for
    its ``*_src`` columns.

    ``icon_category`` has no ``CHECK``, unlike ``mission_category``: it is the
    icon hierarchy's own vocabulary and grows with the icon set, while the
    mission list is SPEC §39's and does not.
    """

    __tablename__ = "aircraft_classification"
    __table_args__ = (
        CheckConstraint(MISSION_CATEGORY_CHECK, name="ck_aircraft_classification_mission"),
        Index("ix_class_mil", "military", sqlite_where=text("military = 1")),
        Index("ix_class_gov", "government", sqlite_where=text("government = 1")),
        Index("ix_class_law", "law_enforcement", sqlite_where=text("law_enforcement = 1")),
        Index("ix_class_mission", "mission_category"),
        {"sqlite_with_rowid": False},
    )

    icao24: Mapped[str] = mapped_column(Text, primary_key=True)

    military: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    military_src: Mapped[str | None] = mapped_column(Text)
    military_conf: Mapped[float | None] = mapped_column(REAL)
    government: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    government_src: Mapped[str | None] = mapped_column(Text)
    government_conf: Mapped[float | None] = mapped_column(REAL)
    law_enforcement: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    law_enforcement_src: Mapped[str | None] = mapped_column(Text)
    law_enforcement_conf: Mapped[float | None] = mapped_column(REAL)
    mission_category: Mapped[str] = mapped_column(
        Text, nullable=False, default="unknown", server_default=text("'unknown'")
    )
    mission_src: Mapped[str | None] = mapped_column(Text)
    mission_conf: Mapped[float | None] = mapped_column(REAL)
    #: Input to the map icon hierarchy (SPEC §34), not a mission category.
    icon_category: Mapped[str] = mapped_column(
        Text, nullable=False, default="unknown", server_default=text("'unknown'")
    )
    updated_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"AircraftClassification(icao24={self.icao24!r}, "
            f"mission_category={self.mission_category!r})"
        )


class RouteCache(Base):
    """Cached route lookups for the enrichment provider (§7, slice 026).

    SPEC §28's instruction is to *cache aggressively and respect provider
    limits*, and this table is what makes that mechanical: a callsign is asked
    about at most once per key, however many sightings, restarts or aircraft
    ask about it.

    The key is the **normalized callsign**, and nothing else (§7). It carried a
    UTC date bucket until slice 070 measured what that cost on the owner's
    receiver: 62 % of a day's airline callsigns had been seen the previous day,
    so a dated key was buying the same answer again every morning at ~190
    lookups an hour. ``expires_ms`` is now the whole of the staleness rule —
    ``enrichment.route_ttl_days`` (default 7) for an answer, 24 h for a
    "no route yet" that is often just an unfiled schedule.

    ``confirmations`` counts the separate calendar days a refresh has returned
    the *same* pair of airports; at three the row is frozen for 30 days, which
    is how a scheduled service earns its place without being re-bought weekly.
    ``first_fetched_ms`` records when the answer now stored was first seen, so
    that run of confirmations is legible after the fact. A differing answer
    resets both.

    ``WITHOUT ROWID`` with the text key as the primary key: every access is a
    point lookup by that key, and the table is small — one row per airline
    flight actually heard, pruned by expiry.

    The index is on ``expires_ms`` alone, which is the only non-key query:
    maintenance deleting what has expired.
    """

    __tablename__ = "route_cache"
    __table_args__ = (
        CheckConstraint(ROUTE_CACHE_STATUS_CHECK, name="ck_route_cache_status"),
        Index("ix_route_cache_expiry", "expires_ms"),
        {"sqlite_with_rowid": False},
    )

    cache_key: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    origin_ident: Mapped[str | None] = mapped_column(Text)
    destination_ident: Mapped[str | None] = mapped_column(Text)
    #: Provider extras kept verbatim for diagnostics — never the request, and
    #: therefore never the API key. Schema-validated on the way in by
    #: :mod:`flightsite.enrichment.aerodatabox`.
    payload_json: Mapped[str | None] = mapped_column(Text)
    fetched_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Separate calendar days a refresh has confirmed the stored answer.
    confirmations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: When the answer now stored was first reported. Nullable because rows
    #: written before revision 0014 have no such record and inventing one
    #: would be a claim about a past this build did not observe.
    first_fetched_ms: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RouteCache(cache_key={self.cache_key!r}, status={self.status!r})"


class Airport(Base):
    """One airport, heliport or landing field (``docs/DATA_MODEL.md`` §3.6).

    Imported from OurAirports (public domain) by
    :mod:`flightsite.airports.ourairports` and read exactly twice in a process's
    life: once at startup and once after an import, both times to build the
    in-memory grid index :mod:`flightsite.airports.index`. Nothing on the live
    path queries this table — nearest-airport lookups answer from that index,
    which is what keeps SQLite off the per-observation path
    (``docs/ARCHITECTURE.md`` §3.1).

    The surrogate ``id`` is OurAirports' own row id rather than a fresh
    sequence: it is stable upstream, it makes a re-import diffable, and
    ``ident`` — the ICAO/GPS identifier everything else joins on — carries the
    ``UNIQUE`` constraint that actually matters.

    ``ix_airports_lat`` covers ``(lat, lon)`` because §3.6's documented lookup
    is a **bounding box refined by great-circle in code**: at ~70k rows that
    needs no R*Tree, and SQLite ships none by default. In practice the index
    serves the rebuild's ordered scan; the box query itself lives in the
    in-memory index.

    ``type`` has no ``CHECK``. The vocabulary is upstream's and grows
    (``balloonport`` postdates the dataset's first release); the *filter* over
    it is FlightSite's decision and lives in
    :data:`flightsite.airports.records.IMPORTED_AIRPORT_TYPES`, where it can be
    changed without rebuilding a table.
    """

    __tablename__ = "airports"
    __table_args__ = (
        Index("ix_airports_lat", "lat", "lon"),
        # Partial: fewer than one row in seven carries an IATA code, so
        # indexing only those keeps the by-IATA lookup independent of the
        # 60k-odd rows that could never answer it.
        Index("ix_airports_iata", "iata", sqlite_where=text("iata IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: ICAO or GPS identifier, e.g. ``KSEA``, ``EGLL``, ``00AK``. Unique.
    ident: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    iata: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Upstream size class: ``large_airport``/``medium_airport``/
    #: ``small_airport``/``heliport``. See the class docstring on the absent
    #: ``CHECK``.
    type: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float] = mapped_column(REAL, nullable=False)
    lon: Mapped[float] = mapped_column(REAL, nullable=False)
    #: Field elevation, ``NULL`` for the ~16% of rows upstream has none for.
    #: The inference treats a missing elevation as sea level rather than
    #: skipping the field — see :mod:`flightsite.airports.inference`.
    elevation_ft: Mapped[int | None] = mapped_column(Integer)
    iso_country: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Airport(ident={self.ident!r}, name={self.name!r})"


class ReceiverMetricRaw(Base):
    """One high-resolution receiver sample (``docs/DATA_MODEL.md`` §6.1).

    A wide row per ~15 s sample: whatever the decoder's own statistics
    endpoint supplied, normalized, plus what FlightSite computed from the live
    set. Every measurement column is nullable because a decoder that does not
    report a metric must leave it *absent* rather than zero (SPEC §60) — zero
    is a measurement, and FlightSite does not invent measurements (SPEC §39).

    ``WITHOUT ROWID`` keyed on ``ts_ms``: every read is a time range and every
    write is an append at the high end, so the clustered b-tree is exactly the
    access order and there is no second copy of the key to maintain. This is
    the only prunable table in the group — ADR-0009's rolling window — and the
    clustering also makes the prune a contiguous head-of-table delete.
    """

    __tablename__ = "receiver_metrics_raw"
    __table_args__ = ({"sqlite_with_rowid": False},)

    ts_ms: Mapped[int] = mapped_column(Integer, primary_key=True)
    messages_per_sec: Mapped[float | None] = mapped_column(REAL)
    positions_per_sec: Mapped[float | None] = mapped_column(REAL)
    aircraft_visible: Mapped[int | None] = mapped_column(Integer)
    aircraft_with_pos: Mapped[int | None] = mapped_column(Integer)
    max_range_nm: Mapped[float | None] = mapped_column(REAL)
    rssi_avg_db: Mapped[float | None] = mapped_column(REAL)
    rssi_peak_db: Mapped[float | None] = mapped_column(REAL)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ReceiverMetricRaw(ts_ms={self.ts_ms!r})"


class _ReceiverMetricSummaryColumns:
    """The summary column set shared by the hourly and daily tables.

    ``docs/DATA_MODEL.md`` §6.2 states the daily table as *"identical shape
    keyed by local calendar day"*, so the two are one declaration and a
    different primary key rather than two copies that could drift. The
    aggregation code folds raw samples into this shape once and writes the
    result to whichever table the bucket belongs to.

    ``sample_count`` is the only non-nullable column: how many raw samples a
    bucket was built from is always known, even when every metric in it was
    absent.
    """

    messages_total: Mapped[int | None] = mapped_column(Integer)
    positions_total: Mapped[int | None] = mapped_column(Integer)
    msgs_per_sec_avg: Mapped[float | None] = mapped_column(REAL)
    msgs_per_sec_max: Mapped[float | None] = mapped_column(REAL)
    pos_per_sec_avg: Mapped[float | None] = mapped_column(REAL)
    pos_per_sec_max: Mapped[float | None] = mapped_column(REAL)
    aircraft_avg: Mapped[float | None] = mapped_column(REAL)
    aircraft_max: Mapped[int | None] = mapped_column(Integer)
    max_range_nm: Mapped[float | None] = mapped_column(REAL)
    rssi_avg_db: Mapped[float | None] = mapped_column(REAL)
    rssi_peak_db: Mapped[float | None] = mapped_column(REAL)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)


class ReceiverMetricHourly(_ReceiverMetricSummaryColumns, Base):
    """Hourly receiver summaries (``docs/DATA_MODEL.md`` §6.2).

    Keyed by the UTC hour the bucket starts at. Retained **indefinitely** —
    ADR-0009 is explicit that hourly and daily rows are permanent, because
    ~8.8k rows a year is nothing next to the detail they preserve once the
    high-resolution window has rolled past.
    """

    __tablename__ = "receiver_metrics_hourly"
    __table_args__ = ({"sqlite_with_rowid": False},)

    hour_start_ms: Mapped[int] = mapped_column(Integer, primary_key=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ReceiverMetricHourly(hour_start_ms={self.hour_start_ms!r})"


class ReceiverMetricDaily(_ReceiverMetricSummaryColumns, Base):
    """Daily receiver summaries (``docs/DATA_MODEL.md`` §6.2).

    Keyed by the **receiver-local** calendar date (``docs/DATA_MODEL.md``
    §10), so a DST day rolls up as the 23 or 25 hours it actually was.
    Retained indefinitely, like the hourly table.
    """

    __tablename__ = "receiver_metrics_daily"
    __table_args__ = ({"sqlite_with_rowid": False},)

    #: ``YYYY-MM-DD`` in the configured IANA timezone at write time.
    day: Mapped[str] = mapped_column(Text, primary_key=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ReceiverMetricDaily(day={self.day!r})"


class RangeByBearingDaily(Base):
    """Per-day maximum range in each 5° bearing sector (§6.3).

    72 buckets of 5°, which is what the polar plot (SPEC §62) draws and what
    the coverage records are read from. One row per (day, sector) that had any
    positioned aircraft in it, kept indefinitely: 72 x 365 rows a year is
    trivial, and this is the only record of where the receiver could actually
    hear.

    ``icao24`` records *which* aircraft set the record. It is deliberately not
    a foreign key to ``aircraft``: this row must outlive any conceivable
    aircraft-row cleanup, and its purpose is a fact about the moment, not a
    join.
    """

    __tablename__ = "range_by_bearing_daily"
    __table_args__ = ({"sqlite_with_rowid": False},)

    day: Mapped[str] = mapped_column(Text, primary_key=True)
    #: ``0..71``; sector ``n`` covers bearings ``[5n, 5n + 5)`` degrees true.
    bearing_bucket: Mapped[int] = mapped_column(Integer, primary_key=True)
    max_range_nm: Mapped[float] = mapped_column(REAL, nullable=False)
    at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    icao24: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RangeByBearingDaily(day={self.day!r}, bearing_bucket={self.bearing_bucket!r})"


class LifetimeStat(Base):
    """Since-T0 receiver aggregates and records (§6.4, SPEC §63).

    A narrow key/value table rather than a wide row, because the set of
    records grows slice by slice (035 adds milestones over the same facts) and
    a new record should be a new key, not a migration.

    These rows are the half of ADR-0009 that pruning may never touch: totals
    are accumulated from the *increments* observed as each sample is recorded,
    never re-derived from ``receiver_metrics_raw``, so a record survives every
    downsample-and-prune cycle by construction rather than by luck.
    """

    __tablename__ = "lifetime_stats"
    __table_args__ = ({"sqlite_with_rowid": False},)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value_num: Mapped[float | None] = mapped_column(REAL)
    value_text: Mapped[str | None] = mapped_column(Text)
    updated_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"LifetimeStat(key={self.key!r}, value_num={self.value_num!r})"


class DailyStats(Base):
    """One receiver-local calendar day of analytics rollup (§6.5, slice 031).

    The row a chart reads instead of aggregating a year of ``sightings``. Every
    figure on it is a **total function of the sightings that started that local
    day** (``docs/DATA_MODEL.md`` §10 fixes the bucket to the receiver-local
    date), so the row can be rebuilt from ground truth at any time and the
    rebuild always produces the same values — which is what makes the
    incremental maintenance in :mod:`flightsite.analytics.service` and the
    repair job in :mod:`flightsite.analytics.backfill` two callers of one
    fold rather than two implementations that have to be kept in step.

    ``busiest_hour`` is deliberately ``NULL`` while the day is still in
    progress: §6.5 makes this column the finalized **closed-day** value, and
    the in-progress day's busiest hour is served from slice 033's
    ``receiver_metrics_hourly`` instead. A number here always means "this day
    is over and this was its busiest local hour".

    ``WITHOUT ROWID`` on the ``day`` text key: every read is either a point
    lookup or an ordered range over that key (a preset's window is a
    contiguous run of days), so the clustered b-tree is the access path.
    """

    __tablename__ = "daily_stats"
    __table_args__ = ({"sqlite_with_rowid": False},)

    #: Receiver-local ``YYYY-MM-DD`` (``docs/DATA_MODEL.md`` §10).
    day: Mapped[str] = mapped_column(Text, primary_key=True)
    unique_aircraft: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: Aircraft whose first-ever sighting fell on this day.
    new_aircraft: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    sightings: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: Sightings carrying a non-null ``max_alert_severity`` (slice 038 fills it).
    interesting: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    military: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    government: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    law_enforcement: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_range_nm: Mapped[float | None] = mapped_column(REAL)
    #: 0-23 receiver-local; ``NULL`` until the day has closed (see above).
    busiest_hour: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DailyStats(day={self.day!r}, sightings={self.sightings!r})"


class DailyTypeStats(Base):
    """Per-day counts for one ICAO type designator (§6.5, slice 031).

    Written only for sightings whose airframe has a *resolved* type
    (``aircraft_metadata_resolved.type_code``): an aircraft nobody has metadata
    for contributes to :class:`DailyStats` and to nothing here, which is
    ``docs/API.md`` §2.7's rule that unknown is unknown rather than a bucket.
    """

    __tablename__ = "daily_type_stats"
    __table_args__ = ({"sqlite_with_rowid": False},)

    day: Mapped[str] = mapped_column(Text, primary_key=True)
    type_code: Mapped[str] = mapped_column(Text, primary_key=True)
    sightings: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_aircraft: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DailyTypeStats(day={self.day!r}, type_code={self.type_code!r})"


class DailyOperatorStats(Base):
    """Per-day counts for one curated operator group (§6.5, slice 031).

    Keyed by the *group* rather than by the exact operator string: SPEC §38
    keeps the exact string on the metadata row and the grouping beside it, and
    "most common operators" is a question about the group. An airframe whose
    operator no group claims contributes nowhere here, for the same reason
    :class:`DailyTypeStats` skips an unresolved type.
    """

    __tablename__ = "daily_operator_stats"
    __table_args__ = ({"sqlite_with_rowid": False},)

    day: Mapped[str] = mapped_column(Text, primary_key=True)
    operator_group_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sightings: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_aircraft: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DailyOperatorStats(day={self.day!r}, group={self.operator_group_id!r})"


class TypeStats(Base):
    """Since-T0 totals for one ICAO type designator (§6.5, slice 031).

    The **receiver-relative** rarity source: "how unusual is a B738 *here*" is
    a statement about what this receiver has heard since T0, not about the
    world's fleet. Slice 038's rarity alert conditions read it, and slice 031's
    ``GET /api/v1/analytics/rarity`` already does.

    Re-derived in full from ``aircraft`` joined to the resolved metadata rather
    than accumulated: that join is bounded by *airframes ever heard* (thousands
    at multi-year scale), and re-deriving is what makes a type resolved late —
    the ordinary case, since metadata imports land hours after a first sighting
    — correct the moment it resolves, with no backfill of its own.
    """

    __tablename__ = "type_stats"
    __table_args__ = ({"sqlite_with_rowid": False},)

    type_code: Mapped[str] = mapped_column(Text, primary_key=True)
    unique_aircraft: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    total_sightings: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    first_seen_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    last_seen_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"TypeStats(type_code={self.type_code!r}, unique={self.unique_aircraft!r})"


class Watchlist(Base):
    """A user-defined watchlist (``docs/DATA_MODEL.md`` §4.1, SPEC §42, slice 037).

    A plain rowid table, like :class:`Aircraft` and :class:`Sighting`: rows are
    few (a handful to a few dozen, created and edited through the internal
    CRUD API), addressed by surrogate id from :class:`WatchlistEntry`'s foreign
    key, and never bulk-scanned — the opposite access pattern from the
    ``WITHOUT ROWID`` rollup tables above.
    """

    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Watchlist(id={self.id!r}, name={self.name!r})"


class WatchlistEntry(Base):
    """One membership rule on a watchlist (§4.1).

    ``kind`` names which field of a live aircraft this entry matches against —
    ``icao24``, ``registration``, ``type_code``, ``operator`` or ``category``
    (SPEC §42's reference list) — and ``value`` is that field's *normalized*
    form: lower-case for ``icao24``, upper-case for ``registration`` and
    ``type_code``, upper-case for ``operator``, and the
    :class:`~flightsite.classification.vocabulary.MissionCategory` spelling for
    ``category``. Normalizing at write time is what lets the in-memory match
    index (:mod:`flightsite.watchlists.matcher`) compare a live aircraft's own
    normalized fields with simple equality rather than re-normalizing on every
    lookup.

    ``ON DELETE CASCADE`` — the only cascading foreign key in the schema —
    because an entry has no meaning once its watchlist is gone and deleting a
    watchlist is meant to delete everything on it in one action; ADR-0001 runs
    with ``PRAGMA foreign_keys = ON``, which is what makes SQLite enforce the
    cascade rather than merely declare it.

    The ``UNIQUE`` constraint is per watchlist: the same ICAO hex may appear on
    two different watchlists (a user tracking it for two different reasons),
    but not twice on the same one. ``ix_wentries_kind_value`` is the match
    index's read path if it is ever rebuilt from SQL instead of held in
    memory, and is what a future audit query over "every entry naming this
    aircraft" would use.
    """

    __tablename__ = "watchlist_entries"
    __table_args__ = (
        CheckConstraint(WATCHLIST_ENTRY_KIND_CHECK, name="ck_watchlist_entries_kind"),
        UniqueConstraint(
            "watchlist_id", "kind", "value", name="uq_watchlist_entries_watchlist_kind_value"
        ),
        Index("ix_wentries_kind_value", "kind", "value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"WatchlistEntry(id={self.id!r}, watchlist_id={self.watchlist_id!r}, "
            f"kind={self.kind!r}, value={self.value!r})"
        )


class ActivityEvent(Base):
    """One thing worth telling the user about (§5, SPEC §55, slice 035).

    The activity feed's storage. Two columns carry the whole design:

    * ``type`` has **no** ``CHECK``. ``docs/DATA_MODEL.md`` §5 names its values
      in a comment rather than a constraint, and it deliberately lists more
      than slice 035 emits — the alert and emergency events belong to phase 6,
      ``maintenance_issue`` and ``data_reset`` to later slices still. Widening
      a ``CHECK`` on SQLite means rebuilding the table, so the vocabulary stays
      open and lives in :class:`flightsite.activity.model.ActivityEventType`,
      with a test asserting it covers what ``docs/API.md`` §3.9 publishes.
    * ``dedupe_key`` is ``UNIQUE``, and it is the restart/replay idempotency
      guarantee at the storage layer. Every producer derives it from *stored
      state* rather than from the moment it ran, so re-observing the same fact
      after a restart, a catch-up scan or an event replay computes the same
      string and the insert becomes a no-op. It is nullable because SQLite
      treats each ``NULL`` as distinct, which is the shape a future genuinely
      repeatable event would want; slice 035 fills it on every row it writes.

    ``severity`` does carry a ``CHECK``: it is the fixed four-value ladder of
    ``docs/API.md`` §2.8, shared with ``alert_rules`` and ``alert_matches``.
    """

    __tablename__ = "activity_events"
    __table_args__ = (
        CheckConstraint(ACTIVITY_SEVERITY_CHECK, name="ck_activity_events_severity"),
        # Newest-first is the feed's only ordering, so migration 0010 creates
        # this index `ON activity_events (ts_ms DESC)` exactly as §5 spells it.
        # It is declared here as a plain column index on purpose: SQLite's
        # index reflection cannot report a column's sort direction, so
        # declaring the expression would make every autogenerate run report a
        # phantom drop-and-recreate of an index that never changed.
        Index("ix_activity_ts", "ts_ms"),
        Index("ix_activity_type_ts", "type", "ts_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: UTC epoch milliseconds — when the thing described happened, which is not
    #: the moment the row was written: a producer runs on its own pass.
    ts_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        Text, nullable=False, default="info", server_default=text("'info'")
    )
    aircraft_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("aircraft.id"))
    sighting_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sightings.id"))
    #: The renderable detail as JSON; the shape is per event type and lives in
    #: :mod:`flightsite.activity.model`.
    payload_json: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ActivityEvent(id={self.id!r}, type={self.type!r})"


class Milestone(Base):
    """One achievement that can happen only once (§5, SPEC §54, slice 035).

    The primary key **is** the fire-once guarantee: ``first_military``,
    ``unique_aircraft_1000``, ``first_type_B52``. A producer inserts with
    ``ON CONFLICT DO NOTHING``, so a restart, a catch-up scan or two passes
    racing the same fact all leave exactly one milestone row and exactly one
    activity event announcing it.

    Rolling records — the furthest detection ever, the busiest day, the highest
    simultaneous count — deliberately do *not* live here: they can be beaten,
    which a natural-key table cannot express. They live in ``lifetime_stats``
    (§6.4) and announce themselves as ``activity_events`` whose ``dedupe_key``
    names the record value they describe.
    """

    __tablename__ = "milestones"
    __table_args__ = ({"sqlite_with_rowid": False},)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    achieved_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    aircraft_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("aircraft.id"))
    value_num: Mapped[float | None] = mapped_column(REAL)
    payload_json: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Milestone(key={self.key!r}, achieved_ms={self.achieved_ms!r})"


class AlertRule(Base):
    """One interesting-aircraft rule (``docs/DATA_MODEL.md`` §4.2, slice 038).

    The conditions are an **embedded, Pydantic-validated JSON document** rather
    than a child table, and §4.2 gives the reason: v1's conditions are a small
    closed set combined with ``AND`` only (SPEC §43), evaluated in memory
    against live state and never queried relationally, so a conditions table
    would add joins and migration surface for no query benefit. The document is
    versioned (``conditions_json.version``) so that a future nested-expression
    feature migrates explicitly rather than by guesswork —
    :class:`flightsite.alerts.model.RuleConditions` owns its shape.

    ``template_key`` is the provenance §4.2 asks for: non-``NULL`` on a rule
    instantiated from one of SPEC §45's shipped templates, ``NULL`` on a rule a
    user wrote. It carries no ``UNIQUE`` constraint, deliberately — a user may
    duplicate a shipped rule and tune the copy — so the once-only guarantee for
    template instantiation is *"instantiate only when no template-provenance
    row exists at all"*, which
    :class:`flightsite.alerts.service.AlertService` applies.

    Emergency-squawk detection is **not** representable here and is not meant
    to be: §4.2's condition set has no squawk kind, because SPEC §47 makes
    emergency detection built in and rule-independent. See
    :mod:`flightsite.alerts.builtins`.
    """

    __tablename__ = "alert_rules"
    __table_args__ = (CheckConstraint(ALERT_ROW_SEVERITY_CHECK, name="ck_alert_rules_severity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    template_key: Mapped[str | None] = mapped_column(Text)
    conditions_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AlertRule(id={self.id!r}, name={self.name!r}, severity={self.severity!r})"


class AlertMatch(Base):
    """One rule (or built-in) that matched one sighting (§4.3, slice 038).

    The two partial ``UNIQUE`` indexes **are** the once-per-sighting-per-rule
    guarantee of SPEC §48, and they are what makes it survive a restart: the
    engine's in-memory record of what it has already fired is an optimisation,
    while the constraint is the contract. A rule and a built-in are indexed
    separately because a row carries exactly one of them, and SQLite treats
    each ``NULL`` in a unique index as distinct — a single index over both
    columns would therefore not constrain anything.

    Severity upgrades of the built-ins use *distinct* ``builtin_key``\\ s
    (``emergency_7600`` then ``emergency_7700``), which §4.3 names as exactly
    the allowed "a newly matched higher-priority condition may notify again"
    path: two different keys are two different rows, not one rule firing twice.

    ``notified`` is delivery state for the browser notifications of slice 040:
    true once at least one FlightSite client has actually shown a browser
    ``Notification`` for this match. It is written by that client, through
    ``POST /api/internal/alerts/matches/{id}/notified`` (issue #104), and never
    by the server on broadcast — putting a frame on a socket is not the same
    fact. Rows are inserted with the default; the transition only ever runs
    ``0`` → ``1``.
    """

    __tablename__ = "alert_matches"
    __table_args__ = (
        CheckConstraint(ALERT_ROW_SEVERITY_CHECK, name="ck_alert_matches_severity"),
        CheckConstraint(ALERT_MATCH_ORIGIN_CHECK, name="ck_alert_matches_origin"),
        Index(
            "ux_amatch_rule_sighting",
            "rule_id",
            "sighting_id",
            unique=True,
            sqlite_where=text("rule_id IS NOT NULL"),
        ),
        Index(
            "ux_amatch_builtin_sighting",
            "builtin_key",
            "sighting_id",
            unique=True,
            sqlite_where=text("builtin_key IS NOT NULL"),
        ),
        Index("ix_amatch_matched", "matched_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: ``NULL`` for a built-in match, which has no rule row to point at.
    rule_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("alert_rules.id"))
    #: ``NULL`` for a rule match; otherwise a built-in detector's stable key.
    builtin_key: Mapped[str | None] = mapped_column(Text)
    sighting_id: Mapped[int] = mapped_column(Integer, ForeignKey("sightings.id"), nullable=False)
    aircraft_id: Mapped[int] = mapped_column(Integer, ForeignKey("aircraft.id"), nullable=False)
    matched_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    #: A human-readable sentence: what matched, and why (SPEC §48's "match
    #: reason"). Composed when the match happens, from the values that
    #: produced it, so history keeps the reason the user was actually shown
    #: even after the rule behind it is edited.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    notified: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"AlertMatch(id={self.id!r}, rule_id={self.rule_id!r}, "
            f"builtin_key={self.builtin_key!r}, sighting_id={self.sighting_id!r})"
        )
