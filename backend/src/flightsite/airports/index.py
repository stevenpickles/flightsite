"""The in-memory nearest-airport index.

``docs/ARCHITECTURE.md`` §3.1: *no live request or decoder poll ever waits on
SQLite.* A nearest-airport question arrives once per low aircraft per decoder
poll, so it cannot be a query — it has to be answered from memory, and this is
the structure that answers it.

Why a grid, and why this one
----------------------------

``docs/DATA_MODEL.md`` §3.6 describes the lookup as *"bounding-box on the
``(lat, lon)`` index, refined by great-circle in code"* and notes that at this
row count no R*Tree is needed. The same reasoning applies one level up: the
whole dataset is ~70k rows of eight small fields, so it fits in memory, and
once it is in memory the bounding box is a dictionary lookup rather than a
b-tree descent.

Airports are bucketed into fixed half-degree cells. A query computes the cells
its search radius can reach, walks only those, and measures the handful of
candidates in them with the same haversine
(:func:`flightsite.live.geo.distance_nm`) the receiver-relative distances use.
Over a 30 nm radius that is at most a few dozen cells, and in the sky a
receiver actually sees, a few dozen airports.

Two geometries the grid has to survive, both of which have tests:

* **Longitude convergence.** A cell is half a degree wide in *longitude*, which
  is 30 nm at the equator and metres near the pole. The number of cells a
  radius spans is therefore computed from the query's own latitude, and above
  :data:`POLAR_LATITUDE_DEG` — or whenever the span would exceed half the world
  — the whole latitude band is scanned instead. Scanning a band is cheap
  precisely because almost nothing is bucketed up there.
* **The antimeridian.** Longitude cells are indexed from ``-180`` and taken
  modulo the number of cells, so a query at 179.9°E reaches candidates at
  179.9°W without a special case and without a seam.

The index is immutable once built. A re-import builds a new one and the service
swaps its reference — a single atomic attribute assignment — so a query in
flight during an import reads the whole old index rather than a half-replaced
one. That is the same invalidation discipline
:class:`~flightsite.metadata.cache.MetadataCache` follows.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from typing import Final, NamedTuple

from flightsite.airports.records import AirportRecord
from flightsite.ingest import Position
from flightsite.live.geo import distance_nm

#: Cell size in degrees, in both axes. Half a degree is 30 nm of latitude —
#: about the widest search this index is ever asked for — so a typical query
#: touches a 3x3 to 5x5 neighbourhood. Smaller cells would mean more of them to
#: walk per query for fewer candidates each; larger ones would mean measuring
#: airports that were never plausible.
CELL_DEG: Final = 0.5

#: Cells spanning the full latitude range, ``-90`` to ``+90``.
LAT_CELLS: Final = int(180 / CELL_DEG)

#: Cells spanning the full longitude range, ``-180`` to ``+180``. Indices are
#: taken modulo this, which is what makes the antimeridian a non-event.
LON_CELLS: Final = int(360 / CELL_DEG)

#: Nautical miles in one degree of latitude, exactly by definition of the
#: nautical mile as one minute of arc.
NM_PER_DEGREE_LATITUDE: Final = 60.0

#: Above this latitude, a query scans its whole latitude band rather than
#: computing a longitude span. The convergence of the meridians makes the span
#: grow without bound approaching the pole, and there is almost nothing up
#: there to walk.
POLAR_LATITUDE_DEG: Final = 85.0


class NearestAirport(NamedTuple):
    """An airport and how far the query point is from it."""

    airport: AirportRecord
    distance_nm: float


def _lat_cell(lat: float) -> int:
    """The latitude cell holding ``lat``, clamped into range.

    The clamp matters only at exactly ±90°, which would otherwise index one
    cell past the end.
    """
    return min(LAT_CELLS - 1, max(0, int((lat + 90.0) / CELL_DEG)))


def _lon_cell(lon: float) -> int:
    """The longitude cell holding ``lon``, wrapped into range.

    Modular rather than clamped: longitude is cyclic, so ``180.0`` and
    ``-180.0`` are the same meridian and must land in the same cell.
    """
    return int((lon + 180.0) % 360.0 / CELL_DEG) % LON_CELLS


class AirportIndex:
    """A read-only spatial index over a set of airports.

    Built once from a dataset and never mutated. Construction buckets every
    record; queries walk cells. An empty index — the normal state on an install
    that has never run an import — answers every query with ``None`` at the
    cost of one dictionary miss.

    Args:
        airports: the dataset to index. Order matters only for tie-breaking,
            which the repository makes deterministic by loading in ident order.
    """

    __slots__ = ("_by_ident", "_cells", "_size")

    def __init__(self, airports: Iterable[AirportRecord] = ()) -> None:
        cells: dict[tuple[int, int], list[AirportRecord]] = {}
        by_ident: dict[str, AirportRecord] = {}
        for airport in airports:
            by_ident[airport.ident] = airport
            cells.setdefault((_lat_cell(airport.lat), _lon_cell(airport.lon)), []).append(airport)
        self._cells = cells
        self._by_ident = by_ident
        self._size = len(by_ident)

    def __len__(self) -> int:
        return self._size

    @property
    def size(self) -> int:
        """How many airports this index holds."""
        return self._size

    def get(self, ident: str) -> AirportRecord | None:
        """The airport with this ident, or ``None``.

        Not part of the nearest-airport path; it is how a caller holding only a
        stored ``inferred_airport_ident`` gets a name back without a query.
        """
        return self._by_ident.get(ident.upper())

    def nearest(self, position: Position, *, within_nm: float) -> NearestAirport | None:
        """The closest airport within ``within_nm``, or ``None`` if none is.

        Ties are broken by ident so the answer is stable: two airports at
        genuinely identical range — a heliport on an airport's own field, which
        does happen — must not alternate between polls.
        """
        if within_nm <= 0.0 or not self._cells:
            return None

        best: NearestAirport | None = None
        for airport in self._candidates(position, within_nm):
            distance = distance_nm(position, Position(latitude=airport.lat, longitude=airport.lon))
            if distance > within_nm:
                continue
            if best is None or (distance, airport.ident) < (best.distance_nm, best.airport.ident):
                best = NearestAirport(airport=airport, distance_nm=distance)
        return best

    def _candidates(self, position: Position, within_nm: float) -> Iterator[AirportRecord]:
        """Every airport bucketed in a cell the search radius can reach.

        Deliberately generous: a cell is included whenever any part of it could
        hold a point inside the radius, and the caller measures. Being wrong in
        this direction costs a haversine call; being wrong in the other would
        lose an airport.
        """
        lat_span = math.ceil(within_nm / NM_PER_DEGREE_LATITUDE / CELL_DEG)
        centre_lat = _lat_cell(position.latitude)
        centre_lon = _lon_cell(position.longitude)

        for lat_offset in range(-lat_span, lat_span + 1):
            lat_cell = centre_lat + lat_offset
            if not 0 <= lat_cell < LAT_CELLS:
                # Past a pole. The band does not exist rather than wrapping
                # onto the far side of the world, which is what a modulus here
                # would silently do.
                continue
            for lon_cell in self._lon_cells(lat_cell, centre_lon, within_nm):
                yield from self._cells.get((lat_cell, lon_cell), ())

    @staticmethod
    def _lon_cells(lat_cell: int, centre_lon: int, within_nm: float) -> Sequence[int]:
        """The longitude cells to walk in one latitude band.

        The band's own latitude decides the span, not the query's: a search
        centred at 60°N reaching two bands north covers more longitude up there
        than it does at its centre, and using the centre's span would clip the
        corners off the search area.
        """
        band_lat = abs((lat_cell + 0.5) * CELL_DEG - 90.0)
        if band_lat >= POLAR_LATITUDE_DEG:
            return range(LON_CELLS)
        # Degrees of longitude the radius spans at this latitude. The meridians
        # converge by cos(latitude), so this grows as the band approaches a
        # pole, and the guard above catches the point where it stops being a
        # useful number at all.
        span_deg = within_nm / (NM_PER_DEGREE_LATITUDE * math.cos(math.radians(band_lat)))
        if span_deg >= 180.0:
            return range(LON_CELLS)
        span = math.ceil(span_deg / CELL_DEG)
        return [(centre_lon + offset) % LON_CELLS for offset in range(-span, span + 1)]


__all__ = [
    "CELL_DEG",
    "LAT_CELLS",
    "LON_CELLS",
    "NM_PER_DEGREE_LATITUDE",
    "POLAR_LATITUDE_DEG",
    "AirportIndex",
    "NearestAirport",
]
