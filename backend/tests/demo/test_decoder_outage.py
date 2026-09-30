"""The scripted demo decoder outage (slice 088).

The roadmap's acceptance criterion — *"a demo decoder outage produces exactly
one offline and one restored notification"* — driven end to end on the
backend: a full hour of sampler ticks through the scripted probe, the real
self-alert monitor and the real activity service, counting what reaches the
WebSocket listener. Notifications are one per event on the client (tested in
``frontend/src/features/notifications``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from flightsite.activity import ActivityService, StoredActivityEvent
from flightsite.alerts.self_alerts import SelfAlertMonitor
from flightsite.config import SelfAlertSettings
from flightsite.db import Database, database_path
from flightsite.demo.decoder_outage import (
    DECODER_CYCLE_S,
    DECODER_OUTAGE_S,
    DECODER_OUTAGE_START_S,
    DEMO_OUTAGE_ERROR,
    decoder_outage,
    scripted_decoder_health,
)
from flightsite.ingest.health import AdapterHealth, HealthState
from flightsite.receiver_metrics.baseline import BaselineState, RateBaseline
from flightsite.receiver_metrics.model import MetricSample

#: The top of an hour, so one cycle is exactly this hour.
CYCLE_START_MS = 1_790_000_000_000 - 1_790_000_000_000 % (DECODER_CYCLE_S * 1000)
TICK_MS = 15_000


@pytest.fixture
async def database(isolated_data_dir: Path) -> AsyncIterator[Database]:
    instance = Database(database_path(isolated_data_dir))
    await instance.upgrade_to("head")
    try:
        yield instance
    finally:
        await instance.dispose()


def test_the_outage_is_half_past_for_seven_minutes() -> None:
    start = CYCLE_START_MS + DECODER_OUTAGE_START_S * 1000
    assert not decoder_outage(start - 1000)
    assert decoder_outage(start)
    assert decoder_outage(start + (DECODER_OUTAGE_S - 1) * 1000)
    assert not decoder_outage(start + DECODER_OUTAGE_S * 1000)


def test_outside_the_outage_the_real_health_passes_through() -> None:
    real = AdapterHealth(state=HealthState.CONNECTED)
    now = [CYCLE_START_MS]
    probe = scripted_decoder_health(lambda: real, clock=lambda: now[0])

    assert probe() is real
    now[0] = CYCLE_START_MS + DECODER_OUTAGE_START_S * 1000
    scripted = probe()
    assert scripted is not None
    assert scripted.state is HealthState.DOWN
    assert scripted.last_error == DEMO_OUTAGE_ERROR
    assert scripted_decoder_health(lambda: None, clock=lambda: now[0])() is None


async def test_one_demo_outage_is_exactly_one_raise_and_one_restore(database: Database) -> None:
    now = [CYCLE_START_MS]
    activity = ActivityService(database=database, clock=lambda: now[0])
    await activity.start()
    published: list[StoredActivityEvent] = []
    activity.subscribe(published.extend)

    async def learning(_at_ms: int, _zone: ZoneInfo) -> RateBaseline:
        return RateBaseline(hour_of_week=0, state=BaselineState.LEARNING)

    monitor = SelfAlertMonitor(
        database=database,
        settings=SelfAlertSettings,
        health=scripted_decoder_health(
            lambda: AdapterHealth(state=HealthState.CONNECTED), clock=lambda: now[0]
        ),
        sink=activity.record_self_alert,
        baseline_loader=learning,
    )
    await monitor.start()

    for ts in range(CYCLE_START_MS, CYCLE_START_MS + DECODER_CYCLE_S * 1000, TICK_MS):
        now[0] = ts
        await monitor.observe(MetricSample(ts_ms=ts, messages_per_sec=50.0))
        await activity.flush()
    await activity.stop()

    assert [(event.type, event.payload["condition"]) for event in published] == [
        ("self_alert_raised", "decoder_down"),
        ("self_alert_restored", "decoder_down"),
    ]
    raise_, restore = published
    assert raise_.severity == "high"
    assert raise_.payload["error"] == DEMO_OUTAGE_ERROR
    assert raise_.payload["since_ms"] == CYCLE_START_MS + DECODER_OUTAGE_START_S * 1000
    assert restore.payload["since_ms"] == raise_.payload["since_ms"]
