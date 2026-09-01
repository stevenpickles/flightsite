"""``GET /api/v1/airspace`` — the user-supplied overlay (roadmap slice 028,
``docs/adr/0012-airspace-data-source.md``), through the real app so the file is
read from a genuine ``settings.data_dir`` rather than the loader called directly
(that is :mod:`tests.airspace.test_loader`'s job).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from flightsite.airspace.loader import AIRSPACE_FILENAME, MAX_AIRSPACE_BYTES
from flightsite.api.schemas import AirspaceFeatureCollection
from flightsite.app import create_app

VALID_FEATURE_COLLECTION: dict[str, Any] = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"class": "B", "name": "Test Class B"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-122.5, 47.3], [-122.5, 47.7], [-121.9, 47.7], [-121.9, 47.3], [-122.5, 47.3]]
                ],
            },
        }
    ],
}


async def get_airspace(app: FastAPI) -> dict[str, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/airspace")
        assert response.status_code == 200
        result: dict[str, Any] = response.json()
        return result


# ------------------------------------------------------------------------ absence


async def test_absent_file_answers_an_empty_feature_collection(isolated_data_dir: Path) -> None:
    app = create_app(isolated_data_dir)

    async with app.router.lifespan_context(app):
        body = await get_airspace(app)

    assert body == {"type": "FeatureCollection", "features": []}


# --------------------------------------------------------------------- validity


async def test_a_valid_file_is_served_in_full(isolated_data_dir: Path) -> None:
    (isolated_data_dir / AIRSPACE_FILENAME).write_text(
        json.dumps(VALID_FEATURE_COLLECTION), encoding="utf-8"
    )
    app = create_app(isolated_data_dir)

    async with app.router.lifespan_context(app):
        body = await get_airspace(app)

    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["class"] == "B"


async def test_the_payload_validates_against_the_published_schema(
    isolated_data_dir: Path,
) -> None:
    (isolated_data_dir / AIRSPACE_FILENAME).write_text(
        json.dumps(VALID_FEATURE_COLLECTION), encoding="utf-8"
    )
    app = create_app(isolated_data_dir)

    async with app.router.lifespan_context(app):
        body = await get_airspace(app)

    AirspaceFeatureCollection.model_validate(body)


# ------------------------------------------------------------------ degradation


async def test_invalid_json_degrades_to_empty_with_no_error(isolated_data_dir: Path) -> None:
    (isolated_data_dir / AIRSPACE_FILENAME).write_text("{not json", encoding="utf-8")
    app = create_app(isolated_data_dir)

    async with app.router.lifespan_context(app):
        body = await get_airspace(app)

    assert body == {"type": "FeatureCollection", "features": []}


async def test_wrong_top_level_type_degrades_to_empty(isolated_data_dir: Path) -> None:
    (isolated_data_dir / AIRSPACE_FILENAME).write_text(
        json.dumps({"type": "Feature"}), encoding="utf-8"
    )
    app = create_app(isolated_data_dir)

    async with app.router.lifespan_context(app):
        body = await get_airspace(app)

    assert body == {"type": "FeatureCollection", "features": []}


async def test_oversized_file_degrades_to_empty(isolated_data_dir: Path) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"padding": "x" * (MAX_AIRSPACE_BYTES + 1)},
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            }
        ],
    }
    (isolated_data_dir / AIRSPACE_FILENAME).write_text(json.dumps(document), encoding="utf-8")
    app = create_app(isolated_data_dir)

    async with app.router.lifespan_context(app):
        body = await get_airspace(app)

    assert body == {"type": "FeatureCollection", "features": []}


async def test_a_feature_with_bad_coordinates_is_dropped_not_the_whole_file(
    isolated_data_dir: Path,
) -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "bad"},
                "geometry": {"type": "Point", "coordinates": [999.0, 999.0]},
            },
            {
                "type": "Feature",
                "properties": {"name": "good"},
                "geometry": {"type": "Point", "coordinates": [-122.3, 47.5]},
            },
        ],
    }
    (isolated_data_dir / AIRSPACE_FILENAME).write_text(json.dumps(document), encoding="utf-8")
    app = create_app(isolated_data_dir)

    async with app.router.lifespan_context(app):
        body = await get_airspace(app)

    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["name"] == "good"
