"""``flightsite.airports.overlay`` — bbox/size-class queries and ``bbox`` parsing
for the map overlay (roadmap slice 028).
"""

from __future__ import annotations

import pytest

from flightsite.airports import AirportRepository
from flightsite.airports.overlay import (
    AirportOverlayRepository,
    BboxError,
    BoundingBox,
    parse_bbox,
)
from flightsite.db import Database

from .conftest import BASE_EPOCH_MS, BOEING_FIELD, SEATTLE_TACOMA, airport

#: A small deliberate world: two large fields near each other, a small field
#: and a heliport nearby, a medium field far away, and a large field on the
#: other side of the world — enough to exercise bbox, size-class and
#: largest-first-cap independently.
WORLD = (
    airport("KBFI", *BOEING_FIELD, name="Boeing Field", type="large_airport", iata="BFI"),
    airport("KSEA", *SEATTLE_TACOMA, name="Seattle-Tacoma International", type="large_airport"),
    airport("S60", 47.33, -122.23, name="Auburn Municipal", type="small_airport"),
    airport("W16", 47.60, -122.20, name="A Heliport", type="heliport"),
    airport("KFAR", 46.9207, -96.8158, name="Hector International", type="medium_airport"),
    airport("FAR_AWAY", 10.0, 10.0, name="Far Away Field", type="large_airport"),
)


@pytest.fixture
async def seeded(database: Database, repository: AirportRepository) -> AirportOverlayRepository:
    """The overlay repository over a database holding :data:`WORLD`."""
    await repository.replace_all(
        WORLD, source="airports", at_ms=BASE_EPOCH_MS, dataset_version="fixture"
    )
    return AirportOverlayRepository(database)


# ------------------------------------------------------------------- parse_bbox


def test_parses_west_south_east_north_order() -> None:
    assert parse_bbox("-123.5,47.0,-121.5,48.0") == BoundingBox(
        west=-123.5, south=47.0, east=-121.5, north=48.0
    )


@pytest.mark.parametrize(
    "raw",
    [
        "1,2,3",
        "1,2,3,4,5",
        "a,b,c,d",
        "-200,0,10,10",
        "0,-100,10,10",
        "10,0,-10,10",
        "0,10,10,0",
    ],
)
def test_rejects_malformed_or_out_of_range_bbox(raw: str) -> None:
    with pytest.raises(BboxError):
        parse_bbox(raw)


# ------------------------------------------------------------------------ bbox


async def test_bbox_restricts_to_airports_inside_it(seeded: AirportOverlayRepository) -> None:
    bbox = BoundingBox(west=-123.0, south=47.0, east=-121.5, north=48.0)

    records = await seeded.query(bbox=bbox)

    assert {r.ident for r in records} == {"KBFI", "KSEA", "S60", "W16"}


async def test_no_bbox_queries_the_whole_table(seeded: AirportOverlayRepository) -> None:
    records = await seeded.query(bbox=None)

    assert {r.ident for r in records} == {r.ident for r in WORLD}


# --------------------------------------------------------------------- min_size


async def test_min_size_medium_excludes_small_and_heliport(
    seeded: AirportOverlayRepository,
) -> None:
    records = await seeded.query(min_size="medium")

    assert {r.ident for r in records} == {"KBFI", "KSEA", "KFAR", "FAR_AWAY"}


async def test_min_size_large_is_large_airports_only(seeded: AirportOverlayRepository) -> None:
    records = await seeded.query(min_size="large")

    assert {r.ident for r in records} == {"KBFI", "KSEA", "FAR_AWAY"}


async def test_min_size_heliport_includes_every_size_class(
    seeded: AirportOverlayRepository,
) -> None:
    records = await seeded.query(min_size="heliport")

    assert {r.ident for r in records} == {r.ident for r in WORLD}


async def test_bbox_and_min_size_combine(seeded: AirportOverlayRepository) -> None:
    bbox = BoundingBox(west=-123.0, south=47.0, east=-121.5, north=48.0)

    records = await seeded.query(bbox=bbox, min_size="medium")

    assert {r.ident for r in records} == {"KBFI", "KSEA"}


# --------------------------------------------------------------- cap + priority


async def test_a_capped_result_keeps_the_largest_first(
    database: Database, repository: AirportRepository
) -> None:
    small_fields = tuple(
        airport(f"SM{index:02d}", 47.5 + index * 0.001, -122.3, type="small_airport")
        for index in range(5)
    )
    await repository.replace_all(
        (*WORLD, *small_fields), source="airports", at_ms=BASE_EPOCH_MS, dataset_version="fixture"
    )
    overlay = AirportOverlayRepository(database)

    records = await overlay.query(limit=3)

    # Three large airports exist in the fixture world; a cap of 3 must return
    # exactly those three, never a small field ahead of one of them.
    assert [record.type for record in records] == ["large_airport"] * 3
    assert {record.ident for record in records} == {"KBFI", "KSEA", "FAR_AWAY"}


async def test_a_cap_larger_than_the_result_returns_everything(
    seeded: AirportOverlayRepository,
) -> None:
    records = await seeded.query(limit=1_000)

    assert len(records) == len(WORLD)
