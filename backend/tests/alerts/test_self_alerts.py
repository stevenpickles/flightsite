"""Receiver self-alerts (slice 088, issue #231): conditions, monitor, config.

The two condition state machines are exercised directly on a hand-driven
timeline — minimum duration, hysteresis, one raise and one restore per
episode. The monitor is exercised against a real migrated database (for its
``meta`` row) with an injected baseline, so no test needs weeks of samples.
The last few go through the real application for hot-apply and diagnostics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from flightsite.activity import SelfAlertEpisode
from flightsite.alerts.self_alerts import (
    ACTIVE_META_KEY,
    CONDITION_DECODER_DOWN,
    CONDITION_FEEDER_OFFLINE,
    CONDITION_MESSAGE_RATE,
    DECODER_RESTORE_HOLD_MS,
    RATE_RESTORE_HOLD_MS,
    DecoderDownCondition,
    MessageRateCondition,
    SelfAlertMonitor,
)
from flightsite.app import create_app
from flightsite.config import SelfAlertSettings, Settings
from flightsite.db import Database
from flightsite.db.meta import MetaRepository
from flightsite.ingest.health import AdapterHealth, HealthState
from flightsite.receiver_metrics.baseline import BaselineState, RateBaseline
from flightsite.receiver_metrics.model import MetricSample

BASE_MS = 1_790_000_000_000
TICK_MS = 15_000
MINUTE_MS = 60_000

CONNECTED = AdapterHealth(state=HealthState.CONNECTED)
DOWN = AdapterHealth(state=HealthState.DOWN, last_error="connection refused")
DEGRADED = AdapterHealth(state=HealthState.DEGRADED)

READY = RateBaseline(hour_of_week=27, state=BaselineState.READY, msgs_per_sec=100.0, weeks=4)
LEARNING = RateBaseline(hour_of_week=27, state=BaselineState.LEARNING, msgs_per_sec=100.0, weeks=1)


def ticks(start_ms: int, minutes: float) -> list[int]:
    """Every sampler tick in ``[start_ms, start_ms + minutes)``."""
    return list(range(start_ms, start_ms + int(minutes * MINUTE_MS), TICK_MS))


# ------------------------------------------------------------ decoder_down


def drive_decoder(
    condition: DecoderDownCondition,
    health: AdapterHealth | None,
    start_ms: int,
    minutes: float,
    *,
    threshold: int = 5,
) -> list[SelfAlertEpisode]:
    episodes = []
    for now in ticks(start_ms, minutes):
        episode = condition.observe(now, health, minutes=threshold)
        if episode is not None:
            episodes.append(episode)
    return episodes


def test_a_short_outage_raises_nothing() -> None:
    condition = DecoderDownCondition()
    assert drive_decoder(condition, DOWN, BASE_MS, 4.9) == []
    assert drive_decoder(condition, CONNECTED, BASE_MS + 5 * MINUTE_MS, 10) == []
    assert condition.active is None


def test_an_outage_past_the_threshold_raises_once_then_restores_once() -> None:
    condition = DecoderDownCondition()

    raised = drive_decoder(condition, DOWN, BASE_MS, 30)
    restored = drive_decoder(condition, CONNECTED, BASE_MS + 30 * MINUTE_MS, 10)

    assert [episode.raised for episode in raised] == [True]
    (raise_,) = raised
    assert raise_.condition == CONDITION_DECODER_DOWN
    assert raise_.since_ms == BASE_MS
    assert raise_.at_ms == BASE_MS + 5 * MINUTE_MS
    assert raise_.severity == "high"
    assert raise_.detail == {"minutes": 5, "error": "connection refused"}

    assert [episode.raised for episode in restored] == [False]
    (restore,) = restored
    assert restore.since_ms == BASE_MS
    assert restore.at_ms == BASE_MS + 30 * MINUTE_MS + DECODER_RESTORE_HOLD_MS
    assert restore.duration_ms == 30 * MINUTE_MS + DECODER_RESTORE_HOLD_MS


def test_a_brief_reconnect_mid_outage_neither_restores_nor_raises_again() -> None:
    condition = DecoderDownCondition()
    episodes = drive_decoder(condition, DOWN, BASE_MS, 10)
    # 45 s connected: under the one-minute restore hold.
    episodes += drive_decoder(condition, CONNECTED, BASE_MS + 10 * MINUTE_MS, 0.75)
    episodes += drive_decoder(condition, DOWN, BASE_MS + 11 * MINUTE_MS, 20)

    assert [episode.raised for episode in episodes] == [True]


def test_flapping_below_the_threshold_never_raises() -> None:
    condition = DecoderDownCondition()
    episodes: list[SelfAlertEpisode] = []
    now = BASE_MS
    for _ in range(20):
        episodes += drive_decoder(condition, DOWN, now, 3)
        episodes += drive_decoder(condition, CONNECTED, now + 3 * MINUTE_MS, 0.5)
        now += int(3.5 * MINUTE_MS)
    assert episodes == []


def test_degraded_ends_a_pending_run_without_counting_as_recovery() -> None:
    condition = DecoderDownCondition()
    assert drive_decoder(condition, DOWN, BASE_MS, 4) == []
    drive_decoder(condition, DEGRADED, BASE_MS + 4 * MINUTE_MS, 1)
    # The run starts again: four more minutes is not enough.
    assert drive_decoder(condition, DOWN, BASE_MS + 5 * MINUTE_MS, 4) == []
    assert drive_decoder(condition, DOWN, BASE_MS + 9 * MINUTE_MS, 2)[0].raised


def test_no_decoder_at_all_is_never_an_outage() -> None:
    condition = DecoderDownCondition()
    assert drive_decoder(condition, None, BASE_MS, 60) == []


# ------------------------------------------------------------ message_rate


def drive_rate(
    condition: MessageRateCondition,
    rate: float | None,
    start_ms: int,
    minutes: float,
    *,
    baseline: RateBaseline | None = READY,
    connected: bool = True,
) -> list[SelfAlertEpisode]:
    episodes = []
    for now in ticks(start_ms, minutes):
        episode = condition.observe(
            now,
            rate,
            baseline,
            share_pct=40,
            minutes=15,
            decoder_connected=connected,
        )
        if episode is not None:
            episodes.append(episode)
    return episodes


def test_a_quiet_night_hour_matching_its_baseline_does_not_trip() -> None:
    """Roadmap acceptance: a quiet hour is judged against *that* hour."""
    night = RateBaseline(hour_of_week=27, state=BaselineState.READY, msgs_per_sec=3.0, weeks=6)
    condition = MessageRateCondition()
    assert drive_rate(condition, 2.8, BASE_MS, 120, baseline=night) == []
    assert condition.active is None
    assert condition.pending_since_ms is None


def test_a_collapse_below_the_share_for_the_duration_raises_once() -> None:
    condition = MessageRateCondition()
    assert drive_rate(condition, 39.0, BASE_MS, 14.9) == []
    episodes = drive_rate(condition, 39.0, BASE_MS + int(14.9 * MINUTE_MS) + 1, 60)

    (raise_,) = episodes
    assert raise_.raised
    assert raise_.condition == CONDITION_MESSAGE_RATE
    assert raise_.since_ms == BASE_MS
    assert raise_.detail == {
        "rate_msgs_s": 39.0,
        "baseline_msgs_s": 100.0,
        "share_pct": 40,
        "minutes": 15,
        "baseline_weeks": 4,
    }


def test_restoring_needs_the_rate_past_the_hysteresis_band_for_five_minutes() -> None:
    condition = MessageRateCondition()
    drive_rate(condition, 10.0, BASE_MS, 20)
    assert condition.active is not None
    later = BASE_MS + 20 * MINUTE_MS

    # 45 msg/s is above the 40 threshold but inside the band below 50.
    assert drive_rate(condition, 45.0, later, 60) == []
    # Recovered, but not for long enough.
    assert drive_rate(condition, 80.0, later + 60 * MINUTE_MS, 4.9) == []
    # A dip into the band resets the recovery run.
    assert drive_rate(condition, 45.0, later + 65 * MINUTE_MS, 1) == []
    (restore,) = drive_rate(condition, 80.0, later + 66 * MINUTE_MS, 10)

    assert not restore.raised
    assert restore.since_ms == BASE_MS
    assert restore.at_ms == later + 66 * MINUTE_MS + RATE_RESTORE_HOLD_MS


def test_a_learning_baseline_never_fires() -> None:
    condition = MessageRateCondition()
    assert drive_rate(condition, 0.0, BASE_MS, 600, baseline=LEARNING) == []
    assert drive_rate(condition, 0.0, BASE_MS, 60, baseline=None) == []


def test_a_decoder_that_is_not_connected_holds_the_rate_condition() -> None:
    """One cause, one alert: a dead decoder is ``decoder_down``'s to report."""
    condition = MessageRateCondition()
    assert drive_rate(condition, 0.0, BASE_MS, 120, connected=False) == []


