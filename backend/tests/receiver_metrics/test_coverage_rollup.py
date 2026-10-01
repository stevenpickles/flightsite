"""The banded range rollup of slice 087: bucketing, folding, storage, day keys.

``range_by_bearing_band_daily`` is fed exactly the way ``range_by_bearing_daily``
is — the sampler reads the live snapshot, the service folds per receiver-local
day between flushes, and the repository folds each flush into the stored rows
in the one flush transaction — so these tests drive the same real path: the
live store, the sampler, the service on a simulated clock, and the migrated
database.
"""

from __future__ import annotations

import time
from zoneinfo import ZoneInfo

import pytest

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate
from flightsite.live import LiveStore
from flightsite.perf.budgets import budget_for
from flightsite.receiver_metrics.aggregate import local_day, local_day_start_ms
from flightsite.receiver_metrics.coverage import (
    ALTITUDE_BANDS,
    BandRange,
    altitude_band,
    merge_band_range,
)
from flightsite.receiver_metrics.lifetime import LifetimeDelta
from flightsite.receiver_metrics.model import RangeRecord, bearing_bucket
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.sampler import MetricSampler
from flightsite.receiver_metrics.service import ReceiverMetricsService
from tests.receiver_metrics.conftest import RECEIVER, SimulatedTime, destination

SAMPLE_INTERVAL_S = 15.0


def fly(
    live: LiveStore,
    clock: SimulatedTime,
    *,
    icao: str,
    bearing_deg: float,
    distance_nm: float,
    altitude_ft: float | None,
) -> None:
    """One positioned observation of ``icao`` at a chosen bearing, range and altitude."""
    live.apply(
        AircraftStateBatch(
            timestamp=clock.now(),
            updates=(
                AircraftStateUpdate(
                    icao=icao,
                    timestamp=clock.now(),
                    position=destination(RECEIVER, bearing_deg, distance_nm),
                    position_source="adsb",
                    altitude_ft=altitude_ft,
                ),
            ),
        )
    )


def build(
    database: Database, live: LiveStore, clock: SimulatedTime, *, timezone: str = "UTC"
) -> ReceiverMetricsService:
    return ReceiverMetricsService(
        database=database,
        live=live,
        timezone=timezone,
        sample_interval_s=SAMPLE_INTERVAL_S,
        flush_interval_s=3_600.0,
        clock=clock.epoch_ms,
        counters=CounterRegistry(),
    )


def cell(
    band: int, bearing: float, nm: float, at_ms: int, icao: str, samples: int = 1
) -> BandRange:
    return BandRange(
        band=band,
        record=RangeRecord(bearing_deg=bearing, max_range_nm=nm, at_ms=at_ms, icao24=icao),
        samples=samples,
    )


# --------------------------------------------------------------- bucketing


@pytest.mark.parametrize(
    ("altitude_ft", "band"),
    [
        (-200.0, 0),  # a low airfield on a high-pressure day
        (0.0, 0),
        (9_999.0, 0),
        (10_000.0, 1),  # edges are half-open: the boundary is the upper band
        (24_975.0, 1),
        (25_000.0, 2),
        (45_000.0, 2),
    ],
)
def test_altitudes_fall_in_half_open_bands(altitude_ft: float, band: int) -> None:
    assert altitude_band(altitude_ft) == band


def test_an_unknown_altitude_is_in_no_band() -> None:
    assert altitude_band(None) is None


def test_the_bands_are_indexed_in_storage_order() -> None:
    assert [band.index for band in ALTITUDE_BANDS] == [0, 1, 2]
    assert [band.key for band in ALTITUDE_BANDS] == ["below_10k", "10k_25k", "above_25k"]


