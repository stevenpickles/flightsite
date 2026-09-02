"""Typed response models for the published ``/api/v1`` OpenAPI schema.

``docs/API.md`` §2.10 puts an OpenAPI document at ``/api/v1/openapi.json``, and
a schema is only worth serving if it is accurate. These models are therefore
not decoration: every REST endpoint in this slice declares one as its
``response_model``, so FastAPI validates the dict
:mod:`flightsite.api.serializers` produced against the shape it just published.
A serializer that drifted from the documented shape fails the request instead
of quietly serving something the schema denies.

The WebSocket endpoint has no entry here because OpenAPI 3.1 does not describe
WebSockets; its protocol is documented in :mod:`flightsite.api.ws`, and the
aircraft objects it carries are exactly :class:`AircraftView` — the same
serializer builds both.

Every field is optional-by-value rather than optional-by-absence: §2.7 makes
``null`` the representation of unknown, and §6 lets v1 add fields but not
remove them, so a client can rely on the key set being stable.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: ``docs/API.md`` §2.8 / SPEC §21. ``none`` means tracked without a valid
#: position (Mode S only), which is a first-class live entry, not an error.
PositionSourceLiteral = Literal["adsb", "mlat", "none", "other"]

#: §2.2: UTC ISO-8601 with a ``Z`` suffix and millisecond precision.
IsoTimestamp = Annotated[str, Field(examples=["2026-08-31T14:03:22.418Z"])]


class _Model(BaseModel):
    """Base for the response models: no extra keys, no silent coercion."""

    model_config = ConfigDict(extra="forbid")


class GeoPosition(_Model):
    """A WGS-84 surface position in decimal degrees."""

    lat: float
    lon: float


class Classification(_Model):
    """Military / government / law-enforcement classification (slice 024).

    Modelled now because it is part of the §3.3 object a client codes against;
    live payloads carry ``null`` until the classification engine lands.
    """

    military: bool
    government: bool
    law_enforcement: bool
    mission: str | None = None
    icon_category: str | None = None
    confidence: str | None = None


class RouteView(_Model):
    """Origin and destination of the flight — ``docs/API.md`` §2.6.

    Externally reported only (slice 026), and attributed in ``provenance``
    under the key ``route``. Local arrival/departure inference (slice 027) is
    deliberately a different field: SPEC §41 keeps what somebody told
    FlightSite structurally apart from what FlightSite guessed.

    Both keys are always present; either may be ``null`` on its own — a
    provider that named one airport and not the other is reporting half a
    route, which is information, not an error.
    """

    origin: str | None = None
    destination: str | None = None


class NearestAirportView(_Model):
    """Locally inferred airport context — ``docs/API.md`` §3.3, SPEC §41.

    Nullable **as a whole**, unlike :class:`RouteView`. A route is a thing every
    flight has whether or not FlightSite knows it, so an object of nulls is the
    honest shape; a nearest airport is something most aircraft genuinely do not
    have, and an object of nulls there would imply the question was asked and
    came back empty.

    Everything here is attributed ``heuristic`` in ``provenance`` under the key
    ``nearest_airport``, and it is deliberately a different field from
    :class:`RouteView`: SPEC §41 requires arrival/departure status to be clearly
    labeled as inferred, and keeping what FlightSite guessed structurally apart
    from what somebody told it is how that survives any later rendering.

    ``phase`` is ``null`` far more often than not — an aircraft can be
    confidently four miles from a field with its intentions unreadable, which is
    exactly what an aircraft on the ground is.
    """

    ident: str
    name: str
    #: Great-circle range from the aircraft to the field, nautical miles.
    distance_nm: float
    #: ``docs/DATA_MODEL.md`` §2.3's ``inferred_phase`` vocabulary. The UI
    #: renders these as *likely arriving* / *likely departing*; the hedging is
    #: display, the value is the enum.
    phase: Literal["arriving", "departing"] | None = None


class InterestingMatch(_Model):
    """An active alert match (slice 038); ``null`` when nothing matches."""

    severity: Literal["info", "interesting", "high", "critical"]
    reasons: list[str] = Field(default_factory=list)


class AircraftView(_Model):
    """One live aircraft — ``docs/API.md`` §3.3.

    The same object appears in ``GET /api/v1/aircraft/current`` and in every
    WebSocket ``snapshot`` and ``delta`` frame.
    """

    icao: Annotated[str, Field(pattern=r"^[0-9a-f]{6}$", examples=["ae1463"])]
    callsign: str | None = None
    registration: str | None = None

    position: GeoPosition | None = None
    position_source: PositionSourceLiteral = "none"
    altitude_ft: float | None = None
    ground_speed_kt: float | None = None
    track_deg: float | None = None
    vertical_rate_fpm: float | None = None
    squawk: str | None = None
    emergency: Literal["7500", "7600", "7700"] | None = None
    on_ground: bool | None = None

    distance_nm: float | None = None
    bearing_deg: float | None = None
    rssi_db: float | None = None
    message_count: int | None = None
    seen_s: float | None = None
    seen_pos_s: float | None = None

    last_seen: IsoTimestamp
    state: Literal["live", "stale"]
    sighting_id: int | None = None

    aircraft_type: str | None = None
    model: str | None = None
    operator: str | None = None
    operator_group: str | None = None
    classification: Classification | None = None
    #: Never ``null`` as a whole — see :class:`RouteView`.
    route: RouteView = Field(default_factory=RouteView)
    #: ``null`` whenever there is nothing to say — see
    #: :class:`NearestAirportView`.
    nearest_airport: NearestAirportView | None = None
    interesting: InterestingMatch | None = None
    #: Watchlist names this aircraft currently matches (SPEC §42, slice 037).
    #: Always present; ``[]`` when nothing matches — never a missing key.
    watchlists: list[str] = Field(default_factory=list)

    #: §2.6. Keys name fields; values are the canonical provenance vocabulary.
    #: A field with no entry is decoder-direct.
    provenance: dict[str, str] = Field(default_factory=dict)


class CurrentAircraftResponse(_Model):
    """The full live picture — positioned and non-positioned (SPEC §20).

    ``items``/``total`` is the §2.4 list envelope. ``limit`` and ``offset`` are
    absent on purpose: this endpoint is not paginated (a truncated live picture
    would be a wrong one), so a page window would be a field that never means
    anything. ``total`` is the exact size of the returned set.
    """

    items: list[AircraftView] = Field(default_factory=list)
    total: int


#: §3.5's documented sort keys for ``GET /api/v1/aircraft``.
AircraftSortKey = Literal[
    "registration",
    "icao",
    "type",
    "operator",
    "classification",
    "first_seen",
    "last_seen",
    "sighting_count",
    "closest_approach_nm",
    "max_range_nm",
]

#: §2.4's sort direction.
SortOrder = Literal["asc", "desc"]


class LifetimeRecord(_Model):
    """Receiver-relative lifetime records — SPEC §53, ``docs/API.md`` §3.5."""

    first_seen: IsoTimestamp
    last_seen: IsoTimestamp
    sighting_count: int
    cumulative_duration_s: int
    closest_approach_nm: float | None = None
    max_range_nm: float | None = None
    lowest_altitude_ft: int | None = None
    highest_altitude_ft: int | None = None


class AircraftHistoryRow(_Model):
    """One row of the Aircraft page — ``docs/API.md`` §3.5, SPEC §56.

    Field names mirror :class:`AircraftView` where the same fact appears, so
    a live aircraft and a historical row render through the same frontend
    field components.
    """

    icao: Annotated[str, Field(pattern=r"^[0-9a-f]{6}$", examples=["ae1463"])]
    registration: str | None = None
    aircraft_type: str | None = None
    model: str | None = None
    operator: str | None = None
    operator_group: str | None = None
    classification: Classification | None = None
    first_seen: IsoTimestamp
    last_seen: IsoTimestamp
    sighting_count: int
    closest_approach_nm: float | None = None
    max_range_nm: float | None = None

    #: §2.6. See :class:`AircraftView`'s field of the same name.
    provenance: dict[str, str] = Field(default_factory=dict)


class AircraftHistoryListResponse(_Model):
    """``GET /api/v1/aircraft`` — the §2.4 paginated list envelope."""

    items: list[AircraftHistoryRow] = Field(default_factory=list)
    #: Exact count of matching rows. See :mod:`flightsite.api.history` for
    #: why this endpoint computes it rather than exercising §2.4's
    #: allowance to omit or approximate it.
    total: int | None = None
    limit: int
    offset: int


class AircraftDetail(_Model):
    """``GET /api/v1/aircraft/{icao}`` — ``docs/API.md`` §3.5.

    Identity, metadata with provenance, classification and the SPEC §53
    lifetime block for one airframe, whether or not it is currently live.
    """

    icao: Annotated[str, Field(pattern=r"^[0-9a-f]{6}$", examples=["ae1463"])]
    registration: str | None = None
    aircraft_type: str | None = None
    model: str | None = None
    manufacture_year: int | None = None
    operator: str | None = None
    operator_group: str | None = None
    owner: str | None = None
    classification: Classification | None = None
    #: True when this airframe is in the live picture right now — the
    #: frontend's cue to offer a jump to its Live Map selection.
    live: bool
    lifetime: LifetimeRecord

    #: §2.6. See :class:`AircraftView`'s field of the same name.
    provenance: dict[str, str] = Field(default_factory=dict)


#: ``docs/API.md`` §3.6's documented sort keys for ``GET /api/v1/sightings``.
SightingSortKey = Literal["started_at", "duration_s", "closest_approach_nm", "max_range_nm"]

#: §2.8's ``closure_reason`` vocabulary.
ClosureReasonLiteral = Literal["gap_timeout", "shutdown_recovery", "data_reset"]

#: §2.8's alert severity ladder — carried by ``max_alert_severity`` ahead of
#: slice 038, which is the first to ever write a non-``null`` value.
AlertSeverityLiteral = Literal["info", "interesting", "high", "critical"]

#: ``docs/DATA_MODEL.md`` §2.5's ``sighting_events.type`` vocabulary.
SightingEventTypeLiteral = Literal[
    "callsign_change",
    "squawk_change",
    "emergency_start",
    "emergency_end",
    "route_enriched",
    "classification_available",
    "alert_matched",
    "alert_severity_upgraded",
]


class SightingRow(_Model):
    """One row of the Sightings page — ``docs/API.md`` §3.6, SPEC §57.

    Field names mirror :class:`AircraftHistoryRow` where the same fact
    appears, for the same reason: one set of frontend field components
    renders both a historical aircraft row and a sighting row.
    """

    id: int
    icao: Annotated[str, Field(pattern=r"^[0-9a-f]{6}$", examples=["ae1463"])]
    callsign: str | None = None
    registration: str | None = None
    aircraft_type: str | None = None
    model: str | None = None
    operator: str | None = None
    operator_group: str | None = None
    classification: Classification | None = None
    started_at: IsoTimestamp
    #: ``null`` while the sighting is open (§3.6).
    ended_at: IsoTimestamp | None = None
    #: ``null`` while the sighting is open — duration is only meaningful once
    #: it has actually ended.
    duration_s: int | None = None
    closure_reason: ClosureReasonLiteral | None = None
    closest_approach_nm: float | None = None
    max_range_nm: float | None = None
    lowest_altitude_ft: int | None = None
    highest_altitude_ft: int | None = None
    position_count: int
    had_emergency: bool
    max_alert_severity: AlertSeverityLiteral | None = None

    #: §2.6. See :class:`AircraftView`'s field of the same name.
    provenance: dict[str, str] = Field(default_factory=dict)


class SightingListResponse(_Model):
    """``GET /api/v1/sightings`` and ``GET /api/v1/aircraft/{icao}/sightings``
    — the §2.4 paginated list envelope.
    """

    items: list[SightingRow] = Field(default_factory=list)
    #: Always ``null``: §2.4 names ``/sightings`` the canonical case for
    #: omitting an exact filtered count at multi-year scale. See
    #: :mod:`flightsite.api.sightings` for why this endpoint never computes
    #: it, unlike ``/aircraft``.
    total: int | None = None
    limit: int
    offset: int


class ReceptionStats(_Model):
    """Reception statistics for one sighting — ``docs/API.md`` §3.6, SPEC §51."""

    rssi_peak_db: float | None = None
    rssi_avg_db: float | None = None
    rssi_min_db: float | None = None
    message_count: int
    position_count: int
    #: Percentage of the sighting spent with a valid position.
    pct_with_position: float | None = None


class SightingRecords(_Model):
    """Per-sighting extremes — ``docs/API.md`` §3.6."""

    closest_approach_nm: float | None = None
    max_range_nm: float | None = None
    lowest_altitude_ft: int | None = None
    highest_altitude_ft: int | None = None


class SightingEventView(_Model):
    """One entry of a sighting's event timeline — SPEC §52."""

    at: IsoTimestamp
    type: SightingEventTypeLiteral
    detail: dict[str, str | None] | None = None


