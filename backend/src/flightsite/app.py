"""FastAPI application factory."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from flightsite import __version__
from flightsite.api.internal import router as internal_router
from flightsite.api.v1 import router as v1_router
from flightsite.config import ConfigStore, Settings
from flightsite.db import Database, database_path, initialize_database
from flightsite.db.startup import DATABASE_SUBSYSTEM
from flightsite.ingest import DecoderEndpoint, IngestionService, Position, build_ingestion_service
from flightsite.live import LiveStore
from flightsite.logging import configure_logging
from flightsite.readiness import ReadinessRegistry

logger = structlog.get_logger(__name__)


def _decoder_endpoint(settings: Settings) -> DecoderEndpoint:
    """Translate the receiver section of settings into an ingestion endpoint."""
    receiver = settings.receiver
    return DecoderEndpoint(
        host=receiver.host,
        port=receiver.port,
        path=receiver.path,
        poll_interval_s=receiver.poll_interval_s,
    )


def _build_live_store(settings: Settings) -> LiveStore:
    """Construct the live registry from the configured timings and location.

    The receiver location is optional: until the setup wizard (slice 018)
    collects one, the store simply computes no distance or bearing. Everything
    else — the live set, lifecycle, tracks, events — works exactly the same.
    """
    location = settings.location
    receiver = (
        Position(latitude=location.latitude, longitude=location.longitude)
        if location.latitude is not None and location.longitude is not None
        else None
    )
    return LiveStore(
        stale_s=settings.sighting.stale_s,
        remove_s=settings.sighting.remove_s,
        receiver_location=receiver,
    )


async def _start_ingestion(app: FastAPI) -> IngestionService | None:
    """Start decoder ingestion, unless this install has never been configured.

    On a first run there is no ``config.yaml``, so there is no receiver the
    user has actually chosen — only model defaults. Polling those would
    produce a stream of connection failures and a ``down`` decoder before the
    setup wizard has even been opened, so ingestion is skipped and starts on
    the next boot after a configuration is saved.

    The live store is the sole consumer: every normalized batch goes straight
    into the in-memory registry, and nothing on this path touches the database
    (``docs/ARCHITECTURE.md`` §3.1).

    Decoder health deliberately never affects ``/ready``; the reasoning is in
    :mod:`flightsite.ingest.service`.
    """
    store: ConfigStore = app.state.config_store
    if store.first_run:
        logger.info("ingestion_skipped", reason="first_run")
        return None

    live: LiveStore = app.state.live
    service = build_ingestion_service(
        _decoder_endpoint(app.state.settings),
        readiness=app.state.readiness,
        consumers=(live.apply,),
    )
    await service.start()
    return service


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    readiness: ReadinessRegistry = app.state.readiness
    database: Database = app.state.database
    live: LiveStore = app.state.live

    # Migrations and the integrity check run before startup is declared
    # complete. They never abort startup: a failure leaves the `database`
    # subsystem not-ready (so /api/v1/ready answers 503) while the process
    # stays reachable for diagnosis — see flightsite.db.startup.
    await initialize_database(database, readiness)

    # The lifecycle sweep runs whether or not a decoder is configured: an
    # empty live set costs nothing to sweep, and starting it unconditionally
    # means the store behaves identically the moment ingestion does start.
    await live.start()
    app.state.ingestion = await _start_ingestion(app)
    readiness.mark_startup_complete()
    logger.info("app_startup_complete")
    try:
        yield
    finally:
        # Ingestion first: no new batches should arrive after the live store
        # stops sweeping.
        service: IngestionService | None = app.state.ingestion
        if service is not None:
            await service.stop()
        await live.stop()
        await database.dispose()
        logger.info("app_shutdown")


def create_app(data_dir: str | os.PathLike[str] | None = None) -> FastAPI:
    """Build and configure the FlightSite FastAPI application.

    Loads configuration once (``config.yaml`` / ``secrets.yaml`` /
    ``FLIGHTSITE_*``) and stores the resulting :class:`~flightsite.config.Settings`
    plus its :class:`~flightsite.config.ConfigStore` on ``app.state``;
    ``PUT /api/internal/config`` replaces ``app.state.settings`` in place, so
    request handlers must read it from state rather than caching it at import
    time. Then configures structured logging, initializes the readiness
    registry and uptime clock, constructs the database, and mounts the
    routers.

    The ``database`` subsystem is registered here, not in the lifespan hook,
    so it reads as not-ready from the very first request; the lifespan hook
    migrates the database and marks it ready. Constructing
    :class:`~flightsite.db.Database` opens nothing and creates no directory —
    building an app is still side-effect free.

    The in-memory live aircraft registry is constructed here and exposed as
    ``app.state.live``; startup starts its lifecycle sweep and, when a
    configuration exists, launches decoder ingestion feeding it. Shutdown
    stops both. A decoder that is unreachable does not hold up readiness — the
    app is fully usable without one.

    Args:
        data_dir: overrides data-directory resolution (``FLIGHTSITE_DATA_DIR``,
            then ``/opt/flightsite/data``). Used by tests.
    """
    store = ConfigStore(data_dir)
    settings = store.load()

    # settings.log_level already reflects FLIGHTSITE_LOG_LEVEL when set — the
    # environment outranks config.yaml inside the settings model — so passing
    # it here keeps the env override winning (SPEC §30).
    configure_logging(level=settings.log_level)

    app = FastAPI(title="FlightSite", version=__version__, lifespan=_lifespan)
    app.state.config_store = store
    app.state.settings = settings
    app.state.readiness = ReadinessRegistry()
    app.state.readiness.register(DATABASE_SUBSYSTEM)
    app.state.database = Database(database_path(store.data_dir))
    # The live registry is always present, even on a first run with no
    # decoder: request handlers can then read `app.state.live` unconditionally
    # instead of guarding every access. Constructing it starts nothing.
    app.state.live = _build_live_store(settings)
    app.state.start_time = time.monotonic()

    app.include_router(v1_router, prefix="/api/v1")
    # /api/internal is an unsupported, unversioned surface (ADR-0007) and is
    # kept out of the OpenAPI schema published for /api/v1. One flag here
    # covers every internal endpoint, now and in later slices.
    app.include_router(internal_router, prefix="/api/internal", include_in_schema=False)

    return app
