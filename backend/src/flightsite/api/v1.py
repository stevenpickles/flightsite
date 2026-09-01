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
from datetime import UTC, datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse

from flightsite import __version__
from flightsite.airports.overlay import BboxError, parse_bbox
from flightsite.api.context import LiveApiContext
from flightsite.api.history import DEFAULT_ORDER, DEFAULT_SORT
from flightsite.api.receiver_stats import (
    DEFAULT_SIGNAL_BUCKET_WIDTH_DB,
    MAX_SIGNAL_BUCKET_WIDTH_DB,
    MIN_SIGNAL_BUCKET_WIDTH_DB,
    ReceiverMetricQueryError,
)
from flightsite.api.schemas import (
    AircraftDetail,
    AircraftHistoryListResponse,
    AircraftSortKey,
    AirportFeatureCollection,
    AirportSizeClassLiteral,
    AirspaceFeatureCollection,
    CurrentAircraftResponse,
    ReceiverInfo,
    ReceiverLifetimeStats,
    ReceiverMetricSeries,
    ReceiverRangeByBearing,
    ReceiverScorecard,
    ReceiverSeriesMetric,
    ReceiverSeriesResolution,
    ReceiverSignalDistribution,
    SightingDetail,
    SightingListResponse,
    SightingSortKey,
    SortOrder,
)
from flightsite.api.serializers import airport_feature_collection_payload
from flightsite.api.sightings import DEFAULT_ORDER as SIGHTINGS_DEFAULT_ORDER
from flightsite.api.sightings import DEFAULT_SORT as SIGHTINGS_DEFAULT_SORT
from flightsite.api.ws import router as ws_router
from flightsite.counters import counters
from flightsite.db import to_epoch_ms
from flightsite.readiness import ReadinessRegistry

#: §2.9's ``{icao}`` path parameter validator: lowercase 6-hex-char ICAO
#: 24-bit address. ``current`` and ``interesting`` (§3.3/§3.4) can never
#: match it, so those literal routes and this parameterized one never
#: collide regardless of declaration order.
ICAO_PATTERN = r"^[0-9a-f]{6}$"

#: §2.4 pagination bounds.
DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 500

router = APIRouter()
router.include_router(ws_router)


def _context(request: Request) -> LiveApiContext:
    """The app's live API context, built once in the application factory."""
    context: LiveApiContext = request.app.state.api_context
    return context


def _bound_ms(moment: datetime | None) -> int | None:
    """A ``from``/``to`` query bound as epoch ms, or ``None`` if unset.

    A bound with no offset is assumed UTC rather than rejected: §2.2 says the
    API never returns a naive instant, but a client typing a plain
    ``2026-08-30`` date into a query string is a normal case this endpoint
    should not 500 on.
    """
    if moment is None:
        return None
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return to_epoch_ms(aware)


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
    "/receiver/scorecard",
    response_model=ReceiverScorecard,
    tags=["receiver"],
    summary="Receiver scorecard",
)
async def receiver_scorecard(request: Request) -> dict[str, Any]:
    """SPEC §61's scorecard — ``docs/API.md`` §3.8: current visible/positioned,
    messages/positions per second, max range today/ever, unique aircraft
    today/since T0, decoder and FlightSite uptime, and a health summary.
    """
    return await _context(request).receiver_scorecard()


