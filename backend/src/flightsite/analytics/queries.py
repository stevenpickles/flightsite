"""The read side: ``docs/API.md`` §3.7's seven endpoints, as SQL.

Every query here runs on the request path through
:meth:`~flightsite.db.engine.Database.read_session` (ADR-0001), so none of it
can become a second writer and none of it blocks the persistence worker. The
maintenance side — what keeps the rows these queries read correct — is
:mod:`flightsite.analytics.repository` and :mod:`flightsite.analytics.service`.

Rollups first, sightings only where they must be
------------------------------------------------

The rollup tables exist so a year of analytics is a few hundred row reads
instead of an aggregate over a million sightings, and these queries use them
wherever the figure is *derivable* from them. Two classes of figure are not:

* **Distinct-aircraft counts over a multi-day window.** ``daily_stats`` records
  how many distinct airframes each day saw; summing that across seven days
  counts an aircraft heard on three of them three times. So a windowed
  "unique aircraft" is a real ``COUNT(DISTINCT aircraft_id)`` over
  ``ix_sightings_started``, which is the range scan ``docs/DATA_MODEL.md`` §6.5
  sizes at *"≤ ~45k rows for a 30-day window on a busy receiver"*.
* **Per-airframe rankings.** §6.5 states outright that "most frequently seen
  aircraft" is deliberately not rolled up per (day, aircraft): it is a
  ``GROUP BY aircraft_id`` over the same index.

The whole-history shortcut
--------------------------

§6.5 also names the escape hatch for the one window where those scans would be
a million rows: *"the Since-T0 variant reads ``aircraft.sighting_count``"*. A
window that provably covers every observation this receiver has ever made
(:attr:`~flightsite.analytics.bucketing.Window.whole_history`) needs no scan at
all — one row per airframe already carries its lifetime totals, and one row per
type designator already carries the since-T0 type figures. Every query that has
such a form takes it, keyed on that one flag and on nothing else, so the
``t0`` preset is the *cheapest* preset rather than the most expensive.

Day granularity of the rollup-derived figures
----------------------------------------------

The five presets all begin at a receiver-local midnight, so summing whole days
of rollup over the days a preset touches is exact to the instant. An explicit
``from``/``to`` that begins or ends mid-day is different: the rollup-derived
figures then cover the whole local days the window touches. Every response
therefore carries the window it actually used — bounds *and* day range — rather
than leaving the client to assume.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.analytics.bucketing import Window, local_hour
from flightsite.db import (
    Aircraft,
    AircraftClassification,
    AircraftMetadataResolved,
    DailyOperatorStats,
    DailyStats,
    DailyTypeStats,
    Database,
    OperatorGroup,
    ReceiverMetricDaily,
    ReceiverMetricHourly,
    Sighting,
    TypeStats,
)

#: Default rows in a "top N" list, and the cap on the ``limit`` parameter.
#: A leaderboard, not a paginated table — ``docs/API.md`` §2.4's list envelope
#: belongs to endpoints a client scrolls, and none of §3.7's do.
DEFAULT_TOP_LIMIT: Final = 10
MAX_TOP_LIMIT: Final = 100

#: Lifetime sighting count at or below which an airframe reads as *locally
#: rare* (SPEC §44's "seen fewer than N times", from this receiver's point of
#: view). Two rather than one so a single repeat visit does not immediately
#: stop an airframe being notable.
DEFAULT_RARE_MAX_SIGHTINGS: Final = 2

#: Airframes at or below which a type designator reads as locally rare.
DEFAULT_RARE_MAX_TYPE_AIRCRAFT: Final = 2


@dataclass(frozen=True, slots=True)
class DailyRow:
    """One day of the ``GET /analytics/daily`` series."""

    day: str
    unique_aircraft: int = 0
    new_aircraft: int = 0
    sightings: int = 0
    interesting: int = 0
    military: int = 0
    government: int = 0
    law_enforcement: int = 0
    max_range_nm: float | None = None
    busiest_hour: int | None = None
    #: Slice 033's receiver activity for the same local day (§6.2), or ``None``
    #: where that slice recorded none — a day before metrics existed, or one
    #: the receiver was off for.
    messages_total: int | None = None
    positions_total: int | None = None
    aircraft_max: int | None = None
    receiver_max_range_nm: float | None = None


@dataclass(frozen=True, slots=True)
class Summary:
    """SPEC §59's at-a-glance block, resolved over a window."""

    unique_aircraft: int = 0
    new_aircraft: int = 0
    sightings: int = 0
    interesting: int = 0
    military: int = 0
    government: int = 0
    law_enforcement: int = 0
    max_range_nm: float | None = None
    busiest_hour: int | None = None
    #: Where ``busiest_hour`` came from: ``daily_stats`` for a closed day,
    #: ``receiver_metrics_hourly`` for the day still in progress (§6.5's dual
    #: source), or ``None`` when neither could answer.
    busiest_hour_source: str | None = None
    first_sighting_ms: int | None = None
    last_sighting_ms: int | None = None


