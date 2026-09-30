"""``GET /api/v1/overhead`` — "What was that?" (roadmap slice 090, issue #233).

Which aircraft passed closest to the receiver within ``window`` minutes either
side of a moment? This module finds the candidate sightings and their stored
points; :mod:`flightsite.sightings.overhead` measures the points. It is a
single-moment lookup over what history already stores — SPEC §79 keeps
animated historical playback out of scope — and every answer is a stored
**closest position fix**, never an interpolated position (see that module's
docstring for why, and for how distance is measured).

Mirrors :mod:`flightsite.api.sightings`' shape: every read goes through
:meth:`~flightsite.db.engine.Database.read_session` (ADR-0001), so this can
never become a second writer or hold up the persistence worker.

Candidates: two indexed reads, no new index
-------------------------------------------

A sighting is a candidate when its span overlaps ``[from, to]``. ``sightings``
carries no index on ``ended_ms`` for closed rows — only the partial
``ix_sightings_open`` over the open set — and adding one would cost a second
index rewrite on every 30-second flush of every open sighting (the write cost
issue #115 measured; see :mod:`flightsite.api.sightings`). So the overlap is
answered as two reads that the existing indexes serve directly:

1. **Closed or open, started recently** — a range read of
   ``ix_sightings_started`` over ``[from - CANDIDATE_LOOKBACK_MS, to]``, with
   ``ended_ms >= from`` checked on the rows it finds. The lookback is what
   bounds the read: a sighting only overlaps the window if it started before
   ``to``, and one that started more than :data:`CANDIDATE_LOOKBACK_MS` before
   ``from`` would have had to be received without a ten-minute gap
   (``sighting.close_s``'s default) for all that time. That is a parked,
   transmitting aircraft, not something that flew over; the lookback is the
   stated limit of the lookup rather than an accident of it.
2. **Still open** — ``ix_sightings_open``, the handful of rows that have not
   closed, however long ago they started, filtered to ``started_ms <= to``.

The union costs one index range proportional to a day of traffic — about
1 500 rows at ``docs/DATA_MODEL.md`` §9's Scenario A — whatever the length of
history, which is what keeps it inside the analytics query budget on a
three-year database (``docs/PERFORMANCE.md``, ``analytics_query_ms``).

Decoding: only what could still win
-----------------------------------

A closed sighting's points live in one packed blob per sighting
(``sighting_tracks``, ADR-0005), which SQL cannot look inside, so each
candidate's track is decoded in Python. Candidates are decoded in order of a
**lower bound** on how close they could possibly have come, in small batches,
and decoding stops once ``limit`` results are in hand and no remaining
candidate could beat the worst of them:

* a closed sighting's bound is its ``closest_approach_nm`` — the closest
  *ground* distance over every position the live stream saw. The stored
  track is a subset of those positions and the ranked distance is never less
  than the ground distance, so no stored fix can come closer than that;
* an open sighting's running ``closest_approach_nm`` is flushed on the same
  cadence as its checkpoints but not in lockstep with them, so it is not
  trusted as a bound and an open sighting is always decoded (bound ``0``);
  so is any sighting with no recorded closest approach.

At most :data:`MAX_CANDIDATES` candidates are considered — the ones with the
best bounds — which only a window over pathological traffic can reach, and
the response's ``truncated`` flag says when it happened.

Open sightings are read from ``sighting_track_checkpoints``, the durable tail
the worker appends on its flush cadence — never from the live store — so the
last flush interval of a sighting in progress (about 30 s) is not yet visible
here. That is the stored record answering a question about the stored record.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

import structlog
from sqlalchemy import Select, or_, select

from flightsite.api.serializers import BEARING_DECIMALS, DISTANCE_DECIMALS, iso_utc
from flightsite.db import Database, from_epoch_ms
from flightsite.db.models import (
    Aircraft,
    AircraftMetadataResolved,
    Sighting,
    SightingTrack,
    SightingTrackCheckpoint,
)
from flightsite.ingest import Position
from flightsite.sightings.overhead import ClosestFix, closest_fix
from flightsite.sightings.track_codec import PackedTrack, UnsupportedTrackEncoding, unpack_track
from flightsite.sightings.tracks import TrackSample
from flightsite.sightings.vocabulary import position_source_name

logger = structlog.get_logger(__name__)

MINUTE_MS: Final = 60_000

#: ``window`` bounds, in minutes either side of ``at``. An hour either side
#: is already "what flew over this afternoon" rather than "what was that?";
#: the UI offers 5, 10 and 30.
DEFAULT_WINDOW_MINUTES: Final = 10
MAX_WINDOW_MINUTES: Final = 60

#: ``limit`` bounds: a short ranked list, not a log (that is ``/sightings``).
DEFAULT_OVERHEAD_LIMIT: Final = 10
MAX_OVERHEAD_LIMIT: Final = 50

#: How far before the window a candidate may have started — see the module
#: docstring's "Candidates". Twenty-four hours of continuous reception.
CANDIDATE_LOOKBACK_MS: Final = 24 * 60 * MINUTE_MS

#: The most candidates one lookup considers (module docstring, "Decoding").
MAX_CANDIDATES: Final = 2_000

#: Tracks fetched and decoded per round of the bounded search.
DECODE_BATCH: Final = 16

#: The one method this endpoint answers with, echoed in every response so a
#: client can say so beside the numbers (roadmap slice 090's acceptance
#: criterion: results say "closest position fix").
METHOD: Final = "closest_position_fix"

#: The ``reason`` an empty answer carries when there is nothing to measure
#: from (``docs/API.md`` §2.7: unknown is ``null`` or empty, not an error).
REASON_RECEIVER_UNSET: Final = "receiver_location_unset"


@dataclass(frozen=True, slots=True)
class Candidate:
    """A sighting overlapping the window, with the bound it is decoded in."""

    sighting_id: int
    is_open: bool
    lower_bound_nm: float


@dataclass(frozen=True, slots=True)
class Identity:
    """Who a sighting was: address, callsign and resolved metadata."""

    icao24: str
    callsign: str | None
    registration: str | None
    aircraft_type: str | None
    model: str | None
    operator: str | None


@dataclass(frozen=True, slots=True)
class OverheadPass:
    """One ranked result: a sighting, its closest stored fix, and its identity."""

    sighting_id: int
    is_open: bool
    fix: ClosestFix
    identity: Identity


@dataclass(frozen=True, slots=True)
class OverheadResult:
    """What one lookup found, and how much work finding it took."""

    passes: tuple[OverheadPass, ...]
    candidates: int
    decoded: int
    truncated: bool


def candidate_order(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Best bound first; the sighting id breaks ties so the order is total."""
    return sorted(candidates, key=lambda c: (c.lower_bound_nm, c.sighting_id))


