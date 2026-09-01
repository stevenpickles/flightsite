"""Shared fixture-building helpers for the Sightings page's tests.

Rows are inserted directly against the ORM models — the shape the persistence
worker eventually produces — rather than driven through the full
live→sighting→worker pipeline, for the same reason
:mod:`tests.api.aircraft_history_fixtures` gives: a bulk insert costs
milliseconds per row and exercises exactly the tables
:mod:`flightsite.api.sightings` reads, where driving the real pipeline would
cost seconds per sighting.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, insert, select

from flightsite.db import Database
from flightsite.db.models import (
    Aircraft,
    Sighting,
    SightingEvent,
    SightingTrack,
    SightingTrackCheckpoint,
)
from flightsite.sightings.track_codec import pack_track
from flightsite.sightings.tracks import TrackSample
from flightsite.sightings.vocabulary import position_source_code

from .aircraft_history_fixtures import SeedAircraft, seed_aircraft


@dataclass(slots=True)
class SeedSighting:
    """One ``sightings`` row's worth of input, keyed to an airframe by ICAO."""

    icao24: str
    started_ms: int
    ended_ms: int | None = None
    duration_ms: int | None = None
    closure_reason: str | None = None
    callsign_last: str | None = None
    squawk_last: str | None = None
    had_emergency: bool = False
    closest_approach_nm: float | None = None
    max_range_nm: float | None = None
    lowest_alt_ft: int | None = None
    highest_alt_ft: int | None = None
    pos_count: int = 0
    msg_count: int = 0
    rssi_peak_db: float | None = None
    rssi_avg_db: float | None = None
    rssi_min_db: float | None = None
    pos_time_pct: float | None = None
    max_alert_severity: str | None = None
    origin_ident: str | None = None
    destination_ident: str | None = None
    route_source: str | None = None


def _sighting_row(aircraft_id: int, row: SeedSighting) -> dict[str, Any]:
    return {
        "aircraft_id": aircraft_id,
        "started_ms": row.started_ms,
        "ended_ms": row.ended_ms,
        "duration_ms": row.duration_ms,
        "closure_reason": row.closure_reason,
        "callsign_last": row.callsign_last,
        "squawk_last": row.squawk_last,
        "had_emergency": int(row.had_emergency),
        "any_position": 1,
        "mlat_used": 0,
        "ground_seen": 0,
        "closest_approach_nm": row.closest_approach_nm,
        "max_range_nm": row.max_range_nm,
        "lowest_alt_ft": row.lowest_alt_ft,
        "highest_alt_ft": row.highest_alt_ft,
        "pos_count": row.pos_count,
        "msg_count": row.msg_count,
        "rssi_peak_db": row.rssi_peak_db,
        "rssi_avg_db": row.rssi_avg_db,
        "rssi_min_db": row.rssi_min_db,
        "pos_time_pct": row.pos_time_pct,
        "max_alert_severity": row.max_alert_severity,
        "origin_ident": row.origin_ident,
        "destination_ident": row.destination_ident,
        "route_source": row.route_source,
    }


async def seed_sightings(
    database: Database,
    aircraft_rows: Sequence[SeedAircraft],
    sighting_rows: Sequence[SeedSighting],
    *,
    group_ids: dict[str, int] | None = None,
) -> list[int]:
    """Insert ``aircraft_rows`` then ``sighting_rows``; returns the sighting ids in order.

    A single bulk ``INSERT ... executemany`` (mirroring
    :func:`~tests.api.aircraft_history_fixtures.seed_aircraft`) rather than
    one ``add`` + ``flush`` per row — the perf fixture seeds thousands of
    these, and a flush per row would make fixture setup itself the slow part
    of that test. SQLite assigns ``rowid``-backed autoincrement ids
    sequentially within one transaction and no id is ever reused by these
    tests' fresh, per-test databases, so the ids that come back in ``id``
    order correspond 1:1, in order, to ``sighting_rows``.
    """
    await seed_aircraft(database, aircraft_rows, group_ids=group_ids)
    async with database.writer_session() as session:
        icao_id_rows = (await session.execute(select(Aircraft.icao24, Aircraft.id))).all()
        aircraft_ids = {icao24: int(aircraft_id) for icao24, aircraft_id in icao_id_rows}
        before = await session.scalar(select(func.count(Sighting.id))) or 0
        rows = [_sighting_row(aircraft_ids[row.icao24], row) for row in sighting_rows]
        if rows:
            await session.execute(insert(Sighting), rows)
        inserted = (
            (await session.execute(select(Sighting.id).order_by(Sighting.id).offset(before)))
            .scalars()
            .all()
        )
    return list(inserted)


async def seed_track(database: Database, sighting_id: int, samples: Sequence[TrackSample]) -> None:
    """Write a closed sighting's packed track — the same shape the worker's
    close path produces (``flightsite.sightings.repository._pack_track``)."""
    packed = pack_track(samples)
    async with database.writer_session() as session:
        session.add(
            SightingTrack(
                sighting_id=sighting_id,
                encoding_version=packed.encoding_version,
                point_count=packed.point_count,
                started_ms=packed.started_ms,
                points_blob=packed.points_blob,
            )
        )


async def seed_checkpoints(
    database: Database, sighting_id: int, samples: Sequence[TrackSample]
) -> None:
    """Write an open sighting's checkpointed tail (``sighting_track_checkpoints``)."""
    async with database.writer_session() as session:
        session.add_all(
            [
                SightingTrackCheckpoint(
                    sighting_id=sighting_id,
                    seq=index,
                    ts_ms=sample.ts_ms,
                    lat=sample.latitude,
                    lon=sample.longitude,
                    alt_ft=sample.altitude_ft,
                    gs_kt=sample.ground_speed_kt,
                    track_deg=sample.track_deg,
                    pos_source=position_source_code(sample.position_source),
                )
                for index, sample in enumerate(samples)
            ]
        )


async def seed_events(
    database: Database,
    sighting_id: int,
    events: Sequence[tuple[int, str, dict[str, Any] | None]],
) -> None:
    """Write ``sighting_events`` rows: ``(ts_ms, type, payload)`` tuples."""
    async with database.writer_session() as session:
        session.add_all(
            [
                SightingEvent(
                    sighting_id=sighting_id,
                    ts_ms=ts_ms,
                    type=event_type,
                    payload_json=(
                        None
                        if payload is None
                        else json.dumps(payload, separators=(",", ":"), sort_keys=True)
                    ),
                )
                for ts_ms, event_type, payload in events
            ]
        )


__all__ = [
    "SeedSighting",
    "seed_checkpoints",
    "seed_events",
    "seed_sightings",
    "seed_track",
]