@router.get(
    "/receiver/metrics",
    response_model=ReceiverMetricSeries,
    tags=["receiver"],
    summary="Receiver time-series metrics",
    responses={
        400: {"description": "Unsupported `metric`/`resolution` pairing, or `to` before `from`."}
    },
)
async def receiver_metric_series(
    request: Request,
    metric: Annotated[ReceiverSeriesMetric, Query(description="SPEC §62's v1 chart catalog.")],
    resolution: Annotated[
        ReceiverSeriesResolution,
        Query(description="Storage tier to read (``docs/DATA_MODEL.md`` §6, ADR-0009)."),
    ] = "hourly",
    from_: Annotated[
        datetime | None,
        Query(
            alias="from",
            description="Inclusive lower bound; default is a `resolution`-sized lookback.",
        ),
    ] = None,
    to: Annotated[
        datetime | None, Query(description="Inclusive upper bound. Defaults to now.")
    ] = None,
) -> dict[str, Any] | Response:
    """One SPEC §62 chart's data — ``docs/API.md`` §3.8.

    ``metric="unique_aircraft"`` only answers at ``resolution=daily`` (it has
    no raw-sample or hourly representation); ``messages_total`` and
    ``positions_total`` answer only at ``resolution=hourly`` or ``daily``
    (``receiver_metrics_raw`` stores rates, not totals). Either mismatch, or
    ``from`` after `to`, answers the §2.5 error envelope with a 400.
    """
    from_ms = _bound_ms(from_)
    to_ms = _bound_ms(to)
    if from_ms is not None and to_ms is not None and from_ms > to_ms:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": "invalid_range",
                    "message": "`from` must not be after `to`",
                    "detail": None,
                }
            },
        )
    try:
        return await _context(request).receiver_metric_series(
            metric=metric, resolution=resolution, from_ms=from_ms, to_ms=to_ms
        )
    except ReceiverMetricQueryError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": {"code": "invalid_resolution", "message": str(exc), "detail": None}},
        )


@router.get(
    "/receiver/range-by-bearing",
    response_model=ReceiverRangeByBearing,
    tags=["receiver"],
    summary="Maximum range by bearing (polar)",
)
async def receiver_range_by_bearing(request: Request) -> dict[str, Any]:
    """SPEC §62's polar max-range-by-bearing plot — ``docs/API.md`` §3.8.

    72 five-degree sectors (0° = North, increasing clockwise), for today and
    for the receiver's whole lifetime.
    """
    return await _context(request).receiver_range_by_bearing()


@router.get(
    "/receiver/signal-distribution",
    response_model=ReceiverSignalDistribution,
    tags=["receiver"],
    summary="Signal-strength distribution",
)
async def receiver_signal_distribution(
    request: Request,
    from_: Annotated[
        datetime | None,
        Query(alias="from", description="Inclusive lower bound on sighting `started_at`."),
    ] = None,
    to: Annotated[
        datetime | None, Query(description="Inclusive upper bound on sighting `started_at`.")
    ] = None,
    bucket_width_db: Annotated[
        float,
        Query(
            ge=MIN_SIGNAL_BUCKET_WIDTH_DB,
            le=MAX_SIGNAL_BUCKET_WIDTH_DB,
            description="Histogram bucket width, dB.",
        ),
    ] = DEFAULT_SIGNAL_BUCKET_WIDTH_DB,
) -> dict[str, Any]:
    """SPEC §62's signal-strength distribution — ``docs/API.md`` §3.8.

    Built from per-sighting ``rssi_avg_db`` (roadmap slice 052) over the
    selected window, never from raw receiver-metric samples. An omitted
    ``from``/``to`` is unbounded on that side — every sighting ever recorded,
    by default.
    """
    return await _context(request).receiver_signal_distribution(
        from_ms=_bound_ms(from_), to_ms=_bound_ms(to), bucket_width_db=bucket_width_db
    )


@router.get(
    "/receiver/lifetime",
    response_model=ReceiverLifetimeStats,
    tags=["receiver"],
    summary="Lifetime receiver statistics",
)
async def receiver_lifetime(request: Request) -> dict[str, Any]:
    """SPEC §63's lifetime statistics block, since T0 where possible — ``docs/API.md`` §3.8."""
    return await _context(request).receiver_lifetime()


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