def test_the_sampler_splits_the_furthest_aircraft_by_sector_and_band(
    live: LiveStore, clock: SimulatedTime
) -> None:
    fly(live, clock, icao="a00001", bearing_deg=42.0, distance_nm=30.0, altitude_ft=4_000.0)
    fly(live, clock, icao="a00002", bearing_deg=43.0, distance_nm=55.0, altitude_ft=6_000.0)
    fly(live, clock, icao="a00003", bearing_deg=44.0, distance_nm=150.0, altitude_ft=36_000.0)
    fly(live, clock, icao="a00004", bearing_deg=200.0, distance_nm=90.0, altitude_ft=18_000.0)

    result = MetricSampler().sample(ts_ms=clock.epoch_ms(), aircraft=live.snapshot())

    cells = {c.key: c for c in result.band_ranges}
    sector = bearing_bucket(42.0)
    assert set(cells) == {(0, sector), (2, sector), (1, bearing_bucket(200.0))}
    assert cells[(0, sector)].record.icao24 == "a00002"
    assert cells[(0, sector)].record.max_range_nm == pytest.approx(55.0, abs=0.01)
    assert cells[(2, sector)].record.icao24 == "a00003"
    # Two aircraft in one cell are still one sample of it.
    assert {c.samples for c in result.band_ranges} == {1}
    # The unbanded ring is unchanged by the split: the furthest in the sector.
    unbanded = {r.bearing_bucket: r for r in result.ranges}
    assert unbanded[sector].icao24 == "a00003"


def test_an_aircraft_without_altitude_counts_for_the_ring_but_no_band(
    live: LiveStore, clock: SimulatedTime
) -> None:
    fly(live, clock, icao="a00001", bearing_deg=90.0, distance_nm=80.0, altitude_ft=None)

    result = MetricSampler().sample(ts_ms=clock.epoch_ms(), aircraft=live.snapshot())

    assert [r.icao24 for r in result.ranges] == ["a00001"]
    assert result.band_ranges == ()


# ----------------------------------------------------------------- folding


def test_a_fold_keeps_the_further_record_and_sums_the_samples() -> None:
    near = cell(2, 47.0, 120.0, 1_000, "near", samples=3)
    far = cell(2, 46.0, 180.0, 2_000, "far", samples=2)

    merged = merge_band_range(near, far)

    assert merged.record.icao24 == "far"
    assert merged.record.at_ms == 2_000
    assert merged.samples == 5
    assert merge_band_range(far, near).record.icao24 == "far"


def test_a_tie_keeps_the_earlier_detection() -> None:
    first = cell(1, 10.0, 100.0, 1_000, "first")
    later = cell(1, 11.0, 100.0, 2_000, "later")

    assert merge_band_range(first, later).record.icao24 == "first"


# ----------------------------------------------------------------- storage


async def test_stored_rows_fold_across_flushes(repository: MetricsRepository) -> None:
    empty = LifetimeDelta()
    day = "2026-09-01"

    await repository.record(
        (), {}, empty, at_ms=1, band_ranges={day: [cell(2, 47.0, 120.0, 1_000, "a1", 4)]}
    )
    # A shorter detection later the same day: counted, but the record stands.
    await repository.record(
        (), {}, empty, at_ms=2, band_ranges={day: [cell(2, 46.0, 90.0, 2_000, "a2", 3)]}
    )
    stored = dict(await repository.band_ranges_from(day))
    assert stored[day].record.icao24 == "a1"
    assert stored[day].record.max_range_nm == pytest.approx(120.0)
    assert stored[day].samples == 7

    # A further one moves the whole record — range, moment and airframe together.
    await repository.record(
        (), {}, empty, at_ms=3, band_ranges={day: [cell(2, 45.0, 160.0, 3_000, "a3", 1)]}
    )
    stored = dict(await repository.band_ranges_from(day))
    assert (stored[day].record.icao24, stored[day].record.at_ms) == ("a3", 3_000)
    assert stored[day].record.max_range_nm == pytest.approx(160.0)
    assert stored[day].samples == 8
    # Read back with the sector midpoint, as the unbanded table is.
    assert stored[day].record.bearing_deg == pytest.approx(47.5)


async def test_reads_are_bounded_by_day_and_oldest_first(repository: MetricsRepository) -> None:
    empty = LifetimeDelta()
    for day in ("2026-09-03", "2026-09-01", "2026-09-02"):
        await repository.record(
            (), {}, empty, at_ms=1, band_ranges={day: [cell(0, 5.0, 40.0, 1, "a1")]}
        )

    assert [day for day, _ in await repository.band_ranges_from()] == [
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
    ]
    assert [day for day, _ in await repository.band_ranges_from("2026-09-02")] == [
        "2026-09-02",
        "2026-09-03",
    ]


# ------------------------------------------------------------- the service


