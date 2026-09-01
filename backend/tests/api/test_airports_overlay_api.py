"""``GET /api/v1/airports`` — the map overlay's airport markers (roadmap slice
028), through the real app rather than the repository directly: envelope shape,
query-param wiring, and the §2.5 error shape for a malformed ``bbox``.
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from flightsite.airports import AirportRepository
from flightsite.airports.records import AirportRecord
from flightsite.api.schemas import AirportFeatureCollection

from .conftest import LiveApp

BASE_MS = 1_756_000_000_000

WORLD = (
    AirportRecord(
        ident="KBFI", name="Boeing Field", type="large_airport", lat=47.53, lon=-122.30, iata="BFI"
    ),
    AirportRecord(
        ident="S60", name="Auburn Municipal", type="small_airport", lat=47.33, lon=-122.23
    ),
    AirportRecord(ident="W16", name="A Heliport", type="heliport", lat=47.60, lon=-122.20),
    AirportRecord(
        ident="KFAR", name="Hector International", type="medium_airport", lat=46.92, lon=-96.82
    ),
)


async def seed(live_app: LiveApp) -> None:
    await AirportRepository(live_app.app.state.database).replace_all(
        WORLD, source="airports", at_ms=BASE_MS, dataset_version="fixture"
    )


def idents(body: dict[str, Any]) -> set[str]:
    return {feature["properties"]["ident"] for feature in body["features"]}


# ------------------------------------------------------------------------ shape


async def test_returns_a_geojson_feature_collection_of_points(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(live_app)

    body = (await rest.get("/api/v1/airports")).json()

    assert body["type"] == "FeatureCollection"
    assert idents(body) == {"KBFI", "S60", "W16", "KFAR"}
    kbfi = next(f for f in body["features"] if f["properties"]["ident"] == "KBFI")
    assert kbfi["geometry"] == {"type": "Point", "coordinates": [-122.30, 47.53]}
    assert kbfi["properties"]["size_class"] == "large"
    assert kbfi["properties"]["iata"] == "BFI"


async def test_an_empty_dataset_is_an_empty_feature_collection_not_an_error(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    body = (await rest.get("/api/v1/airports")).json()

    assert body == {"type": "FeatureCollection", "features": []}


async def test_the_payload_validates_against_the_published_schema(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(live_app)

    body = (await rest.get("/api/v1/airports")).json()

    AirportFeatureCollection.model_validate(body)


# ------------------------------------------------------------------------ bbox


async def test_bbox_restricts_the_result(live_app: LiveApp, rest: AsyncClient) -> None:
    await seed(live_app)

    body = (await rest.get("/api/v1/airports?bbox=-123,47.2,-121.9,47.7")).json()

    assert idents(body) == {"KBFI", "S60", "W16"}


async def test_a_malformed_bbox_answers_the_400_error_envelope(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/airports?bbox=not,a,box")

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_bbox"


# --------------------------------------------------------------------- min_size


async def test_min_size_restricts_by_size_class(live_app: LiveApp, rest: AsyncClient) -> None:
    await seed(live_app)

    body = (await rest.get("/api/v1/airports?min_size=medium")).json()

    assert idents(body) == {"KBFI", "KFAR"}


async def test_an_unrecognized_min_size_is_a_422(live_app: LiveApp, rest: AsyncClient) -> None:
    response = await rest.get("/api/v1/airports?min_size=enormous")

    assert response.status_code == 422
