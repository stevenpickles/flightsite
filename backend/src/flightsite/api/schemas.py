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

from typing import Annotated, Literal

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


__all__ = [
    "AircraftDetail",
    "AircraftHistoryListResponse",
    "AircraftHistoryRow",
    "AircraftSortKey",
    "AircraftView",
    "AlertSeverityLiteral",
    "Classification",
    "ClosureReasonLiteral",
    "CurrentAircraftResponse",
    "GeoPosition",
    "InterestingMatch",
    "IsoTimestamp",
    "LifetimeRecord",
    "NearestAirportView",
    "PositionSourceLiteral",
    "ReceiverInfo",
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
