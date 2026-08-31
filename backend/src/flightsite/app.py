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
from flightsite.config import ConfigStore
from flightsite.logging import configure_logging
from flightsite.readiness import ReadinessRegistry

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    readiness: ReadinessRegistry = app.state.readiness
    readiness.mark_startup_complete()
    logger.info("app_startup_complete")
    try:
        yield
    finally:
        logger.info("app_shutdown")


def create_app(data_dir: str | os.PathLike[str] | None = None) -> FastAPI:
    """Build and configure the FlightSite FastAPI application.

    Loads configuration once (``config.yaml`` / ``secrets.yaml`` /
    ``FLIGHTSITE_*``) and stores the resulting :class:`~flightsite.config.Settings`
    plus its :class:`~flightsite.config.ConfigStore` on ``app.state``;
    ``PUT /api/internal/config`` replaces ``app.state.settings`` in place, so
    request handlers must read it from state rather than caching it at import
    time. Then configures structured logging, initializes the readiness
    registry and uptime clock, and mounts the routers. With no subsystems
    registered against the readiness registry, the app becomes ready as soon
    as the lifespan startup hook runs.

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
    app.state.start_time = time.monotonic()

    app.include_router(v1_router, prefix="/api/v1")
    # /api/internal is an unsupported, unversioned surface (ADR-0007) and is
    # kept out of the OpenAPI schema published for /api/v1. One flag here
    # covers every internal endpoint, now and in later slices.
    app.include_router(internal_router, prefix="/api/internal", include_in_schema=False)

    return app
