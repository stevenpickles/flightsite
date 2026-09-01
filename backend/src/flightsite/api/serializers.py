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

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from flightsite.config import Settings
from flightsite.ingest import Position
from flightsite.live import LiveAircraft
from flightsite.metadata.cache import AircraftMetadataView
from flightsite.sightings.state import SightingRoute
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


def _provenance(
    record: LiveAircraft,
    metadata: AircraftMetadataView | None,
    route: SightingRoute | None,
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
    return found


def aircraft_payload(
    record: LiveAircraft,
    *,
    sighting_id: int | None = None,
    metadata: AircraftMetadataView | None = None,
    route: SightingRoute | None = None,
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
        "interesting": None,
        "provenance": _provenance(record, metadata, route),
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


__all__ = [
    "BEARING_DECIMALS",
    "DISTANCE_DECIMALS",
    "EXPOSED_PROVENANCE_FIELDS",
    "METADATA_PROVENANCE_KEYS",
    "aircraft_payload",
    "iso_utc",
    "receiver_payload",
]
