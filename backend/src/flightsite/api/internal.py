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

Slice 037 adds watchlist CRUD: ``GET``/``POST /watchlists``, ``PUT``/``DELETE
/watchlists/{id}``, and entry CRUD under ``/watchlists/{id}/entries``. Every
mutation goes through :class:`~flightsite.watchlists.WatchlistService`, which
rebuilds the in-memory match index before returning — see that module's
docstring — so a client that just changed a watchlist sees the live picture
reflect it on its very next read, with no propagation delay to reason about.

Slice 038 adds alert-rule CRUD and the template catalogue, and it adds them as
a *mounted router* (:mod:`flightsite.api.alert_rules`) rather than as more
handlers in this file. This module is a shared surface that several slices
extend concurrently; keeping each new group in its own module means one
``include_router`` line here per slice instead of competing appends to one
file.

Slice 055 gives ``PUT /config`` an apply step (:func:`_apply_live_settings`).
Writing the file and swapping ``app.state.settings`` is not always the whole of
saving a setting: ``alerts.enabled_templates`` names alert rules to create, and
until this existed a fresh install that chose its templates in the setup wizard
had no alert rules until the backend was restarted (issue #110).

Slice 056 adds the other half of that same first-run story to the same step:
the save that ends the first-run state now starts decoder ingestion and anchors
the live store at the saved location, so a user who finishes the setup wizard
sees aircraft without restarting the backend (issue #122). Slice 068 completes
that entry: the same save also hands the receiver-metrics service the
``stats.json`` poller it was built without, so the decoder-supplied metric
columns stop being ``NULL`` too (issue #129). Endpoint *changes* on an
already-running adapter remain restart-required — see
:mod:`flightsite.api.ingestion` for where that line is drawn and why.

Issue #161 adds a fourth entry to the same step, and it does not stop at
starting: route enrichment is switched on, switched off and re-keyed from the
same save, because nothing about it is expensive to replace. The provider was
previously built once at startup, so enabling enrichment on a running install
wrote the flag and the key and changed nothing until the next restart.

Issue #104 adds the write path for ``alert_matches.notified``, again as its own
mounted router (:mod:`flightsite.api.alert_matches`). The column shipped with
slice 040's migration and nothing ever set it, so the Alerts page rendered a
"Notified" marker that could only say ``false``. It is written by the client
that showed the browser notification, never by the server on broadcast — that
module says why.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, FastAPI, HTTPException, Request, status
from pydantic import ValidationError

from flightsite.alerts import AlertService
from flightsite.api.alert_matches import router as alert_matches_router
from flightsite.api.alert_rules import router as alert_rules_router
from flightsite.api.ingestion import (
    attach_stats_poller,
    ingestion_startable,
    start_decoder_ingestion,
)
from flightsite.api.serializers import iso_utc
from flightsite.config import ConfigError, ConfigStore, ReceiverSettings, Settings
from flightsite.db import from_epoch_ms, utc_now_ms
from flightsite.enrichment import EnrichmentService
from flightsite.enrichment.service import build_provider
from flightsite.ingest import ConnectionTestResult, DecoderEndpoint, Position, check_connection
from flightsite.live import LiveStore
from flightsite.metadata import ImportRun, MetadataService
from flightsite.metadata.registry import SourceStatus, SourceStatusRecord
from flightsite.watchlists import (
    DuplicateEntryError,
    DuplicateWatchlistNameError,
    WatchlistCreateRequest,
    WatchlistEntryCreateRequest,
    WatchlistEntryRecord,
    WatchlistNotFoundError,
    WatchlistRecord,
    WatchlistService,
    WatchlistUpdateRequest,
    WatchlistValueError,
)

logger = structlog.get_logger(__name__)

router = APIRouter()
router.include_router(alert_rules_router)  # slice 038 — see the module docstring
router.include_router(alert_matches_router)  # issue #104 — see the module docstring


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
    await _apply_live_settings(request.app, settings)
    return _config_response(store, settings)


async def _apply_live_settings(app: FastAPI, settings: Settings) -> None:
    """Push the saved configuration at the services that can take it now.

    Most settings need no push at all, and that is the pattern to keep rather
    than replace: a value that can change under a running app is read *late*,
    through a probe closed over ``app`` (``flightsite.app._alert_radius`` is the
    model), so swapping ``app.state.settings`` above is the whole of applying
    it. Anything a subsystem captured at construction is restart-required, and
    the Settings UI says so.

    ``alerts.enabled_templates`` is neither. It is not read late — it names
    rows to create, so re-reading it on every cycle would mean re-deciding
    whether to create them on every cycle — and it must not be
    restart-required, because the setup wizard writes it on a fresh install
    that has not got any alert rules yet and telling that user to restart the
    backend is issue #110. So it is *applied*: handed to the service that owns
    those rows, which decides what the change means (see
    :meth:`~flightsite.alerts.AlertService.apply_enabled_templates`).

    This is the seam for that third kind of setting. Slice 056 adds the two
    entries below it, which are the same shape and come from the same bug
    report: on a fresh install the save that ends the first-run state is the
    moment ingestion becomes possible, so it is also the moment ingestion must
    start (issue #122) against a live store that finally has a location to
    measure from. Ordered deliberately — the anchor is set before the first
    batch can arrive, so no aircraft is ever observed into a store that has no
    receiver location.

    Issue #161 adds the fourth entry, and it is the same kind again: the route
    enrichment provider was built once in ``create_app`` from a flag and a key,
    so an owner who enabled enrichment and pasted their key into the Settings
    page saved both and got nothing until the backend was restarted. Unlike the
    two above it, that one is not a first-run story — it is a setting an
    established install changes, turns off, and re-keys — so the entry applies
    a *state* rather than starting something once.

    Each entry is independently guarded and independently isolated: none can
    skip another by returning early, and a failure in one is logged and
    swallowed exactly as
    :meth:`flightsite.watchlists.WatchlistService._notify_index` swallows a
    listener's. The configuration is already validated, written and live by the
    time any of this runs, so an exception here could only turn a save that
    succeeded into a 500 about it.

    Four entries, and still an explicit list rather than a registry. A registry
    would have to encode the two things this list states by being a list: the
    order, which is load-bearing (the anchor before the start), and the call
    shape, which is not uniform — three of these are coroutines and one is not,
    three take ``settings`` and one takes only ``app``. That is a table plus a
    dispatcher in place of four lines read top to bottom, to centralize a
    guard that :func:`_apply_failed` already centralizes; every entry calls it,
    and adding one is adding a ``try`` block, not re-deriving the pattern. The
    thing that would change the answer is an entry that must run
    *conditionally* on something other than its own state — deciding which
    entries run is what a dispatcher is actually for.
    """
    await _apply_enabled_templates(app, settings)
    _apply_receiver_location(app, settings)
    await _apply_ingestion_start(app)
    await _apply_enrichment(app, settings)


def _apply_failed(setting: str, exc: Exception, **fields: Any) -> None:
    """Report an apply step that raised, without failing the save it followed."""
    logger.warning(
        "config_apply_failed",
        setting=setting,
        error=str(exc),
        error_type=type(exc).__name__,
        **fields,
    )


async def _apply_enabled_templates(app: FastAPI, settings: Settings) -> None:
    """Instantiate newly enabled alert templates (slice 055, issue #110)."""
    alerts: AlertService | None = getattr(app.state, "alerts", None)
    if alerts is None:  # pragma: no cover - the app always builds the service
        return
    try:
        await alerts.apply_enabled_templates(settings.alerts.enabled_templates)
    except Exception as exc:  # pragma: no cover - defensive
        _apply_failed("alerts.enabled_templates", exc)


def _apply_receiver_location(app: FastAPI, settings: Settings) -> None:
    """Anchor the live store's derived distance and bearing, if it has no anchor.

    Only ever fills a blank. The store is built with the location that was
    effective at construction, and on a first run there is none — so without
    this, ingestion started by the entry below would fill the map with aircraft
    whose distance and bearing are ``null``.

    Changing a location the store already has is a different operation and is
    deliberately not done here: every already-observed aircraft would keep a
    distance measured from the old position until it was seen again, which is
    why a location *change* is restart-required and says so on its Settings
    badge. It also keeps demo mode alone — that path installs
    :data:`~flightsite.demo.DEFAULT_CENTER` at boot and generates its traffic
    around it, so a saved location must not move the anchor out from under it.
    """
    live: LiveStore = app.state.live
    latitude = settings.location.latitude
    longitude = settings.location.longitude
    if live.receiver_location is not None or latitude is None or longitude is None:
        return
    try:
        live.set_receiver_location(Position(latitude=latitude, longitude=longitude))
    except Exception as exc:  # pragma: no cover - defensive
        _apply_failed("location", exc)
    else:
        logger.info("receiver_location_applied")


async def _apply_ingestion_start(app: FastAPI) -> None:
    """Start decoder polling if this save is what made it possible (#122, #129).

    Two things poll the decoder and a first-run install builds both of them
    empty: the ingestion service that fills the live map, and the
    receiver-metrics service's ``stats.json`` poller that fills the
    decoder-supplied half of the receiver scorecard. Slice 056 hot-started the
    first; the second stayed absent for the life of the process, so a fresh
    install's decoder metric columns were ``NULL`` until the backend was
    restarted (issue #129).

    Hot-*start* only, and :func:`~flightsite.api.ingestion.ingestion_startable`
    is what keeps it that way: nothing → running, never a second service beside
    a running one and never a reconfiguration of one. See
    :mod:`flightsite.api.ingestion` for why that line is drawn there. Its three
    conditions govern both halves, because both are built together under
    exactly those conditions at boot — and the metrics half declines a second
    time anyway, keeping the poller it already has.

    The halves are isolated from each other as well as from the save: a failure
    in one is logged and leaves the other to run. A failed ingestion start
    leaves ``app.state.ingestion`` unassigned rather than poisoned, so a later
    save simply tries again.
    """
    if not ingestion_startable(app):
        return
    try:
        await start_decoder_ingestion(app)
    except Exception as exc:
        _apply_failed("receiver", exc, action="start_ingestion")
    try:
        await attach_stats_poller(app)
    except Exception as exc:
        _apply_failed("receiver", exc, action="attach_stats_poller")


async def _apply_enrichment(app: FastAPI, settings: Settings) -> None:
    """Reconcile route enrichment with the configuration just saved (#161).

    Unlike the entry above it this is not hot-*start*: enabling, disabling and
    re-keying are all applied, because unlike a decoder adapter there is
    nothing here whose identity a user would lose. Enrichment holds no
    connection anyone is waiting on, no health history and no readiness
    registration — it holds a bounded queue of callsigns it has not asked about
    yet, and the cost of dropping those is that the next observation of each
    flight queues it again.

    The provider is rebuilt from ``app.state.settings``' successor rather than
    from the request body, for the reason
    :mod:`flightsite.api.ingestion` gives for the same choice: a running
    install and its next boot must not read one configuration two ways.
    :meth:`~flightsite.enrichment.EnrichmentService.apply_provider` then
    decides what the new provider *means*, including that a save which did not
    touch this section means nothing at all.
    """
    enrichment: EnrichmentService | None = getattr(app.state, "enrichment", None)
    if enrichment is None:  # pragma: no cover - the app always builds the service
        return
    try:
        await enrichment.apply_provider(build_provider(settings))
    except Exception as exc:
        _apply_failed("enrichment", exc)


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


# --------------------------------------------------------- watchlists (slice 037)


def _watchlist_payload(
    record: WatchlistRecord, entries: Sequence[WatchlistEntryRecord]
) -> dict[str, Any]:
    """One watchlist as the management UI's list/detail row.

    ``entry_count`` is ``len(entries)`` rather than a second query — every
    caller in this module already has the entries in hand, from either
    :meth:`~flightsite.watchlists.service.WatchlistService.list_watchlists_with_entries`
    or a fresh :meth:`~flightsite.watchlists.service.WatchlistService.list_entries`
    call right after a mutation.
    """
    return {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "created_at": iso_utc(from_epoch_ms(record.created_ms)),
        "entry_count": len(entries),
    }


def _entry_payload(record: WatchlistEntryRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "watchlist_id": record.watchlist_id,
        "kind": record.kind.value,
        "value": record.value,
        "note": record.note,
        "created_at": iso_utc(from_epoch_ms(record.created_ms)),
    }


def _watchlist_service(request: Request) -> WatchlistService:
    service: WatchlistService = request.app.state.watchlists
    return service


@router.get("/watchlists")
async def list_watchlists(request: Request) -> dict[str, Any]:
    """Every watchlist, with its entry count (``docs/API.md`` §5)."""
    grouped = await _watchlist_service(request).list_watchlists_with_entries()
    return {
        "watchlists": [_watchlist_payload(watchlist, entries) for watchlist, entries in grouped]
    }


@router.post("/watchlists", status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    request: Request, body: Annotated[WatchlistCreateRequest, Body()]
) -> dict[str, Any]:
    """Create a watchlist. The match index is rebuilt before this returns."""
    try:
        record = await _watchlist_service(request).create_watchlist(
            name=body.name, description=body.description
        )
    except WatchlistValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except DuplicateWatchlistNameError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _watchlist_payload(record, ())


@router.put("/watchlists/{watchlist_id}")
async def update_watchlist(
    request: Request, watchlist_id: int, body: Annotated[WatchlistUpdateRequest, Body()]
) -> dict[str, Any]:
    """Replace a watchlist's name/description. A full replace, not a patch."""
    service = _watchlist_service(request)
    try:
        record = await service.rename_watchlist(
            watchlist_id, name=body.name, description=body.description
        )
    except WatchlistValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except WatchlistNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateWatchlistNameError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    entries = await service.list_entries(watchlist_id)
    return _watchlist_payload(record, entries)


@router.delete("/watchlists/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(request: Request, watchlist_id: int) -> None:
    """Delete a watchlist and every entry on it (``ON DELETE CASCADE``, §4.1)."""
    deleted = await _watchlist_service(request).delete_watchlist(watchlist_id)
    if not deleted:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"no watchlist with id {watchlist_id}"
        )


@router.get("/watchlists/{watchlist_id}/entries")
async def list_watchlist_entries(request: Request, watchlist_id: int) -> dict[str, Any]:
    """One watchlist's entries."""
    service = _watchlist_service(request)
    watchlist = await service.get_watchlist(watchlist_id)
    if watchlist is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"no watchlist with id {watchlist_id}"
        )
    entries = await service.list_entries(watchlist_id)
    return {"entries": [_entry_payload(entry) for entry in entries]}


@router.post("/watchlists/{watchlist_id}/entries", status_code=status.HTTP_201_CREATED)
async def add_watchlist_entry(
    request: Request, watchlist_id: int, body: Annotated[WatchlistEntryCreateRequest, Body()]
) -> dict[str, Any]:
    """Add one entry, validated per its kind. The match index is rebuilt before this returns."""
    try:
        record = await _watchlist_service(request).add_entry(
            watchlist_id, kind=body.kind, value=body.value, note=body.note
        )
    except WatchlistValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except WatchlistNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateEntryError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _entry_payload(record)


@router.delete(
    "/watchlists/{watchlist_id}/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_watchlist_entry(request: Request, watchlist_id: int, entry_id: int) -> None:
    """Remove one entry. The match index is rebuilt before this returns."""
    try:
        removed = await _watchlist_service(request).remove_entry(watchlist_id, entry_id)
    except WatchlistNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"no entry with id {entry_id} on watchlist {watchlist_id}",
        )


# ------------------------------------------------------------- reset (slice 045)
#
# Two destructive Settings actions (SPEC §73, ``docs/API.md`` §5): clearing the
# metadata cache and the deliberate full "Reset FlightSite Data". Appended
# here rather than woven into the imports/handlers above because two sibling
# slices (activity, watchlists) are landing in this same file concurrently —
# keeping this section purely additive, with its own local imports rather
# than edits to the shared header, keeps the two branches from touching the
# same lines. See ``flightsite.reset`` for the implementations: clearing runs
# synchronously through the writer; reset is mark-and-restart, and
# ``flightsite.reset.marker`` explains why a live tear-down was rejected.

#: The exact phrase each destructive action's body must send under
#: ``confirm``. Typed confirmation, not a boolean flag, so a client cannot
#: default its way past the check (SPEC §73).
CLEAR_METADATA_CONFIRM_PHRASE = "clear-metadata"
RESET_DATA_CONFIRM_PHRASE = "reset-flightsite-data"


def _require_confirm_phrase(body: dict[str, Any], expected: str) -> None:
    """Reject anything but the exact confirmation phrase. Nothing runs otherwise.

    Applied before any destructive work starts: a missing ``confirm``, an
    empty string, or the *other* action's phrase all land here rather than
    reaching the deletion code, and all answer the same ``422``.
    """
    if body.get("confirm") != expected:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"confirm must be exactly {expected!r} to perform this action",
        )


async def _record_reset_activity(request: Request, *, kind: str, **fields: Any) -> None:
    """Log a destructive-action activity event if the activity service exists.

    The activity feed (SPEC §35-ish territory) is a sibling slice that may or
    may not be merged yet on the branch this was written from, so its
    interface is not imported here at all — only ever probed with
    ``getattr``/``hasattr``. Its absence, or any failure calling it, degrades
    to a structured log line rather than failing the reset action that
    triggered it: an audit-trail write must never be why a user's confirmed
    destructive action reports an error.

    ``kind`` (not ``event``) so it cannot collide with structlog's own first
    positional argument, which every ``logger.*`` call below is also named
    ``event`` — ``logger.info("...", event=kind)`` would otherwise raise.
    """
    activity = getattr(request.app.state, "activity", None)
    record = getattr(activity, "record", None) if activity is not None else None
    if not callable(record):
        logger.info("reset_activity_event_unavailable", kind=kind, **fields)
        return
    try:
        await record(event=kind, **fields)
    except Exception as exc:
        logger.warning(
            "reset_activity_event_failed",
            kind=kind,
            error=str(exc),
            error_type=type(exc).__name__,
        )


@router.post("/reset/metadata-cache")
async def clear_metadata_cache_endpoint(
    request: Request,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Delete imported metadata, the route cache and airports; leave history intact.

    Requires ``{"confirm": "clear-metadata"}`` (SPEC §73). Runs synchronously
    through the writer — a handful of ``DELETE``/``UPDATE`` statements, not an
    import — and answers with the row counts removed so the Settings UI can
    show the operator what just happened. ``docs/BACKUP.md``'s backup command
    is the strong suggestion the UI surfaces before this is ever called; the
    API itself does not require a backup to have been taken.

    Aircraft, sighting and analytics history is never touched by this
    endpoint — see :func:`flightsite.reset.service.clear_metadata_cache`.
    """
    _require_confirm_phrase(body, CLEAR_METADATA_CONFIRM_PHRASE)

    from flightsite.reset.service import clear_metadata_cache

    metadata: MetadataService = request.app.state.metadata
    result = await clear_metadata_cache(
        database=request.app.state.database,
        metadata=metadata,
        airports=request.app.state.airports,
    )
    await _record_reset_activity(request, kind="metadata_cache_cleared", **result.as_dict())
    return {"cleared": True, **result.as_dict()}


@router.post("/reset/data", status_code=status.HTTP_202_ACCEPTED)
async def reset_flightsite_data(
    request: Request,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Request the deliberate full reset SPEC §73 describes.

    Requires ``{"confirm": "reset-flightsite-data"}``. This is
    mark-and-restart, not a live tear-down (see
    ``flightsite.reset.marker`` for why): it writes a marker file to the data
    directory and answers ``202`` — the database itself is untouched by this
    request. The reset takes effect on the *next* process start, which
    deletes ``flightsite.sqlite3`` (and its WAL sidecars) before anything else
    runs, preserving ``config.yaml``/``secrets.yaml``. The Settings UI is
    expected to tell the operator to restart the stack
    (``docker compose restart``) and to have already put ``docs/BACKUP.md``'s
    backup command in front of them before they typed the confirmation
    phrase.
    """
    _require_confirm_phrase(body, RESET_DATA_CONFIRM_PHRASE)

    from flightsite.reset.marker import write_reset_marker

    store: ConfigStore = request.app.state.config_store
    requested_ms = utc_now_ms()
    write_reset_marker(store.data_dir, requested_ms=requested_ms)
    await _record_reset_activity(request, kind="reset_requested", requested_ms=requested_ms)
    return {
        "accepted": True,
        "requested_ms": requested_ms,
        "restart_required": True,
        "message": (
            "FlightSite data will be reset on the next restart. "
            "Restart the stack (docker compose restart) to apply it."
        ),
    }
