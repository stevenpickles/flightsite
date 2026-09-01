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

Track storage
-------------

Two of these operations are the transactional sequence ADR-0005 defines.
:meth:`SightingRepository.append_checkpoints` writes the thinned batches that
bound what a power cut costs an open sighting;
:meth:`SightingRepository.close_sighting` reads those rows back, unions them
with whatever the accumulator still holds, simplifies the result, packs it into
one ``sighting_tracks`` row and deletes the checkpoints — all inside the
caller's single transaction, because a track that exists in neither table (or
in both) is not a state this schema should ever be found in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, NamedTuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.db.engine import Database
from flightsite.db.models import (
    Aircraft,
    Sighting,
    SightingEvent,
    SightingTrack,
    SightingTrackCheckpoint,
)
from flightsite.sightings.state import ActiveSighting, PendingEvent
from flightsite.sightings.track_codec import PackedTrack, pack_track, unpack_track
from flightsite.sightings.tracks import TrackSample, simplify
from flightsite.sightings.vocabulary import (
    EMERGENCY_SQUAWKS,
    ClosureReason,
    position_source_code,
    position_source_name,
)


class SightingIds(NamedTuple):
    """Primary keys of a persisted sighting and the airframe it belongs to."""

    aircraft_id: int
    sighting_id: int


class ClosedTrack(NamedTuple):
    """What a sighting's packed track cost, for the close log and for tests."""

    point_count: int
    byte_count: int


