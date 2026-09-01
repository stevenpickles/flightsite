"""Demo mode end to end: the live API serving simulated traffic.

SPEC §76 wants the full stack usable with no decoder and no internet, and
slice 011's demo adapter supplies the traffic. This is the check that the
slice 010 surface is part of "the full stack": with ``FLIGHTSITE_DEMO=1`` and
nothing configured, a client gets a growing live picture over REST and the
same picture over the WebSocket.

Unlike the rest of this package these tests run on the real wall clock — the
demo adapter's poll loop is production wiring with no injected clock, so a
short wait is the only way to watch it actually produce traffic. They assert
on outcomes (aircraft appeared, frames arrived), never on how long anything
took.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from flightsite.api.schemas import AircraftView, ReceiverInfo
from flightsite.app import create_app
from flightsite.config import ConfigStore

from .conftest import WebSocketProbe

#: One demo poll interval plus margin. The adapter ticks on the wall clock, so
#: the traffic this waits for is real elapsed time, not simulated.
DEMO_WARMUP_S = 1.5


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")


async def test_demo_mode_serves_a_growing_live_picture(isolated_data_dir: Path) -> None:
    assert ConfigStore(isolated_data_dir).first_run is True
    app = create_app()

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        await asyncio.sleep(DEMO_WARMUP_S)
        body = (await client.get("/api/v1/aircraft/current")).json()

        assert body["total"] > 0
        assert body["total"] == len(body["items"])
        for item in body["items"]:
            AircraftView.model_validate(item)


async def test_the_positioned_filter_partitions_the_demo_traffic(isolated_data_dir: Path) -> None:
    app = create_app()

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        await asyncio.sleep(DEMO_WARMUP_S)
        everything = (await client.get("/api/v1/aircraft/current")).json()
        positioned = (await client.get("/api/v1/aircraft/current?positioned=true")).json()
        unpositioned = (await client.get("/api/v1/aircraft/current?positioned=false")).json()

        assert positioned["total"] > 0
        # The two filters partition the live set: every aircraft either has a
        # position or is tracked without one (SPEC §20), and none is dropped.
        assert positioned["total"] + unpositioned["total"] == everything["total"]
        assert all(item["position"] is not None for item in positioned["items"])
        assert all(item["position"] is None for item in unpositioned["items"])


async def test_demo_mode_is_declared_by_the_receiver_endpoint(isolated_data_dir: Path) -> None:
    app = create_app()

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        info = ReceiverInfo.model_validate((await client.get("/api/v1/receiver")).json())

        # No config.yaml exists, but demo mode injects a receiver location so
        # distance and bearing still compute — and it says it is demo traffic.
        assert info.demo_mode is True
        assert info.latitude is not None


async def test_demo_mode_streams_snapshot_then_deltas(isolated_data_dir: Path) -> None:
    app = create_app()

    async with app.router.lifespan_context(app):
        await asyncio.sleep(DEMO_WARMUP_S)
        probe = WebSocketProbe(app=app)
        await probe.connect()
        try:
            snapshot = await probe.frame()
            assert snapshot["type"] == "snapshot"
            assert len(snapshot["data"]["aircraft"]) > 0
            assert snapshot["data"]["receiver"]["demo_mode"] is True

            # The production broadcaster is running on its own ~1 Hz task here,
            # so the next frame arrives because the sky moved, not because the
            # test asked for it.
            delta = await asyncio.wait_for(probe.frame(), timeout=10.0)
            assert delta["type"] in {"delta", "snapshot"}
            assert delta["seq"] == 2
        finally:
            await probe.disconnect()
