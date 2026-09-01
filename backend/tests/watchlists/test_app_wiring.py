"""Watchlists' place in the application (``flightsite.app.create_app``).

Three claims: the service is constructed inertly, its ``on_resolved`` observer
is the one the metadata cache actually holds, and its index is loaded before
the metadata cache's own startup visits the live set — so a watchlist entry
seeded before the app even starts matches on the very first frame, with
nothing left to "catch up" on a later population round.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from flightsite.api.context import LiveApiContext
from flightsite.app import create_app
from flightsite.db import Database, database_path
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.metadata import MetadataService
from flightsite.watchlists import WatchlistService


def test_the_service_is_constructed_without_touching_anything(isolated_data_dir: Path) -> None:
    app = create_app(isolated_data_dir)

    service: WatchlistService = app.state.watchlists
    assert isinstance(service, WatchlistService)
    assert service.matcher.live_count == 0


def test_the_metadata_cache_holds_the_matcher_s_observer(isolated_data_dir: Path) -> None:
    app = create_app(isolated_data_dir)

    watchlists: WatchlistService = app.state.watchlists
    metadata: MetadataService = app.state.metadata
    assert metadata.cache._on_resolved == watchlists.matcher.on_resolved


async def _seed_entry(isolated_data_dir: Path) -> None:
    """Insert a watchlist and an entry directly, as if a previous process had."""
    database = Database(database_path(isolated_data_dir))
    await database.upgrade_to("head")
    try:
        async with database.writer_session() as session:
            await session.execute(
                text("INSERT INTO watchlists (id, name, created_ms) VALUES (1, 'Tracked', 0)")
            )
            await session.execute(
                text(
                    "INSERT INTO watchlist_entries "
                    "(watchlist_id, kind, value, created_ms) VALUES (1, 'icao24', 'ae1463', 0)"
                )
            )
    finally:
        await database.dispose()


@pytest.fixture
async def app(isolated_data_dir: Path) -> FastAPI:
    """The real app, wired exactly as ``create_app`` leaves it.

    ``app.state.live`` is not replaced: the metadata service (and, through
    it, the watchlist matcher's observer) is bound to that exact object at
    construction time inside ``create_app``, so swapping it afterwards — the
    way ``tests/api/conftest.py``'s live-app harness does for the broadcaster
    — would leave the cache subscribed to a live store this test never
    feeds. A first-run install skips decoder ingestion entirely, so nothing
    else writes to the live store while the test drives it by hand.
    """
    await _seed_entry(isolated_data_dir)
    return create_app(isolated_data_dir)


async def test_a_pre_seeded_entry_matches_a_live_aircraft_on_its_first_frame(
    app: FastAPI,
) -> None:
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        await client.get("/api/v1/health")

        live: LiveStore = app.state.live
        live.apply_updates(
            [
                AircraftStateUpdate(
                    icao="ae1463",
                    timestamp=datetime.now(UTC),
                    position=Position(latitude=47.6, longitude=-122.3),
                )
            ]
        )
        cache = app.state.metadata.cache
        # Publishing is synchronous (put_nowait); the population task
        # needs a few scheduling rounds to pick the event up and clear
        # its idle flag before waiting on it means anything — the same
        # pattern tests/metadata/conftest.py's `settle` follows.
        for _ in range(4):
            await asyncio.sleep(0)
        await cache.wait_idle()

        context: LiveApiContext = app.state.api_context
        payloads = context.aircraft()

    matched = next(aircraft for aircraft in payloads if aircraft["icao"] == "ae1463")
    assert matched["watchlists"] == ["Tracked"]