class SightingPathPoint(_Model):
    """One point of a sighting's simplified path — SPEC §19."""

    t: IsoTimestamp
    lat: float
    lon: float
    altitude_ft: int | None = None
    source: PositionSourceLiteral


class SightingDetail(_Model):
    """``GET /api/v1/sightings/{id}`` — ``docs/API.md`` §3.6.

    Flight context, reception stats, per-sighting records, the event
    timeline and the simplified path. ``path`` is the Douglas-Peucker
    simplified, timestamp-ordered track for a closed sighting; an open
    sighting (``ended_at: null``) reports its checkpointed track so far
    instead (see :mod:`flightsite.api.sightings`).
    """

    id: int
    icao: Annotated[str, Field(pattern=r"^[0-9a-f]{6}$", examples=["ae1463"])]
    callsign: str | None = None
    squawk: str | None = None
    started_at: IsoTimestamp
    ended_at: IsoTimestamp | None = None
    duration_s: int | None = None
    closure_reason: ClosureReasonLiteral | None = None
    #: Never ``null`` as a whole — see :class:`RouteView`.
    route: RouteView = Field(default_factory=RouteView)
    reception: ReceptionStats
    records: SightingRecords
    events: list[SightingEventView] = Field(default_factory=list)
    path: list[SightingPathPoint] = Field(default_factory=list)

    #: §2.6. See :class:`AircraftView`'s field of the same name.
    provenance: dict[str, str] = Field(default_factory=dict)


