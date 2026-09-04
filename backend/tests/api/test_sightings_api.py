"""``GET /api/v1/sightings``, ``GET /api/v1/sightings/{id}`` and
``GET /api/v1/aircraft/{icao}/sightings`` — ``docs/API.md`` §3.6, SPEC §57.

Envelope/pagination per §2.4 (with ``total`` always omitted — the canonical
case the section names), the documented sort keys and filters, the detail
shape's flight context / reception stats / records / events / path, the
path-decode round trip against a written packed track and against checkpoint
rows for an open sighting, the 404 shape (§2.5), and the per-aircraft log.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

from flightsite.api.schemas import SightingDetail, SightingRow
from flightsite.sightings.tracks import TrackSample

from .aircraft_history_fixtures import SeedAircraft, seed_operator_groups
from .conftest import LiveApp
from .sighting_fixtures import (
    SeedSighting,
    seed_checkpoints,
    seed_events,
    seed_sightings,
    seed_track,
)

BASE_MS = 1_756_000_000_000
MINUTE_MS = 60_000
HOUR_MS = 3_600_000


def ids(body: dict[str, Any]) -> list[int]:
    return [item["id"] for item in body["items"]]


async def seed(
    live_app: LiveApp,
    *rows: SeedSighting,
    aircraft: list[SeedAircraft],
    groups: list[tuple[str, str]] | None = None,
) -> list[int]:
    group_ids = await seed_operator_groups(live_app.app.state.database, groups or [])
    return await seed_sightings(live_app.app.state.database, aircraft, rows, group_ids=group_ids)


def closed_sighting(
    icao24: str = "ae1463",
    *,
    started_ms: int = BASE_MS,
    ended_ms: int = BASE_MS + MINUTE_MS,
    **overrides: Any,
) -> SeedSighting:
    defaults: dict[str, Any] = {
        "started_ms": started_ms,
        "ended_ms": ended_ms,
        "duration_ms": ended_ms - started_ms,
        "closure_reason": "gap_timeout",
        "pos_count": 10,
    }
    defaults.update(overrides)
    return SeedSighting(icao24=icao24, **defaults)


def open_sighting(
    icao24: str = "ae1463", *, started_ms: int = BASE_MS, **overrides: Any
) -> SeedSighting:
    defaults: dict[str, Any] = {"started_ms": started_ms, "pos_count": 5}
    defaults.update(overrides)
    return SeedSighting(icao24=icao24, **defaults)


AIRCRAFT = [SeedAircraft(icao24="ae1463", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS)]


# ------------------------------------------------------------------ envelope


async def test_an_empty_log_is_an_empty_list_not_an_error(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/sightings")

    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": None, "limit": 50, "offset": 0}


async def test_total_is_always_omitted_even_with_rows_present(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(live_app, closed_sighting(), aircraft=AIRCRAFT)

    body = (await rest.get("/api/v1/sightings")).json()

    assert body["total"] is None


async def test_default_sort_is_started_at_descending(live_app: LiveApp, rest: AsyncClient) -> None:
    seeded = await seed(
        live_app,
        closed_sighting(started_ms=BASE_MS, ended_ms=BASE_MS + MINUTE_MS),
        closed_sighting(started_ms=BASE_MS + HOUR_MS, ended_ms=BASE_MS + HOUR_MS + MINUTE_MS),
        closed_sighting(started_ms=BASE_MS - HOUR_MS, ended_ms=BASE_MS - HOUR_MS + MINUTE_MS),
        aircraft=AIRCRAFT,
    )

    body = (await rest.get("/api/v1/sightings")).json()

    assert ids(body) == [seeded[1], seeded[0], seeded[2]]


async def test_limit_and_offset_page_through_the_result(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(
        live_app,
        *(
            closed_sighting(
                started_ms=BASE_MS + index * MINUTE_MS, ended_ms=BASE_MS + index * MINUTE_MS + 1000
            )
            for index in range(5)
        ),
        aircraft=AIRCRAFT,
    )

    page = (await rest.get("/api/v1/sightings?sort=started_at&order=asc&limit=2&offset=2")).json()

    assert ids(page) == [seeded[2], seeded[3]]
    assert page["limit"] == 2
    assert page["offset"] == 2


@pytest.mark.parametrize("limit", [0, 501])
async def test_limit_out_of_bounds_is_a_validation_error(
    live_app: LiveApp, rest: AsyncClient, limit: int
) -> None:
    response = await rest.get(f"/api/v1/sightings?limit={limit}")

    assert response.status_code == 422


async def test_an_unrecognized_sort_key_is_a_validation_error(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/sightings?sort=icao")

    assert response.status_code == 422


# ---------------------------------------------------------------------- sort


async def test_sorting_by_duration_orders_ascending(live_app: LiveApp, rest: AsyncClient) -> None:
    seeded = await seed(
        live_app,
        closed_sighting(started_ms=BASE_MS, ended_ms=BASE_MS + 5 * MINUTE_MS),
        closed_sighting(started_ms=BASE_MS + HOUR_MS, ended_ms=BASE_MS + HOUR_MS + MINUTE_MS),
        aircraft=AIRCRAFT,
    )

    body = (await rest.get("/api/v1/sightings?sort=duration_s&order=asc")).json()

    assert ids(body) == [seeded[1], seeded[0]]


async def test_sorting_by_closest_approach_orders_ascending(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(
        live_app,
        closed_sighting(closest_approach_nm=10.0),
        closed_sighting(
            started_ms=BASE_MS + HOUR_MS,
            ended_ms=BASE_MS + HOUR_MS + MINUTE_MS,
            closest_approach_nm=1.0,
        ),
        aircraft=AIRCRAFT,
    )

    body = (await rest.get("/api/v1/sightings?sort=closest_approach_nm&order=asc")).json()

    assert ids(body) == [seeded[1], seeded[0]]


async def test_sorting_by_max_range_orders_descending(live_app: LiveApp, rest: AsyncClient) -> None:
    seeded = await seed(
        live_app,
        closed_sighting(max_range_nm=50.0),
        closed_sighting(
            started_ms=BASE_MS + HOUR_MS, ended_ms=BASE_MS + HOUR_MS + MINUTE_MS, max_range_nm=200.0
        ),
        aircraft=AIRCRAFT,
    )

    body = (await rest.get("/api/v1/sightings?sort=max_range_nm&order=desc")).json()

    assert ids(body) == [seeded[1], seeded[0]]


# ------------------------------------------------------------------- filters


async def test_the_icao_filter_matches_exactly(live_app: LiveApp, rest: AsyncClient) -> None:
    aircraft = [
        SeedAircraft(icao24="ae1463", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
        SeedAircraft(icao24="a1b2c3", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
    ]
    seeded = await seed(
        live_app,
        closed_sighting("ae1463"),
        closed_sighting("a1b2c3"),
        aircraft=aircraft,
    )

    body = (await rest.get("/api/v1/sightings?icao=ae1463")).json()

    assert ids(body) == [seeded[0]]


async def test_a_malformed_icao_filter_is_a_validation_error(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/sightings?icao=NOTHEX")

    assert response.status_code == 422


async def test_from_and_to_bound_started_at_inclusively(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(
        live_app,
        closed_sighting(started_ms=BASE_MS, ended_ms=BASE_MS + MINUTE_MS),
        closed_sighting(started_ms=BASE_MS + HOUR_MS, ended_ms=BASE_MS + HOUR_MS + MINUTE_MS),
        closed_sighting(
            started_ms=BASE_MS + 2 * HOUR_MS, ended_ms=BASE_MS + 2 * HOUR_MS + MINUTE_MS
        ),
        aircraft=AIRCRAFT,
    )
    # Computed from the fixed epoch directly rather than a hardcoded date
    # string, so this never silently drifts if `BASE_MS`/`HOUR_MS` change.
    bound_iso = (
        datetime.fromtimestamp((BASE_MS + HOUR_MS) / 1000, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )

    body = (
        await rest.get(
            f"/api/v1/sightings?from={bound_iso}&to={bound_iso}&sort=started_at&order=asc"
        )
    ).json()

    assert ids(body) == [seeded[1]]


async def test_the_interesting_filter_matches_a_non_null_severity(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(
        live_app,
        closed_sighting(max_alert_severity=None),
        closed_sighting(
            started_ms=BASE_MS + HOUR_MS,
            ended_ms=BASE_MS + HOUR_MS + MINUTE_MS,
            max_alert_severity="high",
        ),
        aircraft=AIRCRAFT,
    )

    body = (await rest.get("/api/v1/sightings?interesting=true")).json()

    assert ids(body) == [seeded[1]]


async def test_the_open_filter_matches_sightings_with_no_ended_at(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(
        live_app,
        closed_sighting(),
        open_sighting(started_ms=BASE_MS + HOUR_MS),
        aircraft=AIRCRAFT,
    )

    body = (await rest.get("/api/v1/sightings?open=true")).json()

    assert ids(body) == [seeded[1]]
    assert body["items"][0]["ended_at"] is None
    assert body["items"][0]["duration_s"] is None


# --------------------------------------------------------------------- shape


async def test_the_row_validates_against_the_published_model(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    aircraft = [
        SeedAircraft(
            icao24="ae1463",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            registration="N302DN",
            type_code="B738",
            model="Boeing 737-800",
            operator_name="Delta Air Lines",
            operator_group_slug="delta",
            mission_category="commercial_passenger",
        )
    ]
    await seed(
        live_app,
        closed_sighting(
            callsign_last="DAL123",
            closest_approach_nm=11.2,
            max_range_nm=96.0,
            lowest_alt_ft=21000,
            highest_alt_ft=28000,
            pos_count=2210,
            had_emergency=True,
        ),
        aircraft=aircraft,
        groups=[("delta", "Delta Air Lines")],
    )

    body = (await rest.get("/api/v1/sightings")).json()

    row = SightingRow.model_validate(body["items"][0])
    assert row.icao == "ae1463"
    assert row.callsign == "DAL123"
    assert row.registration == "N302DN"
    assert row.aircraft_type == "B738"
    assert row.closest_approach_nm == pytest.approx(11.2)
    assert row.max_range_nm == pytest.approx(96.0)
    assert row.lowest_altitude_ft == 21000
    assert row.highest_altitude_ft == 28000
    assert row.position_count == 2210
    assert row.had_emergency is True
    assert row.provenance["registration"] == "mictronics"


async def test_an_aircraft_with_no_resolved_metadata_reports_unknown_fields(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(live_app, closed_sighting(), aircraft=AIRCRAFT)

    body = (await rest.get("/api/v1/sightings")).json()

    row = body["items"][0]
    assert row["registration"] is None
    assert row["aircraft_type"] is None
    assert row["classification"] is None
    assert row["provenance"] == {}


# ---------------------------------------------------------------------- detail


async def test_detail_reports_flight_context_reception_and_records(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(
        live_app,
        closed_sighting(
            callsign_last="RCH492",
            squawk_last="4521",
            closure_reason="gap_timeout",
            rssi_peak_db=-3.2,
            rssi_avg_db=-11.8,
            rssi_min_db=-27.4,
            msg_count=48210,
            pos_count=2210,
            pos_time_pct=92.4,
            closest_approach_nm=11.2,
            max_range_nm=96.0,
            lowest_alt_ft=21000,
            highest_alt_ft=28000,
            origin_ident="KTCM",
            destination_ident="PHIK",
            route_source="aerodatabox",
        ),
        aircraft=AIRCRAFT,
    )

    body = (await rest.get(f"/api/v1/sightings/{seeded[0]}")).json()

    detail = SightingDetail.model_validate(body)
    assert detail.icao == "ae1463"
    assert detail.callsign == "RCH492"
    assert detail.squawk == "4521"
    assert detail.closure_reason == "gap_timeout"
    assert detail.route.origin == "KTCM"
    assert detail.route.destination == "PHIK"
    assert detail.reception.rssi_peak_db == pytest.approx(-3.2)
    assert detail.reception.message_count == 48210
    assert detail.reception.position_count == 2210
    assert detail.reception.pct_with_position == pytest.approx(92.4)
    assert detail.records.closest_approach_nm == pytest.approx(11.2)
    assert detail.records.max_range_nm == pytest.approx(96.0)
    assert detail.records.lowest_altitude_ft == 21000
    assert detail.records.highest_altitude_ft == 28000
    assert detail.provenance["route"] == "aerodatabox"


async def test_detail_reports_no_route_provenance_when_there_is_no_route(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(live_app, closed_sighting(), aircraft=AIRCRAFT)

    body = (await rest.get(f"/api/v1/sightings/{seeded[0]}")).json()

    assert body["route"] == {
        "origin": None,
        "origin_name": None,
        "destination": None,
        "destination_name": None,
    }
    assert "route" not in body["provenance"]


async def test_detail_reports_the_event_timeline_in_order(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(live_app, closed_sighting(), aircraft=AIRCRAFT)
    await seed_events(
        live_app.app.state.database,
        seeded[0],
        [
            (BASE_MS + 5_000, "squawk_change", {"from": "7000", "to": "4521"}),
            (BASE_MS + 10_000, "emergency_start", {"squawk": "7700"}),
            (BASE_MS + 15_000, "emergency_end", {"squawk": "4521"}),
        ],
    )

    body = (await rest.get(f"/api/v1/sightings/{seeded[0]}")).json()

    events = body["events"]
    assert [event["type"] for event in events] == [
        "squawk_change",
        "emergency_start",
        "emergency_end",
    ]
    assert events[0]["detail"] == {"from": "7000", "to": "4521"}
    assert events[1]["detail"] == {"squawk": "7700"}


async def test_detail_404s_for_an_id_that_does_not_exist(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/sightings/999999")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert "999999" in body["error"]["message"]


# ------------------------------------------------------------------- path


CLOSED_PATH = (
    TrackSample(
        ts_ms=BASE_MS, latitude=47.11, longitude=-121.80, position_source="adsb", altitude_ft=21000
    ),
    TrackSample(
        ts_ms=BASE_MS + 92_000,
        latitude=47.19,
        longitude=-121.88,
        position_source="adsb",
        altitude_ft=21850,
    ),
    TrackSample(
        ts_ms=BASE_MS + 184_000,
        latitude=47.25,
        longitude=-121.95,
        position_source="mlat",
        altitude_ft=None,
    ),
)


async def test_a_closed_sightings_path_round_trips_the_packed_track(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(live_app, closed_sighting(), aircraft=AIRCRAFT)
    await seed_track(live_app.app.state.database, seeded[0], CLOSED_PATH)

    body = (await rest.get(f"/api/v1/sightings/{seeded[0]}")).json()

    path = body["path"]
    assert len(path) == len(CLOSED_PATH)
    for point, sample in zip(path, CLOSED_PATH, strict=True):
        assert point["lat"] == pytest.approx(sample.latitude, abs=1e-4)
        assert point["lon"] == pytest.approx(sample.longitude, abs=1e-4)
        assert point["altitude_ft"] == sample.altitude_ft
        assert point["source"] == sample.position_source
    # Timestamp-ordered, oldest first.
    parsed = [datetime.fromisoformat(point["t"].replace("Z", "+00:00")) for point in path]
    assert parsed == sorted(parsed)


async def test_a_closed_sighting_with_no_path_reports_an_empty_list(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(live_app, closed_sighting(), aircraft=AIRCRAFT)

    body = (await rest.get(f"/api/v1/sightings/{seeded[0]}")).json()

    assert body["path"] == []


async def test_an_open_sightings_path_comes_from_its_checkpoints(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    seeded = await seed(live_app, open_sighting(), aircraft=AIRCRAFT)
    checkpoint_path = (
        TrackSample(
            ts_ms=BASE_MS, latitude=47.0, longitude=-122.0, position_source="adsb", altitude_ft=5000
        ),
        TrackSample(
            ts_ms=BASE_MS + 10_000,
            latitude=47.01,
            longitude=-122.01,
            position_source="adsb",
            altitude_ft=5100,
        ),
    )
    await seed_checkpoints(live_app.app.state.database, seeded[0], checkpoint_path)

    body = (await rest.get(f"/api/v1/sightings/{seeded[0]}")).json()

    assert body["ended_at"] is None
    path = body["path"]
    assert len(path) == 2
    assert path[0]["lat"] == pytest.approx(47.0)
    assert path[1]["altitude_ft"] == 5100


# ------------------------------------------------------------ per-aircraft


async def test_the_per_aircraft_endpoint_is_the_same_shape_filtered_by_icao(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    aircraft = [
        SeedAircraft(icao24="ae1463", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
        SeedAircraft(icao24="a1b2c3", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
    ]
    seeded = await seed(
        live_app,
        closed_sighting("ae1463"),
        closed_sighting("a1b2c3"),
        aircraft=aircraft,
    )

    body = (await rest.get("/api/v1/aircraft/ae1463/sightings")).json()

    assert ids(body) == [seeded[0]]
    assert body["total"] is None
    row = SightingRow.model_validate(body["items"][0])
    assert row.icao == "ae1463"


async def test_the_per_aircraft_endpoint_answers_empty_for_a_never_sighted_address(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/aircraft/aaaaaa/sightings")

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.parametrize("icao", ["AE1463", "ae146", "not-hex"])
async def test_the_per_aircraft_endpoint_rejects_a_malformed_icao(
    live_app: LiveApp, rest: AsyncClient, icao: str
) -> None:
    response = await rest.get(f"/api/v1/aircraft/{icao}/sightings")

    assert response.status_code == 422