@dataclass(frozen=True, slots=True)
class AircraftRank:
    """One row of ``GET /analytics/top-aircraft``."""

    icao24: str
    sightings: int
    first_seen_ms: int
    last_seen_ms: int
    registration: str | None = None
    type_code: str | None = None
    model: str | None = None
    operator_name: str | None = None
    operator_group: str | None = None
    mission_category: str | None = None
    military: bool = False
    government: bool = False
    law_enforcement: bool = False
    max_range_nm: float | None = None


@dataclass(frozen=True, slots=True)
class GroupRank:
    """One row of ``GET /analytics/top-types`` or ``/top-operators``."""

    key: str
    label: str | None
    sightings: int
    unique_aircraft: int
    days_seen: int
    first_seen_ms: int | None = None
    last_seen_ms: int | None = None


@dataclass(frozen=True, slots=True)
class RareType:
    """One locally rare type designator."""

    type_code: str
    unique_aircraft: int
    total_sightings: int
    first_seen_ms: int
    last_seen_ms: int


@dataclass(frozen=True, slots=True)
class Rarity:
    """``GET /analytics/rarity`` — never-seen-before counts and rare lists."""

    never_seen_before: int = 0
    rare_aircraft: tuple[AircraftRank, ...] = ()
    rare_types: tuple[RareType, ...] = ()
    rare_max_sightings: int = DEFAULT_RARE_MAX_SIGHTINGS
    rare_max_type_aircraft: int = DEFAULT_RARE_MAX_TYPE_AIRCRAFT


@dataclass(frozen=True, slots=True)
class ClassificationActivity:
    """``GET /analytics/classification-activity`` — SPEC §58's mil/gov/police view."""

    military: int = 0
    government: int = 0
    law_enforcement: int = 0
    interesting: int = 0
    series: tuple[DailyRow, ...] = field(default_factory=tuple)


#: The metadata/classification columns every airframe payload carries.
_AIRFRAME_COLUMNS: Final[tuple[Any, ...]] = (
    Aircraft.icao24,
    Aircraft.first_seen_ms,
    Aircraft.last_seen_ms,
    Aircraft.max_range_nm,
    AircraftMetadataResolved.registration,
    AircraftMetadataResolved.type_code,
    AircraftMetadataResolved.model,
    AircraftMetadataResolved.operator_name,
    OperatorGroup.name.label("operator_group"),
    AircraftClassification.mission_category,
    AircraftClassification.military,
    AircraftClassification.government,
    AircraftClassification.law_enforcement,
)


def _airframe_join(statement: Select[Any]) -> Select[Any]:
    """LEFT JOIN an ``aircraft``-driven select to metadata and classification.

    LEFT rather than inner throughout: an airframe no metadata source has ever
    heard of is still one this receiver saw, and dropping it from its own
    history would be wrong (``docs/API.md`` §2.7).
    """
    return (
        statement.outerjoin(
            AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24
        )
        .outerjoin(OperatorGroup, OperatorGroup.id == AircraftMetadataResolved.operator_group_id)
        .outerjoin(AircraftClassification, AircraftClassification.icao24 == Aircraft.icao24)
    )


def _rank(row: Any, sightings: int) -> AircraftRank:
    return AircraftRank(
        icao24=str(row.icao24),
        sightings=sightings,
        first_seen_ms=int(row.first_seen_ms),
        last_seen_ms=int(row.last_seen_ms),
        registration=row.registration,
        type_code=row.type_code,
        model=row.model,
        operator_name=row.operator_name,
        operator_group=row.operator_group,
        mission_category=row.mission_category,
        military=bool(row.military),
        government=bool(row.government),
        law_enforcement=bool(row.law_enforcement),
        max_range_nm=None if row.max_range_nm is None else float(row.max_range_nm),
    )