@router.get(
    "/aircraft",
    response_model=AircraftHistoryListResponse,
    tags=["history"],
    summary="Paginated historical aircraft list",
)
async def aircraft_history(
    request: Request,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Page size (§2.4).")
    ] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Rows to skip (§2.4).")] = 0,
    sort: Annotated[
        AircraftSortKey, Query(description="§3.5's documented sort keys.")
    ] = DEFAULT_SORT,
    order: Annotated[SortOrder, Query()] = DEFAULT_ORDER,
    classification: Annotated[
        str | None,
        Query(description="Exact `mission_category` match (SPEC §39)."),
    ] = None,
    operator_group: Annotated[str | None, Query(description="Curated operator group slug.")] = None,
    type: Annotated[str | None, Query(description="Exact ICAO type designator match.")] = None,
) -> dict[str, Any]:
    """Every airframe this receiver has ever sighted — ``docs/API.md`` §3.5.

    Sortable and filterable per §3.5; SPEC §56's columns. ``total`` is the
    exact count of rows matching the filters (see
    :mod:`flightsite.api.history` for why this endpoint does not exercise
    §2.4's allowance to omit or approximate it).
    """
    items, total = await _context(request).aircraft_history(
        limit=limit,
        offset=offset,
        sort=sort,
        order=order,
        classification=classification,
        operator_group=operator_group,
        type_code=type,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/aircraft/{icao}",
    response_model=AircraftDetail,
    tags=["history"],
    summary="Full aircraft detail",
    responses={404: {"description": "No aircraft has ever been sighted at this ICAO address."}},
)
async def aircraft_detail(
    request: Request,
    icao: Annotated[
        str,
        Path(pattern=ICAO_PATTERN, description="Lowercase 6-hex-char ICAO 24-bit address."),
    ],
) -> dict[str, Any] | Response:
    """One airframe's identity, metadata, classification and lifetime records.

    ``docs/API.md`` §3.5: identity, metadata with provenance, classification,
    lifetime records (SPEC §53), and whether the airframe is in the live
    picture right now. 404s — in the §2.5 error envelope — for an address
    this receiver has never sighted. ``response_model`` validates only the
    success path: returning a raw :class:`~fastapi.responses.JSONResponse`
    for the 404 bypasses it, which is what lets the error body take a
    different documented shape than ``AircraftDetail``.
    """
    detail = await _context(request).aircraft_detail(icao)
    if detail is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "not_found",
                    "message": f"No aircraft with ICAO {icao}",
                    "detail": None,
                }
            },
        )
    return detail


@router.get(
    "/airports",
    response_model=AirportFeatureCollection,
    tags=["overlays"],
    summary="Airport markers for the map overlay",
)
async def airports_overlay(
    request: Request,
    bbox: Annotated[
        str | None,
        Query(
            description=(
                "`west,south,east,north` in decimal degrees (WGS-84), matching "
                "the current map viewport. Omitted queries the whole dataset."
            ),
            examples=["-123.5,47.0,-121.5,48.0"],
        ),
    ] = None,
    min_size: Annotated[
        AirportSizeClassLiteral | None,
        Query(
            description=(
                "Smallest size class to include (`large` > `medium` > `small` > "
                "`heliport`). Omitted includes every imported size class."
            )
        ),
    ] = None,
) -> dict[str, Any] | Response:
    """Airport markers for the Live Map overlay (roadmap slice 028).

    Reads the same ``airports`` table the nearest-airport context (slice 027)
    already populates — no new fetch, no new dataset, just a new view over
    data `docs/LICENSES.md` already pins (OurAirports, public domain). Rows
    are ordered largest-first and capped
    (:data:`flightsite.airports.overlay.MAX_AIRPORTS_RESPONSE`) so a
    continent-wide viewport degrades to "the biggest fields in view" rather
    than an unbounded response.

    A malformed ``bbox`` answers the §2.5 error envelope with a 400 rather
    than either raising or silently ignoring it.
    """
    try:
        parsed_bbox = parse_bbox(bbox) if bbox is not None else None
    except BboxError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": {"code": "invalid_bbox", "message": str(exc), "detail": None}},
        )
    records = await _context(request).airport_overlay_features(bbox=parsed_bbox, min_size=min_size)
    return airport_feature_collection_payload(records)


@router.get(
    "/airspace",
    response_model=AirspaceFeatureCollection,
    tags=["overlays"],
    summary="User-supplied airspace overlay",
)
async def airspace_overlay(request: Request) -> dict[str, Any]:
    """The user-supplied airspace overlay (roadmap slice 028).

    FlightSite ships no default airspace dataset — see
    ``docs/adr/0012-airspace-data-source.md``. A user who places a valid
    GeoJSON ``FeatureCollection`` at ``<data_dir>/airspace.geojson`` sees it
    here in full; an install with no file, or one whose file failed
    validation, sees the same empty ``FeatureCollection`` either way (never a
    404 or a 500) — the map degrades to "no airspace layer" silently rather
    than surfacing UI noise for a feature that ships no default.
    """
    return _context(request).airspace_feature_collection()