class ReceiverInfo(_Model):
    """Non-secret receiver identity and configuration — ``docs/API.md`` §3.2."""

    site_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    antenna_height_ft: float | None = None
    timezone: str
    units: Literal["aviation", "metric"]
    display_radius_nm: float
    alert_radius_nm: float | None = None
    demo_mode: bool
    #: SPEC §16: when FlightSite first persisted an observation. ``null`` on an
    #: install that has not seen an aircraft yet.
    t0: IsoTimestamp | None = None


#: ``docs/API.md`` §3.8's receiver-health summary. Deliberately coarse — full
#: diagnostics (decoder connection detail, error ring buffers) is slice 042's
#: scope, out of this slice's per the roadmap; this is only what the SPEC §61
#: scorecard needs to render one health cue.
ReceiverHealthLiteral = Literal["ok", "no_stats", "unknown", "demo"]


class ReceiverScorecard(_Model):
    """``GET /api/v1/receiver/scorecard`` — SPEC §61."""

    current_visible: int
    current_positioned: int
    #: The most recent raw sample's own rate — not a windowed average.
    messages_per_sec: float | None = None
    positions_per_sec: float | None = None
    max_range_today_nm: float | None = None
    max_range_ever_nm: float | None = None
    unique_aircraft_today: int
    unique_aircraft_since_t0: int
    #: The decoder's own reported uptime, ``null`` when it reports no
    #: statistics (SPEC §60).
    decoder_uptime_s: float | None = None
    flightsite_uptime_s: float
    health: ReceiverHealthLiteral


#: SPEC §62 v1 chart catalog for ``GET /api/v1/receiver/metrics``, minus the
#: two endpoints with their own shape (range-by-bearing, signal-distribution).
ReceiverSeriesMetric = Literal[
    "messages_per_sec",
    "positions_per_sec",
    "aircraft_count",
    "max_range_nm",
    "messages_total",
    "positions_total",
    "unique_aircraft",
]

#: ``docs/DATA_MODEL.md`` §6's three storage tiers (ADR-0009).
ReceiverSeriesResolution = Literal["high", "hourly", "daily"]


class ReceiverSeriesPoint(_Model):
    """One point of a receiver time-series chart."""

    t: IsoTimestamp
    value: float | None = None


