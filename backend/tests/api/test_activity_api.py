"""``GET /api/v1/activity`` — the §3.9 feed, and the §4.4 frame beside it.

Two surfaces, one shape, one serializer: the last group of tests here asserts
that the object a client fetches over REST and the object it receives over the
WebSocket are byte-for-byte the same document, which is what makes §4.4's
*"activity event, §3.9 shape"* a property rather than a promise.

The app harness is :mod:`tests.api.conftest`'s: driven clocks, no sleeping, and
a WebSocket probe that speaks ASGI on the test's own loop so "record an event,
then broadcast, then read the frame" is a sequence rather than a race.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from flightsite.activity import (
    ActivityBatch,
    ActivityEventType,
    ActivityRepository,
    NewActivityEvent,
    Severity,
)
from flightsite.api.schemas import ActivityListResponse
from flightsite.api.serializers import activity_event_payload, iso_utc
from flightsite.api.ws import LiveBroadcaster
from flightsite.db import Database, from_epoch_ms

from .conftest import LiveApp, open_probe, settle

BASE_MS = 1_780_000_000_000
MS_PER_HOUR = 3_600_000


def event(
    dedupe: str,
    *,
    ts_ms: int = BASE_MS,
    kind: ActivityEventType = ActivityEventType.FIRST_EVER_AIRCRAFT,
    severity: Severity = Severity.INFO,
    payload: dict[str, Any] | None = None,
) -> NewActivityEvent:
    return NewActivityEvent(
        type=kind,
        ts_ms=ts_ms,
        dedupe_key=dedupe,
        severity=severity,
        payload=payload or {},
    )


async def record(live_app: LiveApp, *events: NewActivityEvent) -> None:
    """Write events straight into the table the endpoint reads."""
    database: Database = live_app.app.state.database
    await ActivityRepository(database).record(ActivityBatch(events=events))


async def fetch(rest: AsyncClient, **params: Any) -> ActivityListResponse:
    """Call the endpoint and validate the response against its published model."""
    response = await rest.get("/api/v1/activity", params=params)
    assert response.status_code == 200
    return ActivityListResponse.model_validate(response.json())


async def test_an_install_with_no_history_answers_an_empty_page(rest: AsyncClient) -> None:
    """A first run has nothing to say, and says it with 200 and no rows."""
    page = await fetch(rest)

    assert page.items == []
    assert page.total is None
    assert (page.limit, page.offset) == (50, 0)


async def test_the_feed_is_newest_first(live_app: LiveApp, rest: AsyncClient) -> None:
    await record(
        live_app,
        event("a", ts_ms=BASE_MS),
        event("b", ts_ms=BASE_MS + MS_PER_HOUR),
        event("c", ts_ms=BASE_MS + 2 * MS_PER_HOUR),
    )

    page = await fetch(rest)

    assert [item.id for item in page.items] == [3, 2, 1]


async def test_an_event_serializes_as_the_documented_shape(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """§3.9's typed event with a human-renderable payload.

    The payload is passed through as recorded: its members depend on the type,
    and re-deriving anything here would put a second opinion beside the one
    written when the event happened.
    """
    payload = {"icao": "ae1463", "registration": "G-ABCD", "type_code": "B738", "model": None}
    await record(
        live_app,
        event("a", kind=ActivityEventType.NEW_TYPE, severity=Severity.INTERESTING, payload=payload),
    )

    page = await fetch(rest)

    (item,) = page.items
    assert item.type == "new_type"
    assert item.severity == "interesting"
    assert item.at.endswith("Z")
    assert item.payload == payload
    # No airframe row is linked, so the *event's* address is null even though
    # the payload names one: the link a feed row opens has to be a real row.
    assert item.icao is None
    assert item.sighting_id is None


async def test_the_page_reports_the_bounds_it_was_asked_for(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await record(live_app, *(event(str(index)) for index in range(5)))

    page = await fetch(rest, limit=2, offset=1)

    assert (page.limit, page.offset) == (2, 1)
    assert [item.id for item in page.items] == [4, 3]


async def test_paging_walks_the_whole_feed_without_repeating_or_skipping(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """``total`` is always null, so a client pages until a page comes back short."""
    await record(live_app, *(event(str(index)) for index in range(5)))

    first = await fetch(rest, limit=2, offset=0)
    second = await fetch(rest, limit=2, offset=2)
    third = await fetch(rest, limit=2, offset=4)

    assert [item.id for item in first.items] == [5, 4]
    assert [item.id for item in second.items] == [3, 2]
    assert [item.id for item in third.items] == [1]
    assert third.total is None


async def test_the_type_filter_accepts_several_kinds(live_app: LiveApp, rest: AsyncClient) -> None:
    """Repeatable rather than comma-separated: the feed's chips select several."""
    await record(
        live_app,
        event("a", kind=ActivityEventType.FIRST_EVER_AIRCRAFT),
        event("b", kind=ActivityEventType.NEW_TYPE),
        event("c", kind=ActivityEventType.MILESTONE),
    )

    page = await fetch(rest, type=["new_type", "milestone"])

    assert {item.type for item in page.items} == {"new_type", "milestone"}


async def test_an_unknown_event_type_is_rejected_rather_than_silently_ignored(
    rest: AsyncClient,
) -> None:
    """The published ``Literal`` is the contract; a typo is a 422, not an empty page."""
    response = await rest.get("/api/v1/activity", params={"type": "not_an_event"})

    assert response.status_code == 422


async def test_the_window_filter_is_inclusive_at_both_ends(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await record(
        live_app,
        event("a", ts_ms=BASE_MS),
        event("b", ts_ms=BASE_MS + MS_PER_HOUR),
        event("c", ts_ms=BASE_MS + 2 * MS_PER_HOUR),
    )

    page = await fetch(
        rest,
        **{
            "from": iso_utc(from_epoch_ms(BASE_MS)),
            "to": iso_utc(from_epoch_ms(BASE_MS + MS_PER_HOUR)),
        },
    )

    assert [item.id for item in page.items] == [2, 1]


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (501, 0), (50, -1)])
async def test_pagination_bounds_are_enforced(rest: AsyncClient, limit: int, offset: int) -> None:
    """§2.4's bounds, so one request cannot ask for an unbounded page."""
    response = await rest.get("/api/v1/activity", params={"limit": limit, "offset": offset})

    assert response.status_code == 422


async def test_the_endpoint_is_published_in_the_openapi_document(rest: AsyncClient) -> None:
    """§2.10: the schema is only worth serving if it describes what is served."""
    document = (await rest.get("/api/v1/openapi.json")).json()

    assert "/api/v1/activity" in document["paths"]
    assert "get" in document["paths"]["/api/v1/activity"]


# ------------------------------------------------------- REST/WS agreement


async def test_the_websocket_frame_carries_the_same_object_as_the_feed(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """§4.4's body *is* §3.9's shape, because one serializer builds both.

    Recorded first and broadcast second, so the comparison is between two
    renderings of the same stored row rather than between a live object and a
    stored one.
    """
    broadcaster: LiveBroadcaster = live_app.app.state.broadcaster
    database: Database = live_app.app.state.database
    created = await ActivityRepository(database).record(
        ActivityBatch(events=(event("a", kind=ActivityEventType.MILESTONE),))
    )

    probe, _snapshot = await open_probe(live_app)
    try:
        broadcaster.publish_activity([activity_event_payload(created[0])])
        await settle()
        frame = await probe.frame()
    finally:
        await probe.disconnect()

    page = await fetch(rest)
    assert frame["type"] == "activity"
    assert frame["data"] == page.items[0].model_dump()
