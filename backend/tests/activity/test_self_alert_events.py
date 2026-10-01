"""``self_alert_raised`` / ``self_alert_restored`` — slice 088's activity producer.

The producer is a pure function of :class:`SelfAlertEpisode` facts; the
service tests drive the real repository to prove the dedupe keys hold against
the ``UNIQUE`` index, so an episode announced twice (a restart that resumes
it, a sink called twice) is recorded — and broadcast — once.
"""

from __future__ import annotations

import typing
from pathlib import Path

from fastapi.testclient import TestClient

from flightsite.activity import (
    ActivityEventType,
    ActivityRepository,
    SelfAlertEpisode,
    Severity,
)
from flightsite.activity.producers import self_alert_events
from flightsite.api.schemas import ActivityEventTypeLiteral
from flightsite.app import create_app
from flightsite.db import Database

from .conftest import BASE_MS, MS_PER_MINUTE, ManualClock, service_for

SINCE = BASE_MS
RAISED_AT = BASE_MS + 5 * MS_PER_MINUTE
RESTORED_AT = BASE_MS + 12 * MS_PER_MINUTE


def raised(condition: str = "decoder_down") -> SelfAlertEpisode:
    return SelfAlertEpisode(
        condition=condition,
        raised=True,
        since_ms=SINCE,
        at_ms=RAISED_AT,
        detail={"minutes": 5, "error": "connection refused"},
    )


def restored(condition: str = "decoder_down") -> SelfAlertEpisode:
    return SelfAlertEpisode(
        condition=condition,
        raised=False,
        since_ms=SINCE,
        at_ms=RESTORED_AT,
        detail={"minutes": 5},
    )


def test_a_raise_is_high_severity_and_keyed_by_condition_and_start() -> None:
    (event,) = self_alert_events([raised()]).events

    assert event.type is ActivityEventType.SELF_ALERT_RAISED
    assert event.severity is Severity.HIGH
    assert event.ts_ms == RAISED_AT
    assert event.dedupe_key == f"self_alert_raised:decoder_down:{SINCE}"
    assert event.aircraft_id is None
    assert event.payload == {
        "condition": "decoder_down",
        "since_ms": SINCE,
        "duration_s": None,
        "minutes": 5,
        "error": "connection refused",
    }


def test_a_restore_is_info_and_reports_the_episode_length() -> None:
    (event,) = self_alert_events([restored()]).events

    assert event.type is ActivityEventType.SELF_ALERT_RESTORED
    assert event.severity is Severity.INFO
    assert event.dedupe_key == f"self_alert_restored:decoder_down:{SINCE}"
    assert event.payload["duration_s"] == 12 * 60.0


def test_the_detail_cannot_overwrite_the_identifying_fields() -> None:
    episode = SelfAlertEpisode(
        condition="message_rate",
        raised=True,
        since_ms=SINCE,
        at_ms=RAISED_AT,
        detail={"condition": "spoofed", "since_ms": 1},
    )
    (event,) = self_alert_events([episode]).events
    assert event.payload["condition"] == "message_rate"
    assert event.payload["since_ms"] == SINCE


async def _types(repository: ActivityRepository) -> list[str]:
    return [event.type for event in await repository.list_events(limit=100)]


async def test_one_raise_and_one_restore_per_episode(
    database: Database, clock: ManualClock
) -> None:
    service = service_for(database, clock=clock)
    await service.start()
    published: list[str] = []
    service.subscribe(lambda events: published.extend(event.type for event in events))

    service.record_self_alert(raised())
    await service.flush()
    # A monitor that resumed the episode after a restart and re-announced it.
    service.record_self_alert(raised())
    await service.flush()
    service.record_self_alert(restored())
    service.record_self_alert(restored())
    await service.flush()

    assert await _types(service.repository) == ["self_alert_restored", "self_alert_raised"]
    assert published == ["self_alert_raised", "self_alert_restored"]
    await service.stop()


async def test_two_conditions_at_once_are_two_episodes(
    database: Database, clock: ManualClock
) -> None:
    service = service_for(database, clock=clock)
    await service.start()
    service.record_self_alert(raised("decoder_down"))
    service.record_self_alert(raised("message_rate"))
    await service.flush()

    events = await service.repository.list_events(limit=10, types=["self_alert_raised"])
    assert sorted(event.payload["condition"] for event in events) == [
        "decoder_down",
        "message_rate",
    ]
    await service.stop()


def test_the_published_filter_accepts_the_new_types(isolated_data_dir: Path) -> None:
    with TestClient(create_app(isolated_data_dir)) as client:
        for event_type in ("self_alert_raised", "self_alert_restored"):
            response = client.get("/api/v1/activity", params={"type": event_type})
            assert response.status_code == 200, response.text


def test_the_enum_and_the_published_literal_agree() -> None:
    assert {member.value for member in ActivityEventType} == set(
        typing.get_args(ActivityEventTypeLiteral)
    )