class ReceiverMetricSeries(_Model):
    """``GET /api/v1/receiver/metrics`` — one SPEC §62 chart's data."""

    metric: ReceiverSeriesMetric
    #: The resolution actually used — always ``"daily"`` for
    #: ``metric="unique_aircraft"`` regardless of what was requested.
    resolution: ReceiverSeriesResolution
    points: list[ReceiverSeriesPoint] = Field(default_factory=list)


class ReceiverBearingSector(_Model):
    """One 5° sector of the range-by-bearing polar plot (§6.3)."""

    #: The sector's midpoint, degrees true — ``0`` is North, increasing
    #: clockwise, matching ``docs/DATA_MODEL.md`` §6.3's bucket convention.
    bearing_deg: float
    max_range_nm: float | None = None
    at: IsoTimestamp | None = None
    icao: str | None = None


class ReceiverRangeByBearing(_Model):
    """``GET /api/v1/receiver/range-by-bearing`` — SPEC §62's polar plot.

    Always 72 sectors in each of ``today`` and ``ever``, in bucket order —
    :data:`~flightsite.receiver_metrics.model.BEARING_BUCKETS` many, covering
    the full compass regardless of how much of it the receiver has actually
    heard from.
    """

    sector_width_deg: float
    today: list[ReceiverBearingSector]
    ever: list[ReceiverBearingSector]


class ReceiverSignalBucket(_Model):
    """One bar of the signal-strength distribution."""

    min_db: float
    max_db: float
    count: int


class ReceiverSignalDistribution(_Model):
    """``GET /api/v1/receiver/signal-distribution`` — SPEC §62.

    Built from per-sighting ``rssi_avg_db`` (slice 052), not raw receiver
    metric samples — see ``flightsite.receiver_metrics``'s module docstring.
    """

    #: The requested window bounds, echoed back; ``null`` means unbounded on
    #: that side (§2.7) — the default when a client omits ``from``/``to``.
    from_ts: IsoTimestamp | None = None
    to_ts: IsoTimestamp | None = None
    bucket_width_db: float
    buckets: list[ReceiverSignalBucket] = Field(default_factory=list)
    sample_count: int
    min_db: float | None = None
    max_db: float | None = None
    avg_db: float | None = None


class ReceiverMaxRangeRecord(_Model):
    """The furthest detection ever — one entry of SPEC §63's lifetime block."""

    nm: float
    at: IsoTimestamp
    bearing_deg: float
    icao: str | None = None


class ReceiverBusiestDay(_Model):
    """The receiver-local day with the greatest message total — SPEC §63."""

    day: str
    message_count: int


class ReceiverFrequentAircraft(_Model):
    """The most-sighted airframe — one entry of SPEC §63's lifetime block."""

    icao: Annotated[str, Field(pattern=r"^[0-9a-f]{6}$", examples=["ae1463"])]
    registration: str | None = None
    sighting_count: int


class ReceiverCommonRecord(_Model):
    """One "most common X" record — SPEC §63's type/model/operator entries."""

    value: str
    aircraft_count: int


class ReceiverLifetimeStats(_Model):
    """``GET /api/v1/receiver/lifetime`` — SPEC §63, since T0 where possible."""

    #: T0 (SPEC §16); ``null`` on an install that has never persisted an
    #: observation.
    since: IsoTimestamp | None = None
    unique_aircraft: int
    total_sightings: int
    total_positions: int | None = None
    total_messages: int | None = None
    max_range: ReceiverMaxRangeRecord | None = None
    peak_message_rate_per_sec: float | None = None
    peak_position_rate_per_sec: float | None = None
    max_simultaneous_aircraft: int | None = None
    busiest_day: ReceiverBusiestDay | None = None
    most_frequent_aircraft: ReceiverFrequentAircraft | None = None
    common_type: ReceiverCommonRecord | None = None
    common_model: ReceiverCommonRecord | None = None
    common_operator: ReceiverCommonRecord | None = None


#: The overlay's size-class vocabulary — mirrors
#: :data:`flightsite.airports.overlay.AirportSizeClass` exactly; duplicated
#: rather than imported so this module (the published-schema boundary) never
#: has to import the query layer to describe its own response shape.
AirportSizeClassLiteral = Literal["large", "medium", "small", "heliport"]


class AirportPointGeometry(_Model):
    """A GeoJSON ``Point`` geometry: ``[lon, lat]`` in that order (RFC 7946)."""

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]


class AirportProperties(_Model):
    """One airport marker's properties — ``GET /api/v1/airports`` (slice 028)."""

    ident: str
    name: str
    size_class: AirportSizeClassLiteral
    iata: str | None = None
    elevation_ft: int | None = None


class AirportFeature(_Model):
    """One airport as a GeoJSON ``Feature`` with a ``Point`` geometry."""

    type: Literal["Feature"] = "Feature"
    geometry: AirportPointGeometry
    properties: AirportProperties


class AirportFeatureCollection(_Model):
    """``GET /api/v1/airports`` — airport markers for the map overlay (slice 028).

    A plain GeoJSON ``FeatureCollection`` rather than the §2.4 ``items``/
    ``total`` envelope: the response is meant to be handed to a map layer as-is,
    and every other overlay this codebase serves (range rings, receiver marker)
    is GeoJSON the frontend consumes the same way.
    """

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[AirportFeature] = Field(default_factory=list)


class AirspaceFeatureCollection(_Model):
    """``GET /api/v1/airspace`` — the user-supplied airspace overlay (slice 028,
    ``docs/adr/0012-airspace-data-source.md``).

    ``features`` stays loosely typed (plain dicts) rather than a modeled
    ``AirspaceFeature``: FlightSite ships no default airspace data, so the only
    content ever behind this key is whatever GeoJSON a user supplied — geometry
    type and property keys (a ``class`` the frontend styles by, if present, or
    none) are entirely theirs to define.
    :func:`flightsite.airspace.loader.load_airspace` is what constrains the
    *shape* (a validated ``FeatureCollection``, never a half-parsed file); this
    model does not re-impose structure the loader deliberately left open.
    """

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------- analytics


