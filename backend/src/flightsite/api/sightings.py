"""The Sightings page's queries — ``docs/API.md`` §3.6, SPEC §57.

Mirrors :mod:`flightsite.api.history`'s shape: every read goes through
:meth:`~flightsite.db.engine.Database.read_session` (ADR-0001), so this module
can never become a second writer and never blocks the persistence worker that
owns these same tables.

One query shape, three callers
-------------------------------

:func:`_joined_query` is the single ``SELECT`` the sightings list, the
per-aircraft sightings list and the Aircraft page's future "recent sightings"
panel all build on: ``sightings`` LEFT JOINed to the resolved metadata,
operator group and classification tables the same way
:mod:`flightsite.api.history` joins them for ``aircraft`` — so a sighting row
and a historical aircraft row describe an airframe's type/operator/
classification identically. ``sightings`` INNER JOINs to ``aircraft`` (never
LEFT): every sighting row has an ``aircraft_id`` by construction (SPEC §18),
so there is nothing to preserve by outer-joining it.

Total is omitted, not computed
--------------------------------

Unlike ``/aircraft`` — bounded by *unique airframes ever heard*, and therefore
cheap to count exactly (see :mod:`flightsite.api.history`) — ``/sightings`` is
bounded by *sighting volume*, which grows without bound over a multi-year
install (SPEC §65: sightings are retained indefinitely). §2.4 names
``/sightings`` the canonical case for the allowance to omit ``total``
entirely, so this module never issues the ``COUNT(*)`` history does; a client
pages until a page comes back short of ``limit``.

Sighting detail's path: two sources, one shape
-------------------------------------------------

A closed sighting's path lives packed in ``sighting_tracks``, decoded through
:mod:`flightsite.sightings.track_codec` — reused directly via
:class:`~flightsite.sightings.repository.SightingRepository.load_track` rather
than reimplemented here, so there is exactly one decoder for that format. An
*open* sighting has no ``sighting_tracks`` row yet (it is written once, at
close): its path so far is the checkpointed tail in
``sighting_track_checkpoints`` — the same crash-recovery record ADR-0005
already keeps durable while the sighting is open — decoded by
:meth:`SightingsRepository._load_checkpoints` into the same
:class:`~flightsite.sightings.tracks.TrackSample` shape, so the serializer
never has to know which source a given sighting's path came from.

Which sorts an index covers
----------------------------

``ix_sightings_started`` covers the documented default sort key directly;
``ix_sightings_aircraft`` (a composite on ``(aircraft_id, started_ms)``)
covers the ``icao`` filter — including the per-aircraft sightings endpoint,
which is that filter used alone — combined with `started_at` ordering. The
partial index ``ix_sightings_open`` (``ended_ms IS NULL``) keeps the ``open``
filter cheap regardless of history.

``max_range_nm`` joined them in rev 0013 as ``ix_sightings_max_range``
(``(max_range_nm, id)``, the sort key plus this module's pagination
tiebreaker): slice 050 measured that sort at 8.0 s over 1.64M sightings, an
unbounded cost on a table retained indefinitely. Both directions read it —
forward for ``asc``, backward for ``desc``. The descending plan still names a
temporary B-tree "for last term of order by", because ``Sighting.id`` breaks
ties ascending in *both* directions and a reverse walk hands ``id`` back
descending; that sorts only within groups of equal ranges, not the table.

``duration_s`` and ``closest_approach_nm`` sorts, and the ``interesting``
filter, still carry no index and fall back to SQLite scanning the filtered
result. That is a write-cost decision rather than an oversight: every index on
``sightings`` is maintained on the INSERT *and* on each 30-second flush that
rewrites an open sighting's running columns, and a second sort index measured
~2.6x the baseline per-sighting write cost again (rev 0013's docstring carries
the numbers; issue #115). :mod:`tests.api.test_sightings_perf` is the sanity
check against a large fixture — sighting volume being the scale ``/sightings``
actually has to answer at.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal

from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.engine import RowMapping

from flightsite.db import Database
from flightsite.db.models import (
    Aircraft,
    AircraftClassification,
    AircraftMetadataResolved,
    OperatorGroup,
    Sighting,
    SightingEvent,
    SightingTrackCheckpoint,
)
from flightsite.sightings import SightingRepository, TrackSample
from flightsite.sightings.vocabulary import position_source_name

#: §3.6's documented sort keys, mapped to the column each one orders by.
SORT_COLUMNS: Final[Mapping[str, Any]] = {
    "started_at": Sighting.started_ms,
    "duration_s": Sighting.duration_ms,
    "closest_approach_nm": Sighting.closest_approach_nm,
    "max_range_nm": Sighting.max_range_nm,
}

#: §3.6's documented default.
DEFAULT_SORT: Final[Literal["started_at"]] = "started_at"
DEFAULT_ORDER: Final[Literal["desc"]] = "desc"

#: Every column the list row payload needs.
_LIST_COLUMNS: Final[tuple[Any, ...]] = (
    Sighting.id,
    Sighting.started_ms,
    Sighting.ended_ms,
    Sighting.duration_ms,
    Sighting.closure_reason,
    Sighting.callsign_last,
    Sighting.closest_approach_nm,
    Sighting.max_range_nm,
    Sighting.lowest_alt_ft,
    Sighting.highest_alt_ft,
    Sighting.pos_count,
    Sighting.had_emergency,
    Sighting.max_alert_severity,
    Aircraft.icao24,
    AircraftMetadataResolved.registration,
    AircraftMetadataResolved.registration_src,
    AircraftMetadataResolved.type_code,
    AircraftMetadataResolved.type_code_src,
    AircraftMetadataResolved.model,
    AircraftMetadataResolved.model_src,
    AircraftMetadataResolved.operator_name,
    AircraftMetadataResolved.operator_src,
    OperatorGroup.name.label("operator_group"),
    AircraftClassification.military,
    AircraftClassification.military_src,
    AircraftClassification.military_conf,
    AircraftClassification.government,
    AircraftClassification.government_src,
    AircraftClassification.government_conf,
    AircraftClassification.law_enforcement,
    AircraftClassification.law_enforcement_src,
    AircraftClassification.law_enforcement_conf,
    AircraftClassification.mission_category,
    AircraftClassification.mission_src,
    AircraftClassification.mission_conf,
    AircraftClassification.icon_category,
)

#: Every column the detail payload needs, beyond the events/path queries.
_DETAIL_COLUMNS: Final[tuple[Any, ...]] = (
    Sighting.id,
    Sighting.started_ms,
    Sighting.ended_ms,
    Sighting.duration_ms,
    Sighting.closure_reason,
    Sighting.callsign_last,
    Sighting.squawk_last,
    Sighting.origin_ident,
    Sighting.destination_ident,
    Sighting.route_source,
    Sighting.rssi_peak_db,
    Sighting.rssi_avg_db,
    Sighting.rssi_min_db,
    Sighting.msg_count,
    Sighting.pos_count,
    Sighting.pos_time_pct,
    Sighting.closest_approach_nm,
    Sighting.max_range_nm,
    Sighting.lowest_alt_ft,
    Sighting.highest_alt_ft,
    Aircraft.icao24,
)


def _joined_query() -> Select[Any]:
    """The shared ``sightings`` → aircraft → resolved metadata → classification join.

    ``sightings`` drives the join and INNER JOINs to ``aircraft`` (see the
    module docstring); resolved metadata, operator group and classification
    stay LEFT JOINed exactly as :func:`flightsite.api.history._joined_query`
    joins them, so an airframe with no resolved metadata or classification
    still produces a row, with ``null`` fields (§2.7).
    """
    return (
        select(*_LIST_COLUMNS)
        .select_from(Sighting)
        .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
        .outerjoin(AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24)
        .outerjoin(OperatorGroup, OperatorGroup.id == AircraftMetadataResolved.operator_group_id)
        .outerjoin(AircraftClassification, AircraftClassification.icao24 == Aircraft.icao24)
    )


def _filters(
    *,
    icao: str | None,
    from_ms: int | None,
    to_ms: int | None,
    interesting: bool | None,
    open_only: bool | None,
) -> list[ColumnElement[bool]]:
    """§3.6's documented filters, plus ``open`` (see the module docstring)."""
    conditions: list[ColumnElement[bool]] = []
    if icao is not None:
        conditions.append(Aircraft.icao24 == icao)
    if from_ms is not None:
        conditions.append(Sighting.started_ms >= from_ms)
    if to_ms is not None:
        conditions.append(Sighting.started_ms <= to_ms)
    if interesting:
        conditions.append(Sighting.max_alert_severity.is_not(None))
    if open_only:
        conditions.append(Sighting.ended_ms.is_(None))
    return conditions


