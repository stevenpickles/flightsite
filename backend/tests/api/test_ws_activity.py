"""The ``activity_batch`` frame on ``/api/v1/ws/live`` — ``docs/API.md`` §4.4.

The frame added by slice 035 to the slice-010 protocol and batched by slice
057, so the tests are about the things that addition could have broken and the
things the frame has to do:

* it must not disturb the ``seq`` discipline the live picture depends on — a
  gap in ``seq`` has a meaning (§4.1), so an interleaved activity frame has to
  take its number in sequence like everything else;
* it must inherit the slow-consumer rule rather than acquire an exception to
  it (§4.5), because SPEC §5 says distribution must never stall;
* it must reach the clients that are connected, once each;
* and — slice 057's whole point — **one pass must cost one frame**, so that the
  number of frames a client is sent follows the detector's cadence and not the
  size of what it found. The per-event form sent hundreds of frames on a fresh
  install's first pass and the rule above then evicted every client
  (``docs/PERFORMANCE.md`` §6); the burst test at the bottom of this file is
  what keeps that from coming back.

Every frame here exists because the test asked for it: the broadcaster's tick
and ping clock are both driven by hand.
"""

from __future__ import annotations

from typing import Any

from flightsite.api.schemas import ActivityEventView
from flightsite.api.ws import (
    DEFAULT_CLIENT_QUEUE_SIZE,
    MAX_ACTIVITY_EVENTS_PER_FRAME,
    RESYNC_CLOSE_CODE,
    MessageType,
)
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
    assert frame["type"] == MessageType.ACTIVITY_BATCH.value
    assert frame["seq"] == 2
    assert frame["ts"].endswith("Z")
    # The body is an array even for a single event: one shape on the wire.
    assert isinstance(frame["data"], list)
    ActivityEventView.model_validate(frame["data"][0])


async def test_a_pass_is_one_frame_carrying_every_event(live_app: LiveApp) -> None:
    """Slice 057's contract: one frame per pass, not one per event.

    A frame per event made the burst size a function of how much the detector
    found, which is what overflowed client queues on a fresh install. Batching
    makes it a function of the detector's cadence, which is bounded.
    """
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.broadcaster.publish_activity([activity_event(1), activity_event(2)])
        await settle()
        frames = await probe.frames()
    finally:
        await probe.disconnect()

    assert [frame["type"] for frame in frames] == ["activity_batch"]
    assert [event["id"] for event in frames[0]["data"]] == [1, 2]
    assert [frame["seq"] for frame in frames] == [2]


async def test_the_batch_keeps_the_order_the_service_supplied(live_app: LiveApp) -> None:
    """Oldest first, as the repository returns them (sorted by event id).

    The frontend store prepends a batch reversed to stay newest-first, so the
    order on the wire is part of the contract rather than an accident.
    """
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.broadcaster.publish_activity([activity_event(index) for index in (7, 8, 9)])
        await settle()
        frame = await probe.frame()
    finally:
        await probe.disconnect()

    assert [event["id"] for event in frame["data"]] == [7, 8, 9]


async def test_a_pass_that_recorded_nothing_sends_no_frame(live_app: LiveApp) -> None:
    """The same silence an empty delta keeps (§4.3).

    A re-derivation that wrote nothing has nothing to say, and an empty array
    would still cost every client a frame of queue.
    """
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.broadcaster.publish_activity([])
        await settle()
        frames = await probe.frames()
    finally:
        await probe.disconnect()

    assert frames == []