#: ``docs/API.md`` §3.7's time presets, spelled as the query values.
AnalyticsPresetLiteral = Literal["today", "7d", "30d", "ytd", "t0"]


class AnalyticsWindow(_Model):
    """The window an analytics response was actually computed over.

    Returned on every §3.7 payload rather than left implicit, because a preset
    resolves against the *receiver's* local calendar and its own clock: a
    client that assumed UTC midnights, or that resolved "today" from a browser
    in another zone, would mislabel every chart. ``first_day``/``last_day`` are
    the receiver-local dates the rollup rows were read for.
    """

    preset: AnalyticsPresetLiteral | None = None
    from_: IsoTimestamp = Field(alias="from")
    to: IsoTimestamp
    first_day: str
    last_day: str
    timezone: str

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AnalyticsDailyRow(_Model):
    """One receiver-local day of the §3.7 ``daily`` series.

    ``busiest_hour`` is ``null`` for the day still in progress: it is
    ``docs/DATA_MODEL.md`` §6.5's finalized closed-day value, and the
    in-progress day's is served on the summary block from slice 033's hourly
    metrics instead.

    The ``receiver_*`` fields are slice 033's activity for the same day (SPEC
    §58's "receiver activity over time"), ``null`` where that slice recorded
    none.
    """

    day: str
    unique_aircraft: int
    new_aircraft: int
    sightings: int
    interesting: int
    military: int
    government: int
    law_enforcement: int
    max_range_nm: float | None = None
    busiest_hour: int | None = None
    receiver_messages: int | None = None
    receiver_positions: int | None = None
    receiver_aircraft_max: int | None = None
    receiver_max_range_nm: float | None = None


class AnalyticsDailyResponse(_Model):
    """``GET /api/v1/analytics/daily``."""

    window: AnalyticsWindow
    items: list[AnalyticsDailyRow] = Field(default_factory=list)


class AnalyticsSummary(_Model):
    """SPEC §59's at-a-glance block over the selected window."""

    unique_aircraft: int
    new_aircraft: int
    sightings: int
    interesting: int
    military: int
    government: int
    law_enforcement: int
    max_range_nm: float | None = None
    busiest_hour: int | None = None
    #: ``daily_stats`` (a closed day) or ``receiver_metrics_hourly`` (the day
    #: in progress) — ``docs/DATA_MODEL.md`` §6.5's dual source, named so a
    #: client can say where the figure came from.
    busiest_hour_source: str | None = None
    first_sighting_at: IsoTimestamp | None = None
    last_sighting_at: IsoTimestamp | None = None
    #: SPEC §59's "new milestones/records" — activity-feed milestone and
    #: record events (``first_ever_aircraft``, ``new_type``, ``range_record``,
    #: ``receiver_record``, ``milestone``) whose moment falls inside the
    #: window.
    new_milestones: int


class AnalyticsSummaryResponse(_Model):
    """``GET /api/v1/analytics/summary``."""

    window: AnalyticsWindow
    summary: AnalyticsSummary


class AnalyticsAircraftRow(_Model):
    """One airframe in a §3.7 ranking or rarity list."""

    icao: str
    registration: str | None = None
    type: str | None = None
    model: str | None = None
    operator: str | None = None
    operator_group: str | None = None
    classification: str | None = None
    military: bool = False
    government: bool = False
    law_enforcement: bool = False
    #: Sightings inside the window; the lifetime total for a since-T0 window.
    sightings: int
    first_seen_at: IsoTimestamp
    last_seen_at: IsoTimestamp
    max_range_nm: float | None = None


class AnalyticsAircraftResponse(_Model):
    """``GET /api/v1/analytics/top-aircraft``."""

    window: AnalyticsWindow
    items: list[AnalyticsAircraftRow] = Field(default_factory=list)


class AnalyticsGroupRow(_Model):
    """One type designator or operator group in a §3.7 ranking.

    ``key`` is the stable identifier a client filters by (the ICAO type
    designator, or the operator group id as a string); ``label`` is what to
    display. ``days_seen`` is how many days of the window the group appeared
    on, and is ``0`` for a since-T0 type ranking, which is read from the
    ``type_stats`` totals rather than from daily rows.
    """

    key: str
    label: str | None = None
    sightings: int
    unique_aircraft: int
    days_seen: int
    first_seen_at: IsoTimestamp | None = None
    last_seen_at: IsoTimestamp | None = None


class AnalyticsGroupResponse(_Model):
    """``GET /api/v1/analytics/top-types`` and ``/top-operators``."""

    window: AnalyticsWindow
    items: list[AnalyticsGroupRow] = Field(default_factory=list)


class AnalyticsClassificationResponse(_Model):
    """``GET /api/v1/analytics/classification-activity``."""

    window: AnalyticsWindow
    military: int
    government: int
    law_enforcement: int
    interesting: int
    series: list[AnalyticsDailyRow] = Field(default_factory=list)


class AnalyticsRareType(_Model):
    """One locally rare type designator (receiver-relative, since T0)."""

    type: str
    unique_aircraft: int
    total_sightings: int
    first_seen_at: IsoTimestamp
    last_seen_at: IsoTimestamp


class AnalyticsRarityResponse(_Model):
    """``GET /api/v1/analytics/rarity``."""

    window: AnalyticsWindow
    #: Airframes whose first-ever observation fell inside the window.
    never_seen_before: int
    rare_max_sightings: int
    rare_max_type_aircraft: int
    rare_aircraft: list[AnalyticsAircraftRow] = Field(default_factory=list)
    rare_types: list[AnalyticsRareType] = Field(default_factory=list)


