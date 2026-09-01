"""SQL for the sighting lifecycle, written through the single writer session.

Every statement here runs on a session the caller supplies, never one this
module opens. That is deliberate: ADR-0008 asks for *batched short
transactions*, so the worker opens exactly one writer transaction per cycle and
performs all of that cycle's opens, flushes and closes inside it. A repository
that opened its own session per operation would turn one transaction into
twenty and take the writer lock twenty times.

Reads are the one exception — :meth:`SightingRepository.load_open_sightings`
runs on a read session, because startup recovery is a query, not a write.

The worker is the sole writer (ADR-0001), which is why these methods read a row
and merge it in Python rather than encoding every extreme as a conditional
``UPDATE``. Nothing else can modify these rows between the read and the write,
and the resulting code says plainly what "farthest detection" means.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.db.engine import Database
from flightsite.db.models import Aircraft, Sighting
from flightsite.sightings.state import ActiveSighting
from flightsite.sightings.vocabulary import ClosureReason


class SightingIds(NamedTuple):
    """Primary keys of a persisted sighting and the airframe it belongs to."""

    aircraft_id: int
    sighting_id: int


@dataclass(frozen=True, slots=True)
class OpenSightingRow:
    """A sighting found open (``ended_ms IS NULL``) at startup.

    Carries the airframe's ``icao24`` and its stored ``last_seen_ms``: the row
    itself records when the sighting *started* but not when the aircraft was
    last heard, and until slice 052's track checkpoints exist the airframe's
    last-seen is the best evidence of that available.
    """

    ids: SightingIds
    icao24: str
    started_ms: int
    last_known_ms: int
    callsign_first: str | None = None
    callsign_last: str | None = None
    squawk_last: str | None = None
    had_emergency: bool = False
    any_position: bool = False
    mlat_used: bool = False
    ground_seen: bool = False
    closest_approach_nm: float | None = None
    max_range_nm: float | None = None
    lowest_alt_ft: int | None = None
    highest_alt_ft: int | None = None

    def to_accumulator(self) -> ActiveSighting:
        """Rehydrate the accumulator a previous process was maintaining.

        The stored extremes come back without the moments they were set: the
        sighting row keeps the values, and only the ``aircraft`` row keeps
        their ``_ms`` companions. That costs nothing, because a rehydrated
        extreme has by definition already been merged into the lifetime
        records, and the merge replaces a record only on a *strictly* better
        value — so re-merging an equal one cannot blank the moment it carries.

        The accumulator starts clean: it holds exactly what the database
        already holds, so there is nothing to write until it is observed again.
        """
        return ActiveSighting(
            icao=self.icao24,
            started_ms=self.started_ms,
            last_seen_ms=self.last_known_ms,
            aircraft_id=self.ids.aircraft_id,
            sighting_id=self.ids.sighting_id,
            callsign_first=self.callsign_first,
            callsign_last=self.callsign_last,
            squawk_last=self.squawk_last,
            had_emergency=self.had_emergency,
            any_position=self.any_position,
            mlat_used=self.mlat_used,
            ground_seen=self.ground_seen,
            closest_approach_nm=self.closest_approach_nm,
            max_range_nm=self.max_range_nm,
            lowest_alt_ft=self.lowest_alt_ft,
            highest_alt_ft=self.highest_alt_ft,
            dirty=False,
        )


#: Columns of ``sightings`` this slice maintains from the live stream. Route
#: enrichment (026), airport inference (027), reception statistics (052) and
#: alert outcomes (038) own the rest and are never written here.
_RUNNING_COLUMNS: Final[tuple[str, ...]] = (
    "callsign_first",
    "callsign_last",
    "squawk_last",
    "closest_approach_nm",
    "max_range_nm",
    "lowest_alt_ft",
    "highest_alt_ft",
)


def _better(current: float | None, candidate: float | None, *, larger: bool) -> bool:
    """Whether ``candidate`` replaces ``current`` as an extreme."""
    if candidate is None:
        return False
    if current is None:
        return True
    return candidate > current if larger else candidate < current


@dataclass(frozen=True, slots=True)
class SightingRepository:
    """Persistence operations for ``aircraft`` and ``sightings``."""

    database: Database

    # ------------------------------------------------------------------ reads

    async def load_open_sightings(self) -> tuple[OpenSightingRow, ...]:
        """Every sighting left open, oldest first.

        In steady state this is empty on a fresh start and small after a
        restart — the partial index ``ix_sightings_open`` makes it a scan of
        the open set rather than of the history.
        """
        statement = (
            select(Sighting, Aircraft.icao24, Aircraft.last_seen_ms)
            .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
            .where(Sighting.ended_ms.is_(None))
            .order_by(Sighting.started_ms)
        )
        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            OpenSightingRow(
                ids=SightingIds(aircraft_id=sighting.aircraft_id, sighting_id=sighting.id),
                icao24=icao24,
                started_ms=sighting.started_ms,
                last_known_ms=max(sighting.started_ms, last_seen_ms),
                callsign_first=sighting.callsign_first,
                callsign_last=sighting.callsign_last,
                squawk_last=sighting.squawk_last,
                had_emergency=bool(sighting.had_emergency),
                any_position=bool(sighting.any_position),
                mlat_used=bool(sighting.mlat_used),
                ground_seen=bool(sighting.ground_seen),
                closest_approach_nm=sighting.closest_approach_nm,
                max_range_nm=sighting.max_range_nm,
                lowest_alt_ft=sighting.lowest_alt_ft,
                highest_alt_ft=sighting.highest_alt_ft,
            )
            for sighting, icao24, last_seen_ms in rows
        )

    # ----------------------------------------------------------------- writes

    async def open_sighting(self, session: AsyncSession, active: ActiveSighting) -> SightingIds:
        """Insert the sighting row, creating or updating its airframe.

        The airframe's ``sighting_count`` is incremented here rather than at
        close so that rarity ("first time ever seen", SPEC §44) is true while
        the aircraft is still overhead — which is the only time the answer is
        interesting.
        """
        aircraft = await session.scalar(select(Aircraft).where(Aircraft.icao24 == active.icao))
        if aircraft is None:
            aircraft = Aircraft(
                icao24=active.icao,
                first_seen_ms=active.started_ms,
                last_seen_ms=active.last_seen_ms,
                sighting_count=0,
                total_observed_ms=0,
            )
            session.add(aircraft)
            active.first_ever = True
        aircraft.first_seen_ms = min(aircraft.first_seen_ms, active.started_ms)
        aircraft.last_seen_ms = max(aircraft.last_seen_ms, active.last_seen_ms)
        aircraft.sighting_count += 1
        self._merge_records(aircraft, active)
        await session.flush()

        sighting = Sighting(
            aircraft_id=aircraft.id,
            started_ms=active.started_ms,
            had_emergency=int(active.had_emergency),
            any_position=int(active.any_position),
            mlat_used=int(active.mlat_used),
            ground_seen=int(active.ground_seen),
            **{name: getattr(active, name) for name in _RUNNING_COLUMNS},
        )
        session.add(sighting)
        await session.flush()
        return SightingIds(aircraft_id=aircraft.id, sighting_id=sighting.id)

    async def flush_sighting(
        self, session: AsyncSession, ids: SightingIds, active: ActiveSighting
    ) -> None:
        """Write the running values of an open sighting and its airframe.

        Lifetime extremes are merged on every flush, not only at close, so a
        record set by an aircraft still overhead is visible immediately and
        survives a crash mid-sighting. ``total_observed_ms`` is deliberately
        *not* accumulated here: it is a sum over closed sightings, and adding
        partial durations would double-count on the next flush.
        """
        sighting = await self._require_sighting(session, ids)
        self._apply_running(sighting, active)
        aircraft = await self._require_aircraft(session, ids)
        aircraft.last_seen_ms = max(aircraft.last_seen_ms, active.last_seen_ms)
        self._merge_records(aircraft, active)

    async def close_sighting(
        self,
        session: AsyncSession,
        ids: SightingIds,
        active: ActiveSighting,
        *,
        reason: ClosureReason,
    ) -> None:
        """Close the sighting and fold it into the airframe's lifetime totals.

        ``ended_ms`` is the last moment the aircraft was actually heard, not
        the moment the closure gap expired: the sighting is the observation
        period, and the ten minutes of silence that ended it were not part of
        it.
        """
        sighting = await self._require_sighting(session, ids)
        self._apply_running(sighting, active)
        sighting.ended_ms = active.last_seen_ms
        sighting.duration_ms = active.duration_ms
        sighting.closure_reason = reason.value

        aircraft = await self._require_aircraft(session, ids)
        aircraft.last_seen_ms = max(aircraft.last_seen_ms, active.last_seen_ms)
        aircraft.total_observed_ms += active.duration_ms
        self._merge_records(aircraft, active)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _apply_running(sighting: Sighting, active: ActiveSighting) -> None:
        for name in _RUNNING_COLUMNS:
            setattr(sighting, name, getattr(active, name))
        sighting.had_emergency = int(active.had_emergency)
        sighting.any_position = int(active.any_position)
        sighting.mlat_used = int(active.mlat_used)
        sighting.ground_seen = int(active.ground_seen)

    @staticmethod
    def _merge_records(aircraft: Aircraft, active: ActiveSighting) -> None:
        """Merge one sighting's extremes into the airframe's lifetime records.

        Each record keeps the moment it was set (SPEC §53), so the pair moves
        together or not at all.
        """
        if _better(aircraft.closest_approach_nm, active.closest_approach_nm, larger=False):
            aircraft.closest_approach_nm = active.closest_approach_nm
            aircraft.closest_approach_ms = active.closest_approach_ms
        if _better(aircraft.max_range_nm, active.max_range_nm, larger=True):
            aircraft.max_range_nm = active.max_range_nm
            aircraft.max_range_ms = active.max_range_ms
        if _better(aircraft.lowest_alt_ft, active.lowest_alt_ft, larger=False):
            aircraft.lowest_alt_ft = active.lowest_alt_ft
            aircraft.lowest_alt_ms = active.lowest_alt_ms
        if _better(aircraft.highest_alt_ft, active.highest_alt_ft, larger=True):
            aircraft.highest_alt_ft = active.highest_alt_ft
            aircraft.highest_alt_ms = active.highest_alt_ms

    @staticmethod
    async def _require_sighting(session: AsyncSession, ids: SightingIds) -> Sighting:
        sighting = await session.get(Sighting, ids.sighting_id)
        if sighting is None:  # pragma: no cover - the worker only cites ids it wrote
            raise LookupError(f"sighting {ids.sighting_id} vanished")
        return sighting

    @staticmethod
    async def _require_aircraft(session: AsyncSession, ids: SightingIds) -> Aircraft:
        aircraft = await session.get(Aircraft, ids.aircraft_id)
        if aircraft is None:  # pragma: no cover - the worker only cites ids it wrote
            raise LookupError(f"aircraft {ids.aircraft_id} vanished")
        return aircraft


__all__ = ["OpenSightingRow", "SightingIds", "SightingRepository"]