def test_a_gap_in_the_rates_restarts_the_run() -> None:
    condition = MessageRateCondition()
    assert drive_rate(condition, 5.0, BASE_MS, 10) == []
    drive_rate(condition, None, BASE_MS + 10 * MINUTE_MS, 1)
    assert drive_rate(condition, 5.0, BASE_MS + 11 * MINUTE_MS, 14) == []
    assert condition.pending_since_ms == BASE_MS + 11 * MINUTE_MS


# ----------------------------------------------------------------- monitor


@dataclass
class _Feeder:
    name: str
    label: str
    state: str
    since_ms: int | None


class World:
    """The monitor's inputs, set by hand."""

    def __init__(self) -> None:
        self.settings = SelfAlertSettings()
        self.health: AdapterHealth | None = CONNECTED
        self.baseline: RateBaseline = READY
        self.feeders: list[_Feeder] = []
        self.sunk: list[SelfAlertEpisode] = []
        self.loads = 0

    async def load(self, _at_ms: int, _zone: ZoneInfo) -> RateBaseline:
        self.loads += 1
        return self.baseline

    def monitor(self, database: Database) -> SelfAlertMonitor:
        return SelfAlertMonitor(
            database=database,
            settings=lambda: self.settings,
            health=lambda: self.health,
            sink=self.sunk.append,
            feeders=lambda: self.feeders,
            baseline_loader=self.load,
        )


