"""Shared builders for devtools tests: synthetic batches, no decoder needed.

Capture/replay operate entirely on normalized :mod:`flightsite.ingest.types`
values, so tests build those directly rather than going through a decoder
document — the same reasoning ``flightsite.devtools`` itself is built on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flightsite.ingest.types import AircraftStateBatch, AircraftStateUpdate, Position

#: A fixed, arbitrary reference time so every test fixture is deterministic.
T0 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)

#: The default position stamped onto every synthetic update. ``Position`` is
#: frozen, so sharing this one instance across calls is safe.
_DEFAULT_POSITION = Position(latitude=51.5, longitude=-0.1)


def make_update(
    icao: str = "4ca87c",
    *,
    timestamp: datetime = T0,
    position: Position | None = _DEFAULT_POSITION,
    **overrides: object,
) -> AircraftStateUpdate:
    fields: dict[str, object] = {
        "icao": icao,
        "timestamp": timestamp,
        "position_source": "adsb" if position is not None else "none",
        "callsign": "BAW123",
        "squawk": "7000",
        "position": position,
        "altitude_ft": 35000.0,
        "altitude_geometric_ft": 35120.0,
        "ground_speed_kt": 420.5,
        "track_deg": 271.0,
        "vertical_rate_fpm": -64.0,
        "on_ground": False,
        "rssi_db": -12.5,
        "messages": 812,
        "seen_s": 0.4,
        "seen_pos_s": 0.4,
    }
    fields.update(overrides)
    return AircraftStateUpdate(**fields)  # type: ignore[arg-type]


def make_batch(
    *,
    timestamp: datetime = T0,
    updates: tuple[AircraftStateUpdate, ...] = (),
    skipped: int = 0,
    skipped_non_icao: int = 0,
) -> AircraftStateBatch:
    if not updates:
        updates = (make_update(timestamp=timestamp),)
    return AircraftStateBatch(
        timestamp=timestamp,
        updates=updates,
        skipped=skipped,
        skipped_non_icao=skipped_non_icao,
    )


def make_batches(
    count: int, *, interval_s: float = 1.0, start: datetime = T0
) -> list[AircraftStateBatch]:
    """``count`` batches, one second apart by default, each with two aircraft."""
    batches: list[AircraftStateBatch] = []
    for index in range(count):
        ts = start + timedelta(seconds=interval_s * index)
        batches.append(
            make_batch(
                timestamp=ts,
                updates=(
                    make_update("4ca87c", timestamp=ts),
                    make_update(
                        "abc123",
                        timestamp=ts,
                        callsign=None,
                        squawk=None,
                        position=None,
                        altitude_ft=None,
                        altitude_geometric_ft=None,
                        ground_speed_kt=None,
                        track_deg=None,
                        vertical_rate_fpm=None,
                        on_ground=None,
                        rssi_db=None,
                        messages=None,
                        seen_s=None,
                        seen_pos_s=None,
                    ),
                ),
            )
        )
    return batches