async def test_the_service_counts_one_sample_per_tick_per_cell(
    database: Database, live: LiveStore, clock: SimulatedTime, repository: MetricsRepository
) -> None:
    service = build(database, live, clock)
    for tick in range(5):
        clock.advance(SAMPLE_INTERVAL_S)
        fly(
            live,
            clock,
            icao="a00001",
            bearing_deg=12.0,
            distance_nm=60.0 + tick,
            altitude_ft=31_000.0,
        )
        fly(live, clock, icao="a00002", bearing_deg=13.0, distance_nm=20.0, altitude_ft=32_000.0)
        await service.sample_once()
    await service.flush()

    stored = await repository.band_ranges_from()
    assert len(stored) == 1
    day, only = stored[0]
    assert day == local_day(clock.epoch_ms(), ZoneInfo("UTC"))
    assert only.key == (2, bearing_bucket(12.0))
    assert only.samples == 5
    assert only.record.max_range_nm == pytest.approx(64.0, abs=0.01)


async def test_a_failed_flush_keeps_the_banded_cells_for_the_next(
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
    repository: MetricsRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = build(database, live, clock)
    clock.advance(SAMPLE_INTERVAL_S)
    fly(live, clock, icao="a00001", bearing_deg=300.0, distance_nm=70.0, altitude_ft=12_000.0)
    await service.sample_once()

    working = MetricsRepository.record

    async def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("disk I/O error")

    monkeypatch.setattr(MetricsRepository, "record", refuse)
    assert await service.flush() is False
    assert await repository.band_ranges_from() == ()

    monkeypatch.setattr(MetricsRepository, "record", working)
    assert await service.flush() is True
    [(_, stored)] = await repository.band_ranges_from()
    assert stored.samples == 1
    assert stored.band == 1


async def test_cells_are_keyed_by_the_receivers_local_day(
    database: Database, live: LiveStore, repository: MetricsRepository
) -> None:
    """The slice-076 / issue #205 lesson: the day is the receiver's, resolved live.

    21:00 on 2026-09-20 in New York is 01:00 UTC on the 21st; a cell keyed
    by the UTC date would land on a day the reader never asks for.
    """
    zone = ZoneInfo("America/New_York")
    clock = SimulatedTime(base_ms=local_day_start_ms("2026-09-20", zone) + 21 * 3_600_000)
    live_ny = LiveStore(receiver_location=RECEIVER, clock=clock.monotonic)
    service = build(database, live_ny, clock, timezone="America/New_York")

    fly(live_ny, clock, icao="a00001", bearing_deg=148.0, distance_nm=200.0, altitude_ft=38_000.0)
    await service.sample_once()
    await service.flush()

    assert [day for day, _ in await repository.band_ranges_from()] == ["2026-09-20"]
    # The unbanded record files the same instant under the same day.
    assert await repository.ranges_for_day("2026-09-20")


# --------------------------------------------------------------- write cost


async def test_a_full_flush_of_banded_cells_fits_the_db_write_cycle_budget(
    repository: MetricsRepository,
) -> None:
    """Roadmap 087's acceptance: the rollup's write stays inside ``db_write_cycle``.

    The worst case is every cell of the day occupied — 72 sectors x 3 bands,
    one upsert of 216 rows — landing on rows that already exist, so every row
    takes the conflict path. Measured over repeated flushes and judged on the
    slowest against the reference budget the perf harness reports
    (``docs/PERFORMANCE.md``), so a regression that turned the single upsert
    into per-row statements fails here rather than on a Pi.
    """
    budget_ms = budget_for("db_write_cycle_ms").value
    day = "2026-09-01"
    empty = LifetimeDelta()
    timings: list[float] = []
    for flush in range(8):
        cells = [
            cell(band, bucket * 5.0 + 1.0, 50.0 + flush + band * 40.0, flush, f"{bucket:06x}", 4)
            for band in range(3)
            for bucket in range(72)
        ]
        started = time.perf_counter()
        await repository.record((), {}, empty, at_ms=flush, band_ranges={day: cells})
        timings.append((time.perf_counter() - started) * 1_000.0)

    stored = await repository.band_ranges_from(day)
    assert len(stored) == 216
    assert {entry.samples for _, entry in stored} == {32}
    assert max(timings) < budget_ms, f"slowest banded flush {max(timings):.1f} ms"
