"""The ``activity`` frame on ``/api/v1/ws/live`` — ``docs/API.md`` §4.4.

The frame added by slice 035 to the slice-010 protocol, so the tests are about
the two things that addition could have broken and the one thing it has to do:

* it must not disturb the ``seq`` discipline the live picture depends on — a
  gap in ``seq`` has a meaning (§4.1), so an interleaved activity frame has to
  take its number in sequence like everything else;
* it must inherit the slow-consumer rule rather than acquire an exception to
  it (§4.5), because SPEC §5 says distribution must never stall;
* and it must reach the clients that are connected, once each.

Every frame here exists because the test asked for it: the broadcaster's tick
and ping clock are both driven by hand.
"""

from __future__ import annotations

from typing import Any

from flightsite.api.schemas import ActivityEventView
from flightsite.api.ws import RESYNC_CLOSE_CODE, MessageType
from flightsite.counters import WS_DISCONNECTS, counters

from ..live.conftest import make_update
from .conftest import LiveApp, build_live_app, open_probe, settle

BASE_ISO = "2026-08-31T14:03:22.418Z"


def activity_event(event_id: int = 1, **overrides: Any) -> dict[str, Any]:
    """A §3.9 activity event payload, as the serializer produces one."""
    return {
        "id": event_id,
        "type": "first_ever_aircraft",
        "severity": "info",
        "at": BASE_ISO,
        "icao": "ae1463",
        "sighting_id": 9021,
        "payload": {"icao": "ae1463", "registration": "G-ABCD"},
        **overrides,
    }


async def test_an_activity_event_reaches_a_connected_client(live_app: LiveApp) -> None:
    probe, snapshot = await open_probe(live_app)
    try:
        live_app.broadcaster.publish_activity([activity_event()])
        await settle()
        frame = await probe.frame()
    finally:
        await probe.disconnect()

    assert snapshot["seq"] == 1
    assert frame["type"] == MessageType.ACTIVITY.value
    assert frame["seq"] == 2
    assert frame["ts"].endswith("Z")
    ActivityEventView.model_validate(frame["data"])


async def test_each_event_is_its_own_frame(live_app: LiveApp) -> None:
    """One event per frame, not a batch.

    They arrive a few a minute at most, and a client that has to unwrap a list
    to render one row would be paying for a rate that does not exist.
    """
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.broadcaster.publish_activity([activity_event(1), activity_event(2)])
        await settle()
        frames = await probe.frames()
    finally:
        await probe.disconnect()

    assert [frame["type"] for frame in frames] == ["activity", "activity"]
    assert [frame["data"]["id"] for frame in frames] == [1, 2]
    assert [frame["seq"] for frame in frames] == [2, 3]


async def test_every_connected_client_receives_the_event(live_app: LiveApp) -> None:
    first, _one = await open_probe(live_app)
    second, _two = await open_probe(live_app)
    try:
        live_app.broadcaster.publish_activity([activity_event()])
        await settle()

        assert (await first.frame())["data"]["id"] == 1
        assert (await second.frame())["data"]["id"] == 1
    finally:
        await first.disconnect()
        await second.disconnect()


async def test_an_activity_frame_takes_its_place_in_the_sequence(live_app: LiveApp) -> None:
    """``seq`` gaps have a meaning (§4.1), so this frame must not leave one.

    A delta, an activity event and another delta number 2, 3, 4 — a client
    checking for gaps sees a continuous stream whether or not it understands
    the middle frame.
    """
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.feed(make_update("ae1463"))
        await live_app.broadcast()
        live_app.broadcaster.publish_activity([activity_event()])
        await settle()
        live_app.feed(make_update("a9c2f0"))
        await live_app.broadcast()
        frames = await probe.frames()
    finally:
        await probe.disconnect()

    assert [frame["type"] for frame in frames] == ["delta", "activity", "delta"]
    assert [frame["seq"] for frame in frames] == [2, 3, 4]


async def test_publishing_to_nobody_costs_nothing(live_app: LiveApp) -> None:
    """The events are already durable; a client connecting later reads them over REST.

    Serializing frames no one will receive would be pure waste on an install
    whose browser tab is closed, which is most of the time.
    """
    live_app.broadcaster.publish_activity([activity_event()])

    assert live_app.broadcaster.client_count == 0


async def test_a_client_that_cannot_keep_up_is_dropped_not_buffered() -> None:
    """§4.5's rule, inherited rather than excepted.

    SPEC §5 says distribution must never stall: one client on a saturated link
    must not be able to slow detection down. The dropped client reconnects and
    fetches the feed over REST, which is strictly better than a stream it is
    already behind on.
    """
    harness = build_live_app(client_queue_size=2)
    async with harness.app.router.lifespan_context(harness.app):
        probe, _snapshot = await open_probe(harness)
        try:
            probe.stall()
            harness.broadcaster.publish_activity([activity_event(index) for index in range(10)])
            await settle()

            assert harness.broadcaster.client_count == 0
            assert counters.snapshot()[WS_DISCONNECTS] == 1

            probe.resume()
            assert await probe.close_code() == RESYNC_CLOSE_CODE
        finally:
            await probe.disconnect()


async def test_the_frame_type_is_part_of_the_declared_vocabulary() -> None:
    """§4's list, so a reader of the enum sees the whole protocol in one place."""
    assert {member.value for member in MessageType} == {
        "snapshot",
        "delta",
        "activity",
        "ping",
        "pong",
    }
