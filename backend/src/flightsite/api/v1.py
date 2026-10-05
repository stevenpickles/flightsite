"""Versioned, documented, read-only public API: ``/api/v1``.

Everything mounted here is safe to hand to another LAN tool: it never mutates
application state, it never returns a secret, and its shapes are the ones
``docs/API.md`` publishes (SPEC §74). Mutations live on the unsupported
``/api/internal`` surface instead.

This slice adds the live picture — ``GET /aircraft/current`` (§3.3), ``GET
/receiver`` (§3.2) and the ``ws/live`` WebSocket (§4, documented in
:mod:`flightsite.api.ws`) — on top of the health and readiness endpoints from
slice 001. Later slices add the history (§3.5), sightings (§3.6) and analytics
(§3.7) surfaces, and slice 042 adds diagnostics (§3.10). Slice 077 adds feeder status (§3.12).

The REST endpoints declare Pydantic response models, so the OpenAPI document
served at ``/api/v1/openapi.json`` (§2.10) describes them exactly and every
response is validated against the shape that was published.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Any, Final, get_args
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse

from flightsite import __version__
from flightsite.airports.overlay import BboxError, parse_bbox
from flightsite.analytics.bucketing import Preset, Window
from flightsite.analytics.bucketing import local_day as analytics_local_day
from flightsite.analytics.queries import (
    DEFAULT_RARE_MAX_SIGHTINGS,
    DEFAULT_TOP_LIMIT,
    MAX_TOP_LIMIT,
)
from flightsite.api.context import LiveApiContext
from flightsite.api.history import DEFAULT_ORDER, DEFAULT_SORT
from flightsite.api.overhead import (
    DEFAULT_OVERHEAD_LIMIT,
    DEFAULT_WINDOW_MINUTES,
    MAX_OVERHEAD_LIMIT,
    MAX_WINDOW_MINUTES,
    MINUTE_MS,
    OverheadRepository,
    overhead_payload,
)
from flightsite.api.receiver_stats import (
    DEFAULT_COVERAGE_WINDOW,
    DEFAULT_SIGNAL_BUCKET_WIDTH_DB,
    MAX_SIGNAL_BUCKET_WIDTH_DB,
    MIN_SIGNAL_BUCKET_WIDTH_DB,
    ReceiverMetricQueryError,
)
from flightsite.api.schemas import (
    ActivityEventTypeLiteral,
    ActivityListResponse,
    AircraftDetail,
    AircraftHistoryListResponse,
    AircraftSortKey,
    AirportFeatureCollection,
    AirportSizeClassLiteral,
    AirspaceFeatureCollection,
    AlertMatchListResponse,
    AlertSeverityLiteral,
    AnalyticsAircraftResponse,
    AnalyticsClassificationResponse,
    AnalyticsCountsResponse,
    AnalyticsDailyResponse,
    AnalyticsGroupResponse,
    AnalyticsHourlyResponse,
    AnalyticsPresetLiteral,
    AnalyticsRarityResponse,
    AnalyticsSeenAircraftResponse,
    AnalyticsSeenTypesResponse,
    AnalyticsSummaryResponse,
    CurrentAircraftResponse,
    DiagnosticsResponse,
    FeederHistoryResponse,
    FeederHistoryWindowLiteral,
    FeedersResponse,
    InterestingAircraftResponse,
    OverheadResponse,
    ReceiverCoverage,
    ReceiverCoverageWindow,
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
from flightsite.api.search import MAX_QUERY_LENGTH
from flightsite.api.serializers import (
    airport_feature_collection_payload,
    analytics_aircraft_payload,
    analytics_counts_payload,
    analytics_daily_row_payload,
    analytics_group_payload,
    analytics_hourly_row_payload,
    analytics_rare_type_payload,
    analytics_seen_aircraft_payload,
    analytics_seen_type_payload,
    analytics_summary_payload,
)
from flightsite.api.sightings import DEFAULT_ORDER as SIGHTINGS_DEFAULT_ORDER
from flightsite.api.sightings import DEFAULT_SORT as SIGHTINGS_DEFAULT_SORT
from flightsite.api.ws import router as ws_router
from flightsite.counters import counters
from flightsite.db import Database, to_epoch_ms, utc_now_ms
from flightsite.diagnostics import collect_diagnostics
from flightsite.feeders import FeederService, empty_report
from flightsite.readiness import ReadinessRegistry

#: §2.9's ``{icao}`` path parameter validator: lowercase 6-hex-char ICAO
#: 24-bit address. ``current`` and ``interesting`` (§3.3/§3.4) can never
#: match it, so those literal routes and this parameterized one never
#: collide regardless of declaration order.
ICAO_PATTERN = r"^[0-9a-f]{6}$"

#: §2.4 pagination bounds.
DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 500

#: §3.7's documented default preset.
DEFAULT_PRESET: Final = Preset.TODAY.value

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
    "/diagnostics",
    response_model=DiagnosticsResponse,
    tags=["service"],
    summary="Full system diagnostics",
)
async def diagnostics(request: Request) -> dict[str, Any]:
    """Every SPEC §67 item in one payload — ``docs/API.md`` §3.10.

    Read-only in the strong sense: no writer session, no lock ingestion wants,
    and no fresh ``quick_check`` (that pragma takes the writer lock, so the
    result maintenance already computed is reported instead). A diagnostics
    request arriving during a decoder burst costs the burst nothing.

    The payload is redacted against the configured secrets on the way out, so
    it cannot carry an API key however a later slice extends it.
    """
    return await collect_diagnostics(request.app)


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
    "/receiver/coverage",
    response_model=ReceiverCoverage,
    tags=["receiver"],
    summary="Coverage by bearing and altitude band, against the radio horizon",
)
async def receiver_coverage(
    request: Request,
    window: Annotated[
        ReceiverCoverageWindow,
        Query(description="Whole receiver-local days ending today, or `all`."),
    ] = DEFAULT_COVERAGE_WINDOW,
) -> dict[str, Any]:
    """Roadmap slice 087's coverage analysis — ``docs/API.md`` §3.8.

    For each altitude band (below 10,000 ft, 10,000 to 25,000 ft, 25,000 ft
    and above) and each 5° sector: the furthest detection in the window, the
    evidence behind it, the band's 4/3-Earth radio horizon from the antenna
    height above ground, and the share of it reached — plus findings for
    well-observed sectors that fall short of 60 % of it. With no antenna
    height configured every horizon is ``null`` and there are no findings.
    """
    return await _context(request).receiver_coverage(window=window)


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
    "/aircraft/interesting",
    response_model=InterestingAircraftResponse,
    tags=["live"],
    summary="Currently interesting aircraft",
)
async def interesting_aircraft(request: Request) -> dict[str, Any]:
    """Live aircraft an alert rule or a built-in currently matches — §3.4.

    The §3.3 aircraft object with ``interesting`` guaranteed non-null, ordered
    **severity then distance** (SPEC §49's panel ordering). An aircraft with no
    known distance sorts last within its severity band: a panel that put the
    aircraft it cannot place above the one overhead would answer the wrong
    question.

    Answered entirely from the in-memory live registry and the alert engine's
    already-computed state; nothing on this path touches SQLite
    (``docs/ARCHITECTURE.md`` §3.1). Not paginated, for the reason
    ``/aircraft/current`` is not.

    ``interesting`` reflects what is matching *right now*, so an aircraft whose
    only rule was a distance window it has since left drops out of this list.
    What happened is not lost with it — the sighting keeps its
    ``max_alert_severity`` and ``GET /api/v1/alerts/matches`` keeps the match.
    """
    items = _context(request).interesting_aircraft()
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
    q: Annotated[
        str | None,
        Query(
            max_length=MAX_QUERY_LENGTH,
            description=(
                "Case-insensitive, literal prefix over ICAO address, registration, "
                "most recent callsign, type designator and operator. Trimmed; "
                "blank is ignored. Filters this list only — not a global search."
            ),
            examples=["G-EZ"],
        ),
    ] = None,
) -> dict[str, Any]:
    """Every airframe this receiver has ever sighted — ``docs/API.md`` §3.5.

    Sortable and filterable per §3.5; SPEC §56's columns. ``total`` is the
    exact count of rows matching the filters (see
    :mod:`flightsite.api.history` for why this endpoint does not exercise
    §2.4's allowance to omit or approximate it). ``q`` (slice 083) is the
    list-scoped prefix search :mod:`flightsite.api.search` defines; it
    combines with the other filters and with sorting and pagination.
    """
    items, total = await _context(request).aircraft_history(
        limit=limit,
        offset=offset,
        sort=sort,
        order=order,
        classification=classification,
        operator_group=operator_group,
        type_code=type,
        q=q,
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
    preset: Annotated[
        AnalyticsPresetLiteral | None,
        Query(
            description=(
                "Time preset resolved in receiver-local time, as on the analytics "
                "endpoints (§3.7). Ignored when explicit `from`/`to` bounds are given."
            )
        ),
    ] = None,
    interesting: Annotated[
        bool | None,
        Query(description="Restrict to sightings with a non-null `max_alert_severity`."),
    ] = None,
    open: Annotated[
        bool | None,
        Query(description="Restrict to sightings still open (`ended_at` is null)."),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            max_length=MAX_QUERY_LENGTH,
            description=(
                "Case-insensitive, literal prefix of the ICAO address or the last "
                "callsign. Trimmed; blank is ignored. Filters this list only — not "
                "a global search."
            ),
            examples=["BAW"],
        ),
    ] = None,
) -> dict[str, Any]:
    """The chronological sightings log — ``docs/API.md`` §3.6, SPEC §57.

    Sortable and filterable per §3.6; ``total`` is always ``null`` (see
    :mod:`flightsite.api.sightings` for why this endpoint does not exercise
    §2.4's exact-count path the way ``/aircraft`` does). ``icao`` stays an
    exact six-hex-digit match; ``q`` (slice 083) is the prefix search over
    address or callsign that the Sightings page's filter box sends.
    """
    context = _context(request)
    from_ms, to_ms = _bound_ms(from_), _bound_ms(to)
    if preset is not None and from_ms is None and to_ms is None:
        # The same resolution the analytics endpoints use, so "today" is the
        # receiver's local day here too (slice 098). The window is half-open
        # and this endpoint's `to` is inclusive, hence the millisecond.
        window = await context.analytics_window(preset=preset, from_ms=None, to_ms=None)
        if not window.whole_history:
            from_ms, to_ms = window.start_ms, window.end_ms - 1
    items = await context.sighting_list(
        limit=limit,
        offset=offset,
        sort=sort,
        order=order,
        icao=icao,
        from_ms=from_ms,
        to_ms=to_ms,
        interesting=interesting,
        open_only=open,
        q=q,
    )
    return {"items": items, "total": None, "limit": limit, "offset": offset}


@router.get(
    "/activity",
    response_model=ActivityListResponse,
    tags=["activity"],
    summary="Paginated chronological activity feed",
)
async def activity_feed(
    request: Request,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Page size (§2.4).")
    ] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Rows to skip (§2.4).")] = 0,
    type: Annotated[
        list[ActivityEventTypeLiteral] | None,
        Query(description="Restrict to these event types; repeat for several."),
    ] = None,
    from_: Annotated[
        datetime | None,
        Query(alias="from", description="Inclusive lower bound on `at` (§2.2)."),
    ] = None,
    to: Annotated[
        datetime | None, Query(description="Inclusive upper bound on `at` (§2.2).")
    ] = None,
) -> dict[str, Any]:
    """The activity feed — ``docs/API.md`` §3.9, SPEC §55.

    Newest first, which is the only order a feed is read in, with the event id
    as the tie-break so paging through a burst written in one instant can
    neither repeat nor skip a row.

    ``type`` is repeatable: the feed's filter selects several kinds at once,
    and one repeated query parameter is cheaper for both ends than a
    comma-separated string neither can validate. ``total`` is always ``null``,
    for the reason ``/sightings`` gives (§2.4).
    """
    items = await _context(request).activity_feed(
        limit=limit,
        offset=offset,
        types=type,
        from_ms=_bound_ms(from_),
        to_ms=_bound_ms(to),
    )
    return {"items": items, "total": None, "limit": limit, "offset": offset}


@router.get(
    "/alerts/matches",
    response_model=AlertMatchListResponse,
    tags=["activity"],
    summary="Alert match history",
)
async def alert_matches(
    request: Request,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Page size (§2.4).")
    ] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Rows to skip (§2.4).")] = 0,
    severity: Annotated[
        AlertSeverityLiteral | None,
        Query(description="Restrict to one severity of the §2.8 ladder."),
    ] = None,
    icao: Annotated[
        str | None,
        Query(pattern=ICAO_PATTERN, description="Restrict to one airframe (§2.9)."),
    ] = None,
    rule_id: Annotated[
        int | None,
        Query(
            ge=1,
            description="Restrict to one user rule; an unknown id matches nothing.",
        ),
    ] = None,
    from_: Annotated[
        datetime | None,
        Query(alias="from", description="Inclusive lower bound on `at` (§2.2)."),
    ] = None,
    to: Annotated[
        datetime | None, Query(description="Inclusive upper bound on `at` (§2.2).")
    ] = None,
) -> dict[str, Any]:
    """Every alert that has fired — ``docs/API.md`` §3.10, SPEC §43 to §48.

    Newest first, with the match id as the tie-break so paging through several
    matches recorded in one instant can neither repeat nor skip a row — the
    same ordering ``/activity`` uses and for the same reason.

    One row per rule per sighting (SPEC §48), plus the documented exception: a
    higher-priority condition matching later is a *different* rule, so it is a
    different row. A built-in emergency match has ``rule: null`` and a
    ``builtin_key`` instead, because SPEC §47 makes it fire without a rule at
    all. ``total`` is always ``null``, for the reason ``/activity`` gives.

    ``rule_id`` (issue #98) answers "show me what this rule has caught" from
    the Alerts page. It is a filter and never a lookup: an id no rule has —
    including one whose rule was deleted while the page was open — returns an
    empty page rather than a 404, because "this rule caught nothing" and "this
    rule is gone" are the same rendering. Only a positive integer is accepted;
    anything else is the §2.5 422.
    """
    items = await _context(request).alert_matches(
        limit=limit,
        offset=offset,
        severity=severity,
        icao=icao,
        rule_id=rule_id,
        from_ms=_bound_ms(from_),
        to_ms=_bound_ms(to),
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


@router.get(
    "/overhead",
    response_model=OverheadResponse,
    tags=["history"],
    summary="What passed closest to the receiver around a moment",
)
async def overhead(
    request: Request,
    at: Annotated[
        datetime | None,
        Query(description="The moment asked about (§2.2). Defaults to now; no offset means UTC."),
    ] = None,
    window: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_WINDOW_MINUTES,
            description="Minutes either side of `at` to search.",
        ),
    ] = DEFAULT_WINDOW_MINUTES,
    limit: Annotated[
        int, Query(ge=1, le=MAX_OVERHEAD_LIMIT, description="Ranked results to return.")
    ] = DEFAULT_OVERHEAD_LIMIT,
) -> dict[str, Any]:
    """The "What was that?" lookup — roadmap slice 090, issue #233, ``docs/API.md`` §3.7.1.

    The sightings whose **closest stored position fix** inside
    ``[at - window, at + window]`` came nearest the receiver, nearest first.
    Every row is a point a sighting actually stored — never a position
    interpolated between stored points or beyond them — so a single-moment
    lookup stays one (SPEC §79 keeps playback out of scope). How candidates
    are found and how distance is measured: :mod:`flightsite.api.overhead`
    and :mod:`flightsite.sightings.overhead`.

    Measured from the position the live store measures every other range
    from. With no receiver location set there is nothing to measure from:
    the answer is an empty 200 with ``receiver_configured: false`` and a
    ``reason``, the way every other receiver-relative field degrades to
    unknown rather than an error (§2.7).
    """
    context = _context(request)
    at_ms = _bound_ms(at)
    if at_ms is None:
        at_ms = utc_now_ms()
    receiver = context.live.receiver_location
    if receiver is None:
        return overhead_payload(at_ms=at_ms, window_minutes=window, result=None)
    database: Database = request.app.state.database
    result = await OverheadRepository(database).closest_passes(
        receiver=receiver,
        from_ms=at_ms - window * MINUTE_MS,
        to_ms=at_ms + window * MINUTE_MS,
        limit=limit,
        antenna_height_ft=context.settings.location.antenna_height_ft,
    )
    return overhead_payload(at_ms=at_ms, window_minutes=window, result=result)


# ---------------------------------------------------------------- analytics
#
# ``docs/API.md`` §3.7's seven endpoints (slice 031). Every one of them takes
# the same window parameters, so they share one dependency for it: ``_window``
# resolves ``preset`` or an explicit ``from``/``to`` pair against the
# *receiver's* local calendar and returns both the UTC bounds and the local day
# range, which each response echoes back. A client never has to re-derive what
# "today" meant, and cannot get it wrong from a browser in another zone.
#
# An explicit range longer than
# :data:`~flightsite.analytics.bucketing.MAX_WINDOW_DAYS` is clamped to its
# most recent days rather than materialized — client input is the only way
# these endpoints can be asked for something unbounded, and the echoed window
# block says exactly what was covered.


@dataclass(frozen=True, slots=True)
class _ResolvedWindow:
    """A resolved analytics window, with the block every response echoes."""

    window: Window
    preset: str | None
    block: dict[str, Any]


async def _window(
    request: Request,
    preset: Annotated[
        AnalyticsPresetLiteral | None,
        Query(
            description=(
                "Time preset resolved in receiver-local time (§3.7). Ignored "
                "when explicit `from`/`to` bounds are given."
            )
        ),
    ] = None,
    from_: Annotated[
        datetime | None,
        Query(alias="from", description="Inclusive lower bound, UTC (§2.2)."),
    ] = None,
    to: Annotated[
        datetime | None,
        Query(description="Exclusive upper bound, UTC (§2.2)."),
    ] = None,
) -> _ResolvedWindow:
    """Resolve §3.7's window parameters once, for every analytics endpoint."""
    context = _context(request)
    explicit = from_ is not None or to is not None
    named = None if explicit else (preset or DEFAULT_PRESET)
    window = await context.analytics_window(
        preset=named,
        from_ms=_bound_ms(from_),
        to_ms=_bound_ms(to),
    )
    return _ResolvedWindow(
        window=window,
        preset=named,
        block=context.analytics_window_block(window, preset=named),
    )


WindowParams = Annotated[_ResolvedWindow, Depends(_window)]
TopLimit = Annotated[
    int,
    Query(ge=1, le=MAX_TOP_LIMIT, description="Rows in the ranking (§3.7)."),
]


@router.get(
    "/analytics/summary",
    response_model=AnalyticsSummaryResponse,
    tags=["analytics"],
    summary="Today-at-a-glance block",
)
async def analytics_summary(request: Request, window: WindowParams) -> dict[str, Any]:
    """SPEC §59's block over the selected window — ``docs/API.md`` §3.7.

    ``busiest_hour`` has two sources by time range (``docs/DATA_MODEL.md``
    §6.5): a closed day's finalized value from ``daily_stats``, and the
    in-progress day's from slice 033's hourly receiver metrics. The response
    names which one answered, so a client is never left guessing whether the
    figure it is showing is final.
    """
    summary = await _context(request).analytics.summary(window.window)
    return {"window": window.block, "summary": analytics_summary_payload(summary)}


@router.get(
    "/analytics/daily",
    response_model=AnalyticsDailyResponse,
    tags=["analytics"],
    summary="Daily aircraft, sighting, new-aircraft and range counts",
)
async def analytics_daily(request: Request, window: WindowParams) -> dict[str, Any]:
    """Per-day counts, joined to slice 033's receiver activity — §3.7.

    One row per receiver-local day in the window, including days with no
    traffic: a zero is a measurement, and a series with holes in it would read
    as missing data rather than as a quiet Tuesday.
    """
    rows = await _context(request).analytics.daily(window.window)
    return {"window": window.block, "items": [analytics_daily_row_payload(row) for row in rows]}


@router.get(
    "/analytics/counts",
    response_model=AnalyticsCountsResponse,
    tags=["analytics"],
    summary="Sightings, distinct aircraft, distinct types and new aircraft in a window",
)
async def analytics_counts(request: Request, window: WindowParams) -> dict[str, Any]:
    """A window's four headline figures, counted live (slice 098).

    What the Sightings page heads its window with. Unlike `summary`, nothing
    here is read from a rollup, so the figures agree with the sightings log
    to the second.
    """
    counts = await _context(request).analytics.window_counts(window.window)
    return {"window": window.block, **analytics_counts_payload(counts)}


@router.get(
    "/analytics/aircraft",
    response_model=AnalyticsSeenAircraftResponse,
    tags=["analytics"],
    summary="Every distinct aircraft heard in a window",
)
async def analytics_seen_aircraft(
    request: Request,
    window: WindowParams,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Page size (§2.4).")
    ] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Rows to skip (§2.4).")] = 0,
    type_code: Annotated[
        str | None,
        Query(
            alias="type",
            pattern=r"^[A-Za-z0-9]{2,4}$",
            description="Restrict to one ICAO type designator.",
            examples=["B738"],
        ),
    ] = None,
) -> dict[str, Any]:
    """The window's distinct airframes, most-sighted first, paginated.

    `top-aircraft` without its ceiling (slice 098). Over `preset=t0` this is
    every discrete airframe the receiver has ever heard.
    """
    rows, total = await _context(request).analytics.aircraft_seen(
        window.window,
        limit=limit,
        offset=offset,
        type_code=None if type_code is None else type_code.upper(),
    )
    return {
        "window": window.block,
        "items": [analytics_seen_aircraft_payload(row, window.window) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/analytics/types",
    response_model=AnalyticsSeenTypesResponse,
    tags=["analytics"],
    summary="Every distinct aircraft type heard in a window",
)
async def analytics_seen_types(
    request: Request,
    window: WindowParams,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Page size (§2.4).")
    ] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Rows to skip (§2.4).")] = 0,
) -> dict[str, Any]:
    """The window's distinct ICAO type designators, busiest first, paginated.

    Over `preset=t0` this is every discrete type the receiver has ever heard
    (slice 098). An airframe no registry gives a type belongs to no row.
    """
    rows, total = await _context(request).analytics.types_seen(
        window.window, limit=limit, offset=offset
    )
    return {
        "window": window.block,
        "items": [analytics_seen_type_payload(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/analytics/hourly",
    response_model=AnalyticsHourlyResponse,
    tags=["analytics"],
    summary="One receiver-local day, hour by hour",
)
async def analytics_hourly(
    request: Request,
    day: Annotated[
        date | None,
        Query(
            description=(
                "Receiver-local calendar date, `YYYY-MM-DD`. Defaults to today "
                "in the receiver's timezone."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Sightings, aircraft heard, messages, positions and max range per hour.

    The day-granular analytics series have one point to draw when the window is
    a single day; this is that day at hourly resolution (slice 097). Every
    bucket of the day is returned — the ones that have not begun with `null`
    counts — so a client can lay out the whole day and fill it as it happens.
    """
    context = _context(request)
    now_ms = utc_now_ms()
    queries = context.analytics
    local = analytics_local_day(now_ms, ZoneInfo(context.settings.timezone))
    resolved = local if day is None else day.isoformat()
    rows = await queries.hourly(resolved, now_ms=now_ms)
    return {
        "day": resolved,
        "timezone": context.settings.timezone,
        "items": [analytics_hourly_row_payload(row) for row in rows],
    }


@router.get(
    "/analytics/classification-activity",
    response_model=AnalyticsClassificationResponse,
    tags=["analytics"],
    summary="Military / government / police activity over time",
)
async def analytics_classification_activity(
    request: Request, window: WindowParams
) -> dict[str, Any]:
    """SPEC §58's mil/gov/police view — totals plus the per-day series."""
    activity = await _context(request).analytics.classification_activity(window.window)
    return {
        "window": window.block,
        "complete": activity.complete,
        "military": activity.military,
        "government": activity.government,
        "law_enforcement": activity.law_enforcement,
        "interesting": activity.interesting,
        "series": [analytics_daily_row_payload(row) for row in activity.series],
    }


@router.get(
    "/analytics/top-aircraft",
    response_model=AnalyticsAircraftResponse,
    tags=["analytics"],
    summary="Most frequently seen aircraft",
)
async def analytics_top_aircraft(
    request: Request, window: WindowParams, limit: TopLimit = DEFAULT_TOP_LIMIT
) -> dict[str, Any]:
    """The window's most frequently seen airframes, with first/last seen — §3.7.

    ``sightings`` counts the window; ``first_seen_at``/``last_seen_at`` are the
    airframe's lifetime records (SPEC §53), which is what makes this list
    answer SPEC §58's "first-seen/last-seen information" as well as its
    ranking.
    """
    rows = await _context(request).analytics.top_aircraft(window.window, limit=limit)
    return {"window": window.block, "items": [analytics_aircraft_payload(row) for row in rows]}


@router.get(
    "/analytics/top-types",
    response_model=AnalyticsGroupResponse,
    tags=["analytics"],
    summary="Most frequently seen types and models",
)
async def analytics_top_types(
    request: Request, window: WindowParams, limit: TopLimit = DEFAULT_TOP_LIMIT
) -> dict[str, Any]:
    """The window's most frequent ICAO type designators — §3.7."""
    rows = await _context(request).analytics.top_types(window.window, limit=limit)
    return {"window": window.block, "items": [analytics_group_payload(row) for row in rows]}


@router.get(
    "/analytics/top-operators",
    response_model=AnalyticsGroupResponse,
    tags=["analytics"],
    summary="Most common operators",
)
async def analytics_top_operators(
    request: Request, window: WindowParams, limit: TopLimit = DEFAULT_TOP_LIMIT
) -> dict[str, Any]:
    """The window's most common curated operator groups — §3.7.

    Keyed by the *group* rather than by the exact operator string: SPEC §38
    keeps the exact string on the aircraft and the grouping beside it, and
    "most common operators" is a question about the group.
    """
    rows = await _context(request).analytics.top_operators(window.window, limit=limit)
    return {"window": window.block, "items": [analytics_group_payload(row) for row in rows]}


@router.get(
    "/analytics/rarity",
    response_model=AnalyticsRarityResponse,
    tags=["analytics"],
    summary="Never-seen-before counts and locally rare aircraft and types",
)
async def analytics_rarity(
    request: Request,
    window: WindowParams,
    limit: TopLimit = DEFAULT_TOP_LIMIT,
    max_sightings: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_TOP_LIMIT,
            description="Lifetime sightings at or below which an airframe reads as rare.",
        ),
    ] = DEFAULT_RARE_MAX_SIGHTINGS,
) -> dict[str, Any]:
    """Never-seen-before counts and the locally rare lists — §3.7, SPEC §44.

    Rare is **receiver-relative and since T0**: "how unusual is this here",
    read from the airframe's own lifetime sighting count and from
    ``type_stats``, never from a global fleet census. Both lists are restricted
    to what the window actually contained, so they describe observations rather
    than a catalogue.
    """
    rarity = await _context(request).analytics.rarity(
        window.window, limit=limit, max_sightings=max_sightings
    )
    return {
        "window": window.block,
        "never_seen_before": rarity.never_seen_before,
        "rare_max_sightings": rarity.rare_max_sightings,
        "rare_max_type_aircraft": rarity.rare_max_type_aircraft,
        "rare_aircraft": [analytics_aircraft_payload(row) for row in rarity.rare_aircraft],
        "rare_types": [analytics_rare_type_payload(row) for row in rarity.rare_types],
    }


def _feeders(request: Request) -> FeederService | None:
    """The feeder service, or ``None`` on an app built without one."""
    service: FeederService | None = getattr(request.app.state, "feeders", None)
    return service


@router.get(
    "/feeders",
    response_model=FeedersResponse,
    tags=["feeders"],
    summary="Status of every network the receiver feeds",
)
async def feeders(request: Request) -> dict[str, Any]:
    """Every configured feeder's committed state — §3.12 (slice 077).

    Read from the feeder service's memory, never from the database: the
    answer is what the last poll found, and costs nothing to serve every ten
    seconds. An install with no feeders configured answers with an empty
    ``feeders`` list, not a 404. No stats URL, feeder key, alias or receiver
    coordinate is ever part of this payload — ``stats_link`` is a boolean,
    and the link itself is only reachable through the internal redirect.
    """
    service = _feeders(request)
    if service is None:
        return empty_report(utc_now_ms())
    # The live section, so a save is reflected on the next read.
    live = getattr(getattr(request.app.state, "settings", None), "feeders", None)
    return service.report(
        stats_urls=getattr(live, "stats_urls", None),
        local_pages=getattr(live, "local_pages", None),
    )


@router.get(
    "/feeders/{name}/history",
    response_model=FeederHistoryResponse,
    tags=["feeders"],
    summary="One feeder's episodes, samples and availability over a window",
    responses={404: {"description": "No feeder with this name is configured."}},
)
async def feeder_history(
    request: Request,
    name: Annotated[str, Path(description="The feeder's configured name.")],
    window: Annotated[
        str,
        Query(
            description="How far back to look: `24h`, `7d` or `30d`.",
            json_schema_extra={"enum": list(get_args(FeederHistoryWindowLiteral))},
        ),
    ] = "24h",
) -> dict[str, Any] | Response:
    """Episodes, bucketed samples and availability for one feeder — §3.12.

    Both failures answer in the §2.5 error envelope: ``422 invalid_window``
    for a window outside the three, checked here rather than by parameter
    validation so the body has the envelope's shape, and ``404 not_found``
    for a name that is not configured.
    """
    if window not in get_args(FeederHistoryWindowLiteral):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "invalid_window",
                    "message": "window must be one of 24h, 7d, 30d",
                    "detail": None,
                }
            },
        )
    service = _feeders(request)
    history = None if service is None else await service.history(name, window)
    if history is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "not_found",
                    "message": f"No feeder named {name}",
                    "detail": None,
                }
            },
        )
    return history
