"""The ``/api/v1/ws/live`` protocol: snapshot, deltas, notices, keepalive.

Every frame in these tests exists because the test asked for it: the live
store's clock and the broadcaster's tick are both driven by hand, so an
assertion about "the next frame" is an assertion about the protocol and never
about scheduling luck.
"""

from __future__ import annotations

from typing import Any

from flightsite.api.schemas import AircraftView, ReceiverInfo
from flightsite.counters import counters
from flightsite.ingest import Position

from ..live.conftest import make_update
from .conftest import LiveApp, WebSocketProbe, build_live_app, open_probe, settle

NEARBY = Position(latitude=47.6205, longitude=-122.3493)
FARTHER = Position(latitude=48.0, longitude=-122.0)


def data(frame: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = frame["data"]
    return payload


# ------------------------------------------------------------- connect (§4.2)


async def test_a_new_connection_is_answered_with_a_snapshot(live_app: LiveApp) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY, callsign="RCH492"))

    probe, snapshot = await open_probe(live_app)
    try:
        assert snapshot["type"] == "snapshot"
        assert snapshot["seq"] == 1
        assert snapshot["ts"].endswith("Z")
        aircraft = data(snapshot)["aircraft"]
        assert [entry["icao"] for entry in aircraft] == ["ae1463"]
        AircraftView.model_validate(aircraft[0])
        ReceiverInfo.model_validate(data(snapshot)["receiver"])
    finally:
        await probe.disconnect()


async def test_the_snapshot_carries_the_receiver_block(live_app: LiveApp) -> None:
    probe, snapshot = await open_probe(live_app)
    try:
        assert data(snapshot)["receiver"]["demo_mode"] is False
        assert data(snapshot)["receiver"]["display_radius_nm"] == 250.0
    finally:
        await probe.disconnect()


async def test_an_empty_sky_still_produces_a_snapshot(live_app: LiveApp) -> None:
    probe, snapshot = await open_probe(live_app)
    try:
        assert data(snapshot)["aircraft"] == []
    finally:
        await probe.disconnect()


# --------------------------------------------------------------- deltas (§4.3)


async def test_a_new_aircraft_arrives_as_a_complete_object(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.feed(make_update("ae1463", position=NEARBY, callsign="RCH492"))
        await live_app.broadcast()

        delta = await probe.frame()
        assert delta["type"] == "delta"
        assert delta["seq"] == 2
        updated = data(delta)["updated"]
        # §4.3: complete aircraft objects, never field patches.
        assert set(updated[0]) == set(AircraftView.model_fields)
        assert updated[0]["callsign"] == "RCH492"
        assert data(delta)["stale"] == []
        assert data(delta)["removed"] == []
    finally:
        await probe.disconnect()


async def test_a_batch_reports_one_entry_per_changed_aircraft(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    try:
        # Three observations of the same aircraft inside one tick: the delta
        # carries its latest state once, not three intermediate copies.
        live_app.feed(make_update("ae1463", position=NEARBY, altitude_ft=20_000.0))
        live_app.feed(make_update("ae1463", offset_s=1.0, position=NEARBY, altitude_ft=21_000.0))
        live_app.feed(make_update("ae1463", offset_s=2.0, position=FARTHER, altitude_ft=22_000.0))
        await live_app.broadcast()

        updated = data(await probe.frame())["updated"]
        assert len(updated) == 1
        assert updated[0]["altitude_ft"] == 22_000.0
    finally:
        await probe.disconnect()


async def test_nothing_happening_produces_no_frame(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    try:
        await live_app.broadcast()

        assert await probe.frames() == []
    finally:
        await probe.disconnect()


async def test_crossing_the_stale_threshold_is_announced(live_app: LiveApp) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY))
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.advance(live_app.live.stale_s + 1.0)
        live_app.sweep()
        await live_app.broadcast()

        delta = data(await probe.frame())
        assert delta["stale"] == ["ae1463"]
        assert delta["removed"] == []
    finally:
        await probe.disconnect()


async def test_leaving_the_live_set_is_announced(live_app: LiveApp) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY))
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.advance(live_app.live.remove_s + 1.0)
        live_app.sweep()
        await live_app.broadcast()

        delta = data(await probe.frame())
        assert delta["removed"] == ["ae1463"]
        assert delta["updated"] == []
    finally:
        await probe.disconnect()


