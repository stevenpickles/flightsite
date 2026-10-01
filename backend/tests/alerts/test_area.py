"""The drawn-area geometry: which rings are refused, and what is inside one.

Slice 089's ``within_area`` condition (issue #232). The roadmap names two edge
cases outright — *antimeridian excluded, holes rejected* — and the rest are
the ones point-in-polygon code gets wrong in practice: a point exactly on an
edge or a vertex, a ray passing through a vertex, a point outside the bounding
box entirely, and a concave ring whose notch is outside.
"""

from __future__ import annotations

import math

import pytest

from flightsite.alerts.area import (
    MAX_AREA_VERTICES,
    CompiledArea,
    Vertex,
    normalize_ring,
)

SQUARE: list[Vertex] = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]

#: A "C" opening to the east: the notch (1.5..2, 0.5..1.5) is outside.
CONCAVE: list[Vertex] = [
    (0.0, 0.0),
    (2.0, 0.0),
    (2.0, 0.5),
    (1.0, 0.5),
    (1.0, 1.5),
    (2.0, 1.5),
    (2.0, 2.0),
    (0.0, 2.0),
]


def compiled(ring: list[Vertex]) -> CompiledArea:
    return CompiledArea.from_ring(normalize_ring(ring))


# ---------------------------------------------------------------- the ring


def test_an_unclosed_ring_is_closed() -> None:
    ring = normalize_ring(SQUARE)

    assert ring[0] == ring[-1]
    assert len(ring) == len(SQUARE) + 1


def test_an_already_closed_ring_is_left_as_it_is() -> None:
    closed = [*SQUARE, SQUARE[0]]

    assert normalize_ring(closed) == tuple(closed)


def test_a_triangle_is_the_smallest_area() -> None:
    normalize_ring([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
    with pytest.raises(ValueError, match="between 3 and 64"):
        normalize_ring([(0.0, 0.0), (1.0, 0.0)])


def test_the_closing_vertex_does_not_count_towards_the_minimum() -> None:
    with pytest.raises(ValueError, match="got 2"):
        normalize_ring([(0.0, 0.0), (1.0, 0.0), (0.0, 0.0)])


def test_sixty_four_vertices_is_the_most() -> None:
    def circle(count: int) -> list[Vertex]:
        return [
            (math.cos(2 * math.pi * k / count), math.sin(2 * math.pi * k / count))
            for k in range(count)
        ]

    assert len(normalize_ring(circle(MAX_AREA_VERTICES))) == MAX_AREA_VERTICES + 1
    with pytest.raises(ValueError, match="got 65"):
        normalize_ring(circle(MAX_AREA_VERTICES + 1))


@pytest.mark.parametrize(
    ("vertex", "message"),
    [
        ((181.0, 0.0), "longitude 181"),
        ((0.0, -91.0), "latitude -91"),
        ((float("nan"), 0.0), "finite"),
    ],
)
def test_coordinates_out_of_range_are_refused(vertex: Vertex, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_ring([(0.0, 0.0), (1.0, 0.0), vertex])


def test_a_ring_crossing_the_antimeridian_is_refused() -> None:
    """179°E to 179°W is two degrees the short way and 358 the long way; plain
    longitude/latitude arithmetic would take the long way, so the ring is
    refused instead of evaluated as a band around the planet."""
    with pytest.raises(ValueError, match="antimeridian"):
        normalize_ring([(179.0, 10.0), (-179.0, 10.0), (-179.0, 12.0), (179.0, 12.0)])


def test_a_ring_touching_but_not_crossing_the_antimeridian_is_accepted() -> None:
    normalize_ring([(178.0, 10.0), (180.0, 10.0), (180.0, 12.0), (178.0, 12.0)])


def test_a_self_intersecting_ring_is_refused() -> None:
    bow_tie = [(0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0)]

    with pytest.raises(ValueError, match="crosses edge"):
        normalize_ring(bow_tie)


def test_a_ring_folding_back_on_itself_is_refused() -> None:
    spike = [(0.0, 0.0), (2.0, 0.0), (1.0, 0.0), (1.0, 1.0)]

    with pytest.raises(ValueError, match=r"folds back|crosses"):
        normalize_ring(spike)


def test_a_repeated_vertex_is_refused() -> None:
    with pytest.raises(ValueError, match="repeated"):
        normalize_ring([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (1.0, 0.0), (0.0, 1.0)])


def test_a_collinear_ring_is_refused() -> None:
    with pytest.raises(ValueError, match=r"collinear|folds back"):
        normalize_ring([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])


# ----------------------------------------------------------- containment


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((1.0, 1.0), True),  # the middle
        ((0.0001, 1.9999), True),  # just inside a corner
        ((3.0, 1.0), False),  # bounding-box miss, east
        ((1.0, -0.5), False),  # bounding-box miss, south
        ((2.0, 1.0), True),  # on a vertical edge
        ((1.0, 0.0), True),  # on a horizontal edge
        ((1.0, 2.0), True),  # on the top edge
        ((0.0, 0.0), True),  # exactly on a vertex
        ((2.0, 2.0), True),  # the opposite vertex
        ((2.0000001, 1.0), False),  # a hair outside the edge
    ],
)
def test_containment_in_a_square(point: Vertex, expected: bool) -> None:
    assert compiled(SQUARE).contains(*point) is expected


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((0.5, 1.0), True),  # the solid spine
        ((1.5, 1.0), False),  # inside the bounding box, in the notch
        ((1.5, 0.25), True),  # the lower arm
        ((1.5, 1.75), True),  # the upper arm
        ((1.0, 1.0), True),  # on the notch's inner edge
        # A ray from (0.5, 0.5) east passes exactly through the vertices
        # (1, 0.5) and (2, 0.5): the half-open test must count it once.
        ((0.5, 0.5), True),
        ((1.5, 0.5), True),  # on the horizontal notch edge
    ],
)
def test_containment_in_a_concave_ring(point: Vertex, expected: bool) -> None:
    assert compiled(CONCAVE).contains(*point) is expected


