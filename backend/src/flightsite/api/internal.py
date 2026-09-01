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

Slice 025 adds the "Update Aircraft Metadata" action: ``POST
/metadata/update`` starts (or reports the state of) a run of
:meth:`~flightsite.metadata.MetadataService.update`, and ``GET
/metadata/status`` reports where each registered source stands.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import ValidationError

from flightsite.config import ConfigError, ConfigStore, ReceiverSettings, Settings
from flightsite.db import utc_now_ms
from flightsite.ingest import ConnectionTestResult, DecoderEndpoint, check_connection
from flightsite.metadata import ImportRun, MetadataService
from flightsite.metadata.registry import SourceStatus, SourceStatusRecord

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


# ---------------------------------------------------------- metadata (slice 025)

#: Durable ``SourceStatus`` values as the status endpoint's ``status`` field
#: spells them (``docs/API.md`` §5: "ok/failed/never-run/running"). Hyphenated
#: rather than the enum's own snake_case so the wire vocabulary reads as
#: prose, not as a Python identifier leaking into the API.
_DURABLE_STATUS_LABELS: dict[SourceStatus, str] = {
    SourceStatus.NEVER_RUN: "never-run",
    SourceStatus.OK: "ok",
    SourceStatus.FAILED: "failed",
}


def _metadata_source_payload(record: SourceStatusRecord) -> dict[str, Any]:
    """One source's status row as ``GET /metadata/status`` reports it.

    ``running`` — read from the registry's in-flight state, not the durable
    row — overrides whatever the last completed attempt recorded: a source
    mid-import still has yesterday's ``ok`` or ``failed`` sitting in
    ``metadata_sources`` (the durable row only changes when an attempt
    *finishes*), but what a user watching the Settings page needs to see
    right now is that it is working, not what it last finished as.
    """
    display_status = "running" if record.run.running else _DURABLE_STATUS_LABELS[record.status]
    return {
        "name": record.source,
        "status": display_status,
        "last_success_ms": record.last_success_ms,
        "dataset_version": record.dataset_version,
        "row_count": record.row_count,
        "last_error": record.last_error,
    }


@router.get("/metadata/status")
async def get_metadata_status(request: Request) -> dict[str, Any]:
    """Per-source metadata status: durable outcome merged with in-flight state.

    One row per registered source (``mictronics``, ``faa`` as of slices
    022/023), each independent of the others (SPEC §27) — a source that has
    never run reports ``never-run`` beside one that failed yesterday and one
    that is ``ok`` right now, and none of those three facts affects how the
    other two are read. The Settings page polls this while a run is in
    progress and renders each source's outcome on its own, so one source
    failing never hides another's success.
    """
    metadata: MetadataService = request.app.state.metadata
    statuses = await metadata.statuses()
    return {"sources": [_metadata_source_payload(record) for record in statuses]}


def _log_update_task_result(task: asyncio.Task[ImportRun]) -> None:
    """Consume a finished background run's exception, if any, into the log.

    Nothing ``await``s this task directly — the HTTP request that started it
    has already returned, which is the entire point of running it in the
    background — so nothing else would ever retrieve an exception it raised.
    Without this callback, a bug here would only surface as asyncio's "Task
    exception was never retrieved" warning at the next garbage collection,
    with no context to debug it, instead of a clean log line naming what
    happened. This is distinct from a source failing its own import: that is
    caught inside :meth:`~flightsite.metadata.MetadataImporter.run` and
    reported through ``GET /metadata/status`` as a result, never raised here.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("metadata_update_task_failed", error=str(exc), error_type=type(exc).__name__)


@router.post("/metadata/update", status_code=status.HTTP_202_ACCEPTED)
async def trigger_metadata_update(request: Request) -> dict[str, Any]:
    """Start a metadata update run, or report the one already in progress.

    Downloading and staging a snapshot per source is seconds to minutes of
    network and disk I/O — nothing an HTTP client should hold a connection
    open for — so this schedules :meth:`~flightsite.metadata.MetadataService.update`
    as a background task and returns 202 the instant it is scheduled.
    Progress and outcome are read back from ``GET /metadata/status``, which
    the Settings UI polls until every source has settled.

    A trigger that arrives while an earlier one is still running does not
    start a second run: ``MetadataImporter`` imports its sources one at a
    time, and two overlapping runs would race each other over the same
    staging rows for whichever source is current. Instead this reports the
    in-progress run's own ``started_ms``, which is what lets a double-clicked
    button or a second open tab coalesce onto the run already happening
    instead of racing it. The check-and-schedule below never ``await``s in
    between, so two requests arriving back to back on the same event loop
    cannot both observe "not running" and both schedule a run.
    """
    task: asyncio.Task[ImportRun] | None = request.app.state.metadata_update_task
    if task is not None and not task.done():
        return {
            "started": False,
            "already_running": True,
            "started_ms": request.app.state.metadata_update_started_ms,
        }

    metadata: MetadataService = request.app.state.metadata
    started_ms = utc_now_ms()
    new_task = asyncio.create_task(metadata.update(), name="metadata-update")
    new_task.add_done_callback(_log_update_task_result)
    request.app.state.metadata_update_task = new_task
    request.app.state.metadata_update_started_ms = started_ms
    logger.info("metadata_update_triggered", started_ms=started_ms)
    return {"started": True, "already_running": False, "started_ms": started_ms}
