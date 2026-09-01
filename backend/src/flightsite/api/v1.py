"""Versioned, documented, read-only public API: ``/api/v1``.

Everything mounted here is safe to hand to another LAN tool: it never mutates
application state, it never returns a secret, and its shapes are the ones
``docs/API.md`` publishes (SPEC §74). Mutations live on the unsupported
``/api/internal`` surface instead.

This slice adds the live picture — ``GET /aircraft/current`` (§3.3), ``GET
/receiver`` (§3.2) and the ``ws/live`` WebSocket (§4, documented in
:mod:`flightsite.api.ws`) — on top of the health and readiness endpoints from
slice 001. The remainder (history, sightings, analytics, diagnostics) arrives
in later slices.

The REST endpoints declare Pydantic response models, so the OpenAPI document
served at ``/api/v1/openapi.json`` (§2.10) describes them exactly and every
response is validated against the shape that was published.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response, status

from flightsite import __version__
from flightsite.api.context import LiveApiContext
from flightsite.api.schemas import CurrentAircraftResponse, ReceiverInfo
from flightsite.api.ws import router as ws_router
from flightsite.counters import counters
from flightsite.readiness import ReadinessRegistry

router = APIRouter()
router.include_router(ws_router)


def _context(request: Request) -> LiveApiContext:
    """The app's live API context, built once in the application factory."""
    context: LiveApiContext = request.app.state.api_context
    return context


@router.get("/health", tags=["service"])
async def health(request: Request) -> dict[str, Any]:
    """Liveness endpoint: always 200 once the app is answering requests."""
    start_time: float = request.app.state.start_time
    uptime_s = time.monotonic() - start_time
    return {
        "status": "ok",
        "version": __version__,
        "uptime_s": round(uptime_s, 3),
        "counters": counters.snapshot(),
        # True when ingestion is simulated traffic (FLIGHTSITE_DEMO=1, slice
        # 011) rather than a real decoder — surfaced so the UI and support
        # requests can tell "no real hardware attached" apart from "decoder
        # is down" at a glance.
        "demo": request.app.state.demo_enabled,
    }


@router.get("/ready", tags=["service"])
async def ready(request: Request, response: Response) -> dict[str, Any]:
    """Readiness endpoint: 200 once ready, 503 while started-but-not-ready."""
    readiness: ReadinessRegistry = request.app.state.readiness
    is_ready = readiness.is_ready
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": is_ready, "subsystems": readiness.snapshot()}


@router.get(
    "/receiver",
    response_model=ReceiverInfo,
    tags=["live"],
    summary="Receiver identity and configuration",
)
async def receiver(request: Request) -> dict[str, Any]:
    """Non-secret receiver info — ``docs/API.md`` §3.2.

    Site name, location, antenna height, configured timezone and units, the
    display and alert radii, whether this process is running demo traffic, and
    T0. Every field comes from a named configuration field or from the
    write-once T0 key, so no secret can reach it (SPEC §29).

    Before the setup wizard has collected a receiver position the location
    fields are ``null``, and on an install that has never persisted an
    observation ``t0`` is ``null``. Both are ordinary first-run states, not
    errors.
    """
    return await _context(request).receiver()


@router.get(
    "/aircraft/current",
    response_model=CurrentAircraftResponse,
    tags=["live"],
    summary="The current live aircraft picture",
)
async def current_aircraft(
    request: Request,
    positioned: Annotated[
        bool | None,
        Query(
            description=(
                "Restrict the result to aircraft with a known position "
                "(`true`) or to those tracked without one (`false`). "
                "Omit for the full live picture."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """The live set — positioned **and** non-positioned aircraft (SPEC §20).

    Answered entirely from the in-memory live registry; nothing on this path
    touches SQLite (``docs/ARCHITECTURE.md`` §3.1). The objects are the §3.3
    shape, identical to the ones the WebSocket carries, and the response
    describes the same instant a snapshot taken now would.

    Not paginated: a truncated live picture would be a wrong one, so the §2.4
    envelope appears without ``limit``/``offset`` and ``total`` is the exact
    size of the returned set.
    """
    items = _context(request).aircraft(positioned=positioned)
    return {"items": items, "total": len(items)}
