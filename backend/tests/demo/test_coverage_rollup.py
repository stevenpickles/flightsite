"""Demo traffic fills the coverage rollup (slice 087).

The demo stack is what the e2e suites, screenshots and a first look at
FlightSite run against (SPEC §76), so the Receiver page's coverage chart has
to have something to draw there. Nothing about the rollup is demo-specific —
the metrics service samples the live store whatever feeds it — so this test
drives the real demo scenario through the real live store, sampler, service
and repository, and asserts the banded table ends up with rows in every
altitude band rather than in one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from flightsite.counters import CounterRegistry
from flightsite.db import Database, database_path
from flightsite.db.clock import to_epoch_ms
from flightsite.demo import DEFAULT_CENTER, DemoAdapter
from flightsite.live import LiveStore
from flightsite.receiver_metrics.coverage import ALTITUDE_BANDS, reduce_window
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.service import ReceiverMetricsService

EPOCH = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)

#: Ticks of scenario driven before sampling, at the demo's 1 Hz: long enough
#: for the live set to fill with cruise, climbing and local traffic.
WARMUP_TICKS = 180

#: Samples taken, one per 15 simulated seconds, as the service does.
SAMPLES = 8


async def test_demo_traffic_produces_banded_rows_in_every_band(isolated_data_dir: Path) -> None:
    database = Database(database_path(isolated_data_dir))
    await database.upgrade_to("head")
    try:
        elapsed = {"s": 0.0}
        live = LiveStore(receiver_location=DEFAULT_CENTER, clock=lambda: 1_000.0 + elapsed["s"])
        adapter = DemoAdapter(center=DEFAULT_CENTER, epoch=EPOCH)
        service = ReceiverMetricsService(
            database=database,
            live=live,
            flush_interval_s=3_600.0,
            clock=lambda: to_epoch_ms(EPOCH) + int(elapsed["s"] * 1_000),
            counters=CounterRegistry(),
        )

        tick = 0
        for sample in range(SAMPLES):
            target = WARMUP_TICKS + sample * 15
            while tick <= target:
                live.apply(adapter.batch_for_tick(tick))
                elapsed["s"] = float(tick)
                tick += 1
            await service.sample_once()
        assert await service.flush() is True

        rows = await MetricsRepository(database).band_ranges_from()
        cells = reduce_window(rows)
        bands = {band for band, _bucket in cells}
        assert bands == {band.index for band in ALTITUDE_BANDS}, (
            f"demo traffic only reached bands {sorted(bands)}"
        )
        # Spread round the compass, not piled into one sector.
        assert len({bucket for _band, bucket in cells}) >= 12
        assert all(cell.samples >= 1 and cell.record is not None for cell in cells.values())
    finally:
        await database.dispose()
