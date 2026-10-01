"""The drawn-area condition's geometry: ring validation and point-in-polygon.

Slice 089 lets a rule say *"inside this area"* (issue #232), with the area
drawn on a mini-map in the rule builder. This module is the arithmetic behind
that condition and nothing else — the stored shape, its reason phrase and its
place in the ``AND`` live in :mod:`flightsite.alerts.model`, so this file has
no Pydantic and no imports from the rest of the package.

What a valid area is
--------------------

One **simple polygon**: a single ring of ``[longitude, latitude]`` pairs in
decimal degrees, GeoJSON's axis order (RFC 7946 §3.1.1) because that is what
MapLibre hands the builder and what any tool a user might paste from emits.
:func:`normalize_ring` refuses everything else, at write time, with a message
naming what is wrong — a shape that cannot be evaluated unambiguously is a rule
whose behaviour cannot be explained, which is the same reason
:class:`~flightsite.alerts.model.RuleConditions` refuses an inverted window.

* **3 to 64 distinct vertices.** Fewer is not an area; more is not something a
  person draws by hand on a mini-map, and the bound is what keeps the cost of
  one containment test fixed (see below).
* **Closed or auto-closed.** A ring whose last vertex repeats its first is
  GeoJSON's closed form; one that does not is closed here. Either way the
  stored ring is closed, so a round trip through the API is a fixed point.
* **No holes.** GeoJSON spells a hole as a second ring. The condition has one
  ring; :class:`~flightsite.alerts.model.AreaCondition` refuses a second with
  a message rather than ignoring it, because silently dropping a hole would be
  a rule matching the very area the user cut out.
* **No antimeridian crossing.** An edge whose longitudes differ by more than
  180° is ambiguous — it could go either way round the planet — and the
  evaluation below works in plain longitude/latitude, where such an edge would
  span the whole world the wrong way. A user near 180° draws two rules.
* **No self-intersection, no zero area.** A figure-eight has no single answer
  to "inside" (ray casting gives the even-odd one, which is not what anyone
  drew), and a ring whose vertices are collinear encloses nothing.

Edges are straight lines in longitude/latitude. For the areas this is drawn
for — tens of nautical miles around a receiver — that is indistinguishable
from what the map displays, and it is what makes the test below cheap.

What evaluation costs
---------------------

A ring is compiled **once**, when its rule document is parsed (which happens
when the engine's rule set is reloaded, not per aircraft and not per cycle),
into a :class:`CompiledArea`: a bounding box and a flat tuple of edges. A
containment test is then a four-comparison bounding-box rejection — which is
what nearly every aircraft in a 500-aircraft sky gets for an area of a few
miles — and, for a point inside the box, one ray-casting pass over only the
edges of the latitude band the point falls in (a handful, even at 64 vertices;
see :class:`CompiledArea`), with no allocation.

A point **on** the boundary counts as inside (within :data:`EDGE_TOLERANCE_DEG`).
Ray casting's own answer on an edge depends on which way the edge happens to
run; a user who drew the boundary along a runway means the runway.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

#: Bounds on a ring's distinct vertex count. See the module docstring.
MIN_AREA_VERTICES: Final = 3
MAX_AREA_VERTICES: Final = 64

#: How close to an edge, in degrees, a point counts as on it. About a tenth
#: of a millimetre on the ground: tolerance for float rounding, not a buffer.
EDGE_TOLERANCE_DEG: Final = 1e-9

#: A vertex in GeoJSON axis order: ``(longitude, latitude)``.
Vertex = tuple[float, float]


def _orientation(a: Vertex, b: Vertex, c: Vertex) -> float:
    """Twice the signed area of triangle ``abc``: >0 left turn, <0 right, 0 collinear."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _within_box(a: Vertex, b: Vertex, p: Vertex) -> bool:
    """Whether ``p`` lies inside the axis-aligned box spanned by segment ``ab``."""
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _segments_intersect(a: Vertex, b: Vertex, c: Vertex, d: Vertex) -> bool:
    """Whether closed segments ``ab`` and ``cd`` share any point."""
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if ((o1 > 0 and o2 < 0) or (o1 < 0 and o2 > 0)) and (
        (o3 > 0 and o4 < 0) or (o3 < 0 and o4 > 0)
    ):
        return True
    return (
        (o1 == 0 and _within_box(a, b, c))
        or (o2 == 0 and _within_box(a, b, d))
        or (o3 == 0 and _within_box(c, d, a))
        or (o4 == 0 and _within_box(c, d, b))
    )