class AnalyticsQueries:
    """Serves ``docs/API.md`` §3.7 from the rollups, falling back to sightings.

    Args:
        database: the application database; every read takes a read session.
        timezone: the receiver's IANA zone, needed only to name the local hour
            of a slice-033 hourly bucket.
    """

    __slots__ = ("_database", "_zone")

    def __init__(self, database: Database, *, timezone: str = "UTC") -> None:
        self._database = database
        self._zone = ZoneInfo(timezone)

    # ---------------------------------------------------------------- daily

    async def daily(self, window: Window) -> tuple[DailyRow, ...]:
        """Per-day counts for the window, joined to slice 033's receiver totals.

        Every day in the window gets a row, including days with no traffic:
        a chart of "aircraft per day" with holes in it would read as missing
        data rather than as a quiet Tuesday, and the zero *is* the measurement.
        """
        days = window.days
        if not days:
            return ()
        async with self._database.read_session() as session:
            rollups = {
                str(row.day): row
                for row in (
                    await session.scalars(select(DailyStats).where(DailyStats.day.in_(days)))
                ).all()
            }
            receiver = {
                str(row.day): row
                for row in (
                    await session.scalars(
                        select(ReceiverMetricDaily).where(ReceiverMetricDaily.day.in_(days))
                    )
                ).all()
            }
        return tuple(self._daily_row(day, rollups.get(day), receiver.get(day)) for day in days)

    @staticmethod
    def _daily_row(day: str, rollup: Any, receiver: Any) -> DailyRow:
        base = (
            DailyRow(day=day)
            if rollup is None
            else DailyRow(
                day=day,
                unique_aircraft=int(rollup.unique_aircraft),
                new_aircraft=int(rollup.new_aircraft),
                sightings=int(rollup.sightings),
                interesting=int(rollup.interesting),
                military=int(rollup.military),
                government=int(rollup.government),
                law_enforcement=int(rollup.law_enforcement),
                max_range_nm=None if rollup.max_range_nm is None else float(rollup.max_range_nm),
                busiest_hour=rollup.busiest_hour,
            )
        )
        if receiver is None:
            return base
        return DailyRow(
            **{
                name: getattr(base, name)
                for name in (
                    "day",
                    "unique_aircraft",
                    "new_aircraft",
                    "sightings",
                    "interesting",
                    "military",
                    "government",
                    "law_enforcement",
                    "max_range_nm",
                    "busiest_hour",
                )
            },
            messages_total=receiver.messages_total,
            positions_total=receiver.positions_total,
            aircraft_max=receiver.aircraft_max,
            receiver_max_range_nm=receiver.max_range_nm,
        )

    async def classification_activity(self, window: Window) -> ClassificationActivity:
        """Military / government / police activity over time (SPEC §58)."""
        series = await self.daily(window)
        return ClassificationActivity(
            military=sum(row.military for row in series),
            government=sum(row.government for row in series),
            law_enforcement=sum(row.law_enforcement for row in series),
            interesting=sum(row.interesting for row in series),
            series=series,
        )

    # -------------------------------------------------------------- summary

    async def summary(self, window: Window) -> Summary:
        """SPEC §59's block over the window.

        ``unique_aircraft`` is a true distinct count — see the module docstring
        for why it cannot be summed out of the rollups — and takes the
        whole-history shortcut when the window allows it. Everything else is a
        sum or a maximum over the window's ``daily_stats`` rows, which are
        exactly the figures §6.5 stores because they *are* summable.
        """
        rows = await self.daily(window)
        unique = await self.unique_aircraft(window)
        busiest, source = await self._busiest_hour(window, rows)
        span = await self._sighting_span(window)
        return Summary(
            unique_aircraft=unique,
            new_aircraft=sum(row.new_aircraft for row in rows),
            sightings=sum(row.sightings for row in rows),
            interesting=sum(row.interesting for row in rows),
            military=sum(row.military for row in rows),
            government=sum(row.government for row in rows),
            law_enforcement=sum(row.law_enforcement for row in rows),
            max_range_nm=max(
                (row.max_range_nm for row in rows if row.max_range_nm is not None), default=None
            ),
            busiest_hour=busiest,
            busiest_hour_source=source,
            first_sighting_ms=span[0],
            last_sighting_ms=span[1],
        )

    async def unique_aircraft(self, window: Window) -> int:
        """Distinct airframes with a sighting that started inside the window.

        The whole-history form is ``COUNT(*) FROM aircraft``: a row there is by
        definition an airframe this receiver has heard at least once (SPEC
        §53), so no scan of ``sightings`` can find one it does not already have.
        """
        if window.empty:
            return 0
        async with self._database.read_session() as session:
            if window.whole_history:
                return int(await session.scalar(select(func.count()).select_from(Aircraft)) or 0)
            statement = select(func.count(func.distinct(Sighting.aircraft_id))).where(
                *self._range(window)
            )
            return int(await session.scalar(statement) or 0)

    async def _sighting_span(self, window: Window) -> tuple[int | None, int | None]:
        """First and last sighting start inside the window (SPEC §58's first/last seen)."""
        if window.empty:
            return None, None
        statement = select(func.min(Sighting.started_ms), func.max(Sighting.started_ms)).where(
            *self._range(window)
        )
        async with self._database.read_session() as session:
            first, last = (await session.execute(statement)).one()
        return (
            None if first is None else int(first),
            None if last is None else int(last),
        )

    async def _busiest_hour(
        self, window: Window, rows: Sequence[DailyRow]
    ) -> tuple[int | None, str | None]:
        """§6.5's dual-source busiest hour.

        A window whose last day has closed reads ``daily_stats.busiest_hour``,
        the finalized value. A window that includes the day still in progress
        cannot: that column is deliberately ``NULL`` until the day ends, so the
        in-progress day's busiest hour comes from slice 033's
        ``receiver_metrics_hourly`` instead — the hour of today whose peak
        simultaneous-aircraft count was highest.

        A multi-day window reports the busiest hour of its **most recent day**
        with an answer, which is what "busiest hour" means on a page showing a
        range: the hour of the day, not an hour of the range.
        """
        for row in reversed(rows):
            if row.busiest_hour is not None:
                return row.busiest_hour, "daily_stats"
        hour = await self._busiest_hour_today(window)
        return (hour, "receiver_metrics_hourly") if hour is not None else (None, None)

    async def _busiest_hour_today(self, window: Window) -> int | None:
        """The in-progress day's busiest hour, from slice 033's hourly table.

        ``receiver_metrics_hourly`` is keyed by **UTC** hour (§6.2), so the
        buckets considered are those that begin inside the window. In a zone
        whose offset is not a whole number of hours the bucket straddling local
        midnight is therefore excluded rather than attributed to a day it is
        only half inside — which is the honest reading of a bucket that spans
        two local days, and costs at most the first half hour of the day.
        """
        if window.empty:
            return None
        statement = (
            select(ReceiverMetricHourly.hour_start_ms, ReceiverMetricHourly.aircraft_max)
            .where(
                ReceiverMetricHourly.hour_start_ms >= window.start_ms,
                ReceiverMetricHourly.hour_start_ms < window.end_ms,
                ReceiverMetricHourly.aircraft_max.is_not(None),
            )
            .order_by(
                ReceiverMetricHourly.aircraft_max.desc(),
                ReceiverMetricHourly.hour_start_ms,
            )
            .limit(1)
        )
        async with self._database.read_session() as session:
            row = (await session.execute(statement)).first()
        if row is None:
            return None
        return local_hour(int(row[0]), self._zone)

    # --------------------------------------------------------- top aircraft

    async def top_aircraft(
        self, window: Window, *, limit: int = DEFAULT_TOP_LIMIT
    ) -> tuple[AircraftRank, ...]:
        """Most frequently seen airframes in the window (SPEC §58).

        Two shapes, per §6.5. Whole history sorts ``aircraft.sighting_count``
        over ``ix_aircraft_sightings`` — no aggregate at all. A bounded window
        groups ``sightings`` by airframe over ``ix_sightings_started`` and then
        joins the winners, which keeps the metadata join to ``limit`` rows
        rather than to every airframe in the range.
        """
        if window.empty or limit < 1:
            return ()
        async with self._database.read_session() as session:
            if window.whole_history:
                statement = _airframe_join(
                    select(*_AIRFRAME_COLUMNS, Aircraft.sighting_count).select_from(Aircraft)
                ).order_by(Aircraft.sighting_count.desc(), Aircraft.icao24)
                rows = (await session.execute(statement.limit(limit))).all()
                return tuple(_rank(row, int(row.sighting_count)) for row in rows)

            counted = (
                await session.execute(
                    select(Sighting.aircraft_id, func.count().label("sightings"))
                    .where(*self._range(window))
                    .group_by(Sighting.aircraft_id)
                    .order_by(func.count().desc(), Sighting.aircraft_id)
                    .limit(limit)
                )
            ).all()
            if not counted:
                return ()
            counts = {int(row[0]): int(row[1]) for row in counted}
            detail = await self._airframes(session, counts)
        return tuple(
            _rank(detail[aircraft_id], count)
            for aircraft_id, count in counts.items()
            if aircraft_id in detail
        )

    @staticmethod
    async def _airframes(session: AsyncSession, counts: dict[int, int]) -> dict[int, Any]:
        statement = _airframe_join(
            select(Aircraft.id, *_AIRFRAME_COLUMNS).select_from(Aircraft)
        ).where(Aircraft.id.in_(list(counts)))
        return {int(row.id): row for row in (await session.execute(statement)).all()}

    # ------------------------------------------------- top types / operators

    async def top_types(
        self, window: Window, *, limit: int = DEFAULT_TOP_LIMIT
    ) -> tuple[GroupRank, ...]:
        """Most frequently seen ICAO type designators (SPEC §58).

        Ranked from ``daily_type_stats`` — the rollup exists precisely so this
        does not scan ``sightings`` — with ``days_seen`` falling out of the same
        grouping. The distinct-airframe figure cannot be summed out of daily
        rows (an airframe heard on three days appears in three of them), so it
        is counted exactly, once, for the ranked designators only.
        """
        if window.whole_history:
            return await self._whole_history_types(limit)
        return await self._windowed_groups(
            window,
            limit=limit,
            day_column=DailyTypeStats.day,
            key_column=DailyTypeStats.type_code,
            model=DailyTypeStats,
            fact_key=AircraftMetadataResolved.type_code,
            labels={},
        )

    async def top_operators(
        self, window: Window, *, limit: int = DEFAULT_TOP_LIMIT
    ) -> tuple[GroupRank, ...]:
        """Most common curated operator groups (SPEC §58).

        The same shape as :meth:`top_types` over ``daily_operator_stats``, with
        the group's display name resolved from ``operator_groups`` for the
        ranked ids only. There is no whole-history shortcut here — §6.5 gives
        types a since-T0 table and operators none — so the since-T0 preset
        takes the same path as any other window, over ``daily_operator_stats``
        rows that are one per (day, group) and therefore already small.
        """
        statement = select(OperatorGroup.id, OperatorGroup.name)
        async with self._database.read_session() as session:
            rows = (await session.execute(statement)).all()
        labels = {int(row.id): str(row.name) for row in rows}
        return await self._windowed_groups(
            window,
            limit=limit,
            day_column=DailyOperatorStats.day,
            key_column=DailyOperatorStats.operator_group_id,
            model=DailyOperatorStats,
            fact_key=AircraftMetadataResolved.operator_group_id,
            labels=labels,
        )

    async def _whole_history_types(self, limit: int) -> tuple[GroupRank, ...]:
        """Since-T0 type ranking straight off ``type_stats`` (§6.5)."""
        if limit < 1:
            return ()
        statement = (
            select(TypeStats)
            .order_by(TypeStats.total_sightings.desc(), TypeStats.type_code)
            .limit(limit)
        )
        async with self._database.read_session() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(
            GroupRank(
                key=str(row.type_code),
                label=str(row.type_code),
                sightings=int(row.total_sightings),
                unique_aircraft=int(row.unique_aircraft),
                days_seen=0,
                first_seen_ms=int(row.first_seen_ms),
                last_seen_ms=int(row.last_seen_ms),
            )
            for row in rows
        )

    async def _windowed_groups(
        self,
        window: Window,
        *,
        limit: int,
        day_column: Any,
        key_column: Any,
        model: Any,
        fact_key: Any,
        labels: dict[int, str],
    ) -> tuple[GroupRank, ...]:
        """Rank one daily breakdown table over a window, then count distincts."""
        days = window.days
        if not days or limit < 1:
            return ()
        async with self._database.read_session() as session:
            ranked = (
                await session.execute(
                    select(
                        key_column,
                        func.sum(model.sightings).label("sightings"),
                        func.count().label("days_seen"),
                    )
                    .where(day_column.in_(days))
                    .group_by(key_column)
                    .order_by(func.sum(model.sightings).desc(), key_column)
                    .limit(limit)
                )
            ).all()
            if not ranked:
                return ()
            keys = [row[0] for row in ranked]
            unique = await self._distinct_by_key(session, window, fact_key, keys)
        return tuple(
            GroupRank(
                key=str(row[0]),
                label=labels.get(row[0], str(row[0])) if labels else str(row[0]),
                sightings=int(row[1]),
                unique_aircraft=unique.get(row[0], 0),
                days_seen=int(row[2]),
            )
            for row in ranked
        )

    @staticmethod
    async def _distinct_by_key(
        session: AsyncSession, window: Window, fact_key: Any, keys: Sequence[Any]
    ) -> dict[Any, int]:
        """Exact distinct-airframe counts for the ranked keys, over the window."""
        statement = (
            select(fact_key, func.count(func.distinct(Sighting.aircraft_id)))
            .select_from(Sighting)
            .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
            .join(AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24)
            .where(
                Sighting.started_ms >= window.start_ms,
                Sighting.started_ms < window.end_ms,
                fact_key.in_(list(keys)),
            )
            .group_by(fact_key)
        )
        return {row[0]: int(row[1]) for row in (await session.execute(statement)).all()}

    # --------------------------------------------------------------- rarity

    async def rarity(
        self,
        window: Window,
        *,
        limit: int = DEFAULT_TOP_LIMIT,
        max_sightings: int = DEFAULT_RARE_MAX_SIGHTINGS,
        max_type_aircraft: int = DEFAULT_RARE_MAX_TYPE_AIRCRAFT,
    ) -> Rarity:
        """Never-seen-before counts and the locally rare lists (SPEC §58, §44).

        *Never seen before* is counted from ``aircraft.first_seen_ms`` over
        ``ix_aircraft_first_seen`` rather than summed out of ``new_aircraft``:
        the two agree for a preset, and this one stays exact for an explicit
        mid-day window too.

        Both rare lists are restricted to what the window actually contained.
        "Rare aircraft" with no bound on when they were heard would be the same
        list every day forever, which is a catalogue, not an observation.
        """
        if window.empty:
            return Rarity(
                rare_max_sightings=max_sightings, rare_max_type_aircraft=max_type_aircraft
            )
        async with self._database.read_session() as session:
            never_seen = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Aircraft)
                    .where(
                        Aircraft.first_seen_ms >= window.start_ms,
                        Aircraft.first_seen_ms < window.end_ms,
                    )
                )
                or 0
            )
            rare_rows = (
                await session.execute(
                    _airframe_join(
                        select(*_AIRFRAME_COLUMNS, Aircraft.sighting_count).select_from(Aircraft)
                    )
                    .where(
                        Aircraft.sighting_count <= max_sightings,
                        Aircraft.last_seen_ms >= window.start_ms,
                        Aircraft.last_seen_ms < window.end_ms,
                    )
                    .order_by(Aircraft.sighting_count, Aircraft.last_seen_ms.desc())
                    .limit(max(limit, 0))
                )
            ).all()
            type_rows = (
                await session.scalars(
                    select(TypeStats)
                    .where(
                        TypeStats.unique_aircraft <= max_type_aircraft,
                        TypeStats.last_seen_ms >= window.start_ms,
                    )
                    .order_by(TypeStats.unique_aircraft, TypeStats.last_seen_ms.desc())
                    .limit(max(limit, 0))
                )
            ).all()
        return Rarity(
            never_seen_before=never_seen,
            rare_aircraft=tuple(_rank(row, int(row.sighting_count)) for row in rare_rows),
            rare_types=tuple(
                RareType(
                    type_code=str(row.type_code),
                    unique_aircraft=int(row.unique_aircraft),
                    total_sightings=int(row.total_sightings),
                    first_seen_ms=int(row.first_seen_ms),
                    last_seen_ms=int(row.last_seen_ms),
                )
                for row in type_rows
            ),
            rare_max_sightings=max_sightings,
            rare_max_type_aircraft=max_type_aircraft,
        )

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _range(window: Window) -> tuple[ColumnElement[bool], ...]:
        """The half-open ``started_ms`` predicate every windowed query shares."""
        return (
            Sighting.started_ms >= window.start_ms,
            Sighting.started_ms < window.end_ms,
        )


__all__ = [
    "DEFAULT_RARE_MAX_SIGHTINGS",
    "DEFAULT_RARE_MAX_TYPE_AIRCRAFT",
    "DEFAULT_TOP_LIMIT",
    "MAX_TOP_LIMIT",
    "AircraftRank",
    "AnalyticsQueries",
    "ClassificationActivity",
    "DailyRow",
    "GroupRank",
    "RareType",
    "Rarity",
    "Summary",
]