# ---------------------------------------------------------------- activity


#: ``docs/API.md`` §3.9 / SPEC §55's event vocabulary, spelled as the query and
#: response values. Deliberately a ``Literal`` on the API surface even though
#: ``activity_events.type`` carries no ``CHECK``: the column stays open so a
#: later slice can add a producer without a migration, while the *published*
#: schema names exactly what a client may receive today. Phase 6's
#: ``alert_triggered`` and ``emergency_squawk`` appear because §3.9 lists them;
#: no producer emits either until slice 039.
ActivityEventTypeLiteral = Literal[
    "alert_triggered",
    "first_ever_aircraft",
    "new_type",
    "range_record",
    "receiver_record",
    "emergency_squawk",
    "receiver_offline",
    "receiver_restored",
    "metadata_updated",
    "milestone",
]


class ActivityEventView(_Model):
    """One activity event — ``docs/API.md`` §3.9, and §4.4's frame body.

    One shape over REST and over the WebSocket, built by one serializer, for
    the same reason :class:`AircraftView` is: the feed's first page and the
    live events appended to it must be one kind of object, or the client ends
    up with two renderers that drift.

    ``payload`` is deliberately open. Each event type carries the facts needed
    to render *that* type — an airframe's identity, a record's value and the
    value it beat, an import's per-source outcome — and modelling ten variants
    as a discriminated union would publish a schema that has to change every
    time a producer learns to say something more. What is guaranteed is the
    envelope: every event has a ``type``, and the ``type`` says how to read the
    ``payload``.
    """

    id: int
    type: ActivityEventTypeLiteral
    severity: AlertSeverityLiteral
    at: IsoTimestamp
    #: The airframe this event is about, or ``null`` for a receiver-wide one.
    icao: Annotated[str, Field(pattern=r"^[0-9a-f]{6}$", examples=["ae1463"])] | None = None
    #: The sighting this event happened during, where there is one — the link a
    #: feed row opens.
    sighting_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ActivityListResponse(_Model):
    """``GET /api/v1/activity`` — the §2.4 paginated list envelope."""

    items: list[ActivityEventView] = Field(default_factory=list)
    #: Always ``null``. Like ``/sightings`` this list grows without bound over a
    #: multi-year install (``docs/DATA_MODEL.md`` §11 retains activity events
    #: indefinitely), so §2.4's allowance to omit an exact filtered count
    #: applies: a client pages until a page comes back short of ``limit``.
    total: int | None = None
    limit: int
    offset: int


class InterestingAircraftResponse(_Model):
    """``GET /api/v1/aircraft/interesting`` — ``docs/API.md`` §3.4.

    The same aircraft object as §3.3, with ``interesting`` guaranteed non-null,
    ordered severity then distance. Not paginated, for the reason
    ``/aircraft/current`` is not: this is a view of the live picture, and a
    truncated one would be a wrong one.
    """

    items: list[AircraftView] = Field(default_factory=list)
    total: int


class AlertMatchRuleRef(_Model):
    """The rule an alert match names — ``null`` for a built-in (SPEC §47)."""

    id: int
    #: ``null`` only if the rule row vanished between the match and this read,
    #: which deleting a rule's matches with the rule makes impossible in
    #: practice.
    name: str | None = None


class AlertMatchView(_Model):
    """One recorded alert match — ``docs/API.md`` §3.9.

    ``reason`` is the text recorded when the match happened, not one recomposed
    from the rule as it stands now: history says what the user was shown.
    """

    id: int
    at: IsoTimestamp
    severity: AlertSeverityLiteral
    reason: str
    icao: Annotated[str, Field(pattern=r"^[0-9a-f]{6}$", examples=["ae1463"])]
    sighting_id: int
    #: ``null`` for a built-in emergency match, which has no rule.
    rule: AlertMatchRuleRef | None = None
    #: ``null`` for a rule match; a built-in detector's key otherwise.
    builtin_key: str | None = None
    #: Whether a browser notification has been delivered (slice 040 owns it).
    notified: bool = False


class AlertMatchListResponse(_Model):
    """``GET /api/v1/alerts/matches`` — the §2.4 paginated list envelope."""

    items: list[AlertMatchView] = Field(default_factory=list)
    #: Always ``null``, for the reason ``/activity`` gives: the history grows
    #: without bound, so §2.4's allowance to omit an exact filtered count
    #: applies and a client pages until a page comes back short.
    total: int | None = None
    limit: int
    offset: int


# --------------------------------------------------------------------------
# Diagnostics — docs/API.md §3.10, SPEC §67 (slice 042)
# --------------------------------------------------------------------------

#: Roll-up health of the whole install and of individual sections. Coarse on
#: purpose: the health area renders one banner from it, and the detail lives in
#: the sections themselves.
DiagnosticsStatusLiteral = Literal["ok", "degraded", "down"]

#: Decoder link state. ``unconfigured`` is the first-run install that has no
#: receiver yet — distinct from ``down``, which is a receiver that should be
#: answering and is not.
DecoderStateLiteral = Literal["unconfigured", "connected", "degraded", "down"]


class DiagnosticsVersions(_Model):
    """SPEC §67: frontend/backend version, plus the schema revision."""

    backend: str
    #: Served from the same image and build as the backend, so it is the same
    #: string rather than a second source that could disagree.
    frontend: str
    api: str
    schema_revision: str | None = None


