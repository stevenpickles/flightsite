"""Slow consumers and lost events: the two ways the stream refuses to stall.

SPEC §5 and ``docs/ARCHITECTURE.md`` §3.3 make the same demand from two
directions — one client must never be able to slow ingestion or another
client, and the broadcaster must never pretend a gap in its own event stream
was continuity. ``docs/API.md`` §4.5 names both answers: drop the slow client
so its reconnect resyncs, and resync everyone from a snapshot when events were
lost.
"""

from __future__ import annotations

import pytest

from flightsite.api.ws import (
    RESYNC_CLOSE_CODE,
    ClientConnection,
    Frame,
    LiveBroadcaster,
    MessageType,
)
from flightsite.counters import counters
from flightsite.ingest import Position

from ..live.conftest import make_update
from .conftest import LiveApp, build_live_app, open_probe, settle

NEARBY = Position(latitude=47.6205, longitude=-122.3493)

#: Small enough that a handful of aircraft overflows the broadcaster's own
#: event subscription, which is the only way to reach the drop-and-resync path
#: without publishing thousands of events.
TINY_EVENT_QUEUE = 8


def a_frame() -> Frame:
    return Frame.build(MessageType.DELTA, {"updated": [], "stale": [], "removed": []})


def overflow_the_subscription(harness: LiveApp) -> None:
    """Publish more events than the broadcaster's subscription can hold."""
    for index in range(TINY_EVENT_QUEUE + 8):
        harness.feed(make_update(f"{index:06x}", position=NEARBY))


# ----------------------------------------------------- the connection itself


def test_a_connection_numbers_the_frames_it_accepted() -> None:
    client = ClientConnection(name="ws-1", queue_size=4)

    assert client.deliver(a_frame()) is True
    assert client.deliver(a_frame()) is True
    assert client.seq == 2


async def test_a_full_queue_drops_the_connection() -> None:
    client = ClientConnection(name="ws-1", queue_size=1)
    assert client.deliver(a_frame()) is True

    assert client.deliver(a_frame()) is False
    assert client.closed is True
    assert client.close_code == RESYNC_CLOSE_CODE
    assert counters.snapshot()["ws_disconnects"] == 1


async def test_a_dropped_connection_discards_its_backlog_and_signals() -> None:
    client = ClientConnection(name="ws-1", queue_size=1)
    client.deliver(a_frame())
    client.deliver(a_frame())

    # The queued frame described a picture the client is about to be resynced
    # out of; holding it would only delay the close behind a backlog.
    assert await client.next_frame() is None
    assert client.deliver(a_frame()) is False


def test_a_dropped_frame_does_not_advance_the_sequence() -> None:
    # §4.1 gives a `seq` gap a meaning, so one must never appear by accident.
    client = ClientConnection(name="ws-1", queue_size=1)
    client.deliver(a_frame())

    client.deliver(a_frame())

    assert client.seq == 1


def test_a_connection_needs_room_for_at_least_one_frame() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        ClientConnection(name="ws-1", queue_size=0)


# ------------------------------------------------------ eviction end to end


async def test_a_stalled_client_is_evicted_and_the_others_are_untouched() -> None:
    # A queue of one frame makes "cannot keep up" reachable in a test; the
    # mechanism is the production one, and so is the eviction it triggers.
    harness = build_live_app(client_queue_size=1)
    async with harness.app.router.lifespan_context(harness.app):
        healthy, _snapshot = await open_probe(harness)
        stalled, _stalled_snapshot = await open_probe(harness)
        stalled.stall()
        try:
            for index in range(5):
                harness.feed(make_update("ae1463", offset_s=index, position=NEARBY))
                await harness.broadcast()

            assert harness.broadcaster.client_count == 1
            assert counters.snapshot()["ws_disconnects"] == 1

            # The healthy client saw every frame, in order, unaffected by its
            # neighbour's failure.
            frames = await healthy.frames()
            assert [frame["type"] for frame in frames] == ["delta"] * 5
            assert [frame["seq"] for frame in frames] == [2, 3, 4, 5, 6]

            stalled.resume()
            assert await stalled.close_code() == RESYNC_CLOSE_CODE
        finally:
            await healthy.disconnect()
            await stalled.disconnect()