def rank_key(sighting_id: int, fix: ClosestFix) -> tuple[float, int, int]:
    """How results are ordered: distance, then the earlier fix, then the id."""
    return (fix.distance_nm, fix.ts_ms, sighting_id)


# ------------------------------------------------------------------ statements
#
# Module-level so ``tests/perf/storage/test_overhead.py`` plans exactly the
# statements the endpoint issues rather than hand-copied SQL that could drift.

_CANDIDATE_COLUMNS: Final = (Sighting.id, Sighting.ended_ms, Sighting.closest_approach_nm)


def recent_query(from_ms: int, to_ms: int) -> Select[Any]:
    """Candidate read 1: a bounded range of ``ix_sightings_started``.

    Ordered by the decode bound and capped at one past
    :data:`MAX_CANDIDATES`, so a cut-off is detectable and keeps the best
    bounds.
    """
    return (
        select(*_CANDIDATE_COLUMNS)
        .where(
            Sighting.started_ms >= from_ms - CANDIDATE_LOOKBACK_MS,
            Sighting.started_ms <= to_ms,
            or_(Sighting.ended_ms.is_(None), Sighting.ended_ms >= from_ms),
            Sighting.any_position == 1,
        )
        .order_by(Sighting.closest_approach_nm.asc().nulls_first(), Sighting.id)
        .limit(MAX_CANDIDATES + 1)
    )