@router.get(
    "/aircraft/{icao}/sightings",
    response_model=SightingListResponse,
    tags=["history"],
    summary="Paginated sightings for one aircraft",
)
async def aircraft_sightings(
    request: Request,
    icao: Annotated[
        str,
        Path(pattern=ICAO_PATTERN, description="Lowercase 6-hex-char ICAO 24-bit address."),
    ],
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Page size (§2.4).")
    ] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Rows to skip (§2.4).")] = 0,
    sort: Annotated[
        SightingSortKey, Query(description="§3.6's documented sort keys.")
    ] = SIGHTINGS_DEFAULT_SORT,
    order: Annotated[SortOrder, Query()] = SIGHTINGS_DEFAULT_ORDER,
) -> dict[str, Any]:
    """One airframe's sighting log — ``docs/API.md`` §3.5's deferred third row.

    The same row shape and sort keys as ``GET /api/v1/sightings``, filtered to
    one ICAO address. An address this receiver has never sighted answers with
    an empty list rather than a 404 — this is a list endpoint, and "never
    sighted" and "no sightings" are the same fact from a query's point of
    view; ``GET /api/v1/aircraft/{icao}`` is where "does this address exist"
    is answered.
    """
    items = await _context(request).sighting_list(
        limit=limit, offset=offset, sort=sort, order=order, icao=icao
    )
    return {"items": items, "total": None, "limit": limit, "offset": offset}


@router.get(
    "/sightings",
    response_model=SightingListResponse,
    tags=["history"],
    summary="Paginated chronological sightings log",
)
async def sightings_list(
    request: Request,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Page size (§2.4).")
    ] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Rows to skip (§2.4).")] = 0,
    sort: Annotated[
        SightingSortKey, Query(description="§3.6's documented sort keys.")
    ] = SIGHTINGS_DEFAULT_SORT,
    order: Annotated[SortOrder, Query()] = SIGHTINGS_DEFAULT_ORDER,
    icao: Annotated[
        str | None,
        Query(pattern=ICAO_PATTERN, description="Exact lowercase ICAO address match."),
    ] = None,
    from_: Annotated[
        datetime | None,
        Query(alias="from", description="Inclusive lower bound on `started_at` (§2.2)."),
    ] = None,
    to: Annotated[
        datetime | None,
        Query(description="Inclusive upper bound on `started_at` (§2.2)."),
    ] = None,
    interesting: Annotated[
        bool | None,
        Query(description="Restrict to sightings with a non-null `max_alert_severity`."),
    ] = None,
    open: Annotated[
        bool | None,
        Query(description="Restrict to sightings still open (`ended_at` is null)."),
    ] = None,
) -> dict[str, Any]:
    """The chronological sightings log — ``docs/API.md`` §3.6, SPEC §57.

    Sortable and filterable per §3.6; ``total`` is always ``null`` (see
    :mod:`flightsite.api.sightings` for why this endpoint does not exercise
    §2.4's exact-count path the way ``/aircraft`` does).
    """
    items = await _context(request).sighting_list(
        limit=limit,
        offset=offset,
        sort=sort,
        order=order,
        icao=icao,
        from_ms=_bound_ms(from_),
        to_ms=_bound_ms(to),
        interesting=interesting,
        open_only=open,
    )
    return {"items": items, "total": None, "limit": limit, "offset": offset}


@router.get(
    "/sightings/{sighting_id}",
    response_model=SightingDetail,
    tags=["history"],
    summary="Full sighting detail",
    responses={404: {"description": "No sighting exists with this id."}},
)
async def sighting_detail(
    request: Request,
    sighting_id: Annotated[int, Path(ge=1, description="The sighting's numeric id.")],
) -> dict[str, Any] | Response:
    """One sighting's flight context, reception stats, events and path — §3.6.

    404s — in the §2.5 error envelope — for an id that does not exist.
    """
    detail = await _context(request).sighting_detail(sighting_id)
    if detail is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "not_found",
                    "message": f"No sighting with id {sighting_id}",
                    "detail": None,
                }
            },
        )
    return detail
