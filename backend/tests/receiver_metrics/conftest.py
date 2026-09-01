"""Fixtures for the receiver-metric tests.

Three things are built here, and each exists to make an assertion exact rather
than approximate.

* **One clock.** :class:`SimulatedTime` drives the live store's monotonic
  clock, the metrics service's epoch milliseconds and the decoder timestamps
  from one number, so a fortnight of retention takes no wall-clock time and
  every ``ts_ms`` in the suite is an exact value (``docs/TEST_STRATEGY.md``
  §3: no ``sleep()``-based timing assertions).
* **Aircraft placed by bearing and range.** :func:`place` puts an aircraft an
  exact number of nautical miles from the receiver on an exact bearing, using
  the inverse of the great-circle formula the live store measures it with. A
  sector assertion is then a statement about bucketing, not about arithmetic.
* **Realistic decoder documents.** :func:`readsb_stats` and
  :func:`dump1090fa_stats` build the two shapes SPEC §60 has to normalize —
  the rich set and the smaller one — from the same builder, so a test about
  *what dump1090-fa lacks* names exactly the keys it lacks.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from flightsite.db import Database, database_path
from flightsite.db.clock import to_epoch_ms
from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate, DecoderEndpoint, Position
from flightsite.live import LiveStore
from flightsite.live.geo import EARTH_RADIUS_NM
from flightsite.receiver_metrics.model import MetricSample
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.statsjson import StatsJsonPoller

#: Fixed wall-clock origin. A Tuesday, mid-morning UTC, far from any DST edge,
#: so a test that is not about day boundaries cannot accidentally be about one.
BASE_TIME = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
BASE_EPOCH_MS = to_epoch_ms(BASE_TIME)

#: The receiver. Boeing Field, so the geometry can be checked against a chart.
RECEIVER = Position(latitude=47.5300, longitude=-122.3018)

ENDPOINT = DecoderEndpoint(host="decoder.test", port=8080, path="/data/aircraft.json")
STATS_URL = "http://decoder.test:8080/data/stats.json"

MS_PER_HOUR = 3_600_000
MS_PER_DAY = 24 * MS_PER_HOUR


class SimulatedTime:
    """One clock driving monotonic seconds, epoch milliseconds and timestamps."""

    def __init__(self, base_ms: int = BASE_EPOCH_MS) -> None:
        self.base_ms = base_ms
        self.elapsed_s = 0.0

    def advance(self, seconds: float) -> None:
        """Move every derived clock forward together."""
        self.elapsed_s += seconds

    def monotonic(self) -> float:
        """Monotonic seconds, as the live store reads them."""
        return 1_000.0 + self.elapsed_s

    def epoch_ms(self) -> int:
        """UTC epoch milliseconds, as the metrics service reads them."""
        return self.base_ms + int(self.elapsed_s * 1_000)

    def now(self) -> datetime:
        """The decoder's UTC timestamp for an observation made now."""
        return datetime.fromtimestamp(self.base_ms / 1000, tz=UTC) + timedelta(
            seconds=self.elapsed_s
        )


def destination(origin: Position, bearing_deg: float, distance_nm: float) -> Position:
    """The point ``distance_nm`` from ``origin`` on ``bearing_deg``.

    The inverse of :func:`flightsite.live.geo.distance_and_bearing`, on the
    same sphere, so a placed aircraft reads back at the range and bearing it
    was placed at.
    """
    angular = distance_nm / EARTH_RADIUS_NM
    lat1 = math.radians(origin.latitude)
    lon1 = math.radians(origin.longitude)
    bearing = math.radians(bearing_deg)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular) + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    return Position(latitude=math.degrees(lat2), longitude=math.degrees(lon2))