async def test_a_stalled_client_does_not_stall_the_live_store() -> None:
    harness = build_live_app(client_queue_size=1)
    async with harness.app.router.lifespan_context(harness.app):
        stalled, _snapshot = await open_probe(harness)
        stalled.stall()
        try:
            for index in range(5):
                harness.feed(make_update("ae1463", offset_s=index, position=NEARBY))
                await harness.broadcast()

            # Ingestion kept running throughout: the store holds the aircraft
            # and the REST picture is current, whatever the socket is doing.
            assert len(harness.live) == 1
            assert harness.app.state.api_context.aircraft()[0]["icao"] == "ae1463"
        finally:
            stalled.resume()
            await stalled.disconnect()


# ---------------------------------------------- resync after lost events


async def test_losing_events_broadcasts_a_fresh_snapshot() -> None:
    harness = build_live_app(event_queue_size=TINY_EVENT_QUEUE)
    async with harness.app.router.lifespan_context(harness.app):
        probe, _snapshot = await open_probe(harness)
        try:
            # Overflow the broadcaster's own bounded subscription: the live
            # store sheds its oldest events, so the delta stream has a hole.
            overflow_the_subscription(harness)
            await harness.broadcast()

            frame = await probe.frame()
            assert frame["type"] == "snapshot"
            assert frame["seq"] == 2
            icaos = [entry["icao"] for entry in frame["data"]["aircraft"]]
            assert icaos == sorted(icaos)
            assert len(icaos) == len(harness.live)
        finally:
            await probe.disconnect()


async def test_a_resync_is_not_repeated_once_the_gap_is_acknowledged() -> None:
    harness = build_live_app(event_queue_size=TINY_EVENT_QUEUE)
    async with harness.app.router.lifespan_context(harness.app):
        probe, _snapshot = await open_probe(harness)
        try:
            overflow_the_subscription(harness)
            await harness.broadcast()
            assert (await probe.frame())["type"] == "snapshot"

            harness.feed(make_update("ae1463", offset_s=99.0, position=NEARBY))
            await harness.broadcast()

            assert (await probe.frame())["type"] == "delta"
        finally:
            await probe.disconnect()


async def test_events_are_drained_even_with_nobody_listening() -> None:
    # An idle socket must not let the subscription fill up and start shedding:
    # draining is cheap, and serializing frames no one will read is not.
    harness = build_live_app()
    async with harness.app.router.lifespan_context(harness.app):
        harness.feed(make_update("ae1463", position=NEARBY))
        await harness.broadcast()

        assert harness.broadcaster.client_count == 0
        assert counters.snapshot()["live_events_dropped"] == 0


async def test_a_client_connecting_during_a_gap_still_gets_a_coherent_picture() -> None:
    harness = build_live_app(event_queue_size=TINY_EVENT_QUEUE)
    async with harness.app.router.lifespan_context(harness.app):
        overflow_the_subscription(harness)

        probe, snapshot = await open_probe(harness)
        try:
            # The snapshot is read from the store, not replayed from events,
            # so a hole in the event stream cannot make it wrong.
            await settle()
            assert len(snapshot["data"]["aircraft"]) == len(harness.live)
        finally:
            await probe.disconnect()


async def test_dropping_a_connection_twice_counts_once() -> None:
    client = ClientConnection(name="ws-1", queue_size=1)
    client.deliver(a_frame())

    client.deliver(a_frame())
    client.deliver(a_frame())

    # The connection is already gone; counting it again would make
    # `ws_disconnects` a measure of broadcast attempts rather than of clients.
    assert counters.snapshot()["ws_disconnects"] == 1


def test_a_broadcaster_needs_a_positive_interval() -> None:
    context = build_live_app().app.state.api_context

    with pytest.raises(ValueError, match="broadcast interval"):
        LiveBroadcaster(context=context, interval_s=0.0)
    with pytest.raises(ValueError, match="ping interval"):
        LiveBroadcaster(context=context, ping_interval_s=-1.0)


async def test_starting_twice_keeps_one_subscription() -> None:
    harness = build_live_app()
    async with harness.app.router.lifespan_context(harness.app):
        # The lifespan already started it; a second start must not attach a
        # second subscription, which would double every event it sees.
        await harness.broadcaster.start()

        assert harness.broadcaster.running is True
        assert harness.live.events.subscriber_count == 2  # broadcaster + persistence


async def test_broadcasting_before_start_is_a_no_op() -> None:
    harness = build_live_app()

    await harness.broadcaster.broadcast_once()

    assert harness.broadcaster.client_count == 0


async def test_stopping_twice_is_harmless() -> None:
    harness = build_live_app()
    async with harness.app.router.lifespan_context(harness.app):
        pass

    await harness.broadcaster.stop()

    assert harness.broadcaster.running is False