@dataclass(frozen=True, slots=True)
class OpenSightingRow:
    """A sighting found open (``ended_ms IS NULL``) at startup.

    Carries the airframe's ``icao24`` and its stored ``last_seen_ms``: the row
    itself records when the sighting *started* but not when the aircraft was
    last heard, and the airframe's last-seen is the best evidence of that
    available.

    ``checkpoint_seq`` / ``checkpoint_ms`` are the high-water marks of the
    sighting's existing checkpoint rows. Without them a restart would restart
    the ``seq`` numbering on top of rows that already exist and re-checkpoint
    every point the live track still holds.
    """

    ids: SightingIds
    icao24: str
    started_ms: int
    last_known_ms: int
    callsign_first: str | None = None
    callsign_last: str | None = None
    squawk_last: str | None = None
    had_emergency: bool = False
    #: Route enrichment already established for this sighting (slice 026). It
    #: has to come back with the rest: a restart that rehydrated without it
    #: would blank a route already written the next time the row flushed.
    origin_ident: str | None = None
    destination_ident: str | None = None
    route_source: str | None = None
    #: Airport inference already recorded for this sighting (slice 027). Comes
    #: back with the rest for the reason the route columns do: a restart that
    #: rehydrated without it would blank an inference already written the next
    #: time the row flushed.
    inferred_airport_ident: str | None = None
    inferred_phase: str | None = None
    #: Alert severity already reached on this sighting (slice 038). Comes back
    #: with the rest for the reason the route columns do, and for one more: it
    #: is what stops a restart mid-sighting from emitting a second
    #: ``alert_matched`` event for an alert the previous process recorded.
    max_alert_severity: str | None = None
    any_position: bool = False
    mlat_used: bool = False
    ground_seen: bool = False
    closest_approach_nm: float | None = None
    max_range_nm: float | None = None
    lowest_alt_ft: int | None = None
    highest_alt_ft: int | None = None
    msg_count: int = 0
    pos_count: int = 0
    rssi_peak_db: float | None = None
    rssi_avg_db: float | None = None
    rssi_min_db: float | None = None
    pos_time_pct: float | None = None
    checkpoint_seq: int = 0
    checkpoint_ms: int | None = None

    def to_accumulator(self) -> ActiveSighting:
        """Rehydrate the accumulator a previous process was maintaining.

        The stored extremes come back without the moments they were set: the
        sighting row keeps the values, and only the ``aircraft`` row keeps
        their ``_ms`` companions. That costs nothing, because a rehydrated
        extreme has by definition already been merged into the lifetime
        records, and the merge replaces a record only on a *strictly* better
        value — so re-merging an equal one cannot blank the moment it carries.

        Three reception statistics need more care than a copy. ``msg_count``
        is a sum of deltas of the decoder's cumulative counter, and the
        counter's last value has no column either — so it comes back as the
        count itself, which is exactly right for the ordinary case where the
        decoder's trackfile began with the sighting, and never worse than the
        alternative of treating the next reading as a first one. ``rssi_avg_db``
        is a mean whose sample count no column carries, so it comes back as a
        prior weighted by ``pos_count`` — the closest stored proxy for how many
        observations went into it, and enough to stop the handful of
        observations after a restart from dominating a mean built over an hour.
        ``pos_time_pct`` comes back as the milliseconds it represented, so the
        percentage keeps accumulating over the whole sighting rather than over
        the part of it this process saw.

        The accumulator starts clean: it holds exactly what the database
        already holds, so there is nothing to write until it is observed again.
        """
        rssi_samples = self.pos_count if self.rssi_avg_db is not None else 0
        elapsed_ms = max(0, self.last_known_ms - self.started_ms)
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
            origin_ident=self.origin_ident,
            destination_ident=self.destination_ident,
            route_source=self.route_source,
            inferred_airport_ident=self.inferred_airport_ident,
            inferred_phase=self.inferred_phase,
            max_alert_severity=self.max_alert_severity,
            # An emergency squawk still standing at restart is not a second
            # episode: deriving this from the stored squawk is what keeps
            # `emergency_start` exactly-once across a process boundary.
            emergency_active=self.squawk_last in EMERGENCY_SQUAWKS,
            any_position=self.any_position,
            mlat_used=self.mlat_used,
            ground_seen=self.ground_seen,
            closest_approach_nm=self.closest_approach_nm,
            max_range_nm=self.max_range_nm,
            lowest_alt_ft=self.lowest_alt_ft,
            highest_alt_ft=self.highest_alt_ft,
            msg_count=self.msg_count,
            # Zero means "the decoder reports no counts": leaving the baseline
            # unset then makes the next reading the first one, which is right.
            messages_seen=self.msg_count or None,
            pos_count=self.pos_count,
            rssi_peak_db=self.rssi_peak_db,
            rssi_min_db=self.rssi_min_db,
            rssi_total_db=(self.rssi_avg_db or 0.0) * rssi_samples,
            rssi_samples=rssi_samples,
            positioned_ms=round((self.pos_time_pct or 0.0) * elapsed_ms / 100.0),
            # The row already accounts for every observation up to this
            # instant, so statistics resume from it: an interval that straddles
            # the restart is measured, and a re-delivered observation from
            # before it is not counted a second time.
            stats_ms=self.last_known_ms,
            checkpoint_seq=self.checkpoint_seq,
            # The live clock's high-water mark is gone with the old process, so
            # the first harvest after a restart re-reads the live track whole
            # and drops what this filters out.
            last_point_ms=self.checkpoint_ms,
            dirty=False,
        )