async def run(
    monitor: SelfAlertMonitor, start_ms: int, minutes: float, rate: float | None = 100.0
) -> None:
    for now in ticks(start_ms, minutes):
        await monitor.observe(MetricSample(ts_ms=now, messages_per_sec=rate))


@pytest.fixture
def world() -> World:
    return World()


async def test_the_monitor_hands_one_raise_and_one_restore_to_the_sink(
    database: Database, world: World
) -> None:
    monitor = world.monitor(database)
    await monitor.start()

    world.health = DOWN
    await run(monitor, BASE_MS, 10, rate=None)
    world.health = CONNECTED
    await run(monitor, BASE_MS + 10 * MINUTE_MS, 5)

    assert [(e.condition, e.raised) for e in world.sunk] == [
        (CONDITION_DECODER_DOWN, True),
        (CONDITION_DECODER_DOWN, False),
    ]
    assert world.sunk[0].since_ms == world.sunk[1].since_ms == BASE_MS


async def test_the_baseline_is_loaded_once_per_hour(database: Database, world: World) -> None:
    monitor = world.monitor(database)
    await run(monitor, BASE_MS - BASE_MS % 3_600_000, 90)
    assert world.loads == 2


async def test_an_active_episode_survives_a_restart_and_restores_once(
    database: Database, world: World
) -> None:
    first = world.monitor(database)
    await first.start()
    world.health = DOWN
    await run(first, BASE_MS, 8, rate=None)
    assert [e.raised for e in world.sunk] == [True]

    stored = json.loads(await MetaRepository(database).get(ACTIVE_META_KEY) or "{}")
    assert stored[CONDITION_DECODER_DOWN]["since_ms"] == BASE_MS

    # A new process: still down after the restart, then back.
    second = world.monitor(database)
    await second.start()
    assert [alert.condition for alert in second.active()] == [CONDITION_DECODER_DOWN]
    await run(second, BASE_MS + 20 * MINUTE_MS, 10, rate=None)
    world.health = CONNECTED
    await run(second, BASE_MS + 30 * MINUTE_MS, 3)

    assert [(e.raised, e.since_ms) for e in world.sunk] == [(True, BASE_MS), (False, BASE_MS)]
    assert json.loads(await MetaRepository(database).get(ACTIVE_META_KEY) or "") == {}


async def test_a_disabled_condition_raises_nothing(database: Database, world: World) -> None:
    world.settings = SelfAlertSettings(decoder_down_enabled=False, message_rate_enabled=False)
    monitor = world.monitor(database)
    world.health = DOWN
    await run(monitor, BASE_MS, 60, rate=0.0)
    assert world.sunk == []
    assert monitor.snapshot()["conditions"][CONDITION_DECODER_DOWN]["state"] == "disabled"