def open_query(to_ms: int) -> Select[Any]:
    """Candidate read 2: every still-open sighting, via ``ix_sightings_open``."""
    return select(*_CANDIDATE_COLUMNS).where(
        Sighting.ended_ms.is_(None),
        Sighting.started_ms <= to_ms,
        Sighting.any_position == 1,
    )


def tracks_query(sighting_ids: Sequence[int]) -> Select[Any]:
    """Closed sightings' packed tracks, by primary key."""
    return select(
        SightingTrack.sighting_id,
        SightingTrack.encoding_version,
        SightingTrack.point_count,
        SightingTrack.started_ms,
        SightingTrack.points_blob,
    ).where(SightingTrack.sighting_id.in_(sighting_ids))


def checkpoints_query(sighting_ids: Sequence[int], from_ms: int, to_ms: int) -> Select[Any]:
    """Open sightings' checkpointed points inside the window, by primary key."""
    return (
        select(
            SightingTrackCheckpoint.sighting_id,
            SightingTrackCheckpoint.ts_ms,
            SightingTrackCheckpoint.lat,
            SightingTrackCheckpoint.lon,
            SightingTrackCheckpoint.alt_ft,
            SightingTrackCheckpoint.pos_source,
        )
        .where(
            SightingTrackCheckpoint.sighting_id.in_(sighting_ids),
            SightingTrackCheckpoint.ts_ms >= from_ms,
            SightingTrackCheckpoint.ts_ms <= to_ms,
        )
        .order_by(SightingTrackCheckpoint.sighting_id, SightingTrackCheckpoint.seq)
    )


