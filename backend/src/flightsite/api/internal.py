"""Unsupported internal API: ``/api/internal``.

Mutations the FlightSite frontend needs. Unversioned, undocumented, and
excluded from the OpenAPI schema published for ``/api/v1`` — the router is
mounted with ``include_in_schema=False`` in
:func:`flightsite.app.create_app`, which keeps the exclusion a single
app-level decision rather than a per-endpoint flag (ADR-0007, docs/API.md §5).

This slice owns configuration mutation. The setup wizard (slice 018) and the
Settings UI (slice 019) consume these endpoints rather than touching
``config.yaml`` themselves, so validation and atomic write-back have exactly
one implementation.

Slice 007 adds the decoder connection test the same two consumers need before
they can save a receiver endpoint (SPEC §11).
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import ValidationError

from flightsite.config import ConfigError, ConfigStore, ReceiverSettings, Settings
from flightsite.ingest import ConnectionTestResult, DecoderEndpoint, check_connection

logger = structlog.get_logger(__name__)

router = APIRouter()


def _config_response(store: ConfigStore, settings: Settings) -> dict[str, Any]:
    """Build the config payload.

    ``config`` is the full effective configuration with secrets masked;
    ``secrets_set`` reports, per secret, whether a value is stored, so the
    Settings UI can render "configured / not configured" without ever
    receiving the value (SPEC §29).
    """
    return {
        "first_run": store.first_run,
        "config": settings.dump_public(),
        "secrets_set": settings.secrets_state(),
    }


def _safe_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Render validation errors without echoing the rejected input.

    Pydantic includes the offending value in ``input``; for a secret field
    that would hand the value straight back to the client (and into any
    request log). Only the location, message and error type are returned —
    which is what makes the message helpful anyway.
    """
    return [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors(include_url=False)
    ]


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    """Return the effective configuration with secrets masked, plus first-run state."""
    store: ConfigStore = request.app.state.config_store
    settings: Settings = request.app.state.settings
    return _config_response(store, settings)


@router.put("/config")
async def put_config(
    request: Request,
    patch: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Apply a partial or full configuration update.

    The payload is the same document shape ``GET`` returns. It is validated
    against the settings model, written atomically (non-secret fields to
    ``config.yaml``, secret fields to ``secrets.yaml``), and applied to the
    running app. A secret sent back as its mask is left unchanged; an explicit
    ``null`` clears it.

    Nothing is written when validation fails, so a rejected update leaves both
    files and the running settings untouched.
    """
    store: ConfigStore = request.app.state.config_store
    try:
        settings = store.apply_update(patch)
    except ConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=_safe_errors(exc)) from exc

    request.app.state.settings = settings
    # Log the changed key paths only — never the values, which may include a
    # secret the caller just set (SPEC §29).
    logger.info("config_updated", fields=sorted(patch))
    return _config_response(store, settings)


@router.post("/decoder/test")
async def test_decoder_connection(
    request: Request,
    receiver: Annotated[ReceiverSettings | None, Body()] = None,
) -> ConnectionTestResult:
    """Probe a decoder endpoint once and report what was found.

    The body is a receiver document (``host`` / ``port`` / ``path``), validated
    by the same model ``PUT /config`` uses, so the wizard cannot test an
    endpoint it would not be allowed to save. An empty body tests the
    currently configured receiver.

    Nothing is written and the running ingestion loop is untouched: this opens
    its own short-lived client, which is what makes it safe to call repeatedly
    from a settings form while the live map keeps running.
    """
    settings: Settings = request.app.state.settings
    candidate = receiver if receiver is not None else settings.receiver
    return await check_connection(
        DecoderEndpoint(
            host=candidate.host,
            port=candidate.port,
            path=candidate.path,
            poll_interval_s=candidate.poll_interval_s,
        )
    )