def place(
    live: LiveStore,
    clock: SimulatedTime,
    *,
    icao: str,
    bearing_deg: float | None = None,
    distance_nm: float = 50.0,
    messages: int | None = None,
) -> None:
    """Apply one observation of ``icao`` at a chosen bearing and range.

    ``bearing_deg`` of ``None`` means an aircraft with no position at all — a
    Mode S-only target (SPEC §20), which counts toward simultaneous aircraft
    and toward nothing else.
    """
    position = None if bearing_deg is None else destination(RECEIVER, bearing_deg, distance_nm)
    live.apply(
        AircraftStateBatch(
            timestamp=clock.now(),
            updates=(
                AircraftStateUpdate(
                    icao=icao,
                    timestamp=clock.now(),
                    position=position,
                    position_source="adsb" if position is not None else "none",
                    messages=messages,
                ),
            ),
        )
    )


# ----------------------------------------------------------- decoder documents


def _window(
    *,
    start: float,
    end: float,
    messages: int,
    global_ok: int,
    local_ok: int,
    signal: float | None,
    peak_signal: float | None,
    strong_signals: int | None,
) -> dict[str, Any]:
    """One statistics window block, shared by both decoder shapes."""
    local: dict[str, Any] = {
        "samples_processed": 4_000_000_000,
        "samples_dropped": 0,
        "modeac": 0,
        "modes": messages + 12_000,
        "bad": 11_431,
        "unknown_icao": 274,
        "accepted": [messages - 900, 900],
        "noise": -31.5,
    }
    if signal is not None:
        local["signal"] = signal
    if peak_signal is not None:
        local["peak_signal"] = peak_signal
    if strong_signals is not None:
        local["strong_signals"] = strong_signals

    return {
        "start": start,
        "end": end,
        "local": local,
        "remote": {"modeac": 0, "modes": 0, "bad": 0, "unknown_icao": 0, "accepted": [0, 0]},
        "cpr": {
            "surface": 1_204,
            "airborne": global_ok + local_ok,
            "global_ok": global_ok,
            "global_bad": 12,
            "global_range": 3,
            "global_speed": 1,
            "global_skipped": 209,
            "local_ok": local_ok,
            "local_aircraft_relative": 104,
            "local_receiver_relative": 512,
            "local_skipped": 21,
            "local_range": 2,
            "local_speed": 0,
            "filtered": 5,
        },
        "altitude_suppressed": 0,
        "tracks": {"all": 5_432, "single_message": 210},
        "messages": messages,
        "cpu": {"demod": 0, "reader": 1_004, "background": 3_120},
    }


def readsb_stats(
    *,
    messages: int = 4_212_345,
    global_ok: int = 45_678,
    local_ok: int = 52_341,
    signal: float = -14.2,
    peak_signal: float = -2.1,
    uptime_s: float = 24_800.0,
    max_range_nm: float | None = 189.05,
) -> dict[str, Any]:
    """A readsb ``stats.json``: the rich field set, every window present."""
    start = 1_758_100_000.0
    total = _window(
        start=start,
        end=start + uptime_s,
        messages=messages,
        global_ok=global_ok,
        local_ok=local_ok,
        signal=signal,
        peak_signal=peak_signal,
        strong_signals=4_321,
    )
    if max_range_nm is not None:
        total["max_distance_in_metres"] = max_range_nm * 1852.0
        total["max_distance_in_nautical_miles"] = max_range_nm

    document: dict[str, Any] = {"total": total}
    for name in ("latest", "last1min", "last5min", "last15min"):
        document[name] = _window(
            start=start + uptime_s - 60.0,
            end=start + uptime_s,
            messages=9_120,
            global_ok=104,
            local_ok=131,
            signal=signal,
            peak_signal=peak_signal,
            strong_signals=12,
        )
    return document


