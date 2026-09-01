"""REST and the WebSocket describe the same instant identically.

Roadmap slice 010's first acceptance criterion, tested twice over: the
snapshot a connection opens with equals what ``GET /api/v1/aircraft/current``
returns at that moment, and a client that applies the delta stream in the
documented order stays equal to it — which is the stronger claim, because a
snapshot that matches once proves nothing about the deltas that follow.
"""

from __future__ import annotations

from typing import Any

from httpx import ASGITransport, AsyncClient

from flightsite.ingest import Position

from ..live.conftest import make_update
from .conftest import LiveApp, build_live_app, open_probe

NEARBY = Position(latitude=47.6205, longitude=-122.3493)
FARTHER = Position(latitude=48.2, longitude=-121.4)


def apply_delta(picture: dict[str, dict[str, Any]], delta: dict[str, Any]) -> None:
    """Fold one delta into a client's picture, in the documented order.

    ``removed``, then ``stale``, then ``updated`` — the order
    :mod:`flightsite.api.ws` specifies. A real client (slice 014's store) does
    exactly this.
    """
    for icao in delta["removed"]:
        picture.pop(icao, None)
    for icao in delta["stale"]:
        if icao in picture:
            picture[icao]["state"] = "stale"
    for aircraft in delta["updated"]:
        picture[aircraft["icao"]] = aircraft


async def rest_picture(client: AsyncClient) -> dict[str, dict[str, Any]]:
    body = (await client.get("/api/v1/aircraft/current")).json()
    return {aircraft["icao"]: aircraft for aircraft in body["items"]}


async def test_the_opening_snapshot_equals_the_rest_picture(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(
        make_update("ae1463", position=NEARBY, callsign="RCH492", altitude_ft=24_975.0),
        make_update("a9c2f0", position=FARTHER, squawk="7700"),
        make_update("00beef"),
    )

    probe, snapshot = await open_probe(live_app)
    try:
        body = (await rest.get("/api/v1/aircraft/current")).json()

        # Identical documents, not merely equal sets: both are ordered by ICAO
        # and built by the same serializer.
        assert snapshot["data"]["aircraft"] == body["items"]
    finally:
        await probe.disconnect()


async def test_the_snapshot_receiver_block_equals_the_receiver_endpoint(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    probe, snapshot = await open_probe(live_app)
    try:
        body = (await rest.get("/api/v1/receiver")).json()

        assert snapshot["data"]["receiver"] == body
    finally:
        await probe.disconnect()


async def test_applying_the_delta_stream_converges_on_the_rest_picture(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(
        make_update("ae1463", position=NEARBY, altitude_ft=20_000.0),
        make_update("a9c2f0", position=FARTHER),
        make_update("00beef"),
    )

    probe, snapshot = await open_probe(live_app)
    try:
        picture = {entry["icao"]: entry for entry in snapshot["data"]["aircraft"]}

        # A second of ordinary traffic: one aircraft climbs, one appears.
        live_app.feed(
            make_update("ae1463", offset_s=1.0, position=NEARBY, altitude_ft=21_000.0),
            make_update("ffaa11", offset_s=1.0, position=FARTHER, callsign="DAL42"),
        )
        await live_app.broadcast()
        apply_delta(picture, (await probe.frame())["data"])
        assert picture == await rest_picture(rest)

        # Then silence: one crosses the stale threshold, and later leaves.
        live_app.advance(live_app.live.stale_s + 1.0)
        live_app.sweep()
        await live_app.broadcast()
        apply_delta(picture, (await probe.frame())["data"])
        assert picture == await rest_picture(rest)

        live_app.advance(live_app.live.remove_s)
        live_app.sweep()
        await live_app.broadcast()
        apply_delta(picture, (await probe.frame())["data"])
        assert picture == await rest_picture(rest)
        assert picture == {}
    finally:
        await probe.disconnect()


async def test_a_reconnecting_client_gets_a_coherent_fresh_snapshot(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY))
    first, _snapshot = await open_probe(live_app)

    # The client goes away mid-stream and misses everything that follows;
    # §4.5 has no delta replay, so its recovery is entirely the new snapshot.
    await first.disconnect()
    live_app.feed(make_update("a9c2f0", position=FARTHER, callsign="DAL42"))
    live_app.advance(live_app.live.stale_s + 1.0)
    live_app.sweep()
    await live_app.broadcast()

    second, snapshot = await open_probe(live_app)
    try:
        assert snapshot["seq"] == 1
        assert (
            snapshot["data"]["aircraft"]
            == (await rest.get("/api/v1/aircraft/current")).json()["items"]
        )
        states = {entry["icao"]: entry["state"] for entry in snapshot["data"]["aircraft"]}
        assert states == {"a9c2f0": "stale", "ae1463": "stale"}
    finally:
        await second.disconnect()


async def test_a_resync_snapshot_equals_the_rest_picture() -> None:
    # The broadcaster's own event stream loses events, so it resyncs everyone
    # with a fresh snapshot rather than a delta built on a gap. That snapshot
    # is read from the live store, so it is exactly what REST would say.
    harness = build_live_app(event_queue_size=8)
    async with (
        harness.app.router.lifespan_context(harness.app),
        AsyncClient(
            transport=ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client,
    ):
        probe, _snapshot = await open_probe(harness)
        try:
            for index in range(16):
                harness.feed(make_update(f"{index:06x}", position=NEARBY))
            await harness.broadcast()

            resync = await probe.frame()
            assert resync["type"] == "snapshot"
            picture = {entry["icao"]: entry for entry in resync["data"]["aircraft"]}

            assert picture == await rest_picture(client)
        finally:
            await probe.disconnect()
