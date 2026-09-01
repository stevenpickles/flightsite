"""``GET /api/v1/aircraft`` and ``GET /api/v1/aircraft/{icao}`` — ``docs/API.md`` §3.5.

Pagination/sorting/envelope per §2.4, the documented sort keys and filters,
the SPEC §53 lifetime block, provenance (§2.6), the 404 shape (§2.5) and the
``{icao}`` path validator (§2.9).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from flightsite.api.schemas import AircraftDetail, AircraftHistoryRow

from ..live.conftest import make_update
from .aircraft_history_fixtures import SeedAircraft, seed_aircraft, seed_operator_groups
from .conftest import LiveApp

BASE_MS = 1_756_000_000_000
DAY_MS = 86_400_000


def icaos(body: dict[str, Any]) -> list[str]:
    return [item["icao"] for item in body["items"]]


async def seed(
    live_app: LiveApp, *rows: SeedAircraft, groups: list[tuple[str, str]] | None = None
) -> None:
    group_ids = await seed_operator_groups(live_app.app.state.database, groups or [])
    await seed_aircraft(live_app.app.state.database, rows, group_ids=group_ids)


# ------------------------------------------------------------------ envelope


async def test_an_empty_history_is_an_empty_list_not_an_error(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/aircraft")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_default_sort_is_last_seen_descending(live_app: LiveApp, rest: AsyncClient) -> None:
    await seed(
        live_app,
        SeedAircraft(icao24="aaaaaa", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
        SeedAircraft(icao24="bbbbbb", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS + DAY_MS),
        SeedAircraft(icao24="cccccc", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS - DAY_MS),
    )

    body = (await rest.get("/api/v1/aircraft")).json()

    assert icaos(body) == ["bbbbbb", "aaaaaa", "cccccc"]


async def test_limit_and_offset_page_through_the_result(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        *(
            SeedAircraft(icao24=f"{index:06x}", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS)
            for index in range(5)
        ),
    )

    page = (await rest.get("/api/v1/aircraft?sort=icao&order=asc&limit=2&offset=2")).json()

    assert icaos(page) == ["000002", "000003"]
    assert page["total"] == 5
    assert page["limit"] == 2
    assert page["offset"] == 2


@pytest.mark.parametrize("limit", [0, 501])
async def test_limit_out_of_bounds_is_a_validation_error(
    live_app: LiveApp, rest: AsyncClient, limit: int
) -> None:
    response = await rest.get(f"/api/v1/aircraft?limit={limit}")

    assert response.status_code == 422


async def test_negative_offset_is_a_validation_error(live_app: LiveApp, rest: AsyncClient) -> None:
    response = await rest.get("/api/v1/aircraft?offset=-1")

    assert response.status_code == 422


async def test_an_unrecognized_sort_key_is_a_validation_error(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/aircraft?sort=altitude_ft")

    assert response.status_code == 422


# ---------------------------------------------------------------------- sort


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("icao", ["111111", "222222", "333333"]),
        ("registration", ["333333", "111111", "222222"]),  # N1, N2, N3
        ("type", ["222222", "333333", "111111"]),  # A320, B738, C172
        ("operator", ["111111", "333333", "222222"]),  # Alpha, Beta, Charlie
        ("first_seen", ["222222", "111111", "333333"]),
        ("sighting_count", ["222222", "111111", "333333"]),
        ("closest_approach_nm", ["222222", "333333", "111111"]),
        ("max_range_nm", ["222222", "333333", "111111"]),
    ],
)
async def test_ascending_sort_orders_by_the_documented_column(
    live_app: LiveApp, rest: AsyncClient, sort: str, expected: list[str]
) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="111111",
            first_seen_ms=BASE_MS + DAY_MS,
            last_seen_ms=BASE_MS,
            sighting_count=5,
            closest_approach_nm=3.0,
            max_range_nm=200.0,
            registration="N2ABC",
            type_code="C172",
            operator_name="Alpha Airlines",
        ),
        SeedAircraft(
            icao24="222222",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            sighting_count=1,
            closest_approach_nm=1.0,
            max_range_nm=50.0,
            registration="N3XYZ",
            type_code="A320",
            operator_name="Charlie Charters",
        ),
        SeedAircraft(
            icao24="333333",
            first_seen_ms=BASE_MS + 2 * DAY_MS,
            last_seen_ms=BASE_MS,
            sighting_count=9,
            closest_approach_nm=2.0,
            max_range_nm=150.0,
            registration="N1AAA",
            type_code="B738",
            operator_name="Beta Jets",
        ),
    )

    body = (await rest.get(f"/api/v1/aircraft?sort={sort}&order=asc")).json()

    assert icaos(body) == expected


async def test_descending_order_reverses_the_same_key(live_app: LiveApp, rest: AsyncClient) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="111111", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS, sighting_count=1
        ),
        SeedAircraft(
            icao24="222222", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS, sighting_count=9
        ),
    )

    body = (await rest.get("/api/v1/aircraft?sort=sighting_count&order=desc")).json()

    assert icaos(body) == ["222222", "111111"]


async def test_a_classification_sort_places_never_classified_aircraft_together(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        # Neither has any classification claim, so neither gets a row in
        # `aircraft_classification` at all (`_classification_populated`) —
        # the LEFT JOIN reads `mission_category` as SQL NULL for both, which
        # SQLite sorts before any non-NULL value in ascending order.
        SeedAircraft(icao24="aaaaaa", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
        SeedAircraft(icao24="bbbbbb", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
        SeedAircraft(
            icao24="cccccc",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            military=True,
            mission_category="military",
        ),
    )

    body = (await rest.get("/api/v1/aircraft?sort=classification&order=asc")).json()

    # Both unclassified rows sort first (tied, broken by the icao
    # tiebreaker); the classified row sorts last.
    assert icaos(body) == ["aaaaaa", "bbbbbb", "cccccc"]
    unclassified = {item["icao"]: item["classification"] for item in body["items"][:2]}
    assert unclassified == {"aaaaaa": None, "bbbbbb": None}


async def test_ties_break_on_icao_ascending_regardless_of_sort_direction(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="cccccc", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS, sighting_count=4
        ),
        SeedAircraft(
            icao24="aaaaaa", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS, sighting_count=4
        ),
        SeedAircraft(
            icao24="bbbbbb", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS, sighting_count=4
        ),
    )

    ascending = (await rest.get("/api/v1/aircraft?sort=sighting_count&order=asc")).json()
    descending = (await rest.get("/api/v1/aircraft?sort=sighting_count&order=desc")).json()

    assert icaos(ascending) == ["aaaaaa", "bbbbbb", "cccccc"]
    assert icaos(descending) == ["aaaaaa", "bbbbbb", "cccccc"]


# ------------------------------------------------------------------- filters


async def test_the_classification_filter_matches_mission_category_exactly(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="aaaaaa",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            military=True,
            mission_category="military",
        ),
        SeedAircraft(
            icao24="bbbbbb",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            mission_category="cargo",
        ),
    )

    body = (await rest.get("/api/v1/aircraft?classification=military")).json()

    assert icaos(body) == ["aaaaaa"]
    assert body["total"] == 1


async def test_the_operator_group_filter_matches_the_curated_slug(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="aaaaaa",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            operator_name="United States Air Force",
            operator_group_slug="us-military",
        ),
        SeedAircraft(
            icao24="bbbbbb",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            operator_name="Delta Air Lines",
            operator_group_slug="delta",
        ),
        groups=[("us-military", "US Military"), ("delta", "Delta Air Lines")],
    )

    body = (await rest.get("/api/v1/aircraft?operator_group=us-military")).json()

    assert icaos(body) == ["aaaaaa"]
    assert body["items"][0]["operator_group"] == "US Military"


async def test_the_type_filter_normalizes_to_upper_case(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="aaaaaa", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS, type_code="B738"
        ),
        SeedAircraft(
            icao24="bbbbbb", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS, type_code="A320"
        ),
    )

    body = (await rest.get("/api/v1/aircraft?type=b738")).json()

    assert icaos(body) == ["aaaaaa"]


# --------------------------------------------------------------------- shape


async def test_the_row_validates_against_the_published_model(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="ae1463",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS + DAY_MS,
            sighting_count=41,
            closest_approach_nm=2.1,
            max_range_nm=141.8,
            registration="N302DN",
            type_code="B738",
            model="Boeing 737-800",
            operator_name="Delta Air Lines",
            operator_group_slug="delta",
            mission_category="commercial_passenger",
        ),
        groups=[("delta", "Delta Air Lines")],
    )

    body = (await rest.get("/api/v1/aircraft")).json()

    row = AircraftHistoryRow.model_validate(body["items"][0])
    assert row.icao == "ae1463"
    assert row.registration == "N302DN"
    assert row.aircraft_type == "B738"
    assert row.operator_group == "Delta Air Lines"
    assert row.classification is not None
    assert row.classification.mission == "commercial_passenger"
    assert row.provenance["registration"] == "mictronics"
    assert row.provenance["operator_group"] == "derived"
    assert row.provenance["classification"] == "heuristic"


async def test_a_law_enforcement_flag_is_the_primary_claim_over_mission(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    # Mirrors `Classification.primary_claim`'s order (military, law
    # enforcement, government, mission): law enforcement outranks a mission
    # claim on the same row.
    await seed(
        live_app,
        SeedAircraft(
            icao24="aaaaaa",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            law_enforcement=True,
            mission_category="government",
        ),
    )

    body = (await rest.get("/api/v1/aircraft")).json()

    classification = body["items"][0]["classification"]
    assert classification["law_enforcement"] is True
    assert classification["confidence"] == "medium"
    assert body["items"][0]["provenance"]["classification"] == "heuristic"


async def test_a_government_flag_is_the_primary_claim_over_mission(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="aaaaaa",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            government=True,
            mission_category="government",
        ),
    )

    body = (await rest.get("/api/v1/aircraft")).json()

    classification = body["items"][0]["classification"]
    assert classification["government"] is True
    assert classification["confidence"] == "medium"
    assert body["items"][0]["provenance"]["classification"] == "heuristic"


async def test_an_icon_category_alone_is_a_classification_with_no_confidence(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    # A classification can assert only an icon hint — no flag, no mission —
    # in which case there is no claim to attach a confidence or source to.
    await seed(
        live_app,
        SeedAircraft(
            icao24="aaaaaa", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS, icon_category="helicopter"
        ),
    )

    body = (await rest.get("/api/v1/aircraft")).json()

    classification = body["items"][0]["classification"]
    assert classification == {
        "military": False,
        "government": False,
        "law_enforcement": False,
        "mission": "unknown",
        "icon_category": "helicopter",
        "confidence": None,
    }
    assert "classification" not in body["items"][0]["provenance"]


async def test_an_aircraft_with_no_resolved_metadata_reports_unknown_fields(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    # A freshly-sighted airframe: an `aircraft` row exists, but nothing has
    # ever resolved its metadata or classification (§2.7 — null, not a guess).
    await seed(live_app, SeedAircraft(icao24="ffffff", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS))

    body = (await rest.get("/api/v1/aircraft")).json()

    row = body["items"][0]
    assert row["registration"] is None
    assert row["aircraft_type"] is None
    assert row["operator_group"] is None
    assert row["classification"] is None
    assert row["provenance"] == {}


# ---------------------------------------------------------------------- detail


async def test_detail_reports_the_documented_lifetime_block(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="ae1463",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS + DAY_MS,
            sighting_count=41,
            total_observed_ms=51_840_000,
            closest_approach_nm=2.1,
            max_range_nm=141.8,
            lowest_alt_ft=1250,
            highest_alt_ft=41000,
        ),
    )

    body = (await rest.get("/api/v1/aircraft/ae1463")).json()

    detail = AircraftDetail.model_validate(body)
    assert detail.lifetime.sighting_count == 41
    assert detail.lifetime.cumulative_duration_s == 51_840
    assert detail.lifetime.closest_approach_nm == pytest.approx(2.1)
    assert detail.lifetime.max_range_nm == pytest.approx(141.8)
    assert detail.lifetime.lowest_altitude_ft == 1250
    assert detail.lifetime.highest_altitude_ft == 41000
    assert detail.live is False


async def test_detail_reports_manufacture_year_and_owner_with_provenance(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        SeedAircraft(
            icao24="ae1463",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            manufacture_year=2018,
            owner="Some Owner LLC",
        ),
    )

    body = (await rest.get("/api/v1/aircraft/ae1463")).json()

    assert body["manufacture_year"] == 2018
    assert body["owner"] == "Some Owner LLC"
    assert body["provenance"]["manufacture_year"] == "faa"
    assert body["provenance"]["owner"] == "faa"


async def test_detail_reports_live_true_for_a_currently_live_aircraft(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(live_app, SeedAircraft(icao24="ae1463", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS))
    live_app.feed(make_update("ae1463"))

    body = (await rest.get("/api/v1/aircraft/ae1463")).json()

    assert body["live"] is True


async def test_detail_404s_for_an_address_this_receiver_has_never_sighted(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/aircraft/aaaaaa")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert "aaaaaa" in body["error"]["message"]


@pytest.mark.parametrize("icao", ["AE1463", "ae146", "ae1463z", "not-hex"])
async def test_detail_rejects_a_malformed_icao_per_the_29_validator(
    live_app: LiveApp, rest: AsyncClient, icao: str
) -> None:
    response = await rest.get(f"/api/v1/aircraft/{icao}")

    assert response.status_code == 422


async def test_the_reserved_current_segment_never_reaches_the_detail_route(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    # `current` fails the §2.9 icao pattern, so `/aircraft/current` can only
    # ever match the dedicated live-picture route, never the detail one.
    response = await rest.get("/api/v1/aircraft/current")

    assert response.status_code == 200
    assert "error" not in response.json()
