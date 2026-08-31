"""Versioned, documented, read-only public API: ``/api/v1``.

This slice only adds the health and readiness endpoints; the remainder of the
``/api/v1`` surface (aircraft, sightings, WebSocket, ...) arrives in later
slices.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request, Response, status

from flightsite import __version__
from flightsite.counters import counters
from flightsite.readiness import ReadinessRegistry

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Liveness endpoint: always 200 once the app is answering requests."""
    start_time: float = request.app.state.start_time
    uptime_s = time.monotonic() - start_time
    return {
        "status": "ok",
        "version": __version__,
        "uptime_s": round(uptime_s, 3),
        "counters": counters.snapshot(),
    }


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, Any]:
    """Readiness endpoint: 200 once ready, 503 while started-but-not-ready."""
    readiness: ReadinessRegistry = request.app.state.readiness
    is_ready = readiness.is_ready
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": is_ready, "subsystems": readiness.snapshot()}
