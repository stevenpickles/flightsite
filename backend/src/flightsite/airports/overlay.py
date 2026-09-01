"""Bounding-box queries over the ``airports`` table for the map overlay (roadmap
slice 028).

Unlike :mod:`flightsite.airports.repository`, whose :meth:`~flightsite.airports.
repository.AirportRepository.load_all` builds the in-memory nearest-airport index
once at startup, this module answers a fresh SQL query on every call. That is
deliberate, not an oversight of ``docs/ARCHITECTURE.md`` §3.1's "no live request
or decoder poll ever waits on SQLite": the overlay answers ``GET
/api/v1/airports``, a REST read the map fires once per (debounced) viewport move,
not a per-observation lookup on the decoder path. Caching the whole dataset in a
Python structure the request handler then filtered itself would duplicate what
``ix_airports_lat`` (``lat``, ``lon`` — added for exactly this "bounding box"
lookup shape in ``docs/DATA_MODEL.md`` §3.6, though the nearest-airport path
never itself queries it) already does at the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from sqlalchemy import case, select

from flightsite.airports.records import AirportRecord
from flightsite.db import Airport, Database

#: The overlay's own size-class vocabulary — the query-param and GeoJSON
#: ``properties.size_class`` spelling, friendlier than the upstream ``type``
#: column's ``*_airport`` suffix.
AirportSizeClass = Literal["large", "medium", "small", "heliport"]

#: Upstream ``type`` values in largest-first order, and the priority a bbox
#: query sorts and caps by. Mirrors :data:`flightsite.airports.records.
#: IMPORTED_AIRPORT_TYPES` exactly — a row whose ``type`` is not one of these
#: four (never true for an imported row today) sorts last via the query's
#: ``else_`` branch rather than being excluded.
SIZE_PRIORITY: Final[dict[str, int]] = {
    "large_airport": 0,
    "medium_airport": 1,
    "small_airport": 2,
    "heliport": 3,
}

#: :data:`AirportSizeClass` to the upstream ``type`` value it names.
SIZE_CLASS_TYPES: Final[dict[AirportSizeClass, str]] = {
    "large": "large_airport",
    "medium": "medium_airport",
    "small": "small_airport",
    "heliport": "heliport",
}

#: The inverse of :data:`SIZE_CLASS_TYPES` — how a row's ``type`` serializes
#: into the overlay's GeoJSON ``size_class`` property.
TYPE_SIZE_CLASSES: Final[dict[str, AirportSizeClass]] = {
    value: key for key, value in SIZE_CLASS_TYPES.items()
}

#: Airports returned in one response, largest-first once a bbox holds more
#: than this. High enough that a realistic viewport never hits it outside a
#: continent-wide zoom-out; low enough that the response — and the symbol
#: layer it feeds — both stay well clear of "so many markers it's a wall of
#: ink" (roadmap slice 028: "perform acceptably").
MAX_AIRPORTS_RESPONSE: Final = 1_500


class BboxError(ValueError):
    """A ``bbox`` query parameter could not be parsed as a bounding box."""


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """A WGS-84 bounding box, ``west,south,east,north`` — OGC/GeoJSON bbox order.

    Deliberately does not wrap the antimeridian: :func:`parse_bbox` requires
    ``west <= east``. A viewport that straddles ±180° is a real but rare case
    this slice does not attempt — MapLibre's own ``getBounds()`` on a
    receiver-centred Live Map does not itself cross it at any zoom level the
    frontend uses, so the simplification costs nothing a real session hits.
    """

    west: float
    south: float
    east: float
    north: float


def parse_bbox(raw: str) -> BoundingBox:
    """Parse the ``bbox`` query parameter, or raise :class:`BboxError`.

    Expects exactly four comma-separated decimal-degree floats in
    ``west,south,east,north`` order (the same order GeoJSON's own ``bbox``
    member and most map-viewport APIs use), each within its coordinate's
    valid range, with ``west <= east`` and ``south <= north``.
    """
    parts = raw.split(",")
    if len(parts) != 4:
        raise BboxError(f"bbox must have exactly 4 comma-separated values, got {len(parts)}")
    try:
        west, south, east, north = (float(part) for part in parts)
    except ValueError as exc:
        raise BboxError(f"bbox values must be numbers: {raw!r}") from exc
    if not -180.0 <= west <= 180.0 or not -180.0 <= east <= 180.0:
        raise BboxError(f"bbox longitude out of range: {raw!r}")
    if not -90.0 <= south <= 90.0 or not -90.0 <= north <= 90.0:
        raise BboxError(f"bbox latitude out of range: {raw!r}")
    if west > east:
        raise BboxError(
            "bbox west must not exceed east (antimeridian-crossing bbox is not supported)"
        )
    if south > north:
        raise BboxError("bbox south must not exceed north")
    return BoundingBox(west=west, south=south, east=east, north=north)


@dataclass(frozen=True, slots=True)
class AirportOverlayRepository:
    """Answers ``GET /api/v1/airports`` from the ``airports`` table directly."""

    database: Database

    async def query(
        self,
        *,
        bbox: BoundingBox | None = None,
        min_size: AirportSizeClass | None = None,
        limit: int = MAX_AIRPORTS_RESPONSE,
    ) -> list[AirportRecord]:
        """Airports in ``bbox`` (or the whole table) at or above ``min_size``.

        Ordered largest-first and capped at ``limit``: the overlay's job when
        there are more airports than a viewport can usefully hold is to show
        the most significant fields, not an arbitrary subset of them.

        Args:
            bbox: restricts to airports whose coordinate falls inside the
                box, via ``ix_airports_lat``'s ``(lat, lon)`` index. ``None``
                queries the whole table.
            min_size: the smallest size class to include — ``"medium"``
                returns ``large`` and ``medium`` airports, never ``small`` or
                ``heliport``. ``None`` includes every imported size class.
            limit: caps the result at this many rows, largest-first.
        """
        priority = case(
            *((Airport.type == type_, rank) for type_, rank in SIZE_PRIORITY.items()),
            else_=len(SIZE_PRIORITY),
        )
        statement = (
            select(
                Airport.ident,
                Airport.iata,
                Airport.name,
                Airport.type,
                Airport.lat,
                Airport.lon,
                Airport.elevation_ft,
                Airport.iso_country,
            )
            .order_by(priority, Airport.ident)
            .limit(limit)
        )

        if bbox is not None:
            statement = statement.where(
                Airport.lat >= bbox.south,
                Airport.lat <= bbox.north,
                Airport.lon >= bbox.west,
                Airport.lon <= bbox.east,
            )
        if min_size is not None:
            ceiling = SIZE_PRIORITY[SIZE_CLASS_TYPES[min_size]]
            allowed = [type_ for type_, rank in SIZE_PRIORITY.items() if rank <= ceiling]
            statement = statement.where(Airport.type.in_(allowed))

        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).all()
        return [
            AirportRecord(
                ident=ident,
                iata=iata,
                name=name,
                type=type_,
                lat=lat,
                lon=lon,
                elevation_ft=elevation_ft,
                iso_country=iso_country,
            )
            for ident, iata, name, type_, lat, lon, elevation_ft, iso_country in rows
        ]


__all__ = [
    "MAX_AIRPORTS_RESPONSE",
    "SIZE_CLASS_TYPES",
    "SIZE_PRIORITY",
    "TYPE_SIZE_CLASSES",
    "AirportOverlayRepository",
    "AirportSizeClass",
    "BboxError",
    "BoundingBox",
    "parse_bbox",
]
