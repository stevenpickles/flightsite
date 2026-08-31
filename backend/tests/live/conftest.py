"""Shared helpers for live-store tests: a hand-driven clock and update builders.

Every lifecycle assertion here runs against :class:`ManualClock`, never
``asyncio.sleep`` — ``docs/TEST_STRATEGY.md`` §3 makes simulated time the rule
for the 15 s / 60 s thresholds, so the whole suite exercises hours of ageing in
microseconds and cannot flake on a loaded machine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate, Position
from flightsite.live import LiveStore

#: Wall-clock origin for decoder timestamps. Fixed, so every expectation about
#: ``first_seen`` / ``last_seen`` is exact rather than approximate.
BASE_TIME = datetime(2026, 8, 30, 22, 0, 0, tzinfo=UTC)

#: The receiver used wherever a configured location matters: Seattle-Tacoma.
SEATTLE = Position(latitude=47.4502, longitude=-122.3088)

ICAO = "ae1463"


class ManualClock:
    """A monotonic clock a test drives by hand.

    Satisfies :data:`flightsite.live.MonotonicClock` (it is callable and
    returns seconds), and never moves unless a test says so.
    """

    def __init__(self, start: float = 1_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        """Move time forward and return the new reading."""
        self._now += seconds
        return self._now


def make_update(
    icao: str = ICAO,
    *,
    offset_s: float = 0.0,
    position: Position | None = None,
    **fields: Any,
) -> AircraftStateUpdate:
    """Build one observation, defaulting ``position_source`` from ``position``.

    Keeping the source consistent with the position by default means a test
    only spells it out when the distinction is the point (MLAT, TIS-B).
    """
    source = fields.pop("position_source", "adsb" if position is not None else "none")
    return AircraftStateUpdate(
        icao=icao,
        timestamp=BASE_TIME + timedelta(seconds=offset_s),
        position=position,
        position_source=source,
        **fields,
    )


def make_batch(*updates: AircraftStateUpdate, offset_s: float = 0.0) -> AircraftStateBatch:
    """Wrap updates in a batch stamped with the decoder's clock."""
    return AircraftStateBatch(timestamp=BASE_TIME + timedelta(seconds=offset_s), updates=updates)


@pytest.fixture
def clock() -> ManualClock:
    """A monotonic clock the test advances explicitly."""
    return ManualClock()


@pytest.fixture
def live_store(clock: ManualClock) -> LiveStore:
    """A live store on the default 15 s / 60 s thresholds and a known receiver.

    Named ``live_store`` rather than ``store`` so it cannot be confused with
    the root suite's ``ConfigStore`` fixture of that name.
    """
    return LiveStore(clock=clock, receiver_location=SEATTLE)