async def test_a_removal_supersedes_an_update_in_the_same_batch(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.feed(make_update("ae1463", position=NEARBY))
        live_app.advance(live_app.live.remove_s + 1.0)
        live_app.sweep()
        await live_app.broadcast()

        delta = data(await probe.frame())
        # Appeared and removed within one second: the removal is the only
        # truthful statement, and an `updated` entry for a gone aircraft would
        # leave the client holding a ghost.
        assert delta["removed"] == ["ae1463"]
        assert delta["updated"] == []
    finally:
        await probe.disconnect()


async def test_an_aircraft_that_changed_and_went_stale_appears_in_both_lists(
    live_app: LiveApp,
) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY, altitude_ft=20_000.0))
    probe, _snapshot = await open_probe(live_app)
    try:
        live_app.feed(make_update("ae1463", offset_s=1.0, position=NEARBY, altitude_ft=21_000.0))
        live_app.advance(live_app.live.stale_s + 1.0)
        live_app.sweep()
        await live_app.broadcast()

        delta = data(await probe.frame())
        assert delta["stale"] == ["ae1463"]
        # The update is not lost, and the complete object it carries already
        # says `stale`, so the two notices cannot contradict each other.
        assert delta["updated"][0]["altitude_ft"] == 21_000.0
        assert delta["updated"][0]["state"] == "stale"
    finally:
        await probe.disconnect()


async def test_an_aircraft_heard_again_after_going_stale_is_live_again(
    live_app: LiveApp,
) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY))
    live_app.advance(live_app.live.stale_s + 1.0)
    live_app.sweep()
    probe, snapshot = await open_probe(live_app)
    try:
        assert data(snapshot)["aircraft"][0]["state"] == "stale"

        live_app.feed(make_update("ae1463", offset_s=20.0, position=NEARBY))
        await live_app.broadcast()

        delta = data(await probe.frame())
        assert delta["stale"] == []
        assert delta["updated"][0]["state"] == "live"
    finally:
        await probe.disconnect()


# ------------------------------------------------------------ sequencing (§4.1)


async def test_seq_increases_by_one_per_frame_on_a_connection(live_app: LiveApp) -> None:
    probe, snapshot = await open_probe(live_app)
    try:
        seqs = [snapshot["seq"]]
        for index in range(4):
            live_app.feed(make_update("ae1463", offset_s=index, position=NEARBY))
            await live_app.broadcast()
            seqs.append((await probe.frame())["seq"])

        assert seqs == [1, 2, 3, 4, 5]
    finally:
        await probe.disconnect()


async def test_each_connection_has_its_own_sequence(live_app: LiveApp) -> None:
    first, _snapshot = await open_probe(live_app)
    try:
        live_app.feed(make_update("ae1463", position=NEARBY))
        await live_app.broadcast()
        assert (await first.frame())["seq"] == 2

        second, late_snapshot = await open_probe(live_app)
        try:
            # A client that joined late starts at 1, not at the broadcaster's
            # running count: `seq` is per connection (§4.1).
            assert late_snapshot["seq"] == 1

            live_app.feed(make_update("a9c2f0", position=NEARBY))
            await live_app.broadcast()
            assert (await first.frame())["seq"] == 3
            assert (await second.frame())["seq"] == 2
        finally:
            await second.disconnect()
    finally:
        await first.disconnect()


# ------------------------------------------------------- keepalive (§4.5)


async def test_the_server_pings_on_its_schedule() -> None:
    harness = build_live_app(ping_interval_s=30.0)
    async with harness.app.router.lifespan_context(harness.app):
        probe, _snapshot = await open_probe(harness)
        try:
            await harness.broadcast()
            assert await probe.frames() == []

            harness.ping_clock.advance(31.0)
            await harness.broadcast()

            ping = await probe.frame()
            assert ping["type"] == "ping"
            assert ping["seq"] == 2
        finally:
            await probe.disconnect()