def _check_vertex(index: int, vertex: Vertex) -> None:
    lon, lat = vertex
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise ValueError(f"vertex {index + 1} is not a finite coordinate")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(
            f"vertex {index + 1} has longitude {lon:g}, outside -180 to 180 "
            "(coordinates are [longitude, latitude])"
        )
    if not -90.0 <= lat <= 90.0:
        raise ValueError(
            f"vertex {index + 1} has latitude {lat:g}, outside -90 to 90 "
            "(coordinates are [longitude, latitude])"
        )


def normalize_ring(points: Sequence[Vertex]) -> tuple[Vertex, ...]:
    """Validate one ring and return it closed. See the module docstring.

    Raises:
        ValueError: naming the first thing wrong with the ring, in terms a
            person who drew it can act on.
    """
    ring = [(float(lon), float(lat)) for lon, lat in points]
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    count = len(ring)
    if not MIN_AREA_VERTICES <= count <= MAX_AREA_VERTICES:
        raise ValueError(
            f"an area needs between {MIN_AREA_VERTICES} and {MAX_AREA_VERTICES} "
            f"distinct vertices (got {count})"
        )
    for index, vertex in enumerate(ring):
        _check_vertex(index, vertex)
    if len(set(ring)) != count:
        raise ValueError("an area's vertices must be distinct: a vertex is repeated")

    edges = [(ring[index], ring[(index + 1) % count]) for index in range(count)]
    for start, end in edges:
        if abs(end[0] - start[0]) > 180.0:
            raise ValueError(
                "an area may not cross the antimeridian (180° longitude): "
                "split it into two rules, one each side"
            )

    for i in range(count):
        a, b = edges[i]
        # Adjacent edges share a vertex by construction; what they must not do
        # is fold back over each other (a spike), which is collinear overlap.
        _, after = edges[(i + 1) % count]
        if _orientation(a, b, after) == 0 and (
            (b[0] - a[0]) * (after[0] - b[0]) + (b[1] - a[1]) * (after[1] - b[1]) < 0
        ):
            raise ValueError(
                f"an area's edges may not cross: the edge at vertex {i + 2} folds back"
            )
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue  # the closing edge is adjacent to the first
            c, d = edges[j]
            if _segments_intersect(a, b, c, d):
                raise ValueError(
                    f"an area's edges may not cross: edge {i + 1} crosses edge {j + 1}"
                )
    # After the crossing check, so a figure-eight (whose signed lobes cancel)
    # is reported as crossing rather than as empty.
    doubled_area = sum(a[0] * b[1] - b[0] * a[1] for a, b in edges)
    if abs(doubled_area) <= EDGE_TOLERANCE_DEG**2:
        raise ValueError("an area must enclose some area: its vertices are collinear")
    return (*ring, ring[0])


#: Edge = ``(lon1, lat1, lon2, lat2, dlon_per_dlat)``: flat, so the hot loop
#: unpacks five floats rather than nested tuples, with the inverse slope
#: precomputed so a crossing costs a multiply rather than a divide.
#: Horizontal edges carry ``0.0`` there; their slope is never used.
Edge = tuple[float, float, float, float, float]

#: Most latitude bands a compiled area is split into. See :class:`CompiledArea`.
MAX_BANDS: Final = 16