def dump1090fa_stats(
    *,
    messages: int = 1_004_221,
    global_ok: int = 12_004,
    local_ok: int = 15_887,
    signal: float = -18.7,
    peak_signal: float | None = None,
    uptime_s: float = 9_600.0,
) -> dict[str, Any]:
    """A dump1090-fa ``stats.json``: the smaller set SPEC §60 must degrade to.

    No ``max_distance_*`` at all — dump1090-fa does not know the receiver's
    position — and, in the older builds this fixture models by default, no
    ``peak_signal`` and no ``strong_signals`` either.
    """
    start = 1_758_100_000.0
    return {
        "total": _window(
            start=start,
            end=start + uptime_s,
            messages=messages,
            global_ok=global_ok,
            local_ok=local_ok,
            signal=signal,
            peak_signal=peak_signal,
            strong_signals=None,
        ),
        "last1min": _window(
            start=start + uptime_s - 60.0,
            end=start + uptime_s,
            messages=2_004,
            global_ok=31,
            local_ok=44,
            signal=signal,
            peak_signal=peak_signal,
            strong_signals=None,
        ),
    }


def stats_poller(
    handler: httpx.MockTransport | None = None, *, documents: Sequence[Any] | None = None
) -> StatsJsonPoller:
    """A poller wired to a mock transport rather than to a socket.

    ``documents`` cycles through the given JSON bodies, one per poll, so a
    rate test can hand the decoder two readings of a rising counter.
    """
    if handler is None:
        assert documents is not None, "supply a transport or a document sequence"
        remaining = list(documents)

        def respond(request: httpx.Request) -> httpx.Response:
            body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            return httpx.Response(200, json=body)

        handler = httpx.MockTransport(respond)

    transport = handler
    return StatsJsonPoller(ENDPOINT, client_factory=lambda: httpx.AsyncClient(transport=transport))


def status_poller(status_code: int) -> StatsJsonPoller:
    """A poller against a decoder that answers with ``status_code`` and nothing else."""
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code))
    return StatsJsonPoller(ENDPOINT, client_factory=lambda: httpx.AsyncClient(transport=transport))


# ------------------------------------------------------------------- samples


def sample(ts_ms: int, **fields: Any) -> MetricSample:
    """One raw sample, defaulting every metric to absent."""
    return MetricSample(ts_ms=ts_ms, **fields)


def steady_samples(
    *,
    start_ms: int = BASE_EPOCH_MS,
    count: int,
    interval_ms: int = 15_000,
    messages_per_sec: float | None = 400.0,
    positions_per_sec: float | None = 40.0,
    aircraft: Iterable[int] | None = None,
) -> tuple[MetricSample, ...]:
    """A regular run of samples, for aggregation and retention fixtures."""
    counts = (
        list(aircraft) if aircraft is not None else [30 + (index % 7) for index in range(count)]
    )
    return tuple(
        MetricSample(
            ts_ms=start_ms + index * interval_ms,
            messages_per_sec=messages_per_sec,
            positions_per_sec=positions_per_sec,
            aircraft_visible=counts[index % len(counts)],
            aircraft_with_pos=max(0, counts[index % len(counts)] - 3),
            max_range_nm=100.0 + index % 11,
            rssi_avg_db=-14.0 - (index % 5) * 0.1,
            rssi_peak_db=-3.0 - (index % 3) * 0.2,
        )
        for index in range(count)
    )


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def clock() -> SimulatedTime:
    """Simulated time, advanced explicitly by each test."""
    return SimulatedTime()


@pytest.fixture
def db_path(isolated_data_dir: Path) -> Path:
    """Path the application would use for its database in this test's data dir."""
    return database_path(isolated_data_dir)


@pytest.fixture
async def database(db_path: Path) -> AsyncIterator[Database]:
    """A database migrated to head."""
    instance = Database(db_path)
    try:
        await instance.upgrade_to("head")
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def repository(database: Database) -> MetricsRepository:
    """The receiver-metric repository over the migrated database."""
    return MetricsRepository(database)


@pytest.fixture
def live(clock: SimulatedTime) -> LiveStore:
    """A live store with the receiver at Boeing Field."""
    return LiveStore(receiver_location=RECEIVER, clock=clock.monotonic)
