"""Domain records to the JSON shapes ``docs/API.md`` documents.

One function per documented shape, each returning a plain JSON-ready ``dict``.
Plain dicts rather than Pydantic instances are deliberate: the WebSocket
broadcaster serializes an aircraft **once per frame** and hands the same bytes
to every connected client (``docs/ARCHITECTURE.md`` §3.3), so the hot path must
not pay for model construction per client. The Pydantic models in
:mod:`flightsite.api.schemas` describe these same shapes for OpenAPI and
validate them on the REST path, which keeps the published schema and the
WebSocket payload provably one shape rather than two that drift.

What the aircraft payload does and does not contain
---------------------------------------------------

``docs/API.md`` §3.3 shows the full v1 aircraft object, which spans several
slices. Slice 010 built the live-state half of it — identity, position,
kinematics, receiver-relative range, lifecycle state and the open sighting id —
with the metadata half (``registration``, ``aircraft_type``, ``model``,
``operator``, ``operator_group``, ``classification``) present and ``null``.
Slice 024 fills those in from the metadata cache, and the shape did not have to
change to accommodate it: §2.7 makes ``null`` the honest statement of
"unknown", so emitting the full key set from the start meant a client written
against §3.3 needed no change when the values began arriving.

Slice 026 adds the ``route`` block of §2.6 — origin and destination for the
aircraft's *current* sighting — on the same terms: both keys are always
present, both are ``null`` until enrichment has something to say, and the
provenance entry appears only when there is a value to attribute.

Slice 027 adds ``nearest_airport`` beside it, and the two are deliberately
*not* the same shape. ``route`` is an always-present object of nullable members
because a route is a thing every flight has, known or not. ``nearest_airport``
is a nullable object because most aircraft simply do not have one: at cruise
there is no nearest field in any meaningful sense, and an object of nulls would
imply a question was asked and came back empty rather than that it was never a
question at all. The key is always present; its value is ``null`` until an
aircraft is low near a field. Everything inside it is attributed
``heuristic`` — SPEC §41 requires the inference to be clearly labeled, and
§2.6's own example names exactly this provenance key.

Slice 037 adds ``watchlists``: always a list, ``[]`` when nothing matches,
never absent — the same always-present, empty-when-none shape §2.7's null
pattern takes for a list rather than a scalar. ``docs/API.md`` §5 notes an
``interesting``/``watchlist`` linkage arriving with slice 038's alert engine;
this field is additive on purpose so that slice can read watchlist membership
(:meth:`~flightsite.watchlists.matcher.WatchlistMatcher.matches`) as one of
several conditions without this payload's shape changing under it.

The metadata is passed in rather than looked up here. This function is called
once per aircraft per WebSocket frame and must not touch SQLite
(``docs/ARCHITECTURE.md`` §3.1); the caller supplies an
:class:`~flightsite.metadata.cache.AircraftMetadataView`, which is a pure
in-memory read, or ``None`` for an aircraft the cache has not resolved yet.
``None`` and "resolved to nothing" both serialize as ``null`` fields — the
difference matters to the cache, not to a client.

The alert match (``interesting``) still arrives with slice 038.

``emergency`` is not a separate decoder field — it is the squawk restated when
the squawk is one of the three emergency codes (:data:`EMERGENCY_SQUAWKS`), so
a client does not have to carry the code list to render an emergency.

Provenance
----------

§2.6: a ``provenance`` entry names the source of a non-decoder field, and
fields without an entry are decoder-direct. The live record
(:mod:`flightsite.live.aircraft`) tracks provenance for the three values that
layer decides — ``distance_nm``, ``bearing_deg`` and ``ground_state`` — and
this payload publishes the first two, which are the two that appear in it.
``ground_state`` is deliberately not published: the API field is ``on_ground``,
which carries the decoder's own determination or ``null``, never the live
layer's airborne inference, so there is no derived value here to attribute.

The metadata half contributes the rest. Two rules govern it. **Entries name
payload fields**, so the resolved type's provenance key is ``aircraft_type``
(what §3.3 calls the field) rather than ``type_code`` (what the resolved table
calls the column) — :data:`METADATA_PROVENANCE_KEYS` is that translation.
**Only published fields get an entry**: the resolved row also carries
``manufacture_year`` and ``owner``, which this payload does not show, and a
provenance entry for a field that is not there would name the source of
nothing.

Rounding
--------

``distance_nm`` and ``bearing_deg`` are computed from a great-circle formula
and arrive with full float precision, which is fifteen significant digits of
which about five mean anything. They are rounded — to about two metres and to
a hundredth of a degree respectively — because at 500 aircraft and 1 Hz the
unrounded digits are pure payload weight. Every other number is passed through
exactly as the decoder reported it; FlightSite does not re-derive or "tidy"
decoder values.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy.engine import RowMapping

from flightsite.airports.model import AirportContext
from flightsite.airports.overlay import TYPE_SIZE_CLASSES
from flightsite.airports.records import AirportRecord
from flightsite.analytics.bucketing import Window
from flightsite.analytics.queries import AircraftRank, DailyRow, GroupRank, RareType, Summary
from flightsite.api.receiver_stats import CommonRecord, MostFrequentAircraft, SignalHistogram
from flightsite.classification.vocabulary import Confidence, IconCategory, MissionCategory
from flightsite.config import Settings
from flightsite.db.clock import from_epoch_ms
from flightsite.ingest import Position
from flightsite.live import LiveAircraft, LiveCounts
from flightsite.metadata.cache import AircraftMetadataView
from flightsite.receiver_metrics import LifetimeValue, MetricSample
from flightsite.receiver_metrics.model import (
    BEARING_BUCKETS,
    BEARING_SECTOR_DEG,
    LIFETIME_BUSIEST_DAY,
    LIFETIME_BUSIEST_DAY_COUNT,
    LIFETIME_MAX_RANGE_AT_MS,
    LIFETIME_MAX_RANGE_BEARING,
    LIFETIME_MAX_RANGE_ICAO24,
    LIFETIME_MAX_RANGE_NM,
    LIFETIME_MAX_SIMULTANEOUS,
    LIFETIME_PEAK_MSG_RATE,
    LIFETIME_PEAK_POS_RATE,
    LIFETIME_TOTAL_MESSAGES,
    LIFETIME_TOTAL_POSITIONS,
    RangeRecord,
)
from flightsite.sightings.state import SightingRoute
from flightsite.sightings.tracks import TrackSample
from flightsite.sightings.vocabulary import EMERGENCY_SQUAWKS

#: Provenance keys from the live record that name a field this payload exposes.
#: See the module docstring for why ``ground_state`` is not among them.
EXPOSED_PROVENANCE_FIELDS: Final[frozenset[str]] = frozenset({"distance_nm", "bearing_deg"})

#: Metadata provenance keys (``docs/API.md`` §2.6, as
#: :data:`~flightsite.metadata.precedence.PROVENANCE_KEYS` produces them) mapped
#: to the §3.3 payload field they describe. A key absent from this map names a
#: resolved field this payload does not publish, and is dropped.
METADATA_PROVENANCE_KEYS: Final[Mapping[str, str]] = {
    "registration": "registration",
    "type_code": "aircraft_type",
    "model": "model",
    "operator": "operator",
    "operator_group": "operator_group",
    "classification": "classification",
}

#: Decimal places kept on the two derived receiver-relative values.
DISTANCE_DECIMALS: Final = 3
BEARING_DECIMALS: Final = 2

#: Provenance value for everything in the ``nearest_airport`` block
#: (``docs/API.md`` §2.6). One entry covers the block rather than one per
#: member: the distance is arithmetic and the name is a lookup, but *which*
#: airport is the nearest one is the judgement being published, and attributing
#: its parts differently would invite a reader to trust some of it more than
#: the whole deserves.
NEAREST_AIRPORT_PROVENANCE: Final = "heuristic"


def iso_utc(moment: datetime) -> str:
    """Format an instant as ``docs/API.md`` §2.2 UTC ISO-8601.

    Millisecond precision with a literal ``Z``: ``2026-08-31T14:03:22.418Z``.
    Naive datetimes are rejected rather than assumed to be UTC — the same rule
    the storage layer applies (:func:`flightsite.db.clock.to_epoch_ms`), for
    the same reason.
    """
    if moment.tzinfo is None:
        raise ValueError("refusing to serialize a naive datetime; timestamps must be UTC-aware")
    utc = moment.astimezone(UTC)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond // 1000:03d}Z"


def _position(record: LiveAircraft) -> dict[str, float] | None:
    """The ``{lat, lon}`` block, or ``None`` for a non-positioned aircraft."""
    position = record.position
    if position is None:
        return None
    return {"lat": position.latitude, "lon": position.longitude}


def _emergency(squawk: str | None) -> str | None:
    """The squawk when it declares an emergency, else ``None`` (§3.3)."""
    return squawk if squawk in EMERGENCY_SQUAWKS else None


def _round(value: float | None, decimals: int) -> float | None:
    return None if value is None else round(value, decimals)


def _route(route: SightingRoute | None) -> dict[str, str | None]:
    """The §2.6 ``route`` block: both keys always, values ``null`` if unknown.

    A stable object rather than a nullable one. "No route yet", "not an airline
    flight", "enrichment is off" and "nobody has a route for this flight" are
    four different reasons for the same display, and a client that has to
    distinguish an absent block from a block of nulls before it can render
    *Unknown* is carrying that distinction for nothing (§2.7).
    """
    if route is None:
        return {"origin": None, "destination": None}
    return {"origin": route.origin_ident, "destination": route.destination_ident}


def _nearest_airport(context: AirportContext | None) -> dict[str, Any] | None:
    """The §3.3 ``nearest_airport`` block, or ``None`` when there is not one.

    Nullable as a whole, unlike ``route`` — see the module docstring. ``phase``
    is a member rather than a sibling block because it is meaningless without
    the field it is about: "likely arriving" names nowhere on its own.
    """
    if context is None:
        return None
    return {
        "ident": context.ident,
        "name": context.name,
        "distance_nm": round(context.distance_nm, DISTANCE_DECIMALS),
        "phase": None if context.phase is None else context.phase.value,
    }


def _provenance(
    record: LiveAircraft,
    metadata: AircraftMetadataView | None,
    route: SightingRoute | None,
    airport: AirportContext | None,
) -> dict[str, str]:
    """The §2.6 provenance map, restricted to fields this payload publishes."""
    found = {
        field: provenance.value
        for field, provenance in record.provenance.items()
        if field in EXPOSED_PROVENANCE_FIELDS
    }
    if metadata is not None:
        for key, source in metadata.provenance().items():
            published = METADATA_PROVENANCE_KEYS.get(key)
            if published is not None:
                found[published] = source
    # Only when there is a route to attribute: §2.6's entries name the source
    # of a value, and a provenance for two nulls would name the source of
    # nothing. `route_source` is the sighting column, which is the same
    # vocabulary — ``aerodatabox`` — the provenance map uses.
    if route is not None:
        found["route"] = route.source
    # Same rule, same reason: no block, nothing to attribute.
    if airport is not None:
        found["nearest_airport"] = NEAREST_AIRPORT_PROVENANCE
    return found


def aircraft_payload(
    record: LiveAircraft,
    *,
    sighting_id: int | None = None,
    metadata: AircraftMetadataView | None = None,
    route: SightingRoute | None = None,
    airport: AirportContext | None = None,
    watchlists: Sequence[str] = (),
) -> dict[str, Any]:
    """One live aircraft as the ``docs/API.md`` §3.3 object.

    The same object is served by ``GET /api/v1/aircraft/current`` and carried
    by every WebSocket ``snapshot`` and ``delta`` frame — §3.3 says "the same
    shape used by the WebSocket", and one function is how that stays true.

    Args:
        record: the live registry's current record for the aircraft.
        sighting_id: the id of its open sighting, or ``None`` when the
            persistence worker has not committed one yet (the normal state for
            the first second or so of a new aircraft, and the permanent state
            when persistence is degraded).
        metadata: the metadata cache's entry for the aircraft, or ``None`` when
            it has not been resolved yet — which is the normal state for the
            first sub-second of a new aircraft's life, and the permanent state
            on an install with no metadata database. Every metadata field is
            ``null`` in that case, per §2.7.
        route: the route route enrichment (slice 026) has established for the
            aircraft's *current* sighting, or ``None``. ``None`` is the normal
            state everywhere: enrichment is optional and off by default, only
            airline-form callsigns are ever looked up, and the answer arrives a
            second or two after the aircraft does. It serializes as a ``route``
            block of nulls, never as a missing key.
        airport: the nearest-airport context slice 027's heuristic holds for
            this aircraft *right now*, or ``None``. ``None`` is the normal
            state for most of the sky: no airport dataset imported, the
            aircraft is at cruise, or it is nowhere near a field. It serializes
            as ``nearest_airport: null``, never as a missing key.
        watchlists: the names of every watchlist (SPEC §42, roadmap slice 037)
            this aircraft currently matches, from
            :meth:`~flightsite.watchlists.matcher.WatchlistMatcher.matches` —
            a pure in-memory lookup, so this never costs the aircraft path a
            database read. Always present and ``[]`` when there is no match,
            per §2.7's null-stable pattern extended to a list field: an empty
            list, not a missing key, is "no watchlist matches this", and a
            client never has to tell that apart from "watchlists is not a
            thing this build carries".
    """
    resolved = None if metadata is None else metadata.metadata
    return {
        "icao": record.icao,
        "callsign": record.callsign,
        "registration": None if resolved is None else resolved.registration,
        "position": _position(record),
        "position_source": record.position_source,
        "altitude_ft": record.altitude_ft,
        "ground_speed_kt": record.ground_speed_kt,
        "track_deg": record.track_deg,
        "vertical_rate_fpm": record.vertical_rate_fpm,
        "squawk": record.squawk,
        "emergency": _emergency(record.squawk),
        "on_ground": record.on_ground,
        "distance_nm": _round(record.distance_nm, DISTANCE_DECIMALS),
        "bearing_deg": _round(record.bearing_deg, BEARING_DECIMALS),
        "rssi_db": record.rssi_db,
        "message_count": record.messages,
        "seen_s": record.seen_s,
        "seen_pos_s": record.seen_pos_s,
        "last_seen": iso_utc(record.last_seen),
        "state": record.state.value,
        "sighting_id": sighting_id,
        "aircraft_type": None if resolved is None else resolved.type_code,
        "model": None if resolved is None else resolved.model,
        "operator": None if resolved is None else resolved.operator_name,
        "operator_group": None if metadata is None else metadata.operator_group,
        "classification": None if metadata is None else metadata.classification.payload(),
        "route": _route(route),
        "nearest_airport": _nearest_airport(airport),
        "interesting": None,
        "watchlists": list(watchlists),
        "provenance": _provenance(record, metadata, route, airport),
    }


def receiver_payload(
    settings: Settings,
    *,
    demo_mode: bool,
    t0: datetime | None,
    location: Position | None,
) -> dict[str, Any]:
    """The ``docs/API.md`` §3.2 receiver info block.

    Non-secret by construction: every value is read from a named field of the
    settings model, so no secret can arrive here by accident (SPEC §29). An
    unconfigured receiver — the first-run state, before the setup wizard of
    slice 018 — reports ``null`` location fields rather than an error; §2.7
    makes that the honest answer, and the live picture works without them.

    Args:
        settings: the running configuration (read from ``app.state`` per
            request, since ``PUT /api/internal/config`` replaces it).
        demo_mode: whether this process is serving simulated traffic.
        t0: the moment FlightSite first persisted an observation (SPEC §16),
            or ``None`` on an install that has never seen an aircraft.
        location: the position FlightSite is *actually* measuring from —
            :attr:`~flightsite.live.store.LiveStore.receiver_location`, not the
            configured one. The two are the same everywhere except demo mode,
            which injects a location into an unconfigured install so the
            simulated sky has ranges (SPEC §76). Reporting the configured
            ``null`` there would leave a client drawing range rings around
            nothing while every aircraft carried a ``distance_nm``.
    """
    site = settings.location
    return {
        "site_name": site.site_name,
        "latitude": None if location is None else location.latitude,
        "longitude": None if location is None else location.longitude,
        "antenna_height_ft": site.antenna_height_ft,
        "timezone": settings.timezone,
        "units": settings.units,
        "display_radius_nm": settings.display_radius_nm,
        "alert_radius_nm": settings.alert_radius_nm,
        "demo_mode": demo_mode,
        "t0": None if t0 is None else iso_utc(t0),
    }


def _lifetime_num(lifetime: Mapping[str, LifetimeValue], key: str) -> float | None:
    value = lifetime.get(key)
    return None if value is None else value.value_num


def _lifetime_text(lifetime: Mapping[str, LifetimeValue], key: str) -> str | None:
    value = lifetime.get(key)
    return None if value is None else value.value_text


def _receiver_health(*, demo_mode: bool, stats_supported: bool | None) -> str:
    """The SPEC §61 health cue — see :data:`~flightsite.api.schemas.ReceiverHealthLiteral`."""
    if demo_mode:
        return "demo"
    if stats_supported is None:
        return "unknown"
    return "ok" if stats_supported else "no_stats"


def receiver_scorecard_payload(
    *,
    counts: LiveCounts,
    latest_sample: MetricSample | None,
    max_range_today_nm: float | None,
    lifetime: Mapping[str, LifetimeValue],
    unique_today: int,
    unique_since_t0: int,
    decoder_uptime_s: float | None,
    flightsite_uptime_s: float,
    stats_supported: bool | None,
    demo_mode: bool,
) -> dict[str, Any]:
    """The SPEC §61 scorecard — ``docs/API.md`` §3.8.

    Args:
        counts: the live registry's current summary
            (:meth:`~flightsite.live.store.LiveStore.counts`) — "current
            visible"/"current positioned".
        latest_sample: the most recent raw receiver-metric sample, or
            ``None`` before the first one has been taken; its own rate is
            "current" messages/sec and positions/sec, not a windowed average.
        max_range_today_nm: the furthest range observed anywhere on the
            compass so far today (the caller reduces
            :meth:`~flightsite.receiver_metrics.repository.MetricsRepository.ranges_for_day`
            across sectors), or ``None`` on a day with no positioned traffic
            yet.
        lifetime: every lifetime record (§6.4), for "max range ever".
        decoder_uptime_s: the decoder's own reported uptime, or ``None`` when
            it reports no statistics (SPEC §60).
        stats_supported: whether the decoder serves a usable statistics
            document — ``None`` before the first poll, ``False`` for a
            decoder with none (a supported configuration, not a fault).
    """
    return {
        "current_visible": counts.total,
        "current_positioned": counts.positioned,
        "messages_per_sec": None if latest_sample is None else latest_sample.messages_per_sec,
        "positions_per_sec": None if latest_sample is None else latest_sample.positions_per_sec,
        "max_range_today_nm": max_range_today_nm,
        "max_range_ever_nm": _lifetime_num(lifetime, LIFETIME_MAX_RANGE_NM),
        "unique_aircraft_today": unique_today,
        "unique_aircraft_since_t0": unique_since_t0,
        "decoder_uptime_s": decoder_uptime_s,
        "flightsite_uptime_s": round(flightsite_uptime_s, 3),
        "health": _receiver_health(demo_mode=demo_mode, stats_supported=stats_supported),
    }


def receiver_metric_series_payload(
    *, metric: str, resolution: str, points: Sequence[tuple[int, float | None]]
) -> dict[str, Any]:
    """``GET /api/v1/receiver/metrics`` — one SPEC §62 chart's data.

    ``points`` is ``(ts_ms, value)`` pairs, already selected for the requested
    metric and resolution and ordered by time — the caller
    (:meth:`~flightsite.api.context.LiveApiContext.receiver_metric_series`)
    does the resolution-dependent reads; this function only formats them.
    """
    return {
        "metric": metric,
        "resolution": resolution,
        "points": [
            {
                "t": iso_utc(from_epoch_ms(ts_ms)),
                "value": None if value is None else float(value),
            }
            for ts_ms, value in points
        ],
    }


def _bearing_sector_payload(record: RangeRecord | None, *, bearing_deg: float) -> dict[str, Any]:
    if record is None:
        return {"bearing_deg": bearing_deg, "max_range_nm": None, "at": None, "icao": None}
    return {
        "bearing_deg": bearing_deg,
        "max_range_nm": record.max_range_nm,
        "at": iso_utc(from_epoch_ms(record.at_ms)),
        "icao": record.icao24,
    }


def receiver_range_by_bearing_payload(
    *, today: Mapping[int, RangeRecord], ever: Mapping[int, RangeRecord]
) -> dict[str, Any]:
    """``GET /api/v1/receiver/range-by-bearing`` — SPEC §62's polar plot.

    Always emits all :data:`~flightsite.receiver_metrics.model.BEARING_BUCKETS`
    sectors for both series, in bucket order (0 = North, increasing clockwise
    per ``docs/DATA_MODEL.md`` §6.3), so the frontend never has to fill gaps
    itself — a sector nothing has been heard in is a real entry with
    ``max_range_nm: null``, not a missing one.
    """
    sectors_today = []
    sectors_ever = []
    for bucket in range(BEARING_BUCKETS):
        bearing_deg = bucket * BEARING_SECTOR_DEG + BEARING_SECTOR_DEG / 2
        sectors_today.append(_bearing_sector_payload(today.get(bucket), bearing_deg=bearing_deg))
        sectors_ever.append(_bearing_sector_payload(ever.get(bucket), bearing_deg=bearing_deg))
    return {"sector_width_deg": BEARING_SECTOR_DEG, "today": sectors_today, "ever": sectors_ever}


def receiver_signal_distribution_payload(
    histogram: SignalHistogram, *, from_ms: int | None, to_ms: int | None
) -> dict[str, Any]:
    """``GET /api/v1/receiver/signal-distribution`` — SPEC §62.

    ``histogram`` is already computed
    (:func:`~flightsite.api.receiver_stats.signal_histogram`); this only
    formats it alongside the window it was computed over.
    """
    return {
        "from_ts": None if from_ms is None else iso_utc(from_epoch_ms(from_ms)),
        "to_ts": None if to_ms is None else iso_utc(from_epoch_ms(to_ms)),
        "bucket_width_db": histogram.bucket_width_db,
        "buckets": [
            {"min_db": bucket.min_db, "max_db": bucket.max_db, "count": bucket.count}
            for bucket in histogram.buckets
        ],
        "sample_count": histogram.sample_count,
        "min_db": histogram.min_db,
        "max_db": histogram.max_db,
        "avg_db": histogram.avg_db,
    }


def receiver_lifetime_stats_payload(
    *,
    t0: datetime | None,
    lifetime: Mapping[str, LifetimeValue],
    unique_aircraft: int,
    total_sightings: int,
    most_frequent: MostFrequentAircraft | None,
    common_type: CommonRecord | None,
    common_model: CommonRecord | None,
    common_operator: CommonRecord | None,
) -> dict[str, Any]:
    """``GET /api/v1/receiver/lifetime`` — SPEC §63, since T0 where possible."""
    max_range_nm = _lifetime_num(lifetime, LIFETIME_MAX_RANGE_NM)
    max_range: dict[str, Any] | None = None
    if max_range_nm is not None:
        at_ms = _lifetime_num(lifetime, LIFETIME_MAX_RANGE_AT_MS)
        max_range = {
            "nm": max_range_nm,
            "at": None if at_ms is None else iso_utc(from_epoch_ms(int(at_ms))),
            "bearing_deg": _lifetime_num(lifetime, LIFETIME_MAX_RANGE_BEARING),
            "icao": _lifetime_text(lifetime, LIFETIME_MAX_RANGE_ICAO24),
        }

    busiest_day_name = _lifetime_text(lifetime, LIFETIME_BUSIEST_DAY)
    busiest_day: dict[str, Any] | None = None
    if busiest_day_name is not None:
        count = _lifetime_num(lifetime, LIFETIME_BUSIEST_DAY_COUNT)
        busiest_day = {
            "day": busiest_day_name,
            "message_count": None if count is None else int(count),
        }

    max_simultaneous = _lifetime_num(lifetime, LIFETIME_MAX_SIMULTANEOUS)
    total_messages = _lifetime_num(lifetime, LIFETIME_TOTAL_MESSAGES)
    total_positions = _lifetime_num(lifetime, LIFETIME_TOTAL_POSITIONS)

    def _common_payload(record: CommonRecord | None) -> dict[str, Any] | None:
        if record is None:
            return None
        return {"value": record.value, "aircraft_count": record.aircraft_count}

    return {
        "since": None if t0 is None else iso_utc(t0),
        "unique_aircraft": unique_aircraft,
        "total_sightings": total_sightings,
        "total_positions": None if total_positions is None else int(total_positions),
        "total_messages": None if total_messages is None else int(total_messages),
        "max_range": max_range,
        "peak_message_rate_per_sec": _lifetime_num(lifetime, LIFETIME_PEAK_MSG_RATE),
        "peak_position_rate_per_sec": _lifetime_num(lifetime, LIFETIME_PEAK_POS_RATE),
        "max_simultaneous_aircraft": None if max_simultaneous is None else int(max_simultaneous),
        "busiest_day": busiest_day,
        "most_frequent_aircraft": None
        if most_frequent is None
        else {
            "icao": most_frequent.icao24,
            "registration": most_frequent.registration,
            "sighting_count": most_frequent.sighting_count,
        },
        "common_type": _common_payload(common_type),
        "common_model": _common_payload(common_model),
        "common_operator": _common_payload(common_operator),
    }


def _classification_from_row(row: RowMapping) -> tuple[dict[str, Any] | None, str | None]:
    """The §3.3 ``classification`` object from a joined history row, plus its source.

    Mirrors :class:`flightsite.classification.model.Classification` field by
    field — ``is_unknown``, ``primary_claim`` and ``payload()`` — but reads
    the already-computed ``aircraft_classification`` columns a history query
    joined in rather than reconstructing ``Claim`` objects, which the
    Aircraft page's row shape has no use for. A row with no matching
    ``aircraft_classification`` (the LEFT JOIN found nothing) reads as every
    flag ``False`` and both category columns ``None``, which resolves to
    "unknown" exactly as an unclassified airframe should.

    The claim precedence — military, then law enforcement, then government,
    then mission — is the same order :attr:`Classification.primary_claim`
    uses, so the ``confidence`` and provenance source this returns is the
    same one the live payload would show for the same airframe.
    """
    military = bool(row["military"])
    government = bool(row["government"])
    law_enforcement = bool(row["law_enforcement"])
    mission = row["mission_category"] or MissionCategory.UNKNOWN.value
    icon_category = row["icon_category"] or IconCategory.UNKNOWN.value
    mission_known = mission != MissionCategory.UNKNOWN.value

    if not (
        military
        or government
        or law_enforcement
        or mission_known
        or icon_category != IconCategory.UNKNOWN.value
    ):
        return None, None

    if military:
        score, source = row["military_conf"], row["military_src"]
    elif law_enforcement:
        score, source = row["law_enforcement_conf"], row["law_enforcement_src"]
    elif government:
        score, source = row["government_conf"], row["government_src"]
    elif mission_known:
        score, source = row["mission_conf"], row["mission_src"]
    else:
        score, source = None, None

    payload = {
        "military": military,
        "government": government,
        "law_enforcement": law_enforcement,
        "mission": mission,
        "icon_category": icon_category,
        "confidence": None if score is None else Confidence.from_score(score).value,
    }
    return payload, source


def _resolved_provenance_from_row(row: RowMapping) -> dict[str, str]:
    """The resolved-metadata half of a history row's §2.6 provenance map.

    Only the fields the Aircraft page's row and detail payloads actually
    publish get an entry — the same "only published fields" rule
    :func:`_provenance` follows for the live payload.
    """
    found: dict[str, str] = {}
    if row["registration"] is not None and row["registration_src"] is not None:
        found["registration"] = row["registration_src"]
    if row["type_code"] is not None and row["type_code_src"] is not None:
        found["aircraft_type"] = row["type_code_src"]
    if row["model"] is not None and row["model_src"] is not None:
        found["model"] = row["model_src"]
    if row["operator_name"] is not None and row["operator_src"] is not None:
        found["operator"] = row["operator_src"]
    if row["operator_group"] is not None:
        found["operator_group"] = "derived"
    return found


def lifetime_payload(row: RowMapping) -> dict[str, Any]:
    """The SPEC §53 lifetime record block from a joined history row.

    ``docs/API.md`` §3.5's documented shape, verbatim: every field here is a
    denormalized column on :class:`~flightsite.db.models.Aircraft`
    (``docs/DATA_MODEL.md`` §2.2), so this is a rename-and-convert, not a
    computation — the persistence worker is what keeps the source columns
    correct.
    """
    return {
        "first_seen": iso_utc(from_epoch_ms(row["first_seen_ms"])),
        "last_seen": iso_utc(from_epoch_ms(row["last_seen_ms"])),
        "sighting_count": row["sighting_count"],
        "cumulative_duration_s": row["total_observed_ms"] // 1000,
        "closest_approach_nm": row["closest_approach_nm"],
        "max_range_nm": row["max_range_nm"],
        "lowest_altitude_ft": row["lowest_alt_ft"],
        "highest_altitude_ft": row["highest_alt_ft"],
    }


def aircraft_history_row_payload(row: RowMapping) -> dict[str, Any]:
    """One Aircraft page row — ``docs/API.md`` §3.5, SPEC §56's column list.

    Field names deliberately match the live §3.3 object where the same fact
    appears (``aircraft_type``, ``operator_group``, ``classification``,
    ``provenance``) rather than the SQL columns' own names, so a client — and
    the frontend's shared field components — can render a live aircraft and a
    historical row through the same code.
    """
    classification, classification_source = _classification_from_row(row)
    provenance = _resolved_provenance_from_row(row)
    if classification_source is not None:
        provenance["classification"] = classification_source
    return {
        "icao": row["icao24"],
        "registration": row["registration"],
        "aircraft_type": row["type_code"],
        "model": row["model"],
        "operator": row["operator_name"],
        "operator_group": row["operator_group"],
        "classification": classification,
        "first_seen": iso_utc(from_epoch_ms(row["first_seen_ms"])),
        "last_seen": iso_utc(from_epoch_ms(row["last_seen_ms"])),
        "sighting_count": row["sighting_count"],
        "closest_approach_nm": row["closest_approach_nm"],
        "max_range_nm": row["max_range_nm"],
        "provenance": provenance,
    }


def aircraft_detail_payload(row: RowMapping, *, live: bool) -> dict[str, Any]:
    """One aircraft's full detail — ``docs/API.md`` §3.5: identity, metadata
    with provenance, classification, and the SPEC §53 lifetime block.

    Args:
        row: the joined row :meth:`~flightsite.api.history.AircraftHistoryRepository.get_aircraft`
            returned for a known ``icao24`` — callers 404 before this is
            called for an unknown one.
        live: whether this airframe is in the live picture right now
            (:attr:`~flightsite.live.store.LiveStore` at read time), so the
            frontend can offer a jump to its Live Map selection instead of
            showing a live section it has no data for.
    """
    classification, classification_source = _classification_from_row(row)
    provenance = _resolved_provenance_from_row(row)
    if row["manufacture_year"] is not None and row["year_src"] is not None:
        provenance["manufacture_year"] = row["year_src"]
    if row["owner"] is not None and row["owner_src"] is not None:
        provenance["owner"] = row["owner_src"]
    if classification_source is not None:
        provenance["classification"] = classification_source
    return {
        "icao": row["icao24"],
        "registration": row["registration"],
        "aircraft_type": row["type_code"],
        "model": row["model"],
        "manufacture_year": row["manufacture_year"],
        "operator": row["operator_name"],
        "operator_group": row["operator_group"],
        "owner": row["owner"],
        "classification": classification,
        "live": live,
        "lifetime": lifetime_payload(row),
        "provenance": provenance,
    }


def airport_feature_collection_payload(records: Sequence[AirportRecord]) -> dict[str, Any]:
    """``records`` as a GeoJSON ``FeatureCollection`` — ``GET /api/v1/airports``
    (slice 028).

    Each airport becomes one ``Point`` feature, ``[lon, lat]`` per RFC 7946
    (GeoJSON's axis order is the opposite of the ``AirportRecord.lat, lon``
    field order this codebase otherwise uses). ``type`` is rendered as the
    friendlier :data:`~flightsite.airports.overlay.AirportSizeClass` spelling
    (``TYPE_SIZE_CLASSES``) rather than upstream's ``*_airport`` suffix, so
    the frontend's size-class filter and this payload's property share one
    vocabulary. A record whose ``type`` is not one of the four imported
    classes (never true for anything :mod:`flightsite.airports.records`
    actually stores) is skipped rather than serialized with a size class that
    does not exist — the same "drop rather than guess" posture the rest of
    this codebase takes on unrecognized upstream data.
    """
    features: list[dict[str, Any]] = []
    for record in records:
        size_class = TYPE_SIZE_CLASSES.get(record.type)
        if size_class is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [record.lon, record.lat]},
                "properties": {
                    "ident": record.ident,
                    "name": record.name,
                    "size_class": size_class,
                    "iata": record.iata,
                    "elevation_ft": record.elevation_ft,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def sighting_row_payload(row: RowMapping) -> dict[str, Any]:
    """One Sightings page row — ``docs/API.md`` §3.6, SPEC §57's column list.

    Field names deliberately match :func:`aircraft_history_row_payload`
    (``aircraft_type``, ``operator_group``, ``classification``,
    ``provenance``) rather than the SQL columns' own names, for the reason
    its docstring gives: one set of frontend field components renders both.
    ``callsign``/``registration`` are both published so the client can
    render SPEC §57's combined "tail/callsign" column, preferring whichever
    is known.
    """
    classification, classification_source = _classification_from_row(row)
    provenance = _resolved_provenance_from_row(row)
    if classification_source is not None:
        provenance["classification"] = classification_source
    return {
        "id": row["id"],
        "icao": row["icao24"],
        "callsign": row["callsign_last"],
        "registration": row["registration"],
        "aircraft_type": row["type_code"],
        "model": row["model"],
        "operator": row["operator_name"],
        "operator_group": row["operator_group"],
        "classification": classification,
        "started_at": iso_utc(from_epoch_ms(row["started_ms"])),
        "ended_at": None if row["ended_ms"] is None else iso_utc(from_epoch_ms(row["ended_ms"])),
        "duration_s": None if row["duration_ms"] is None else row["duration_ms"] // 1000,
        "closure_reason": row["closure_reason"],
        "closest_approach_nm": row["closest_approach_nm"],
        "max_range_nm": row["max_range_nm"],
        "lowest_altitude_ft": row["lowest_alt_ft"],
        "highest_altitude_ft": row["highest_alt_ft"],
        "position_count": row["pos_count"],
        "had_emergency": bool(row["had_emergency"]),
        "max_alert_severity": row["max_alert_severity"],
        "provenance": provenance,
    }


def sighting_event_payload(row: RowMapping) -> dict[str, Any]:
    """One ``sighting_events`` row as the §3.6 event-timeline entry (SPEC §52).

    ``payload_json`` is opaque storage (:mod:`flightsite.db.models`'
    ``SightingEvent`` docstring); this is the one place it is parsed back
    into the structured ``detail`` object the documented shape carries.
    """
    payload_json = row["payload_json"]
    return {
        "at": iso_utc(from_epoch_ms(row["ts_ms"])),
        "type": row["type"],
        "detail": None if payload_json is None else json.loads(payload_json),
    }


def sighting_path_point_payload(sample: TrackSample) -> dict[str, Any]:
    """One decoded track sample as the §3.6 ``path`` point shape."""
    return {
        "t": iso_utc(from_epoch_ms(sample.ts_ms)),
        "lat": sample.latitude,
        "lon": sample.longitude,
        "altitude_ft": sample.altitude_ft,
        "source": sample.position_source,
    }


def sighting_detail_payload(
    row: RowMapping,
    *,
    events: Sequence[RowMapping],
    path: Sequence[TrackSample],
) -> dict[str, Any]:
    """One sighting's full detail — ``docs/API.md`` §3.6.

    Flight context, reception stats (SPEC §51), per-sighting records, the
    event timeline and the simplified (or, for an open sighting, checkpointed)
    path. ``route``'s provenance follows the same "only when there is a value
    to attribute" rule :func:`_provenance` applies to the live payload: a
    sighting with no route enrichment publishes no ``route`` provenance
    entry at all, not one naming a source for two nulls.
    """
    return {
        "id": row["id"],
        "icao": row["icao24"],
        "callsign": row["callsign_last"],
        "squawk": row["squawk_last"],
        "started_at": iso_utc(from_epoch_ms(row["started_ms"])),
        "ended_at": None if row["ended_ms"] is None else iso_utc(from_epoch_ms(row["ended_ms"])),
        "duration_s": None if row["duration_ms"] is None else row["duration_ms"] // 1000,
        "closure_reason": row["closure_reason"],
        "route": {"origin": row["origin_ident"], "destination": row["destination_ident"]},
        "reception": {
            "rssi_peak_db": row["rssi_peak_db"],
            "rssi_avg_db": row["rssi_avg_db"],
            "rssi_min_db": row["rssi_min_db"],
            "message_count": row["msg_count"],
            "position_count": row["pos_count"],
            "pct_with_position": row["pos_time_pct"],
        },
        "records": {
            "closest_approach_nm": row["closest_approach_nm"],
            "max_range_nm": row["max_range_nm"],
            "lowest_altitude_ft": row["lowest_alt_ft"],
            "highest_altitude_ft": row["highest_alt_ft"],
        },
        "events": [sighting_event_payload(event) for event in events],
        "path": [sighting_path_point_payload(sample) for sample in path],
        "provenance": {} if row["route_source"] is None else {"route": row["route_source"]},
    }


# --------------------------------------------------------------- analytics


def _at(epoch_ms: int | None) -> str | None:
    """An epoch-millisecond column as §2.2's UTC ISO-8601, or ``None``."""
    return None if epoch_ms is None else iso_utc(from_epoch_ms(epoch_ms))