class DiagnosticsUptime(_Model):
    """SPEC §67: backend uptime, and the decoder's own reported uptime."""

    backend_s: float | None = None
    #: Derived from the monotonic origin the process records; a duration clock
    #: cannot name an instant, so this is a reconstruction, not a measurement.
    started_at: IsoTimestamp | None = None
    decoder_s: float | None = None


class DiagnosticsDecoder(_Model):
    """SPEC §67: decoder connection state."""

    configured: bool
    state: DecoderStateLiteral
    last_success: IsoTimestamp | None = None
    last_failure: IsoTimestamp | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    next_retry_delay_s: float | None = None
    batches_ingested: int = 0
    updates_ingested: int = 0
    demo_mode: bool = False


class DiagnosticsLive(_Model):
    """SPEC §67: last successful aircraft update, and the current picture."""

    #: The freshest ``last_seen`` in the live picture. ``null`` on an empty
    #: sky, which is a different fact from a broken feed — read it together
    #: with :class:`DiagnosticsDecoder`.
    last_aircraft_update: IsoTimestamp | None = None
    last_aircraft_update_age_s: float | None = None
    total: int = 0
    positioned: int = 0
    non_positioned: int = 0
    stale: int = 0


class DiagnosticsQuickCheck(_Model):
    """SPEC §67: database health, as the last retained integrity check."""

    #: ``null`` before maintenance has ever run one.
    healthy: bool | None = None
    checked_at: IsoTimestamp | None = None
    error: str | None = None
    rows: list[str] = Field(default_factory=list)


class DiagnosticsStorage(_Model):
    """SPEC §67: database size and free disk space."""

    database_bytes: int | None = None
    file_bytes: int | None = None
    wal_bytes: int | None = None
    reclaimable_bytes: int | None = None
    reclaimable_ratio: float | None = None
    disk_free_bytes: int | None = None
    page_count: int | None = None
    page_size: int | None = None


class DiagnosticsRowCounts(_Model):
    """SPEC §67: useful row counts.

    A curated set, not the whole schema: the question a user is asking is
    whether their data is accumulating. ``null`` means the count could not be
    read, which is itself worth showing.
    """

    aircraft: int | None = None
    sightings: int | None = None
    sighting_tracks: int | None = None
    activity_events: int | None = None
    alert_matches: int | None = None
    aircraft_metadata: int | None = None
    airports: int | None = None
    receiver_metrics_raw: int | None = None


class DiagnosticsMaintenanceJob(_Model):
    """One maintenance job's last attempt (SPEC §70)."""

    outcome: Literal["ok", "skipped", "failed"]
    started_at: IsoTimestamp | None = None
    duration_ms: int = 0
    detail: dict[str, Any] = Field(default_factory=dict)


class DiagnosticsVacuumRefusal(_Model):
    """Why the guarded ``VACUUM`` last declined to run (SPEC §70).

    ``required_free_bytes`` against ``available_free_bytes`` is the point:
    ``VACUUM`` builds a complete second copy, so the requirement scales with
    the database and on a multi-year history can exceed anything the card will
    ever have free — a refusal that never clears rather than one that clears
    tonight (issue #116).
    """

    reason: str
    required_free_bytes: int = 0
    available_free_bytes: int = 0


class DiagnosticsMaintenance(_Model):
    """Maintenance outcomes surfaced into diagnostics (SPEC §70)."""

    cycles: int = 0
    last_cycle_at: IsoTimestamp | None = None
    healthy: bool | None = None
    running: bool = False
    jobs: dict[str, DiagnosticsMaintenanceJob] = Field(default_factory=dict)
    #: ``None`` when the last evaluation let a ``VACUUM`` run, or before the
    #: job has ever been due.
    vacuum_refusal: DiagnosticsVacuumRefusal | None = None


class DiagnosticsRecovery(_Model):
    """Unclean-shutdown recovery outcome (SPEC §71)."""

    recovered: int = 0
    continued: int = 0
    points_recovered: int = 0
    orphan_checkpoints: int = 0
    orphan_sightings: int = 0
    failed: int = 0
    anomalies: int = 0


class DiagnosticsDatabase(_Model):
    """SPEC §67: database health, size, and row counts."""

    status: DiagnosticsStatusLiteral
    reachable: bool = True
    quick_check: DiagnosticsQuickCheck = Field(default_factory=DiagnosticsQuickCheck)
    storage: DiagnosticsStorage = Field(default_factory=DiagnosticsStorage)
    row_counts: DiagnosticsRowCounts = Field(default_factory=DiagnosticsRowCounts)
    maintenance: DiagnosticsMaintenance = Field(default_factory=DiagnosticsMaintenance)
    recovery: DiagnosticsRecovery = Field(default_factory=DiagnosticsRecovery)


class DiagnosticsMetadataSource(_Model):
    """One metadata dataset's freshness (SPEC §67 "metadata database age")."""

    source: str
    status: Literal["never_run", "ok", "failed"]
    last_attempt_at: IsoTimestamp | None = None
    last_success_at: IsoTimestamp | None = None
    age_s: float | None = None
    dataset_version: str | None = None
    row_count: int | None = None
    last_error: str | None = None
    running: bool = False


class DiagnosticsMetadata(_Model):
    """SPEC §67: metadata database age, per source and overall."""

    sources: list[DiagnosticsMetadataSource] = Field(default_factory=list)
    #: The most recent successful import across sources — "how old is my
    #: metadata?" as one number.
    newest_success_at: IsoTimestamp | None = None
    age_s: float | None = None


class DiagnosticsNotifications(_Model):
    """SPEC §67: notification status, as far as the backend can know it.

    Browser permission is a client fact no server can observe, so
    ``permission_known_by`` is always ``"client"``: the health page joins this
    with slice 040's notification store to show the granted permission.
    """

    configured_enabled: bool = False
    severities: dict[str, bool] = Field(default_factory=dict)
    permission_known_by: Literal["client"] = "client"