def test_the_bounding_box_is_the_ring_extent() -> None:
    area = compiled(CONCAVE)

    assert (area.min_lon, area.max_lon, area.min_lat, area.max_lat) == (0.0, 2.0, 0.0, 2.0)
    assert area.edge_count == len(CONCAVE)


def test_containment_works_west_of_greenwich_and_south_of_the_equator() -> None:
    """Negative coordinates are where sign mistakes in ray casting surface."""
    area = compiled([(-3.0, -51.0), (-1.0, -51.0), (-1.0, -49.0), (-3.0, -49.0)])

    assert area.contains(-2.0, -50.0)
    assert not area.contains(-0.5, -50.0)
    assert not area.contains(-2.0, -48.0)


def _naive_contains(ring: list[Vertex], lon: float, lat: float) -> bool:
    """Textbook even-odd ray casting over every edge: no banding, no box."""
    inside = False
    count = len(ring)
    for index in range(count):
        (x1, y1), (x2, y2) = ring[index], ring[(index + 1) % count]
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def test_banded_containment_agrees_with_naive_ray_casting_on_a_64_point_star() -> None:
    """The latitude bands are an optimisation and must never change an answer.

    A 64-vertex star is the adversarial shape for banding: long spikes span
    many bands and deep notches put "outside" between "inside" on one row.
    The sample grid's spacing keeps it off the boundary, where the two differ
    by design (the boundary is inside).
    """
    star: list[Vertex] = [
        (
            -1.0 + (1.0 if k % 2 == 0 else 0.35) * math.cos(2 * math.pi * k / 64),
            51.0 + (1.0 if k % 2 == 0 else 0.35) * math.sin(2 * math.pi * k / 64),
        )
        for k in range(64)
    ]
    area = compiled(star)
    disagreements = [
        (lon, lat)
        for lon in (-2.05 + i * 0.0137 for i in range(300))
        for lat in (49.95 + j * 0.0141 for j in range(150))
        if area.contains(lon, lat) != _naive_contains(star, lon, lat)
    ]

    assert disagreements == []