def analytics_window_payload(
    window: Window, *, preset: str | None, timezone: str
) -> dict[str, Any]:
    """The window block every ``docs/API.md`` §3.7 response carries.

    Bounds *and* receiver-local day range, because a preset resolves against
    the receiver's calendar and its own clock: a client that re-derived "today"
    from its own browser zone would mislabel every chart.
    """
    return {
        "preset": preset,
        "from": iso_utc(from_epoch_ms(window.start_ms)),
        "to": iso_utc(from_epoch_ms(window.end_ms)),
        "first_day": window.first_day,
        "last_day": window.last_day,
        "timezone": timezone,
    }


def analytics_daily_row_payload(row: DailyRow) -> dict[str, Any]:
    """One day of the §3.7 ``daily`` series, receiver activity included."""
    return {
        "day": row.day,
        "unique_aircraft": row.unique_aircraft,
        "new_aircraft": row.new_aircraft,
        "sightings": row.sightings,
        "interesting": row.interesting,
        "military": row.military,
        "government": row.government,
        "law_enforcement": row.law_enforcement,
        "max_range_nm": _rounded(row.max_range_nm),
        "busiest_hour": row.busiest_hour,
        "receiver_messages": row.messages_total,
        "receiver_positions": row.positions_total,
        "receiver_aircraft_max": row.aircraft_max,
        "receiver_max_range_nm": _rounded(row.receiver_max_range_nm),
    }