async def test_switching_off_an_active_condition_ends_it_silently(
    database: Database, world: World
) -> None:
    monitor = world.monitor(database)
    world.health = DOWN
    await run(monitor, BASE_MS, 6, rate=None)
    assert monitor.active()

    world.settings = SelfAlertSettings(decoder_down_enabled=False)
    await run(monitor, BASE_MS + 6 * MINUTE_MS, 1, rate=None)

    assert monitor.active() == ()
    assert [e.raised for e in world.sunk] == [True]


async def test_a_new_threshold_applies_on_the_next_sample(database: Database, world: World) -> None:
    """Hot-apply: the monitor reads the section on every evaluation."""
    monitor = world.monitor(database)
    world.health = DOWN
    await run(monitor, BASE_MS, 3, rate=None)
    assert world.sunk == []

    world.settings = SelfAlertSettings(decoder_down_minutes=2)
    await monitor.observe(MetricSample(ts_ms=BASE_MS + 3 * MINUTE_MS))

    assert [e.detail["minutes"] for e in world.sunk] == [2]


async def test_the_rate_condition_fires_through_the_monitor(
    database: Database, world: World
) -> None:
    monitor = world.monitor(database)
    await run(monitor, BASE_MS, 20, rate=20.0)
    assert [(e.condition, e.raised) for e in world.sunk] == [(CONDITION_MESSAGE_RATE, True)]
    assert monitor.snapshot()["conditions"][CONDITION_MESSAGE_RATE]["state"] == "active"


async def test_feeder_outages_are_listed_only_while_their_toggle_is_on(
    database: Database, world: World
) -> None:
    world.feeders = [
        _Feeder("fr24", "FlightRadar24", "down", BASE_MS),
        _Feeder("adsbx", "ADS-B Exchange", "up", BASE_MS),
    ]
    monitor = world.monitor(database)

    (alert,) = monitor.active()
    assert (alert.condition, alert.subject, alert.label, alert.since_ms) == (
        CONDITION_FEEDER_OFFLINE,
        "fr24",
        "FlightRadar24",
        BASE_MS,
    )
    world.settings = SelfAlertSettings(feeder_offline_enabled=False)
    assert monitor.active() == ()


async def test_the_snapshot_reports_learning_pending_and_the_active_list(
    database: Database, world: World
) -> None:
    world.baseline = LEARNING
    monitor = world.monitor(database)
    world.health = DOWN
    await run(monitor, BASE_MS, 1, rate=None)

    snapshot = monitor.snapshot()
    assert snapshot["conditions"][CONDITION_DECODER_DOWN]["state"] == "pending"
    assert snapshot["conditions"][CONDITION_MESSAGE_RATE]["state"] == "learning"
    assert snapshot["active"] == []

    await run(monitor, BASE_MS + MINUTE_MS, 5, rate=None)
    (active,) = monitor.snapshot()["active"]
    assert active["condition"] == CONDITION_DECODER_DOWN
    assert active["since"].endswith("Z")


# ----------------------------------------------------------------- config


def test_the_defaults_are_the_documented_ones() -> None:
    settings = Settings().self_alerts
    assert settings.message_rate_enabled and settings.decoder_down_enabled
    assert settings.feeder_offline_enabled
    assert (settings.message_rate_share_pct, settings.message_rate_minutes) == (40, 15)
    assert settings.decoder_down_minutes == 5


@pytest.mark.parametrize(
    "field",
    [
        {"message_rate_share_pct": 4},
        {"message_rate_share_pct": 96},
        {"message_rate_minutes": 4},
        {"message_rate_minutes": 241},
        {"decoder_down_minutes": 0},
        {"decoder_down_minutes": 241},
        {"unknown_key": True},
    ],
)
def test_out_of_range_values_are_refused(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SelfAlertSettings(**field)


def test_a_save_is_applied_and_reported_by_diagnostics(isolated_data_dir: Path) -> None:
    with TestClient(create_app(isolated_data_dir)) as client:
        response = client.put(
            "/api/internal/config",
            json={"self_alerts": {"decoder_down_minutes": 12, "message_rate_enabled": False}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["config"]["self_alerts"]["decoder_down_minutes"] == 12

        rejected = client.put(
            "/api/internal/config", json={"self_alerts": {"decoder_down_minutes": 0}}
        )
        assert rejected.status_code == 422

        block = client.get("/api/v1/diagnostics").json()["self_alerts"]
        assert block["conditions"][CONDITION_DECODER_DOWN]["minutes"] == 12
        assert block["conditions"][CONDITION_MESSAGE_RATE]["state"] == "disabled"
        assert block["active"] == []
