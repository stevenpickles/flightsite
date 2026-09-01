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
:class:`OperatorGroup`, :class:`Operator`) in slice 021, and
:class:`AircraftClassification` in slice 024.
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