class OverheadRepository:
    """Answers ``GET /api/v1/overhead`` from the running database."""

    __slots__ = ("_database",)

    def __init__(self, database: Database) -> None:
        self._database = database

    async def closest_passes(
        self,
        *,
        receiver: Position,
        from_ms: int,
        to_ms: int,
        limit: int,
        antenna_height_ft: float | None = None,
    ) -> OverheadResult:
        """The ``limit`` sightings whose stored fixes came closest in ``[from_ms, to_ms]``."""
        candidates, truncated = await self.candidates(from_ms=from_ms, to_ms=to_ms)
        ordered = candidate_order(candidates)

        found: dict[int, ClosestFix] = {}
        open_ids = {candidate.sighting_id for candidate in ordered if candidate.is_open}
        decoded = 0
        for start in range(0, len(ordered), DECODE_BATCH):
            batch = ordered[start : start + DECODE_BATCH]
            if len(found) >= limit:
                worst = sorted(rank_key(sid, fix) for sid, fix in found.items())[limit - 1]
                if batch[0].lower_bound_nm > worst[0]:
                    break
            paths = await self.paths(
                [c.sighting_id for c in batch if not c.is_open],
                [c.sighting_id for c in batch if c.is_open],
                from_ms=from_ms,
                to_ms=to_ms,
            )
            decoded += len(batch)
            for sighting_id, samples in paths.items():
                fix = closest_fix(
                    samples,
                    receiver,
                    from_ms=from_ms,
                    to_ms=to_ms,
                    antenna_height_ft=antenna_height_ft,
                )
                if fix is not None:
                    found[sighting_id] = fix

        winners = sorted(found.items(), key=lambda item: rank_key(*item))[:limit]
        identities = await self.identities([sighting_id for sighting_id, _ in winners])
        passes = tuple(
            OverheadPass(
                sighting_id=sighting_id,
                is_open=sighting_id in open_ids,
                fix=fix,
                identity=identities[sighting_id],
            )
            for sighting_id, fix in winners
            if sighting_id in identities
        )
        return OverheadResult(
            passes=passes, candidates=len(ordered), decoded=decoded, truncated=truncated
        )

    # ------------------------------------------------------------ candidates

    async def candidates(self, *, from_ms: int, to_ms: int) -> tuple[list[Candidate], bool]:
        """Sightings with a position whose span overlaps ``[from_ms, to_ms]``.

        The two indexed reads of the module docstring, merged by id. Returns
        the candidates and whether :data:`MAX_CANDIDATES` cut the list short.
        """
        async with self._database.read_session() as session:
            recent_rows = (await session.execute(recent_query(from_ms, to_ms))).all()
            open_rows = (await session.execute(open_query(to_ms))).all()

        truncated = len(recent_rows) > MAX_CANDIDATES
        by_id: dict[int, Candidate] = {}
        for row in (*recent_rows[:MAX_CANDIDATES], *open_rows):
            is_open = row.ended_ms is None
            bound = 0.0 if is_open or row.closest_approach_nm is None else row.closest_approach_nm
            by_id[int(row.id)] = Candidate(
                sighting_id=int(row.id), is_open=is_open, lower_bound_nm=float(bound)
            )
        return list(by_id.values()), truncated

    # ----------------------------------------------------------------- paths

    async def paths(
        self,
        closed_ids: Sequence[int],
        open_ids: Sequence[int],
        *,
        from_ms: int,
        to_ms: int,
    ) -> dict[int, tuple[TrackSample, ...]]:
        """Stored points for one batch: packed tracks and checkpointed tails.

        Checkpoints are filtered to the window in SQL, since they are plain
        rows; a packed track can only be decoded whole and is filtered by
        :func:`~flightsite.sightings.overhead.closest_fix`. A track this build
        cannot decode is skipped with a warning rather than failing the
        lookup: one unreadable blob must not hide every other answer.
        """
        result: dict[int, tuple[TrackSample, ...]] = {}
        async with self._database.read_session() as session:
            if closed_ids:
                tracks = (await session.execute(tracks_query(closed_ids))).all()
                for row in tracks:
                    try:
                        result[int(row.sighting_id)] = unpack_track(
                            PackedTrack(
                                encoding_version=row.encoding_version,
                                point_count=row.point_count,
                                started_ms=row.started_ms,
                                points_blob=row.points_blob,
                            )
                        )
                    except UnsupportedTrackEncoding as exc:
                        logger.warning(
                            "overhead_track_undecodable",
                            sighting_id=int(row.sighting_id),
                            error=str(exc),
                        )
            if open_ids:
                checkpoints = (
                    await session.execute(checkpoints_query(open_ids, from_ms, to_ms))
                ).all()
                tails: dict[int, list[TrackSample]] = {}
                for point in checkpoints:
                    tails.setdefault(int(point.sighting_id), []).append(
                        TrackSample(
                            ts_ms=point.ts_ms,
                            latitude=point.lat,
                            longitude=point.lon,
                            position_source=position_source_name(point.pos_source),
                            altitude_ft=point.alt_ft,
                        )
                    )
                result.update({key: tuple(value) for key, value in tails.items()})
        return result

    # ------------------------------------------------------------- identity

    async def identities(self, sighting_ids: Sequence[int]) -> dict[int, Identity]:
        """Address, callsign and resolved metadata for the winners only.

        Joined after ranking rather than for every candidate: the metadata
        is only ever shown for the handful of rows the response returns.
        Field names follow :class:`~flightsite.api.schemas.SightingRow`.
        """
        if not sighting_ids:
            return {}
        query = (
            select(
                Sighting.id,
                Sighting.callsign_last,
                Aircraft.icao24,
                AircraftMetadataResolved.registration,
                AircraftMetadataResolved.type_code,
                AircraftMetadataResolved.model,
                AircraftMetadataResolved.operator_name,
            )
            .select_from(Sighting)
            .join(Aircraft, Aircraft.id == Sighting.aircraft_id)
            .outerjoin(AircraftMetadataResolved, AircraftMetadataResolved.icao24 == Aircraft.icao24)
            .where(Sighting.id.in_(sighting_ids))
        )
        async with self._database.read_session() as session:
            rows = (await session.execute(query)).all()
        return {
            int(row.id): Identity(
                icao24=row.icao24,
                callsign=row.callsign_last,
                registration=row.registration,
                aircraft_type=row.type_code,
                model=row.model,
                operator=row.operator_name,
            )
            for row in rows
        }


