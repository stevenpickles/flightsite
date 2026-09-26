"""``feeder_offline`` / ``feeder_restored`` — slice 077's activity producers.

The producer is a pure function of :class:`FeederEpisode` facts; the service
tests below drive the real repository to prove the dedupe keys hold against
the ``UNIQUE`` index, so an outage announced twice is recorded once.
"""

from __future__ import annotations

import typing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flightsite.activity import (
    ActivityEventType,
    ActivityRepository,
    FeederEpisode,
    Severity,
)
from flightsite.activity.producers import feeder_health_events
from flightsite.api.schemas import ActivityEventTypeLiteral
from flightsite.app import create_app
from flightsite.db import Database

from .conftest import BASE_MS, MS_PER_MINUTE, ManualClock, service_for

OUTAGE_START = BASE_MS
RESTORED_AT = BASE_MS + 3 * MS_PER_MINUTE


def offline(feeder: str = "fr24", since_ms: int = OUTAGE_START) -> FeederEpisode:
    return FeederEpisode(
        feeder=feeder,
        label="FlightRadar24",
        kind="fr24",
        offline=True,
        since_ms=since_ms,
        at_ms=since_ms,
    )


def restored(feeder: str = "fr24", since_ms: int = OUTAGE_START) -> FeederEpisode:
    return FeederEpisode(
        feeder=feeder,
        label="FlightRadar24",
        kind="fr24",
        offline=False,
        since_ms=since_ms,
        at_ms=RESTORED_AT,
    )


# ------------------------------------------------------------- the producer


def test_an_outage_is_high_severity_and_keyed_by_feeder_and_start() -> None:
    batch = feeder_health_events([offline()])

    (event,) = batch.events
    assert event.type is ActivityEventType.FEEDER_OFFLINE
    assert event.severity is Severity.HIGH
    assert event.ts_ms == OUTAGE_START
    assert event.dedupe_key == f"feeder_offline:fr24:{OUTAGE_START}"
    assert event.aircraft_id is None
    assert event.payload == {
        "feeder": "fr24",
        "label": "FlightRadar24",
        "kind": "fr24",
        "since_ms": OUTAGE_START,
        "outage_s": None,
    }


def test_a_restore_is_info_and_reports_the_outage_length() -> None:
    batch = feeder_health_events([restored()])

    (event,) = batch.events
    assert event.type is ActivityEventType.FEEDER_RESTORED
    assert event.severity is Severity.INFO
    assert event.ts_ms == RESTORED_AT
    assert event.dedupe_key == f"feeder_restored:fr24:{OUTAGE_START}"
    assert event.payload["since_ms"] == OUTAGE_START
    assert event.payload["outage_s"] == 180.0


def test_the_payload_carries_only_configuration_and_timestamps() -> None:
    """``docs/SECURITY.md`` §3: no vendor document field can ride along."""
    for episode in (offline(), restored()):
        (event,) = feeder_health_events([episode]).events
        assert set(event.payload) == {"feeder", "label", "kind", "since_ms", "outage_s"}


def test_two_feeders_down_at_the_same_moment_are_two_events() -> None:
    batch = feeder_health_events([offline("fr24"), offline("adsbx")])

    assert [event.dedupe_key for event in batch.events] == [
        f"feeder_offline:fr24:{OUTAGE_START}",
        f"feeder_offline:adsbx:{OUTAGE_START}",
    ]


def test_a_restore_never_reports_a_negative_outage() -> None:
    skewed = FeederEpisode(
        feeder="fr24",
        label="FR24",
        kind="fr24",
        offline=False,
        since_ms=RESTORED_AT,
        at_ms=OUTAGE_START,
    )
    (event,) = feeder_health_events([skewed]).events
    assert event.payload["outage_s"] == 0.0


# -------------------------------------------------------------- the service


async def _types(repository: ActivityRepository) -> list[str]:
    return [event.type for event in await repository.list_events(limit=100)]


async def test_an_outage_and_its_restore_are_recorded_once_each(
    database: Database, clock: ManualClock
) -> None:
    service = service_for(database, clock=clock)
    await service.start()
    published: list[str] = []
    service.subscribe(lambda events: published.extend(event.type for event in events))

    service.record_feeder_episode(offline())
    await service.flush()
    # A hook that fires twice, or a transition re-announced after a restart.
    service.record_feeder_episode(offline())
    await service.flush()
    service.record_feeder_episode(restored())
    service.record_feeder_episode(restored())
    await service.flush()

    assert await _types(service.repository) == ["feeder_restored", "feeder_offline"]
    assert published == ["feeder_offline", "feeder_restored"]
    await service.stop()


async def test_a_failed_pass_keeps_the_feeder_episode(
    database: Database, clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = service_for(database, clock=clock)
    await service.start()

    async def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    service.record_feeder_episode(offline())
    monkeypatch.setattr(ActivityRepository, "record", explode)
    await service.flush()
    monkeypatch.undo()
    await service.flush()

    assert await _types(service.repository) == ["feeder_offline"]
    await service.stop()


async def test_the_feed_filters_by_the_new_types(database: Database, clock: ManualClock) -> None:
    service = service_for(database, clock=clock)
    await service.start()
    service.record_feeder_episode(offline())
    service.record_feeder_episode(restored())
    await service.flush()

    events = await service.repository.list_events(limit=10, types=["feeder_offline"])
    assert [event.type for event in events] == ["feeder_offline"]
    assert events[0].payload["feeder"] == "fr24"
    await service.stop()


def test_the_published_filter_accepts_the_new_types(isolated_data_dir: Path) -> None:
    """``ActivityEventTypeLiteral`` names both, so ``?type=`` does not 422."""
    with TestClient(create_app(isolated_data_dir)) as client:
        for event_type in ("feeder_offline", "feeder_restored"):
            response = client.get("/api/v1/activity", params={"type": event_type})
            assert response.status_code == 200, response.text


def test_the_enum_and_the_published_literal_agree() -> None:
    assert set(typing.get_args(ActivityEventTypeLiteral)) >= {
        ActivityEventType.FEEDER_OFFLINE.value,
        ActivityEventType.FEEDER_RESTORED.value,
    }
    assert {member.value for member in ActivityEventType} == set(
        typing.get_args(ActivityEventTypeLiteral)
    )