async def test_a_huge_pass_is_split_at_the_per_frame_cap(live_app: LiveApp) -> None:
    """One frame per pass, but bounded (:data:`MAX_ACTIVITY_EVENTS_PER_FRAME`).

    A fresh install's first pass is ~500 first-ever sightings. One frame would
    fit the queue, but it would also sit in *every* client's queue at once and
    land in every browser as a single update; a few bounded frames are still
    an eighth of the queue and cannot evict anybody.
    """
    total = MAX_ACTIVITY_EVENTS_PER_FRAME * 2 + 5
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.broadcaster.publish_activity([activity_event(index) for index in range(total)])
        await settle()
        frames = await probe.frames()
    finally:
        await probe.disconnect()

    assert [frame["type"] for frame in frames] == ["activity_batch"] * 3
    assert [len(frame["data"]) for frame in frames] == [
        MAX_ACTIVITY_EVENTS_PER_FRAME,
        MAX_ACTIVITY_EVENTS_PER_FRAME,
        5,
    ]
    # Split, not resampled: every event is delivered exactly once, in order.
    delivered = [event["id"] for frame in frames for event in frame["data"]]
    assert delivered == list(range(total))


async def test_every_connected_client_receives_the_event(live_app: LiveApp) -> None:
    first, _one = await open_probe(live_app)
    second, _two = await open_probe(live_app)
    try:
        live_app.broadcaster.publish_activity([activity_event()])
        await settle()

        assert [event["id"] for event in (await first.frame())["data"]] == [1]
        assert [event["id"] for event in (await second.frame())["data"]] == [1]
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

    assert [frame["type"] for frame in frames] == ["delta", "activity_batch", "delta"]
    assert [frame["seq"] for frame in frames] == [2, 3, 4]


async def test_publishing_to_nobody_costs_nothing(live_app: LiveApp) -> None:
    """The events are already durable; a client connecting later reads them over REST.

    Serializing frames no one will receive would be pure waste on an install
    whose browser tab is closed, which is most of the time.
    """
    live_app.broadcaster.publish_activity([activity_event()])

    assert live_app.broadcaster.client_count == 0


async def test_a_fresh_install_backlog_no_longer_evicts_anybody(live_app: LiveApp) -> None:
    """Slice 057's reason to exist, pinned against the production queue size.

    A new database at 500 aircraft makes every one of them a first-ever
    sighting, so a single 5-second pass used to publish ~500 frames into a
    32-frame queue and shed every connected client (``docs/PERFORMANCE.md``
    §6). The client here does not read *at all* — the harshest form of the
    case — and still survives, because a pass is now four frames.

    Deliberately not parameterised down to a small queue: the number that has
    to hold is the one shipped installs run with.
    """
    probe, _snapshot = await open_probe(live_app)
    try:
        probe.stall()
        live_app.broadcaster.publish_activity([activity_event(index) for index in range(500)])
        await settle()

        assert live_app.broadcaster.client_count == 1
        assert counters.snapshot()[WS_DISCONNECTS] == 0

        probe.resume()
        await settle()
        frames = await probe.frames()
    finally:
        await probe.disconnect()

    # Four frames, well inside the queue, carrying all 500 events once each.
    assert len(frames) == -(-500 // MAX_ACTIVITY_EVENTS_PER_FRAME)
    assert len(frames) < DEFAULT_CLIENT_QUEUE_SIZE
    assert sum(len(frame["data"]) for frame in frames) == 500


async def test_a_client_that_cannot_keep_up_is_dropped_not_buffered() -> None:
    """§4.5's rule, inherited rather than excepted.

    Batching gives this method far fewer occasions to trip the rule; it does
    not exempt it. SPEC §5 says distribution must never stall: one client on a
    saturated link must not be able to slow detection down. The dropped client
    reconnects and fetches the feed over REST, which is strictly better than a
    stream it is already behind on.

    Ten *passes* rather than one pass of ten events — since slice 057 the
    frame count follows the detector's cadence, so a client is only outrun by
    a socket that stays stalled across passes, which is exactly the failure
    the rule is for.
    """
    harness = build_live_app(client_queue_size=2)
    async with harness.app.router.lifespan_context(harness.app):
        probe, _snapshot = await open_probe(harness)
        try:
            probe.stall()
            for index in range(10):
                harness.broadcaster.publish_activity([activity_event(index)])
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
        "activity_batch",
        "ping",
        "pong",
    }
