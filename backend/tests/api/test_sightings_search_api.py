"""``q`` on ``GET /api/v1/sightings`` — slice 083.

The Sightings page's filter box sends ``q``: an ICAO-address *or* callsign
prefix with :mod:`flightsite.api.search`'s semantics. The pre-existing exact
``icao`` filter keeps its meaning for every caller that already uses it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from flightsite.api.search import MAX_QUERY_LENGTH
from flightsite.api.sightings import SightingsRepository

from .conftest import LiveApp
from .search_fixtures import BASE_MS, DAY_MS, ROSTER, SIGHTINGS, airframe, icaos
from .sighting_fixtures import SeedSighting, seed_sightings


@pytest.fixture
async def roster(live_app: LiveApp) -> LiveApp:
    await seed_sightings(live_app.app.state.database, ROSTER, SIGHTINGS)
    return live_app


async def test_a_sighting_is_found_by_its_callsign_prefix(
    roster: LiveApp, rest: AsyncClient
) -> None:
    body = (await rest.get("/api/v1/sightings", params={"q": "ezy"})).json()

    assert [item["callsign"] for item in body["items"]] == ["EZY42"]


async def test_every_sighting_of_an_address_prefix_is_found(
    roster: LiveApp, rest: AsyncClient
) -> None:
    """Both of ``a1b2c3``'s sightings, newest first — callsign changes aside."""
    body = (await rest.get("/api/v1/sightings", params={"q": "A1B"})).json()

    assert [item["callsign"] for item in body["items"]] == ["UAL1", "QFA9"]
    assert body["total"] is None


async def test_a_sightings_search_matches_the_address_or_the_callsign(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """``ca`` is one airframe's address prefix and another's callsign prefix."""
    await seed_sightings(
        live_app.app.state.database,
        [airframe("ca0001"), airframe("100001")],
        [
            SeedSighting(icao24="ca0001", started_ms=BASE_MS - DAY_MS, callsign_last="QXE1"),
            SeedSighting(icao24="100001", started_ms=BASE_MS, callsign_last="CAL5"),
        ],
    )

    body = (await rest.get("/api/v1/sightings", params={"q": "CA"})).json()

    assert icaos(body) == ["100001", "ca0001"]


async def test_sightings_search_is_literal_and_trimmed(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed_sightings(
        live_app.app.state.database,
        [airframe("200001"), airframe("200002")],
        [
            SeedSighting(icao24="200001", started_ms=BASE_MS, callsign_last="N_1"),
            SeedSighting(icao24="200002", started_ms=BASE_MS, callsign_last="NX1"),
        ],
    )

    body = (await rest.get("/api/v1/sightings", params={"q": " n_ "})).json()

    assert icaos(body) == ["200001"]


@pytest.mark.parametrize("q", ["", "   "])
async def test_a_blank_sightings_query_is_no_query(
    roster: LiveApp, rest: AsyncClient, q: str
) -> None:
    body = (await rest.get("/api/v1/sightings", params={"q": q})).json()

    assert len(body["items"]) == len(SIGHTINGS)


async def test_the_sightings_query_length_is_capped(roster: LiveApp, rest: AsyncClient) -> None:
    response = await rest.get("/api/v1/sightings", params={"q": "x" * (MAX_QUERY_LENGTH + 1)})

    assert response.status_code == 422


async def test_the_exact_icao_filter_is_unchanged(roster: LiveApp, rest: AsyncClient) -> None:
    """Existing ``?icao=`` callers keep an exact, six-hex-digit match."""
    exact = await rest.get("/api/v1/sightings", params={"icao": "a1b2c3"})
    prefix = await rest.get("/api/v1/sightings", params={"icao": "a1b"})

    assert icaos(exact.json()) == ["a1b2c3", "a1b2c3"]
    assert prefix.status_code == 422


async def test_sightings_search_combines_with_filters_sort_and_paging(
    roster: LiveApp, rest: AsyncClient
) -> None:
    windowed = (
        await rest.get(
            "/api/v1/sightings",
            params={"q": "a1b", "from": "2025-08-10T00:00:00Z", "limit": 1},
        )
    ).json()
    second_page = (
        await rest.get(
            "/api/v1/sightings",
            params={"q": "a1b", "sort": "started_at", "order": "asc", "limit": 1, "offset": 1},
        )
    ).json()

    assert [item["callsign"] for item in windowed["items"]] == ["UAL1"]
    assert [item["callsign"] for item in second_page["items"]] == ["UAL1"]


async def test_the_sightings_repository_trims_the_query_itself(roster: LiveApp) -> None:
    repository = SightingsRepository(roster.app.state.database)

    rows = await repository.list_sightings(limit=50, offset=0, q="  rch ")

    assert [row["callsign_last"] for row in rows] == ["RCH871"]


async def test_the_query_parameter_is_published_in_openapi(rest: AsyncClient) -> None:
    document = (await rest.get("/api/v1/openapi.json")).json()

    parameters = {
        item["name"]: item for item in document["paths"]["/api/v1/sightings"]["get"]["parameters"]
    }
    assert parameters["q"]["schema"]["anyOf"][0]["maxLength"] == MAX_QUERY_LENGTH
    assert parameters["icao"]["schema"]["anyOf"][0]["pattern"] == "^[0-9a-f]{6}$"