def analytics_summary_payload(summary: Summary) -> dict[str, Any]:
    """SPEC §59's at-a-glance block."""
    return {
        "unique_aircraft": summary.unique_aircraft,
        "new_aircraft": summary.new_aircraft,
        "sightings": summary.sightings,
        "interesting": summary.interesting,
        "military": summary.military,
        "government": summary.government,
        "law_enforcement": summary.law_enforcement,
        "max_range_nm": _rounded(summary.max_range_nm),
        "busiest_hour": summary.busiest_hour,
        "busiest_hour_source": summary.busiest_hour_source,
        "first_sighting_at": _at(summary.first_sighting_ms),
        "last_sighting_at": _at(summary.last_sighting_ms),
    }


def analytics_aircraft_payload(rank: AircraftRank) -> dict[str, Any]:
    """One airframe in a §3.7 ranking or rarity list."""
    return {
        "icao": rank.icao24,
        "registration": rank.registration,
        "type": rank.type_code,
        "model": rank.model,
        "operator": rank.operator_name,
        "operator_group": rank.operator_group,
        "classification": rank.mission_category,
        "military": rank.military,
        "government": rank.government,
        "law_enforcement": rank.law_enforcement,
        "sightings": rank.sightings,
        "first_seen_at": iso_utc(from_epoch_ms(rank.first_seen_ms)),
        "last_seen_at": iso_utc(from_epoch_ms(rank.last_seen_ms)),
        "max_range_nm": _rounded(rank.max_range_nm),
    }