#: Columns of ``sightings`` this repository maintains from the accumulator.
#:
#: Each name is an attribute of :class:`~flightsite.sightings.state.
#: ActiveSighting` too — ``rssi_avg_db`` and ``pos_time_pct`` as derived
#: properties over the running sums — so the copy is a loop rather than a
#: column list repeated in three places.
_RUNNING_COLUMNS: Final[tuple[str, ...]] = (
    "callsign_first",
    "callsign_last",
    "squawk_last",
    "closest_approach_nm",
    "max_range_nm",
    "lowest_alt_ft",
    "highest_alt_ft",
    # Reception statistics (SPEC §51), written on every flush and at close so
    # a sighting the user is watching shows real numbers, not zeroes.
    "msg_count",
    "pos_count",
    "rssi_peak_db",
    "rssi_avg_db",
    "rssi_min_db",
    "pos_time_pct",
    # Route enrichment (slice 026). Not part of the live stream — the values
    # arrive from an external provider on its own task and are set on the
    # accumulator, which is why they ride the ordinary flush rather than
    # needing a write path of their own. All three stay ``None`` on an install
    # with enrichment switched off, so copying them costs nothing there.
    "origin_ident",
    "destination_ident",
    "route_source",
    # Local airport inference (slice 027). Also not part of the live stream:
    # the airport context service sets these on the accumulator from its own
    # task, so like the route columns they ride the ordinary flush. Both stay
    # ``None`` on an install that has never imported the airport dataset.
    "inferred_airport_ident",
    "inferred_phase",
    # Alert evaluation (slice 038). Also not part of the live stream: the alert
    # engine sets it on the accumulator from its own task, so like the route
    # and inference columns it rides the ordinary flush. ``alert_matches`` is
    # the source of truth; this is the denormalized maximum the sightings list
    # and the daily ``interesting`` rollup read. Stays ``None`` on an install
    # with no rules and no emergency squawks.
    "max_alert_severity",
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
        checkpoints = (
            select(
                SightingTrackCheckpoint.sighting_id.label("sighting_id"),
                func.max(SightingTrackCheckpoint.seq).label("last_seq"),
                func.max(SightingTrackCheckpoint.ts_ms).label("last_ts_ms"),
            )
            .group_by(SightingTrackCheckpoint.sighting_id)
            .subquery()
        )
        statement = (
            select(
                Sighting,
                Aircraft.icao24,
                Aircraft.last_seen_ms,
                checkpoints.c.last_seq,
                checkpoints.c.last_ts_ms,
            )
            .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
            # Outer: a sighting whose aircraft never reported a position has no
            # checkpoint rows at all, and it is still an open sighting.
            .outerjoin(checkpoints, checkpoints.c.sighting_id == Sighting.id)
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
                origin_ident=sighting.origin_ident,
                destination_ident=sighting.destination_ident,
                route_source=sighting.route_source,
                inferred_airport_ident=sighting.inferred_airport_ident,
                inferred_phase=sighting.inferred_phase,
                max_alert_severity=sighting.max_alert_severity,
                any_position=bool(sighting.any_position),
                mlat_used=bool(sighting.mlat_used),
                ground_seen=bool(sighting.ground_seen),
                closest_approach_nm=sighting.closest_approach_nm,
                max_range_nm=sighting.max_range_nm,
                lowest_alt_ft=sighting.lowest_alt_ft,
                highest_alt_ft=sighting.highest_alt_ft,
                msg_count=sighting.msg_count,
                pos_count=sighting.pos_count,
                rssi_peak_db=sighting.rssi_peak_db,
                rssi_avg_db=sighting.rssi_avg_db,
                rssi_min_db=sighting.rssi_min_db,
                pos_time_pct=sighting.pos_time_pct,
                checkpoint_seq=0 if last_seq is None else last_seq + 1,
                checkpoint_ms=last_ts_ms,
            )
            for sighting, icao24, last_seen_ms, last_seq, last_ts_ms in rows
        )

    async def load_track(self, sighting_id: int) -> tuple[TrackSample, ...]:
        """The stored path of a closed sighting, decoded.

        The pack/unpack layer is a repository detail (ADR-0005): callers ask
        for a sighting's points and get points. An empty tuple means the
        sighting kept no path — a Mode S-only aircraft that never reported a
        position, which is a first-class outcome (SPEC §20), not a missing row.
        """
        async with self.database.read_session() as session:
            row = await session.get(SightingTrack, sighting_id)
            if row is None:
                return ()
            return unpack_track(
                PackedTrack(
                    encoding_version=row.encoding_version,
                    point_count=row.point_count,
                    started_ms=row.started_ms,
                    points_blob=row.points_blob,
                )
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

    async def append_checkpoints(
        self,
        session: AsyncSession,
        sighting_id: int,
        rows: Sequence[tuple[int, TrackSample]],
    ) -> None:
        """Append one thinned batch of track points to the checkpoint table.

        Pure inserts, no read: this runs on every flush cycle for every
        positioned aircraft in the sky, and it is the one place in the worker
        whose cost scales with the *update* rate rather than the sighting
        count. The rows are deleted again when the sighting closes.
        """
        session.add_all(
            [
                SightingTrackCheckpoint(
                    sighting_id=sighting_id,
                    seq=seq,
                    ts_ms=sample.ts_ms,
                    lat=sample.latitude,
                    lon=sample.longitude,
                    alt_ft=sample.altitude_ft,
                    gs_kt=sample.ground_speed_kt,
                    track_deg=sample.track_deg,
                    pos_source=position_source_code(sample.position_source),
                )
                for seq, sample in rows
            ]
        )

    async def append_events(
        self, session: AsyncSession, sighting_id: int, events: Sequence[PendingEvent]
    ) -> None:
        """Write the sighting's queued flight-context events (SPEC §52)."""
        session.add_all(
            [
                SightingEvent(
                    sighting_id=sighting_id,
                    ts_ms=event.ts_ms,
                    type=event.type.value,
                    payload_json=event.payload_json,
                )
                for event in events
            ]
        )

    async def close_sighting(
        self,
        session: AsyncSession,
        ids: SightingIds,
        active: ActiveSighting,
        *,
        reason: ClosureReason,
    ) -> ClosedTrack:
        """Close the sighting, pack its track, and fold it into the airframe.

        ``ended_ms`` is the last moment the aircraft was actually heard, not
        the moment the closure gap expired: the sighting is the observation
        period, and the ten minutes of silence that ended it were not part of
        it.

        The track is simplified, packed and written here, and the checkpoint
        rows that fed it are deleted in the same transaction — the sequence
        ADR-0005 makes the writer's responsibility, so that the path exists in
        exactly one of the two tables at every instant a reader could look.
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

        return await self._pack_track(session, ids.sighting_id, active)

    # ------------------------------------------------------------- the track

    async def _pack_track(
        self, session: AsyncSession, sighting_id: int, active: ActiveSighting
    ) -> ClosedTrack:
        samples = await self._collect_points(session, sighting_id, active)
        await session.execute(
            delete(SightingTrackCheckpoint).where(
                SightingTrackCheckpoint.sighting_id == sighting_id
            )
        )
        if not samples:
            # A sighting can legitimately have no path: a Mode S-only aircraft
            # never reports a position. No row is better than a row saying
            # zero points, and `load_track` answers both the same way.
            return ClosedTrack(point_count=0, byte_count=0)

        packed = pack_track(simplify(samples))
        session.add(
            SightingTrack(
                sighting_id=sighting_id,
                encoding_version=packed.encoding_version,
                point_count=packed.point_count,
                started_ms=packed.started_ms,
                points_blob=packed.points_blob,
            )
        )
        return ClosedTrack(point_count=packed.point_count, byte_count=len(packed.points_blob))

    @staticmethod
    async def _collect_points(
        session: AsyncSession, sighting_id: int, active: ActiveSighting
    ) -> tuple[TrackSample, ...]:
        """Every point the sighting has, checkpointed or still in memory.

        The two sources overlap by construction — the accumulator's tail is
        what has *not* been checkpointed — so the union is keyed by timestamp
        and the in-memory sample wins any collision: it is the unthinned
        original of a checkpoint row, never a different observation.

        A sighting adopted at startup has no tail at all, and one that never
        reached a flush has no checkpoints; both work out to the same call.
        """
        statement = (
            select(SightingTrackCheckpoint)
            .where(SightingTrackCheckpoint.sighting_id == sighting_id)
            .order_by(SightingTrackCheckpoint.seq)
        )
        merged = {
            row.ts_ms: TrackSample(
                ts_ms=row.ts_ms,
                latitude=row.lat,
                longitude=row.lon,
                position_source=position_source_name(row.pos_source),
                altitude_ft=row.alt_ft,
                ground_speed_kt=row.gs_kt,
                track_deg=row.track_deg,
            )
            for row in (await session.scalars(statement)).all()
        }
        merged.update({sample.ts_ms: sample for sample in active.pending_points})
        return tuple(merged[ts_ms] for ts_ms in sorted(merged))

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


__all__ = ["ClosedTrack", "OpenSightingRow", "SightingIds", "SightingRepository"]