class SightingsRepository:
    """Reads the Sightings page's list and detail queries through the database."""

    __slots__ = ("_database", "_tracks")

    def __init__(self, database: Database) -> None:
        self._database = database
        # Reused for the one thing it already does correctly: decoding a
        # closed sighting's packed track (see the module docstring).
        self._tracks = SightingRepository(database)

    # ------------------------------------------------------------------ list

    async def list_sightings(
        self,
        *,
        limit: int,
        offset: int,
        sort: str = DEFAULT_SORT,
        order: str = DEFAULT_ORDER,
        icao: str | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
        interesting: bool | None = None,
        open_only: bool | None = None,
    ) -> Sequence[RowMapping]:
        """One page of the sightings log — chronological by default (§3.6).

        Args:
            sort: one of :data:`SORT_COLUMNS`'s keys — validated by the
                caller (the endpoint's ``Literal`` query parameter).
            order: ``"asc"`` or ``"desc"``.
        """
        conditions = _filters(
            icao=icao, from_ms=from_ms, to_ms=to_ms, interesting=interesting, open_only=open_only
        )
        column = SORT_COLUMNS[sort]
        direction = column.asc() if order == "asc" else column.desc()

        filtered = _joined_query().where(*conditions) if conditions else _joined_query()
        # A stable tiebreaker, exactly as `flightsite.api.history` uses
        # `Aircraft.icao24` — ascending regardless of the primary direction,
        # so paginating a tied sort key never repeats or skips a row.
        query = filtered.order_by(direction, Sighting.id.asc()).limit(limit).offset(offset)

        async with self._database.read_session() as session:
            return (await session.execute(query)).mappings().all()

    # ---------------------------------------------------------------- detail

    async def get_sighting(self, sighting_id: int) -> RowMapping | None:
        """The joined row for one sighting, or ``None`` if it doesn't exist."""
        query = (
            select(*_DETAIL_COLUMNS)
            .select_from(Sighting)
            .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
            .where(Sighting.id == sighting_id)
        )
        async with self._database.read_session() as session:
            return (await session.execute(query)).mappings().first()

    async def get_events(self, sighting_id: int) -> Sequence[RowMapping]:
        """The sighting's event timeline, oldest first (SPEC §52).

        ``SightingEvent.id`` breaks a tie between two events the worker
        emitted at the same millisecond (a callsign and a squawk change on
        the same observation), so the timeline is always in the order they
        were decided rather than an arbitrary one.
        """
        query = (
            select(SightingEvent.ts_ms, SightingEvent.type, SightingEvent.payload_json)
            .where(SightingEvent.sighting_id == sighting_id)
            .order_by(SightingEvent.ts_ms, SightingEvent.id)
        )
        async with self._database.read_session() as session:
            return (await session.execute(query)).mappings().all()

    async def get_path(self, sighting_id: int, *, is_open: bool) -> tuple[TrackSample, ...]:
        """The sighting's path — decoded, timestamp-ordered — from the right source.

        Args:
            is_open: ``True`` (``ended_at`` is still ``null``) reads the
                checkpointed tail; ``False`` decodes the packed
                ``sighting_tracks`` row. See the module docstring.
        """
        if is_open:
            return await self._load_checkpoints(sighting_id)
        return await self._tracks.load_track(sighting_id)

    async def _load_checkpoints(self, sighting_id: int) -> tuple[TrackSample, ...]:
        query = (
            select(
                SightingTrackCheckpoint.ts_ms,
                SightingTrackCheckpoint.lat,
                SightingTrackCheckpoint.lon,
                SightingTrackCheckpoint.alt_ft,
                SightingTrackCheckpoint.gs_kt,
                SightingTrackCheckpoint.track_deg,
                SightingTrackCheckpoint.pos_source,
            )
            .where(SightingTrackCheckpoint.sighting_id == sighting_id)
            .order_by(SightingTrackCheckpoint.seq)
        )
        async with self._database.read_session() as session:
            rows = (await session.execute(query)).all()
        return tuple(
            TrackSample(
                ts_ms=row.ts_ms,
                latitude=row.lat,
                longitude=row.lon,
                position_source=position_source_name(row.pos_source),
                altitude_ft=row.alt_ft,
                ground_speed_kt=row.gs_kt,
                track_deg=row.track_deg,
            )
            for row in rows
        )


__all__ = [
    "DEFAULT_ORDER",
    "DEFAULT_SORT",
    "SORT_COLUMNS",
    "SightingsRepository",
]