def analytics_group_payload(rank: GroupRank) -> dict[str, Any]:
    """One type designator or operator group in a §3.7 ranking."""
    return {
        "key": rank.key,
        "label": rank.label,
        "sightings": rank.sightings,
        "unique_aircraft": rank.unique_aircraft,
        "days_seen": rank.days_seen,
        "first_seen_at": _at(rank.first_seen_ms),
        "last_seen_at": _at(rank.last_seen_ms),
    }


def analytics_rare_type_payload(rare: RareType) -> dict[str, Any]:
    """One locally rare type designator."""
    return {
        "type": rare.type_code,
        "unique_aircraft": rare.unique_aircraft,
        "total_sightings": rare.total_sightings,
        "first_seen_at": iso_utc(from_epoch_ms(rare.first_seen_ms)),
        "last_seen_at": iso_utc(from_epoch_ms(rare.last_seen_ms)),
    }


def _rounded(value: float | None) -> float | None:
    """A distance rounded to the API's documented precision, or ``None``."""
    return None if value is None else round(value, DISTANCE_DECIMALS)


__all__ = [
    "BEARING_DECIMALS",
    "DISTANCE_DECIMALS",
    "EXPOSED_PROVENANCE_FIELDS",
    "METADATA_PROVENANCE_KEYS",
    "NEAREST_AIRPORT_PROVENANCE",
    "aircraft_detail_payload",
    "aircraft_history_row_payload",
    "aircraft_payload",
    "airport_feature_collection_payload",
    "analytics_aircraft_payload",
    "analytics_daily_row_payload",
    "analytics_group_payload",
    "analytics_rare_type_payload",
    "analytics_summary_payload",
    "analytics_window_payload",
    "iso_utc",
    "lifetime_payload",
    "receiver_lifetime_stats_payload",
    "receiver_metric_series_payload",
    "receiver_payload",
    "receiver_range_by_bearing_payload",
    "receiver_scorecard_payload",
    "receiver_signal_distribution_payload",
    "sighting_detail_payload",
    "sighting_event_payload",
    "sighting_path_point_payload",
    "sighting_row_payload",
]
