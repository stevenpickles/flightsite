"""SQLite for the activity feed: the facts producers judge, and the rows written.

Two halves, and the seam between them is the point. Above this module
everything is :mod:`flightsite.activity.facts` values, so
:mod:`flightsite.activity.producers` can be checked without a database; below
it everything is SQL. The same split slice 031 draws between its fold and its
repository, for the same reason.

Which writer this is
--------------------

:meth:`ActivityRepository.record` takes
:meth:`~flightsite.db.engine.Database.writer_session` — the process's single
serialized writer (ADR-0001, ADR-0008) — rather than joining the sighting
worker's transaction. That is slice 031's and slice 033's decision repeated,
and for the same reason: an activity row is not a sighting row, and folding
its write into the cycle that persists sightings would give a feed bug the
ability to fail a sighting transaction. The lock still guarantees the two are
never interleaved.

Idempotency, in SQL
-------------------

Both writes are conflict-tolerant by construction:

* events go in with ``ON CONFLICT (dedupe_key) DO NOTHING ... RETURNING id``,
  so the ids that come back are exactly the rows this call created — which is
  what the service publishes to the WebSocket. A replayed event returns
  nothing and broadcasts nothing.
* milestones go in with ``ON CONFLICT (key) DO NOTHING``, so the first claim
  wins and every later one is a no-op.

Neither needs a read-then-write, so neither has a window in which two passes
could both decide a fact was new.

Query costs
-----------

Every read here is bounded by something small, and where it is not, it is a
startup cost paid once:

* :meth:`observations` is keyed on a handful of sighting ids.
* :meth:`first_sightings` and :meth:`aircraft_ranks` walk indexes
  (``ix_sightings_aircraft``, the ``aircraft`` primary key).
* :meth:`type_pioneers` is bounded by *airframes of the named types* via
  ``ix_amr_type``, not by sightings.
* :meth:`military_first` walks ``ix_sightings_started`` until it meets a
  military airframe, so the service only calls it once it has seen one — see
  :mod:`flightsite.activity.service`.
* :meth:`longest_sighting` is a full scan of ``sightings`` and is called
  **once per boot**, to seed a record the service then carries in memory.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from flightsite.activity.facts import (
    LongestSighting,
    MilitaryFirst,
    ReceiverRecords,
    SightingObservation,
)
from flightsite.activity.model import ActivityBatch, StoredActivityEvent
from flightsite.db import (
    ActivityEvent,
    Aircraft,
    AircraftClassification,
    AircraftMetadataResolved,
    Database,
    LifetimeStat,
    Milestone,
    Sighting,
)
from flightsite.receiver_metrics.model import (
    LIFETIME_BUSIEST_DAY,
    LIFETIME_BUSIEST_DAY_COUNT,
    LIFETIME_MAX_RANGE_AT_MS,
    LIFETIME_MAX_RANGE_BEARING,
    LIFETIME_MAX_RANGE_ICAO24,
    LIFETIME_MAX_RANGE_NM,
    LIFETIME_MAX_SIMULTANEOUS,
)

#: ``meta`` key holding the highest ``sightings.id`` the service has examined.
#: A boot that finds it absent sets it to the present rather than to zero, so
#: an install upgrading into this slice announces nothing about its history.
SCAN_WATERMARK_KEY: Final = "activity.scanned_sighting_id"

#: Sightings examined by one catch-up pass. A service stopped for a week comes
#: back to thousands of rows; walking them a few thousand at a time keeps each
#: pass's transaction short and lets the writer lock go between them.
DEFAULT_SCAN_LIMIT: Final = 2_000


def _payload(raw: str | None) -> Mapping[str, Any]:
    """Decode a stored payload, treating anything unreadable as empty.

    A payload is presentation detail: a row whose JSON cannot be parsed is
    still a real event with a real type and moment, and dropping it from the
    feed would hide history to protect a rendering nicety.
    """
    if not raw:
        return {}
    try:
        decoded: Any = json.loads(raw)
    except ValueError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _encode(payload: Mapping[str, Any]) -> str | None:
    """Encode a payload for storage; an empty payload stores as ``NULL``."""
    return json.dumps(dict(payload), separators=(",", ":")) if payload else None


@dataclass(frozen=True, slots=True)
class ActivityRepository:
    """Reads and writes the activity feed's two tables."""

    database: Database

    # ------------------------------------------------------------- the writes

    async def record(self, batch: ActivityBatch) -> tuple[StoredActivityEvent, ...]:
        """Write a batch, and return only the events that were actually new.

        Milestones are claimed first, so a milestone row and the event
        announcing it land in one transaction and a crash between them is not
        possible. The returned events are the ones the WebSocket should
        broadcast: a pass that re-derived facts it had already recorded returns
        an empty tuple and says nothing.
        """
        if batch.empty:
            return ()
        async with self.database.writer_session() as session:
            for milestone in batch.milestones:
                await session.execute(
                    sqlite_insert(Milestone)
                    .values(
                        key=milestone.key,
                        achieved_ms=milestone.achieved_ms,
                        aircraft_id=milestone.aircraft_id,
                        value_num=milestone.value_num,
                        payload_json=_encode(milestone.payload),
                    )
                    .on_conflict_do_nothing(index_elements=[Milestone.key])
                )
            inserted: list[int] = []
            for event in batch.events:
                event_id = await session.scalar(
                    sqlite_insert(ActivityEvent)
                    .values(
                        ts_ms=event.ts_ms,
                        type=event.type.value,
                        severity=event.severity.value,
                        aircraft_id=event.aircraft_id,
                        sighting_id=event.sighting_id,
                        payload_json=_encode(event.payload),
                        dedupe_key=event.dedupe_key,
                    )
                    .on_conflict_do_nothing(index_elements=[ActivityEvent.dedupe_key])
                    .returning(ActivityEvent.id)
                )
                if event_id is not None:
                    inserted.append(event_id)
            if not inserted:
                return ()
            # Read back inside the same transaction: the ICAO address comes
            # from `aircraft`, not from the payload, so the feed and the
            # aircraft page can never name different addresses for one event.
            rows = (
                await session.execute(self._event_query().where(ActivityEvent.id.in_(inserted)))
            ).all()
        return tuple(sorted(self._stored(rows), key=lambda event: event.id))

    async def milestone_keys(self) -> frozenset[str]:
        """Every milestone already claimed. Tens of rows; read once at start."""
        async with self.database.read_session() as session:
            return frozenset(await session.scalars(select(Milestone.key)))

    # -------------------------------------------------------------- the facts

    async def max_sighting_id(self) -> int:
        """The highest ``sightings.id``, or 0 on an install with no history."""
        async with self.database.read_session() as session:
            return await session.scalar(select(func.max(Sighting.id))) or 0

    async def sighting_ids_after(self, watermark: int, *, limit: int) -> tuple[int, ...]:
        """Up to ``limit`` sighting ids above ``watermark``, in id order.

        The catch-up scan. It walks the primary key, so "what has happened
        since I last looked" costs a b-tree seek plus the rows it returns,
        whether the service was stopped for a second or for a fortnight.
        """
        statement = (
            select(Sighting.id).where(Sighting.id > watermark).order_by(Sighting.id).limit(limit)
        )
        async with self.database.read_session() as session:
            return tuple(await session.scalars(statement))

    async def observations(self, sighting_ids: Sequence[int]) -> tuple[SightingObservation, ...]:
        """Everything the producers need about the named sightings.

        Four reads rather than one join, because the questions have different
        shapes: the sighting rows themselves, which sighting is each airframe's
        first, where each new airframe sits in the all-time order, and which
        airframe was the first of its type. Folding them into one statement
        would mean a correlated subquery per row and a plan that changes with
        the batch's contents.
        """
        if not sighting_ids:
            return ()
        async with self.database.read_session() as session:
            rows = (
                await session.execute(
                    select(
                        Sighting.id,
                        Sighting.aircraft_id,
                        Sighting.started_ms,
                        Sighting.ended_ms,
                        Sighting.duration_ms,
                        Aircraft.icao24,
                        Aircraft.first_seen_ms,
                        AircraftMetadataResolved.registration,
                        AircraftMetadataResolved.type_code,
                        AircraftMetadataResolved.model,
                        AircraftMetadataResolved.operator_name,
                        AircraftClassification.military,
                    )
                    .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
                    .outerjoin(
                        AircraftMetadataResolved,
                        AircraftMetadataResolved.icao24 == Aircraft.icao24,
                    )
                    .outerjoin(
                        AircraftClassification,
                        AircraftClassification.icao24 == Aircraft.icao24,
                    )
                    .where(Sighting.id.in_(sighting_ids))
                    .order_by(Sighting.id)
                )
            ).all()
            if not rows:
                return ()

            aircraft_ids = {int(row.aircraft_id) for row in rows}
            firsts = await self._first_sightings(session, aircraft_ids)
            first_ids = {
                int(row.aircraft_id)
                for row in rows
                if firsts.get(int(row.aircraft_id)) == int(row.id)
            }
            ranks = await self._aircraft_ranks(session, first_ids)
            type_codes = {row.type_code for row in rows if row.type_code is not None}
            pioneers = await self._type_pioneers(session, type_codes)

        observations: list[SightingObservation] = []
        for row in rows:
            aircraft_id = int(row.aircraft_id)
            first_ever = firsts.get(aircraft_id) == int(row.id)
            pioneer_ms = pioneers.get(row.type_code) if row.type_code is not None else None
            observations.append(
                SightingObservation(
                    sighting_id=int(row.id),
                    aircraft_id=aircraft_id,
                    icao24=row.icao24,
                    started_ms=int(row.started_ms),
                    ended_ms=None if row.ended_ms is None else int(row.ended_ms),
                    duration_ms=None if row.duration_ms is None else int(row.duration_ms),
                    first_ever=first_ever,
                    rank=ranks.get(aircraft_id),
                    registration=row.registration,
                    type_code=row.type_code,
                    model=row.model,
                    operator=row.operator_name,
                    first_of_type=(
                        first_ever
                        and pioneer_ms is not None
                        and int(row.first_seen_ms) == pioneer_ms
                    ),
                    military=bool(row.military),
                )
            )
        return tuple(observations)

    @staticmethod
    async def _first_sightings(
        session: AsyncSession, aircraft_ids: Iterable[int]
    ) -> dict[int, int]:
        """Each airframe's earliest sighting id — its first-ever sighting."""
        ids = list(aircraft_ids)
        if not ids:
            return {}
        rows = (
            await session.execute(
                select(Sighting.aircraft_id, func.min(Sighting.id))
                .where(Sighting.aircraft_id.in_(ids))
                .group_by(Sighting.aircraft_id)
            )
        ).all()
        return {int(aircraft_id): int(first) for aircraft_id, first in rows}

    @staticmethod
    async def _aircraft_ranks(session: AsyncSession, aircraft_ids: Iterable[int]) -> dict[int, int]:
        """1-based position of each airframe among every airframe ever heard.

        Ranked by ``aircraft.id`` rather than by ``first_seen_ms``: the row is
        created the moment an unheard airframe's first sighting opens, so ids
        *are* first-heard order, and a surrogate key cannot drift the way a
        timestamp corrected by a later import could.
        """
        ids = list(aircraft_ids)
        if not ids:
            return {}
        older = aliased(Aircraft)
        rank = (
            select(func.count())
            .select_from(older)
            .where(older.id <= Aircraft.id)
            .scalar_subquery()
            .label("rank")
        )
        rows = (await session.execute(select(Aircraft.id, rank).where(Aircraft.id.in_(ids)))).all()
        return {int(aircraft_id): int(value) for aircraft_id, value in rows}

    @staticmethod
    async def _type_pioneers(session: AsyncSession, type_codes: Iterable[str]) -> dict[str, int]:
        """First-heard moment of the earliest airframe of each named type.

        Bounded by airframes of those types (``ix_amr_type``), never by
        sightings: "has this receiver heard a B738 before" is a question about
        airframes, and asking it of the sightings table would scale with
        history instead of with the fleet.
        """
        codes = list(type_codes)
        if not codes:
            return {}
        rows = (
            await session.execute(
                select(AircraftMetadataResolved.type_code, func.min(Aircraft.first_seen_ms))
                .join(Aircraft, Aircraft.icao24 == AircraftMetadataResolved.icao24)
                .where(AircraftMetadataResolved.type_code.in_(codes))
                .group_by(AircraftMetadataResolved.type_code)
            )
        ).all()
        return {code: int(first) for code, first in rows if first is not None}

    async def military_first(self) -> MilitaryFirst | None:
        """The earliest sighting of a military-classified airframe, if any.

        Called only once the service has actually seen a military airframe and
        only while the ``first_military`` milestone is unclaimed — see
        :mod:`flightsite.activity.service`. It walks ``ix_sightings_started``
        from the beginning of history, which is the right shape for the
        question (*the first one ever*) and the wrong shape to run every pass.
        """
        statement = (
            select(
                Sighting.id,
                Sighting.aircraft_id,
                Sighting.started_ms,
                Aircraft.icao24,
                AircraftMetadataResolved.registration,
                AircraftMetadataResolved.type_code,
                AircraftMetadataResolved.model,
            )
            .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
            .join(AircraftClassification, AircraftClassification.icao24 == Aircraft.icao24)
            .outerjoin(AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24)
            .where(AircraftClassification.military == 1)
            .order_by(Sighting.started_ms, Sighting.id)
            .limit(1)
        )
        async with self.database.read_session() as session:
            row = (await session.execute(statement)).first()
        if row is None:
            return None
        return MilitaryFirst(
            sighting_id=int(row.id),
            aircraft_id=int(row.aircraft_id),
            icao24=row.icao24,
            started_ms=int(row.started_ms),
            registration=row.registration,
            type_code=row.type_code,
            model=row.model,
        )

    async def receiver_records(self) -> ReceiverRecords:
        """The rolling records ``lifetime_stats`` holds (§6.4, slice 033)."""
        async with self.database.read_session() as session:
            rows = (
                await session.execute(
                    select(LifetimeStat.key, LifetimeStat.value_num, LifetimeStat.value_text)
                )
            ).all()
        numbers = {key: value for key, value, _ in rows if value is not None}
        texts = {key: value for key, _, value in rows if value is not None}
        at_ms = numbers.get(LIFETIME_MAX_RANGE_AT_MS)
        return ReceiverRecords(
            max_range_nm=numbers.get(LIFETIME_MAX_RANGE_NM),
            max_range_at_ms=None if at_ms is None else int(at_ms),
            max_range_icao24=texts.get(LIFETIME_MAX_RANGE_ICAO24),
            max_range_bearing_deg=numbers.get(LIFETIME_MAX_RANGE_BEARING),
            busiest_day=texts.get(LIFETIME_BUSIEST_DAY),
            busiest_day_count=numbers.get(LIFETIME_BUSIEST_DAY_COUNT),
            max_simultaneous=numbers.get(LIFETIME_MAX_SIMULTANEOUS),
        )

    async def longest_sighting(self) -> LongestSighting | None:
        """The longest closed sighting ever. One full scan, once per boot."""
        statement = (
            select(Sighting.id, Sighting.duration_ms, Sighting.ended_ms)
            .where(Sighting.duration_ms.is_not(None), Sighting.ended_ms.is_not(None))
            .order_by(Sighting.duration_ms.desc())
            .limit(1)
        )
        async with self.database.read_session() as session:
            row = (await session.execute(statement)).first()
        if row is None:
            return None
        return LongestSighting(
            sighting_id=int(row.id),
            duration_ms=int(row.duration_ms),
            ended_ms=int(row.ended_ms),
        )

    # --------------------------------------------------------------- the feed

    @staticmethod
    def _event_query() -> Select[Any]:
        """The one ``SELECT`` behind both the feed and the broadcast read-back."""
        return (
            select(
                ActivityEvent.id,
                ActivityEvent.ts_ms,
                ActivityEvent.type,
                ActivityEvent.severity,
                ActivityEvent.aircraft_id,
                ActivityEvent.sighting_id,
                ActivityEvent.payload_json,
                Aircraft.icao24,
            )
            .select_from(ActivityEvent)
            .outerjoin(Aircraft, Aircraft.id == ActivityEvent.aircraft_id)
        )

    @staticmethod
    def _stored(rows: Iterable[Any]) -> list[StoredActivityEvent]:
        return [
            StoredActivityEvent(
                id=int(row.id),
                ts_ms=int(row.ts_ms),
                type=row.type,
                severity=row.severity,
                aircraft_id=None if row.aircraft_id is None else int(row.aircraft_id),
                icao24=row.icao24,
                sighting_id=None if row.sighting_id is None else int(row.sighting_id),
                payload=_payload(row.payload_json),
            )
            for row in rows
        ]

    async def list_events(
        self,
        *,
        limit: int,
        offset: int = 0,
        types: Sequence[str] | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
    ) -> tuple[StoredActivityEvent, ...]:
        """One page of the feed, newest first — ``docs/API.md`` §3.9.

        Ordered by ``ts_ms`` descending with ``id`` descending as the
        tie-break, because a burst of events written by one pass shares a
        moment and a page boundary through the middle of one must not be able
        to repeat or skip a row.
        """
        statement = self._event_query()
        if types:
            statement = statement.where(ActivityEvent.type.in_(list(types)))
        if from_ms is not None:
            statement = statement.where(ActivityEvent.ts_ms >= from_ms)
        if to_ms is not None:
            statement = statement.where(ActivityEvent.ts_ms <= to_ms)
        statement = (
            statement.order_by(ActivityEvent.ts_ms.desc(), ActivityEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).all()
        return tuple(self._stored(rows))


__all__ = ["DEFAULT_SCAN_LIMIT", "SCAN_WATERMARK_KEY", "ActivityRepository"]
