"""SQLAlchemy 2.0 typed ORM models.

:class:`Base` is the single declarative base every FlightSite table hangs off,
and therefore the metadata Alembic autogenerate compares against. Adding a
model here without a matching migration (or vice versa) fails the drift test in
``backend/tests/db/test_migrations.py``.

Tables land slice by slice per ``docs/DATA_MODEL.md`` §12: :class:`Meta` in
slice 005, :class:`Aircraft` and :class:`Sighting` in slice 009. Track,
reception-statistics and sighting-event tables belong to slice 052 and are
deliberately absent here.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import REAL, CheckConstraint, ForeignKey, Index, Integer, Text, text
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
    * **reception statistics** — slice 052; the columns exist now so the
      sighting row's shape is stable, and stay at their defaults until then.
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
