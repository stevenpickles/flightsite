"""Persistence for the analytics rollups — the maintenance half of the SQL.

Everything above this module works in :mod:`flightsite.analytics.model` values;
everything below it is SQLite. That split is what lets the fold be
property-tested without a database and the transaction discipline be tested
without arithmetic — the same division slice 033 draws between
:mod:`~flightsite.receiver_metrics.aggregate` and its repository.

The read queries the API serves live next door in
:mod:`flightsite.analytics.queries`; this module is only what maintains the
four tables.

Which writer this is
--------------------

The single-writer discipline (ADR-0001, ADR-0008) is a property of
:meth:`~flightsite.db.engine.Database.writer_session`: it is guarded by an
``asyncio.Lock`` and bound to an engine holding exactly one connection, so
every caller in the process is serialized into one stream of short
transactions. This repository takes that lock like every other writer in
FlightSite — the metadata import, the airport dataset and the receiver metrics
already do — rather than joining the sighting worker's transaction. The
reasoning is slice 033's, and it applies here for the same reason: these four
tables are derived and repairable, the sighting row is not, and folding a
rollup write into the cycle that writes sightings would add a way for an
analytics bug to fail a sighting transaction. What the lock still guarantees is
that a rollup transaction is never interleaved with a sighting one.

Nothing here is ever awaited by ingestion, by the live store or by an API
request. A stalled disk costs the analytics service a delayed rebuild, and the
next pass repeats it.

Transaction boundaries, and why they are where they are
-------------------------------------------------------

* **One day = one transaction.** ``daily_stats``, ``daily_type_stats`` and
  ``daily_operator_stats`` for a day are replaced together, so a reader can
  never see a day whose totals and whose per-type breakdown disagree.
* **Replacement, never accumulation.** The two child tables have their day's
  rows deleted and rewritten, and the parent row is upserted in full. That is
  what makes re-running a rebuild over the same sightings a no-op, and it is
  the only way a type that *stopped* appearing on a day (because a metadata
  correction moved the airframe to a different designator) can disappear from
  the row set.
* **Days are written one transaction each, not one for the batch.** A catch-up
  backfill after an upgrade can be years of days; holding the writer lock for
  all of them would stall sighting persistence for the whole run. One day per
  transaction releases the lock between days — the same reason slice 033
  chunks its prune.
* **``type_stats`` is its own transaction.** It is a single full replacement
  derived from ``aircraft``, unrelated to any one day, and re-deriving it
  inside a day's transaction would make a day's write cost grow with the
  airframe count.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.analytics.model import DayRollup, SightingFact, TypeStat
from flightsite.db import (
    Aircraft,
    AircraftClassification,
    AircraftMetadataResolved,
    DailyOperatorStats,
    DailyStats,
    DailyTypeStats,
    Database,
    Sighting,
    TypeStats,
)

#: ``meta`` key holding the last receiver-local day the rollups are known
#: complete through. Read at startup to bound the backfill; advanced as days
#: close. A `meta` key rather than a column because it is one scalar of
#: application state, which is exactly what ``docs/DATA_MODEL.md`` §2.1's table
#: is for — and because §6.5's table list is closed.
META_KEY_ROLLUP_THROUGH_DAY: Final = "analytics_rollup_through_day"

#: Columns of a ``daily_stats`` row, in §6.5's order.
_DAY_FIELDS: Final[tuple[str, ...]] = (
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


@dataclass(frozen=True, slots=True)
class AnalyticsRepository:
    """Reads sighting ground truth and replaces the §6.5 rollup rows."""

    database: Database

    # -------------------------------------------------------------- the reads

    async def facts_between(self, start_ms: int, end_ms: int) -> tuple[SightingFact, ...]:
        """Every sighting that *started* in ``[start_ms, end_ms)``, as facts.

        One join, driven by ``sightings`` over ``ix_sightings_started``:
        ``aircraft`` for the airframe's first-ever observation, and — LEFT
        JOINed, because most of history has neither — the resolved metadata for
        type and operator group, and the classification row for SPEC §39's
        flags. LEFT JOIN rather than an inner one is what keeps an
        unclassified, unidentified airframe counted in the day's totals with
        its type and operator simply absent (``docs/API.md`` §2.7).
        """
        statement = (
            select(
                Sighting.id,
                Sighting.aircraft_id,
                Sighting.started_ms,
                Sighting.max_range_nm,
                Sighting.max_alert_severity,
                Aircraft.first_seen_ms,
                AircraftMetadataResolved.type_code,
                AircraftMetadataResolved.operator_group_id,
                AircraftClassification.military,
                AircraftClassification.government,
                AircraftClassification.law_enforcement,
            )
            .select_from(Sighting)
            .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
            .outerjoin(AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24)
            .outerjoin(AircraftClassification, AircraftClassification.icao24 == Aircraft.icao24)
            .where(Sighting.started_ms >= start_ms, Sighting.started_ms < end_ms)
            .order_by(Sighting.started_ms)
        )
        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            SightingFact(
                sighting_id=int(row[0]),
                aircraft_id=int(row[1]),
                started_ms=int(row[2]),
                first_seen_ms=int(row[5]),
                max_range_nm=None if row[3] is None else float(row[3]),
                interesting=row[4] is not None,
                military=bool(row[8]),
                government=bool(row[9]),
                law_enforcement=bool(row[10]),
                type_code=row[6],
                operator_group_id=None if row[7] is None else int(row[7]),
            )
            for row in rows
        )

    async def sighting_span_ms(self) -> tuple[int, int] | None:
        """``(earliest, latest)`` ``started_ms``, or ``None`` with no sightings."""
        statement = select(func.min(Sighting.started_ms), func.max(Sighting.started_ms))
        async with self.database.read_session() as session:
            earliest, latest = (await session.execute(statement)).one()
        if earliest is None or latest is None:
            return None
        return int(earliest), int(latest)

    async def stored_days(self) -> set[str]:
        """Every day that already has a ``daily_stats`` row."""
        async with self.database.read_session() as session:
            return {str(day) for day in (await session.scalars(select(DailyStats.day))).all()}

    async def day(self, day: str) -> DayRollup | None:
        """The stored rollup for one day, or ``None`` if it has none.

        The per-type and per-operator breakdowns are *not* loaded: this is the
        maintenance-side read, used to compare a stored row against a freshly
        folded one, and the daily row is what decides whether a write is
        needed.
        """
        async with self.database.read_session() as session:
            row = await session.get(DailyStats, day)
            if row is None:
                return None
            return DayRollup(day=day, **{name: getattr(row, name) for name in _DAY_FIELDS})

    # ------------------------------------------------------------- the writes

    async def replace_day(self, rollup: DayRollup) -> None:
        """Replace one day's three rows with ``rollup``. One transaction.

        A full replacement, never an accumulation — see the module docstring.
        A day that folded to nothing still writes its (all-zero) parent row, so
        "this day was rebuilt and had no traffic" is distinguishable from "this
        day has never been rebuilt", which is what lets the startup repair pass
        recognize a genuinely missing day.
        """
        async with self.database.writer_session() as session:
            await self._write_day(session, rollup)

    async def replace_days(self, rollups: Sequence[DayRollup]) -> None:
        """Replace several days, one transaction each (see the module docstring)."""
        for rollup in rollups:
            await self.replace_day(rollup)

    @staticmethod
    async def _write_day(session: AsyncSession, rollup: DayRollup) -> None:
        statement = sqlite_insert(DailyStats).values(
            {"day": rollup.day, **{name: getattr(rollup, name) for name in _DAY_FIELDS}}
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["day"],
                set_={name: getattr(statement.excluded, name) for name in _DAY_FIELDS},
            )
        )
        await session.execute(delete(DailyTypeStats).where(DailyTypeStats.day == rollup.day))
        if rollup.types:
            await session.execute(
                sqlite_insert(DailyTypeStats).values(
                    [
                        {
                            "day": rollup.day,
                            "type_code": type_code,
                            "sightings": count.sightings,
                            "unique_aircraft": count.unique_aircraft,
                        }
                        for type_code, count in rollup.types.items()
                    ]
                )
            )
        await session.execute(
            delete(DailyOperatorStats).where(DailyOperatorStats.day == rollup.day)
        )
        if rollup.operators:
            await session.execute(
                sqlite_insert(DailyOperatorStats).values(
                    [
                        {
                            "day": rollup.day,
                            "operator_group_id": group_id,
                            "sightings": count.sightings,
                            "unique_aircraft": count.unique_aircraft,
                        }
                        for group_id, count in rollup.operators.items()
                    ]
                )
            )

    # ----------------------------------------------------------- type_stats

    async def derive_type_stats(self) -> tuple[TypeStat, ...]:
        """Re-derive every §6.5 ``type_stats`` row from ``aircraft``.

        Receiver-relative by construction: the driving table is ``aircraft``,
        one row per airframe **this receiver has heard**, so a type designator
        the metadata database knows about but the antenna has never heard has
        no row at all. That is what makes the rarity figures in slice 038 and
        in ``GET /api/v1/analytics/rarity`` a statement about this site.

        Derived rather than accumulated because a type resolves *late*: an
        airframe is heard now and its metadata import lands hours later. An
        accumulator would need its own backfill for that; a derivation is
        simply correct the next time it runs.
        """
        statement = (
            select(
                AircraftMetadataResolved.type_code,
                func.count(Aircraft.id),
                func.sum(Aircraft.sighting_count),
                func.min(Aircraft.first_seen_ms),
                func.max(Aircraft.last_seen_ms),
            )
            .select_from(Aircraft)
            .join(AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24)
            .where(AircraftMetadataResolved.type_code.is_not(None))
            .group_by(AircraftMetadataResolved.type_code)
        )
        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            TypeStat(
                type_code=str(row[0]),
                unique_aircraft=int(row[1]),
                total_sightings=int(row[2] or 0),
                first_seen_ms=int(row[3]),
                last_seen_ms=int(row[4]),
            )
            for row in rows
        )

    async def replace_type_stats(self, stats: Sequence[TypeStat]) -> int:
        """Replace the whole ``type_stats`` table. One transaction.

        A whole-table replacement rather than an upsert per row, because a
        designator can *leave* the set — a metadata correction that reassigns
        the only airframe carrying it — and an upsert would leave the stale row
        behind forever. The table is one row per designator ever heard
        (hundreds), so rewriting it costs less than reasoning about which rows
        went.
        """
        async with self.database.writer_session() as session:
            await session.execute(delete(TypeStats))
            if stats:
                await session.execute(
                    sqlite_insert(TypeStats).values(
                        [
                            {
                                "type_code": stat.type_code,
                                "unique_aircraft": stat.unique_aircraft,
                                "total_sightings": stat.total_sightings,
                                "first_seen_ms": stat.first_seen_ms,
                                "last_seen_ms": stat.last_seen_ms,
                            }
                            for stat in stats
                        ]
                    )
                )
        return len(stats)

    async def type_stats(self) -> tuple[TypeStat, ...]:
        """Every stored ``type_stats`` row, ordered by designator."""
        statement = select(TypeStats).order_by(TypeStats.type_code)
        async with self.database.read_session() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(
            TypeStat(
                type_code=str(row.type_code),
                unique_aircraft=int(row.unique_aircraft),
                total_sightings=int(row.total_sightings),
                first_seen_ms=int(row.first_seen_ms),
                last_seen_ms=int(row.last_seen_ms),
            )
            for row in rows
        )

    # ------------------------------------------------------------ diagnostics

    async def counts(self) -> dict[str, int]:
        """Row counts of the four tables, for tests and later diagnostics."""
        tables: dict[str, Any] = {
            "daily_stats": DailyStats,
            "daily_type_stats": DailyTypeStats,
            "daily_operator_stats": DailyOperatorStats,
            "type_stats": TypeStats,
        }
        async with self.database.read_session() as session:
            return {
                name: int(await session.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in tables.items()
            }


__all__ = ["META_KEY_ROLLUP_THROUGH_DAY", "AnalyticsRepository"]