@dataclass(frozen=True, slots=True)
class CompiledArea:
    """A validated ring, pre-arranged for cheap containment tests.

    Built once per rule document by :meth:`from_ring`; :meth:`contains` is the
    per-aircraft call and allocates nothing.

    Beyond the bounding box, the ring's latitude extent is cut into up to
    :data:`MAX_BANDS` equal bands, each holding only the edges whose latitude
    span touches it. A horizontal ray at latitude *y* can only cross an edge
    whose span contains *y*, so testing the one band *y* falls in gives the
    same answer as testing every edge — and for a 64-vertex ring drawn as a
    rough circle it tests around eight edges instead of sixty-four. The band
    index is computed by the same expression for an edge's ends and for a
    point, so an edge ending exactly on a band boundary is always found.
    """

    min_lon: float
    max_lon: float
    min_lat: float
    max_lat: float
    #: Latitude height of one band, and the bands themselves.
    band_height: float
    bands: tuple[tuple[Edge, ...], ...]
    vertices: frozenset[Vertex]

    @classmethod
    def from_ring(cls, ring: Sequence[Vertex]) -> CompiledArea:
        """Compile a ring :func:`normalize_ring` has already accepted (closed)."""
        open_ring = list(ring[:-1]) if len(ring) > 1 and ring[0] == ring[-1] else list(ring)
        lons = [vertex[0] for vertex in open_ring]
        lats = [vertex[1] for vertex in open_ring]
        count = len(open_ring)
        min_lat, max_lat = min(lats), max(lats)
        band_count = min(MAX_BANDS, count)
        band_height = (max_lat - min_lat) / band_count
        edges: list[Edge] = []
        for index in range(count):
            (x1, y1), (x2, y2) = open_ring[index], open_ring[(index + 1) % count]
            edges.append((x1, y1, x2, y2, 0.0 if y1 == y2 else (x2 - x1) / (y2 - y1)))

        def band_of(lat: float) -> int:
            return min(band_count - 1, int((lat - min_lat) / band_height))

        bands: list[list[Edge]] = [[] for _ in range(band_count)]
        for edge in edges:
            low, high = sorted((edge[1], edge[3]))
            for band in range(band_of(low), band_of(high) + 1):
                bands[band].append(edge)
        return cls(
            min_lon=min(lons),
            max_lon=max(lons),
            min_lat=min_lat,
            max_lat=max_lat,
            band_height=band_height,
            bands=tuple(tuple(band) for band in bands),
            vertices=frozenset(open_ring),
        )

    @property
    def edge_count(self) -> int:
        """Distinct edges in the ring (an edge spanning bands is counted once)."""
        return len({edge for band in self.bands for edge in band})

    def contains(self, lon: float, lat: float) -> bool:
        """Whether ``(lon, lat)`` is inside the area or on its boundary.

        Bounding box first; then even-odd ray casting towards +longitude over
        the point's latitude band, with the half-open
        ``(lat1 > lat) != (lat2 > lat)`` test so a ray through a vertex is
        counted once. Points on an edge, on a horizontal edge, or exactly on
        a vertex are inside — see the module docstring.
        """
        if lon < self.min_lon or lon > self.max_lon or lat < self.min_lat or lat > self.max_lat:
            return False
        bands = self.bands
        band = min(len(bands) - 1, int((lat - self.min_lat) / self.band_height))
        inside = False
        for x1, y1, x2, y2, slope in bands[band]:
            if (y1 > lat) != (y2 > lat):
                crossing = x1 + (lat - y1) * slope
                if abs(crossing - lon) <= EDGE_TOLERANCE_DEG:
                    return True
                if lon < crossing:
                    inside = not inside
            elif y1 == lat == y2 and min(x1, x2) <= lon <= max(x1, x2):
                return True
        return inside or (lon, lat) in self.vertices


__all__ = [
    "EDGE_TOLERANCE_DEG",
    "MAX_AREA_VERTICES",
    "MAX_BANDS",
    "MIN_AREA_VERTICES",
    "CompiledArea",
    "Edge",
    "Vertex",
    "normalize_ring",
]
