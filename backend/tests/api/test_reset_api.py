"""Internal reset API tests: ``POST /api/internal/reset/*`` (SPEC §73, slice 045).

Two destructive Settings actions, exercised end to end through the real ASGI
app:

* **Clear Metadata Cache** (``/reset/metadata-cache``) runs synchronously
  through the writer and is asserted here the way ``tests/api/
  test_metadata_api.py`` asserts the update action: against the real app,
  with a substituted metadata registry so nothing reaches the network.
* **Reset FlightSite Data** (``/reset/data``) is mark-and-restart
  (:mod:`flightsite.reset.marker`), so most of what it does is only visible on
  the *next* ``create_app()`` call — this file's last section builds a second
  app over the same data directory to prove the end-to-end contract: request,
  restart, fresh install.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from flightsite.airports import AirportRecord, AirportRepository
from flightsite.app import create_app
from flightsite.config import ConfigStore
from flightsite.db import (
    Aircraft,
    AircraftMetadata,
    AircraftMetadataResolved,
    Airport,
    Database,
    MetaRepository,
    RouteCache,
    Sighting,
    database_path,
)
from flightsite.enrichment import RouteCacheRepository, RouteInfo
from flightsite.live import LiveStore
from flightsite.metadata import MetadataService, SourceRegistry
from flightsite.reset.marker import RESET_MARKER_FILENAME, reset_pending

from ..metadata.conftest import record
from ..metadata.provider import InMemoryMetadataProvider

CLEAR_PATH = "/api/internal/reset/metadata-cache"
RESET_PATH = "/api/internal/reset/data"

RECORD_A = record("a00001", registration="N1AA", type_code="B738", operator_name="Delta Air Lines")


@pytest.fixture
def registry() -> SourceRegistry:
    """An empty registry each test fills with in-memory providers."""
    return SourceRegistry()


@pytest.fixture
async def app(isolated_data_dir: Path, registry: SourceRegistry) -> AsyncIterator[FastAPI]:
    """A started app whose metadata service runs over the test's own registry.

    The same substitution ``tests/api/test_metadata_api.py``'s fixture makes,
    for the same reason: nothing in this file should ever reach the network.
    """
    application = create_app(isolated_data_dir)
    application.state.metadata = MetadataService(
        database=application.state.database,
        live=LiveStore(clock=lambda: 0.0),
        data_dir=isolated_data_dir,
        registry=registry,
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as async_client:
        yield async_client


async def _table_count(database: Database, model: object) -> int:
    async with database.read_session() as session:
        total = await session.scalar(select(func.count()).select_from(model))  # type: ignore[arg-type]
        return int(total or 0)


async def seed_metadata(app: FastAPI, registry: SourceRegistry) -> None:
    """One real import through the substituted registry — a row to clear."""
    registry.register("mictronics", InMemoryMetadataProvider([RECORD_A], version="mict-1"))
    metadata: MetadataService = app.state.metadata
    run = await metadata.update()
    assert run.succeeded == ("mictronics",)


async def seed_route_cache(database: Database) -> None:
    cache = RouteCacheRepository(database)
    await cache.store_route(
        "DAL1234:2026-08-30", RouteInfo("KATL", "KSLC"), now_ms=1_756_600_000_000
    )


async def seed_airports(database: Database) -> None:
    repository = AirportRepository(database)
    await repository.replace_all(
        [
            AirportRecord(
                ident="KBFI", name="Boeing Field", type="large_airport", lat=47.53, lon=-122.30
            )
        ],
        source="airports",
        at_ms=1_756_600_000_000,
        dataset_version="fixture",
    )


async def seed_history(database: Database) -> None:
    """One aircraft with one sighting — the rows a reset action must never touch."""
    async with database.writer_session() as session:
        session.add(Aircraft(id=1, icao24="a00001", first_seen_ms=1, last_seen_ms=1))
        session.add(Sighting(id=1, aircraft_id=1, started_ms=1))


# ------------------------------------------------------- POST /reset/metadata-cache


async def test_clear_requires_the_exact_confirm_phrase(client: AsyncClient) -> None:
    response = await client.post(CLEAR_PATH, json={"confirm": "wrong"})
    assert response.status_code == 422


async def test_clear_requires_a_confirm_field_at_all(client: AsyncClient) -> None:
    response = await client.post(CLEAR_PATH, json={})
    assert response.status_code == 422


async def test_clear_rejects_the_other_actions_phrase(client: AsyncClient) -> None:
    response = await client.post(CLEAR_PATH, json={"confirm": "reset-flightsite-data"})
    assert response.status_code == 422


async def test_wrong_confirm_clears_nothing(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    await seed_metadata(app, registry)
    database: Database = app.state.database
    before = await _table_count(database, AircraftMetadata)
    assert before > 0

    response = await client.post(CLEAR_PATH, json={"confirm": "nope"})

    assert response.status_code == 422
    assert await _table_count(database, AircraftMetadata) == before


async def test_clear_deletes_metadata_route_cache_and_airports(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    await seed_metadata(app, registry)
    database: Database = app.state.database
    await seed_route_cache(database)
    await seed_airports(database)
    assert await _table_count(database, AircraftMetadata) > 0
    assert await _table_count(database, AircraftMetadataResolved) > 0
    assert await _table_count(database, RouteCache) > 0
    assert await _table_count(database, Airport) > 0

    response = await client.post(CLEAR_PATH, json={"confirm": "clear-metadata"})

    assert response.status_code == 200
    body = response.json()
    assert body["cleared"] is True
    assert body["aircraft_metadata_rows"] == 1
    assert body["resolved_rows"] == 1
    assert body["route_cache_rows"] == 1
    assert body["airport_rows"] == 1

    assert await _table_count(database, AircraftMetadata) == 0
    assert await _table_count(database, AircraftMetadataResolved) == 0
    assert await _table_count(database, RouteCache) == 0
    assert await _table_count(database, Airport) == 0


async def test_clear_invalidates_the_live_caches(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    """The API path, not just the storage layer: in-memory state follows the delete."""
    await seed_metadata(app, registry)
    await seed_airports(app.state.database)
    airports = app.state.airports
    await airports.reload()
    assert airports.known_airports == 1

    response = await client.post(CLEAR_PATH, json={"confirm": "clear-metadata"})

    assert response.status_code == 200
    assert airports.known_airports == 0


async def test_clear_leaves_aircraft_and_sighting_history_intact(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    await seed_metadata(app, registry)
    database: Database = app.state.database
    await seed_history(database)
    aircraft_before = await _table_count(database, Aircraft)
    sightings_before = await _table_count(database, Sighting)
    assert aircraft_before == 1
    assert sightings_before == 1

    response = await client.post(CLEAR_PATH, json={"confirm": "clear-metadata"})

    assert response.status_code == 200
    assert await _table_count(database, Aircraft) == aircraft_before
    assert await _table_count(database, Sighting) == sightings_before


async def test_clear_is_idempotent(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    await seed_metadata(app, registry)

    first = await client.post(CLEAR_PATH, json={"confirm": "clear-metadata"})
    second = await client.post(CLEAR_PATH, json={"confirm": "clear-metadata"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["aircraft_metadata_rows"] == 0


async def test_clear_is_not_in_the_published_openapi_schema(client: AsyncClient) -> None:
    schema = (await client.get("/api/v1/openapi.json")).json()
    assert not any("reset" in path for path in schema["paths"])


# ------------------------------------------------------------- POST /reset/data


async def test_reset_requires_the_exact_confirm_phrase(client: AsyncClient) -> None:
    response = await client.post(RESET_PATH, json={"confirm": "wrong"})
    assert response.status_code == 422


async def test_reset_rejects_the_other_actions_phrase(client: AsyncClient) -> None:
    response = await client.post(RESET_PATH, json={"confirm": "clear-metadata"})
    assert response.status_code == 422


async def test_wrong_confirm_writes_no_marker(client: AsyncClient, isolated_data_dir: Path) -> None:
    response = await client.post(RESET_PATH, json={"confirm": "nope"})

    assert response.status_code == 422
    assert reset_pending(isolated_data_dir) is False


async def test_reset_writes_a_marker_and_answers_202(
    client: AsyncClient, isolated_data_dir: Path
) -> None:
    response = await client.post(RESET_PATH, json={"confirm": "reset-flightsite-data"})

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["restart_required"] is True
    assert isinstance(body["requested_ms"], int)
    assert reset_pending(isolated_data_dir) is True
    assert (isolated_data_dir / RESET_MARKER_FILENAME).exists()


async def test_reset_does_not_touch_the_database_on_its_own(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    """202 is a promise about the *next* startup, not an in-process change."""
    await seed_metadata(app, registry)
    database: Database = app.state.database
    before = await _table_count(database, AircraftMetadata)
    assert before > 0

    response = await client.post(RESET_PATH, json={"confirm": "reset-flightsite-data"})

    assert response.status_code == 202
    assert await _table_count(database, AircraftMetadata) == before


# ----------------------------------------------- the reset actually applying


async def test_a_pending_reset_deletes_the_database_at_the_next_startup(
    isolated_data_dir: Path,
) -> None:
    """The end-to-end contract: request, restart, fresh install.

    Requesting a reset while one process is running, then building a *new*
    app over the same data directory — the shape of ``docker compose
    restart`` — must find no history and no T0, with configuration intact.
    """
    store = ConfigStore(isolated_data_dir)
    store.save(store.load())  # config.yaml now exists: no longer first-run

    first = create_app(isolated_data_dir)
    async with first.router.lifespan_context(first):
        assert first.state.data_reset_applied is False
        async with AsyncClient(
            transport=ASGITransport(app=first), base_url="http://testserver"
        ) as client:
            response = await client.post(RESET_PATH, json={"confirm": "reset-flightsite-data"})
            assert response.status_code == 202

        # A real observation, so there is a T0 and history to prove gone.
        database: Database = first.state.database
        meta = MetaRepository(database)
        await meta.set_t0_once(1_756_600_000_000)
        assert await meta.get_t0() == 1_756_600_000_000

    assert reset_pending(isolated_data_dir) is True

    second = create_app(isolated_data_dir)
    assert second.state.data_reset_applied is True
    assert reset_pending(isolated_data_dir) is False
    async with second.router.lifespan_context(second):
        meta = MetaRepository(second.state.database)
        assert await meta.get_t0() is None

    # config.yaml survived the reset — the install does not need reconfiguring.
    assert store.config_path.exists()
    assert database_path(isolated_data_dir).exists()  # the fresh database


async def test_create_app_without_a_pending_reset_reports_none_applied(
    isolated_data_dir: Path,
) -> None:
    app = create_app(isolated_data_dir)
    assert app.state.data_reset_applied is False