#: Coordinate decimals in the payload: the packed track's own 1e-5 degree resolution.
COORD_DECIMALS: Final = 5


def pass_payload(item: OverheadPass) -> dict[str, Any]:
    """One :class:`~flightsite.api.schemas.OverheadPassRow`."""
    fix = item.fix
    who = item.identity
    return {
        "sighting_id": item.sighting_id,
        "icao": who.icao24,
        "callsign": who.callsign,
        "registration": who.registration,
        "aircraft_type": who.aircraft_type,
        "model": who.model,
        "operator": who.operator,
        "open": item.is_open,
        "fix_at": iso_utc(from_epoch_ms(fix.ts_ms)),
        "lat": round(fix.latitude, COORD_DECIMALS),
        "lon": round(fix.longitude, COORD_DECIMALS),
        "altitude_ft": fix.altitude_ft,
        "distance_nm": round(fix.distance_nm, DISTANCE_DECIMALS),
        "distance_kind": fix.distance_kind,
        "ground_distance_nm": round(fix.ground_distance_nm, DISTANCE_DECIMALS),
        "bearing_deg": round(fix.bearing_deg, BEARING_DECIMALS),
        "position_source": fix.position_source,
    }


def overhead_payload(
    *,
    at_ms: int,
    window_minutes: int,
    result: OverheadResult | None,
) -> dict[str, Any]:
    """The :class:`~flightsite.api.schemas.OverheadResponse` body.

    ``result`` is ``None`` when there was no receiver location to measure
    from: the window is still echoed, and the empty answer carries
    :data:`REASON_RECEIVER_UNSET` rather than being an error (§2.7).
    """
    half_ms = window_minutes * MINUTE_MS
    return {
        "at": iso_utc(from_epoch_ms(at_ms)),
        "window_minutes": window_minutes,
        "window_start": iso_utc(from_epoch_ms(at_ms - half_ms)),
        "window_end": iso_utc(from_epoch_ms(at_ms + half_ms)),
        "method": METHOD,
        "receiver_configured": result is not None,
        "reason": None if result is not None else REASON_RECEIVER_UNSET,
        "candidates": 0 if result is None else result.candidates,
        "truncated": False if result is None else result.truncated,
        "items": [] if result is None else [pass_payload(item) for item in result.passes],
    }


__all__ = [
    "CANDIDATE_LOOKBACK_MS",
    "COORD_DECIMALS",
    "DECODE_BATCH",
    "DEFAULT_OVERHEAD_LIMIT",
    "DEFAULT_WINDOW_MINUTES",
    "MAX_CANDIDATES",
    "MAX_OVERHEAD_LIMIT",
    "MAX_WINDOW_MINUTES",
    "METHOD",
    "MINUTE_MS",
    "REASON_RECEIVER_UNSET",
    "Candidate",
    "Identity",
    "OverheadPass",
    "OverheadRepository",
    "OverheadResult",
    "candidate_order",
    "checkpoints_query",
    "open_query",
    "overhead_payload",
    "pass_payload",
    "rank_key",
    "recent_query",
    "tracks_query",
]
