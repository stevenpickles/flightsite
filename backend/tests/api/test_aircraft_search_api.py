"""``q`` on ``GET /api/v1/aircraft`` — slice 083.

The list-scoped prefix search (issue #226; :mod:`flightsite.api.search`):
each of the five identifiers the Aircraft page matches, the shared "prefix,
case-insensitive, literal, trimmed, bounded" semantics, the most-recent-callsign
rule, and that it composes with the list's filters, sorting and pagination —
``total`` included.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from flightsite.api.history import AircraftHistoryRepository
from flightsite.api.search import MAX_QUERY_LENGTH

from .aircraft_history_fixtures import seed_aircraft, seed_operator_groups
from .conftest import LiveApp
from .search_fixtures import BASE_MS, ROSTER, SIGHTINGS, airframe, icaos
from .sighting_fixtures import SeedSighting, seed_sightings


@pytest.fixture
async def roster(live_app: LiveApp) -> LiveApp:
    await seed_sightings(live_app.app.state.database, ROSTER, SIGHTINGS)
    return live_app


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        pytest.param("a1b", ["a1b2c3"], id="icao"),
        pytest.param("N123", ["a1b2c3"], id="registration"),
        pytest.param("A38", ["7c0011"], id="type"),
        pytest.param("Lufth", ["3c6444"], id="operator"),
        pytest.param("RCH", ["e80000"], id="callsign"),
    ],
)
async def test_each_identifier_is_searched(
    roster: LiveApp, rest: AsyncClient, q: str, expected: list[str]
) -> None:
    body = (await rest.get("/api/v1/aircraft", params={"q": q})).json()

    assert icaos(body) == expected
    assert body["total"] == len(expected)


@pytest.mark.parametrize("q", ["g-ez", "G-EZ", "g-Ez", "EASYJ", "ezy4"])
async def test_the_match_is_case_insensitive(roster: LiveApp, rest: AsyncClient, q: str) -> None:
    body = (await rest.get("/api/v1/aircraft", params={"q": q})).json()

    assert icaos(body) == ["4ca7f1"]


async def test_the_icao_prefix_matches_whatever_case_is_typed(
    roster: LiveApp, rest: AsyncClient
) -> None:
    """Addresses are stored lowercase; a pasted upper-case one still finds them."""
    body = (await rest.get("/api/v1/aircraft", params={"q": "A1B2"})).json()

    assert icaos(body) == ["a1b2c3"]


async def test_it_is_a_prefix_not_a_substring(roster: LiveApp, rest: AsyncClient) -> None:
    """``23AB`` is inside ``N123AB`` but does not start it."""
    body = (await rest.get("/api/v1/aircraft", params={"q": "23AB"})).json()

    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_only_the_most_recent_callsign_is_matched(roster: LiveApp, rest: AsyncClient) -> None:
    """``a1b2c3`` flew ``QFA9`` weeks ago and ``UAL1`` since: ``UAL`` finds it."""
    recent = (await rest.get("/api/v1/aircraft", params={"q": "UAL"})).json()
    stale = (await rest.get("/api/v1/aircraft", params={"q": "QFA"})).json()

    assert icaos(recent) == ["a1b2c3"]
    assert icaos(stale) == []


async def test_an_airframe_matching_on_two_fields_appears_once(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """The candidate union holds duplicates; the page and the count must not."""
    await seed_sightings(
        live_app.app.state.database,
        [airframe("abc123", registration="ABC-1", operator_name="Abc Air")],
        [SeedSighting(icao24="abc123", started_ms=BASE_MS, callsign_last="ABC77")],
    )

    body = (await rest.get("/api/v1/aircraft", params={"q": "abc"})).json()

    assert icaos(body) == ["abc123"]
    assert body["total"] == 1


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        # `%` and `_` are literal: neither is a wildcard.
        pytest.param("N_", ["b00001"], id="underscore-is-literal"),
        pytest.param("N%", ["b00002"], id="percent-is-literal"),
        # A backslash is literal too, and cannot escape what follows it.
        pytest.param("N\\", ["b00003"], id="backslash-is-literal"),
        pytest.param("N\\_", [], id="backslash-then-underscore"),
    ],
)
async def test_like_wildcards_in_the_query_match_themselves(
    live_app: LiveApp, rest: AsyncClient, q: str, expected: list[str]
) -> None:
    await seed_aircraft(
        live_app.app.state.database,
        [
            airframe("b00001", registration="N_1"),
            airframe("b00002", registration="N%2"),
            airframe("b00003", registration="N\\3"),
            airframe("b00004", registration="NX4"),
        ],
    )

    body = (await rest.get("/api/v1/aircraft", params={"q": q})).json()

    assert icaos(body) == expected


@pytest.mark.parametrize("q", ["", " ", "   \t "])
async def test_a_blank_query_is_no_query(roster: LiveApp, rest: AsyncClient, q: str) -> None:
    body = (await rest.get("/api/v1/aircraft", params={"q": q})).json()

    assert body["total"] == len(ROSTER)


async def test_surrounding_whitespace_is_trimmed(roster: LiveApp, rest: AsyncClient) -> None:
    body = (await rest.get("/api/v1/aircraft", params={"q": "  D-AI  "})).json()

    assert icaos(body) == ["3c6444"]


async def test_the_query_length_is_capped(roster: LiveApp, rest: AsyncClient) -> None:
    at_cap = await rest.get("/api/v1/aircraft", params={"q": "x" * MAX_QUERY_LENGTH})
    over_cap = await rest.get("/api/v1/aircraft", params={"q": "x" * (MAX_QUERY_LENGTH + 1)})

    assert at_cap.status_code == 200
    assert at_cap.json()["total"] == 0
    assert over_cap.status_code == 422


async def test_pagination_and_total_reflect_the_search(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """Twelve matches and eight non-matches: ``total`` counts only the twelve."""
    await seed_aircraft(
        live_app.app.state.database,
        [airframe(f"aa{index:04x}", days_ago=index) for index in range(12)]
        + [airframe(f"bb{index:04x}", days_ago=index) for index in range(8)],
    )

    first = (
        await rest.get(
            "/api/v1/aircraft", params={"q": "AA", "sort": "icao", "order": "asc", "limit": 5}
        )
    ).json()
    last = (
        await rest.get(
            "/api/v1/aircraft",
            params={"q": "aa", "sort": "icao", "order": "asc", "limit": 5, "offset": 10},
        )
    ).json()

    assert first["total"] == 12
    assert icaos(first) == [f"aa{index:04x}" for index in range(5)]
    assert last["total"] == 12
    assert icaos(last) == ["aa000a", "aa000b"]


async def test_every_sort_key_still_orders_a_searched_list(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed_aircraft(
        live_app.app.state.database,
        [
            airframe("cc0001", days_ago=3, registration="C-0003"),
            airframe("cc0002", days_ago=1, registration="C-0001"),
            airframe("cc0003", days_ago=2, registration="C-0002"),
            airframe("dd0001", days_ago=0, registration="D-0000"),
        ],
    )

    by_last_seen = (await rest.get("/api/v1/aircraft", params={"q": "cc"})).json()
    by_registration = (
        await rest.get("/api/v1/aircraft", params={"q": "cc", "sort": "registration"})
    ).json()

    assert icaos(by_last_seen) == ["cc0002", "cc0003", "cc0001"]
    assert icaos(by_registration) == ["cc0001", "cc0003", "cc0002"]


async def test_the_search_combines_with_the_other_filters(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    group_ids = await seed_operator_groups(live_app.app.state.database, [("alpha", "Alpha Group")])
    await seed_aircraft(
        live_app.app.state.database,
        [
            airframe("ee0001", type_code="B738", operator_group_slug="alpha"),
            airframe("ee0002", type_code="A320", operator_group_slug="alpha"),
            airframe("ff0001", type_code="B738", operator_group_slug="alpha"),
        ],
        group_ids=group_ids,
    )

    body = (
        await rest.get(
            "/api/v1/aircraft", params={"q": "ee", "type": "B738", "operator_group": "alpha"}
        )
    ).json()

    assert icaos(body) == ["ee0001"]
    assert body["total"] == 1


async def test_the_repository_trims_the_query_itself(roster: LiveApp) -> None:
    """Any caller, not only the endpoint, gets the same blank-means-absent rule."""
    repository = AircraftHistoryRepository(roster.app.state.database)

    _, blank_total = await repository.list_aircraft(limit=50, offset=0, q="   ")
    rows, total = await repository.list_aircraft(limit=50, offset=0, q=" vh-")

    assert blank_total == len(ROSTER)
    assert [row["icao24"] for row in rows] == ["7c0011"]
    assert total == 1


async def test_the_query_parameter_is_published_in_openapi(rest: AsyncClient) -> None:
    document = (await rest.get("/api/v1/openapi.json")).json()

    parameters = {
        item["name"]: item for item in document["paths"]["/api/v1/aircraft"]["get"]["parameters"]
    }
    assert parameters["q"]["schema"]["anyOf"][0]["maxLength"] == MAX_QUERY_LENGTH