async def test_a_client_ping_is_answered_with_a_pong(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    try:
        await probe.send({"type": "ping"})

        pong = await probe.frame()
        assert pong["type"] == "pong"
        assert pong["seq"] == 2
    finally:
        await probe.disconnect()


async def test_a_bare_ping_word_is_also_answered(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    try:
        await probe.send("ping")

        assert (await probe.frame())["type"] == "pong"
    finally:
        await probe.disconnect()


async def test_a_client_that_answers_pings_is_kept() -> None:
    harness = build_live_app(ping_interval_s=30.0)
    async with harness.app.router.lifespan_context(harness.app):
        probe, _snapshot = await open_probe(harness)
        try:
            for _ in range(4):
                harness.ping_clock.advance(31.0)
                await harness.broadcast()
                assert (await probe.frame())["type"] == "ping"
                await probe.send({"type": "pong"})

            assert harness.broadcaster.client_count == 1
        finally:
            await probe.disconnect()


async def test_a_client_that_ignores_two_pings_is_dropped() -> None:
    harness = build_live_app(ping_interval_s=30.0)
    async with harness.app.router.lifespan_context(harness.app):
        probe = WebSocketProbe(app=harness.app)
        await probe.connect()
        await probe.frame()

        for _ in range(3):
            harness.ping_clock.advance(31.0)
            await harness.broadcast()

        # Two unanswered pings is the documented limit; the third ping's turn
        # is when the connection goes.
        assert harness.broadcaster.client_count == 0
        assert await probe.close_code() == 1013
        await probe.disconnect()


async def test_any_client_message_counts_as_liveness() -> None:
    harness = build_live_app(ping_interval_s=30.0)
    async with harness.app.router.lifespan_context(harness.app):
        probe, _snapshot = await open_probe(harness)
        try:
            for _ in range(4):
                harness.ping_clock.advance(31.0)
                await harness.broadcast()
                await probe.frames()
                # Not a pong, not even a known type — but the client is
                # demonstrably alive, which is what the check is for.
                await probe.send({"type": "hello"})
                await settle()

            assert harness.broadcaster.client_count == 1
        finally:
            await probe.disconnect()


# ---------------------------------------------------------- disconnect (§4.5)


async def test_a_client_disconnect_deregisters_it(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    assert live_app.broadcaster.client_count == 1

    await probe.disconnect()

    assert live_app.broadcaster.client_count == 0


async def test_a_clean_disconnect_is_not_counted_as_a_drop(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    await probe.disconnect()

    # `ws_disconnects` measures clients the server had to abandon, so a client
    # closing normally must leave it alone.
    assert counters.snapshot()["ws_disconnects"] == 0


async def test_shutdown_closes_every_client_without_counting_a_drop() -> None:
    harness = build_live_app()
    async with harness.app.router.lifespan_context(harness.app):
        probe, _snapshot = await open_probe(harness)

    assert await probe.close_code() == 1001
    assert counters.snapshot()["ws_disconnects"] == 0
    await probe.disconnect()


async def test_a_message_that_is_not_json_is_ignored(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    try:
        # §6 tells clients to tolerate what they do not understand; the server
        # extends the same courtesy rather than dropping the connection.
        await probe.send("not json at all")

        assert await probe.frames() == []
        assert live_app.broadcaster.client_count == 1
    finally:
        await probe.disconnect()


async def test_a_json_string_ping_is_answered(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    try:
        await probe.send('"ping"')

        assert (await probe.frame())["type"] == "pong"
    finally:
        await probe.disconnect()


async def test_an_unknown_envelope_type_is_ignored(live_app: LiveApp) -> None:
    probe, _snapshot = await open_probe(live_app)
    try:
        await probe.send({"type": "subscribe", "data": {}})

        assert await probe.frames() == []
        assert live_app.broadcaster.client_count == 1
    finally:
        await probe.disconnect()