class DiagnosticsEnrichment(_Model):
    """SPEC §67: enrichment failures."""

    enabled: bool = False
    running: bool = False
    circuit_open: bool = False
    lookups: int = 0
    dropped: int = 0
    pending: int = 0
    failures: int = 0


class DiagnosticsWebSocket(_Model):
    """SPEC §67: WebSocket issues."""

    clients: int = 0
    running: bool = False
    #: Only clients the server had to shed; a clean disconnect is not counted.
    disconnects: int = 0
    events_dropped: int = 0


class DiagnosticsError(_Model):
    """One captured recent error.

    Every string here has already passed the diagnostics redaction boundary
    (``docs/SECURITY.md`` §3), so no field can carry a configured secret.
    """

    at: IsoTimestamp
    category: Literal["ingestion", "database", "enrichment", "websocket", "other"]
    event: str
    level: str
    logger: str
    detail: str | None = None


class DiagnosticsResponse(_Model):
    """``GET /api/v1/diagnostics`` — every SPEC §67 item.

    **Never contains secrets** (``docs/API.md`` §3.10, ``docs/SECURITY.md`` §3):
    the payload passes through a whole-tree redaction against the configured
    secret values before serialization, and a test asserts a sentinel key
    cannot appear anywhere in this response.
    """

    generated_at: IsoTimestamp
    status: DiagnosticsStatusLiteral
    ready: bool = False
    subsystems: dict[str, bool] = Field(default_factory=dict)
    versions: DiagnosticsVersions
    uptime: DiagnosticsUptime = Field(default_factory=DiagnosticsUptime)
    decoder: DiagnosticsDecoder
    live: DiagnosticsLive = Field(default_factory=DiagnosticsLive)
    database: DiagnosticsDatabase
    metadata: DiagnosticsMetadata = Field(default_factory=DiagnosticsMetadata)
    notifications: DiagnosticsNotifications = Field(default_factory=DiagnosticsNotifications)
    enrichment: DiagnosticsEnrichment = Field(default_factory=DiagnosticsEnrichment)
    websocket: DiagnosticsWebSocket = Field(default_factory=DiagnosticsWebSocket)
    counters: dict[str, int] = Field(default_factory=dict)
    #: Keyed by category; each list is newest-first and bounded.
    recent_errors: dict[str, list[DiagnosticsError]] = Field(default_factory=dict)


__all__ = [
    "ActivityEventTypeLiteral",
    "ActivityEventView",
    "ActivityListResponse",
    "AircraftDetail",
    "AircraftHistoryListResponse",
    "AircraftHistoryRow",
    "AircraftSortKey",
    "AircraftView",
    "AirportFeature",
    "AirportFeatureCollection",
    "AirportPointGeometry",
    "AirportProperties",
    "AirportSizeClassLiteral",
    "AirspaceFeatureCollection",
    "AlertMatchListResponse",
    "AlertMatchRuleRef",
    "AlertMatchView",
    "AlertSeverityLiteral",
    "AnalyticsAircraftResponse",
    "AnalyticsAircraftRow",
    "AnalyticsClassificationResponse",
    "AnalyticsDailyResponse",
    "AnalyticsDailyRow",
    "AnalyticsGroupResponse",
    "AnalyticsGroupRow",
    "AnalyticsPresetLiteral",
    "AnalyticsRareType",
    "AnalyticsRarityResponse",
    "AnalyticsSummary",
    "AnalyticsSummaryResponse",
    "AnalyticsWindow",
    "Classification",
    "ClosureReasonLiteral",
    "CurrentAircraftResponse",
    "DecoderStateLiteral",
    "DiagnosticsDatabase",
    "DiagnosticsDecoder",
    "DiagnosticsEnrichment",
    "DiagnosticsError",
    "DiagnosticsLive",
    "DiagnosticsMaintenance",
    "DiagnosticsMaintenanceJob",
    "DiagnosticsMetadata",
    "DiagnosticsMetadataSource",
    "DiagnosticsNotifications",
    "DiagnosticsQuickCheck",
    "DiagnosticsRecovery",
    "DiagnosticsResponse",
    "DiagnosticsRowCounts",
    "DiagnosticsStatusLiteral",
    "DiagnosticsStorage",
    "DiagnosticsUptime",
    "DiagnosticsVacuumRefusal",
    "DiagnosticsVersions",
    "DiagnosticsWebSocket",
    "GeoPosition",
    "InterestingAircraftResponse",
    "InterestingMatch",
    "IsoTimestamp",
    "LifetimeRecord",
    "NearestAirportView",
    "PositionSourceLiteral",
    "ReceiverBearingSector",
    "ReceiverBusiestDay",
    "ReceiverCommonRecord",
    "ReceiverFrequentAircraft",
    "ReceiverHealthLiteral",
    "ReceiverInfo",
    "ReceiverLifetimeStats",
    "ReceiverMaxRangeRecord",
    "ReceiverMetricSeries",
    "ReceiverRangeByBearing",
    "ReceiverScorecard",
    "ReceiverSeriesMetric",
    "ReceiverSeriesPoint",
    "ReceiverSeriesResolution",
    "ReceiverSignalBucket",
    "ReceiverSignalDistribution",
    "ReceptionStats",
    "RouteView",
    "SightingDetail",
    "SightingEventTypeLiteral",
    "SightingEventView",
    "SightingListResponse",
    "SightingPathPoint",
    "SightingRecords",
    "SightingRow",
    "SightingSortKey",
    "SortOrder",
]
