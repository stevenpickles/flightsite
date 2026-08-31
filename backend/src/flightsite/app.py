"""FastAPI application factory."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from flightsite import __version__
from flightsite.api.v1 import router as v1_router
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


def create_app() -> FastAPI:
    """Build and configure the FlightSite FastAPI application.

    Configures structured logging, initializes the readiness registry and
    uptime clock, and mounts the versioned ``/api/v1`` router. With no
    subsystems registered against the readiness registry, the app becomes
    ready as soon as the lifespan startup hook runs.
    """
    configure_logging()

    app = FastAPI(title="FlightSite", version=__version__, lifespan=_lifespan)
    app.state.readiness = ReadinessRegistry()
    app.state.start_time = time.monotonic()

    app.include_router(v1_router, prefix="/api/v1")

    return app
