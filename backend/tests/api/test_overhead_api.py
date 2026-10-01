"""``GET /api/v1/overhead`` — "What was that?" (roadmap slice 090, issue #233).

The published contract (shape, the ``closest_position_fix`` method, UTC in
and out), candidate selection at the window's edges, closed sightings from
their packed track and open ones from their checkpoints, ranking, the
bounded decode, validation, and the empty-with-reason answer when no
receiver location is set.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

from flightsite.api import overhead as overhead_module
from flightsite.api.overhead import CANDIDATE_LOOKBACK_MS, OverheadRepository
from flightsite.api.schemas import OverheadResponse
from flightsite.db.clock import from_epoch_ms, utc_now_ms
from flightsite.db.models import SightingTrack
from flightsite.sightings.tracks import TrackSample

from ..live.conftest import SEATTLE
from .aircraft_history_fixtures import SeedAircraft
from .conftest import LiveApp
from .sighting_fixtures import SeedSighting, seed_checkpoints, seed_sightings, seed_track

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
#: A fixed moment, well away from "now", so the default-``at`` test is the
#: only one that depends on the clock.
AT_MS = 1_756_000_000_000
NM_IN_DEG = 1.0 / 60.0


def point(
    ts_ms: int,
    *,
    north_nm: float = 0.0,
    east_nm: float = 0.0,
    altitude_ft: int | None = 5_000,
) -> TrackSample:
    """A stored point ``north_nm``/``east_nm`` from the test receiver."""
    return TrackSample(
        ts_ms=ts_ms,
        latitude=SEATTLE.latitude + north_nm * NM_IN_DEG,
        longitude=SEATTLE.longitude
        + east_nm * NM_IN_DEG / math.cos(math.radians(SEATTLE.latitude)),
        position_source="adsb",
        altitude_ft=altitude_ft,
    )


def iso(ms: int) -> str:
    return from_epoch_ms(ms).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def closed(icao: str, started_ms: int, ended_ms: int, **fields: Any) -> SeedSighting:
    return SeedSighting(
        icao24=icao,
        started_ms=started_ms,
        ended_ms=ended_ms,
        duration_ms=ended_ms - started_ms,
        closure_reason="gap_timeout",
        pos_count=10,
        **fields,
    )


def opened(icao: str, started_ms: int, **fields: Any) -> SeedSighting:
    return SeedSighting(icao24=icao, started_ms=started_ms, pos_count=5, **fields)


def airframe(icao: str, **fields: Any) -> SeedAircraft:
    return SeedAircraft(icao24=icao, first_seen_ms=AT_MS, last_seen_ms=AT_MS, **fields)


async def seed(
    live_app: LiveApp,
    rows: Sequence[SeedSighting],
    paths: Sequence[Sequence[TrackSample]],
    *,
    aircraft: Sequence[SeedAircraft] | None = None,
) -> list[int]:
    """Seed sightings and each one's stored points (track or checkpoints)."""
    database = live_app.app.state.database
    icaos = sorted({row.icao24 for row in rows})
    ids = await seed_sightings(database, aircraft or [airframe(icao) for icao in icaos], rows)
    for sighting_id, row, samples in zip(ids, rows, paths, strict=True):
        if not samples:
            continue
        if row.ended_ms is None:
            await seed_checkpoints(database, sighting_id, samples)
        else:
            await seed_track(database, sighting_id, samples)
    return ids


async def lookup(rest: AsyncClient, query: str = "") -> dict[str, Any]:
    response = await rest.get(f"/api/v1/overhead?at={iso(AT_MS)}{query}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def ids_of(body: dict[str, Any]) -> list[int]:
    return [item["sighting_id"] for item in body["items"]]


# ------------------------------------------------------------------ contract


async def test_the_response_is_the_published_shape(live_app: LiveApp, rest: AsyncClient) -> None:
    [sighting_id] = await seed(
        live_app,
        [closed("ae1463", AT_MS - 5 * MINUTE_MS, AT_MS + 5 * MINUTE_MS, callsign_last="RCH492")],
        [[point(AT_MS - MINUTE_MS, north_nm=3.0, altitude_ft=4_000)]],
        aircraft=[
            airframe(
                "ae1463",
                registration="N123AB",
                type_code="C17",
                model="C-17A",
                operator_name="USAF",
            )
        ],
    )

    body = await lookup(rest)

    OverheadResponse.model_validate(body)
    assert body["method"] == "closest_position_fix"
    assert body["receiver_configured"] is True
    assert body["reason"] is None
    assert body["at"] == iso(AT_MS)
    assert body["window_minutes"] == 10
    assert body["window_start"] == iso(AT_MS - 10 * MINUTE_MS)
    assert body["window_end"] == iso(AT_MS + 10 * MINUTE_MS)
    assert body["candidates"] == 1
    assert body["truncated"] is False
    [item] = body["items"]
    assert item["sighting_id"] == sighting_id
    assert item["icao"] == "ae1463"
    assert item["callsign"] == "RCH492"
    assert (item["registration"], item["aircraft_type"], item["model"], item["operator"]) == (
        "N123AB",
        "C17",
        "C-17A",
        "USAF",
    )
    assert item["open"] is False
    assert item["fix_at"] == iso(AT_MS - MINUTE_MS)
    assert item["fix_at"].endswith("Z")
    assert item["altitude_ft"] == 4_000
    assert item["distance_kind"] == "slant"
    assert item["ground_distance_nm"] == pytest.approx(3.0, rel=5e-3)
    assert item["distance_nm"] > item["ground_distance_nm"]
    assert item["bearing_deg"] == pytest.approx(0.0, abs=0.1)
    assert item["position_source"] == "adsb"


async def test_the_endpoint_is_in_the_openapi_document(rest: AsyncClient) -> None:
    schema = (await rest.get("/api/v1/openapi.json")).json()

    assert "/api/v1/overhead" in schema["paths"]


async def test_an_offset_at_is_answered_in_utc(live_app: LiveApp, rest: AsyncClient) -> None:
    local = from_epoch_ms(AT_MS).astimezone().isoformat()
    response = await rest.get("/api/v1/overhead", params={"at": local})

    assert response.json()["at"] == iso(AT_MS)


async def test_an_at_without_an_offset_is_taken_as_utc(rest: AsyncClient) -> None:
    naive = from_epoch_ms(AT_MS).replace(tzinfo=None).isoformat()
    response = await rest.get("/api/v1/overhead", params={"at": naive})

    assert response.json()["at"] == iso(AT_MS)


async def test_at_defaults_to_now(live_app: LiveApp, rest: AsyncClient) -> None:
    now_ms = utc_now_ms()
    [sighting_id] = await seed(
        live_app,
        [opened("ae1463", now_ms - 2 * MINUTE_MS)],
        [[point(now_ms - MINUTE_MS, north_nm=1.0)]],
    )

    body = (await rest.get("/api/v1/overhead")).json()

    at = datetime.fromisoformat(body["at"].replace("Z", "+00:00"))
    assert abs(at.timestamp() * 1000 - now_ms) < HOUR_MS
    assert at.tzinfo == UTC
    assert ids_of(body) == [sighting_id]


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("query", ["window=0", "window=61", "limit=0", "limit=51", "window=x"])
async def test_out_of_bounds_parameters_are_a_validation_error(
    rest: AsyncClient, query: str
) -> None:
    response = await rest.get(f"/api/v1/overhead?{query}")

    assert response.status_code == 422


async def test_an_unparseable_at_is_a_validation_error(rest: AsyncClient) -> None:
    response = await rest.get("/api/v1/overhead?at=yesterday")

    assert response.status_code == 422


@pytest.mark.parametrize("query", ["window=1", "window=60", "limit=1", "limit=50"])
async def test_the_bounds_themselves_are_accepted(rest: AsyncClient, query: str) -> None:
    response = await rest.get(f"/api/v1/overhead?{query}")

    assert response.status_code == 200


# ------------------------------------------------------------- receiver unset


async def test_no_receiver_location_is_an_empty_answer_with_a_reason(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        [closed("ae1463", AT_MS - MINUTE_MS, AT_MS + MINUTE_MS)],
        [[point(AT_MS, north_nm=1.0)]],
    )
    live_app.live.set_receiver_location(None)

    body = await lookup(rest)

    OverheadResponse.model_validate(body)
    assert body["receiver_configured"] is False
    assert body["reason"] == "receiver_location_unset"
    assert body["items"] == []
    assert body["candidates"] == 0
    assert body["window_start"] == iso(AT_MS - 10 * MINUTE_MS)


# ------------------------------------------------------- candidate selection


async def test_sightings_spanning_either_window_edge_are_candidates(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    window = 10 * MINUTE_MS
    rows = [
        # Began before the window, ended inside it.
        closed("a00001", AT_MS - window - 30 * MINUTE_MS, AT_MS - 5 * MINUTE_MS),
        # Began inside the window, ended after it.
        closed("a00002", AT_MS + 5 * MINUTE_MS, AT_MS + window + 30 * MINUTE_MS),
        # Spans the whole window.
        closed("a00003", AT_MS - 2 * HOUR_MS, AT_MS + 2 * HOUR_MS),
        # Ended exactly at the window's start (inclusive).
        closed("a00004", AT_MS - HOUR_MS, AT_MS - window),
        # Ended before the window.
        closed("a00005", AT_MS - HOUR_MS, AT_MS - window - 1),
        # Began after the window.
        closed("a00006", AT_MS + window + 1, AT_MS + HOUR_MS),
    ]
    paths = [
        [point(AT_MS - 6 * MINUTE_MS, north_nm=1.0)],
        [point(AT_MS + 6 * MINUTE_MS, north_nm=2.0)],
        [point(AT_MS, north_nm=3.0)],
        [point(AT_MS - window, north_nm=4.0)],
        [point(AT_MS - window - 1, north_nm=0.1)],
        [point(AT_MS + window + 1, north_nm=0.1)],
    ]
    ids = await seed(live_app, rows, paths)

    body = await lookup(rest)

    assert ids_of(body) == ids[:4]
    assert body["candidates"] == 4


async def test_a_sighting_with_no_stored_point_in_the_window_is_left_out(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """Its straight leg crosses the window with both endpoints outside it."""
    await seed(
        live_app,
        [closed("ae1463", AT_MS - HOUR_MS, AT_MS + HOUR_MS)],
        [[point(AT_MS - HOUR_MS, east_nm=-20.0), point(AT_MS + HOUR_MS, east_nm=20.0)]],
    )

    body = await lookup(rest)

    assert body["candidates"] == 1
    assert body["items"] == []


async def test_a_closed_sighting_older_than_the_lookback_is_not_a_candidate(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """The documented limit of the lookup (``flightsite.api.overhead``)."""
    started = AT_MS - 10 * MINUTE_MS - CANDIDATE_LOOKBACK_MS - MINUTE_MS
    await seed(
        live_app,
        [closed("ae1463", started, AT_MS + HOUR_MS)],
        [[point(started, north_nm=5.0), point(AT_MS, north_nm=1.0)]],
    )

    body = await lookup(rest)

    assert body["items"] == []


async def test_an_open_sighting_is_answered_from_its_checkpoints(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    [sighting_id] = await seed(
        live_app,
        [opened("ae1463", AT_MS - 3 * HOUR_MS)],
        [
            [
                point(AT_MS - HOUR_MS, north_nm=0.2),  # closer, but outside the window
                point(AT_MS - 4 * MINUTE_MS, north_nm=6.0),
                point(AT_MS + 2 * MINUTE_MS, north_nm=2.5, altitude_ft=None),
            ]
        ],
    )

    body = await lookup(rest)

    [item] = body["items"]
    assert item["sighting_id"] == sighting_id
    assert item["open"] is True
    assert item["fix_at"] == iso(AT_MS + 2 * MINUTE_MS)
    assert item["altitude_ft"] is None
    assert item["distance_kind"] == "ground"
    assert item["distance_nm"] == item["ground_distance_nm"]


async def test_an_open_sighting_older_than_the_lookback_is_still_a_candidate(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    started = AT_MS - 2 * CANDIDATE_LOOKBACK_MS
    [sighting_id] = await seed(
        live_app, [opened("ae1463", started)], [[point(AT_MS, north_nm=1.0)]]
    )

    body = await lookup(rest)

    assert ids_of(body) == [sighting_id]


async def test_an_open_sighting_that_began_after_the_window_is_not_a_candidate(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed(
        live_app,
        [opened("ae1463", AT_MS + HOUR_MS)],
        [[point(AT_MS + HOUR_MS, north_nm=1.0)]],
    )

    body = await lookup(rest)

    assert body["candidates"] == 0


# ------------------------------------------------------------------- ranking


async def test_results_are_ranked_nearest_first_and_limited(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    rows = [closed(f"a0000{n}", AT_MS - MINUTE_MS, AT_MS + MINUTE_MS) for n in range(1, 5)]
    paths = [
        [point(AT_MS, north_nm=7.0)],
        [point(AT_MS, north_nm=1.0)],
        [point(AT_MS, north_nm=4.0)],
        [point(AT_MS, north_nm=2.0)],
    ]
    ids = await seed(live_app, rows, paths)

    body = await lookup(rest, "&limit=3")

    assert ids_of(body) == [ids[1], ids[3], ids[2]]
    distances = [item["distance_nm"] for item in body["items"]]
    assert distances == sorted(distances)


async def test_a_wider_window_reaches_further(live_app: LiveApp, rest: AsyncClient) -> None:
    [sighting_id] = await seed(
        live_app,
        [closed("ae1463", AT_MS + 20 * MINUTE_MS, AT_MS + 40 * MINUTE_MS)],
        [[point(AT_MS + 25 * MINUTE_MS, north_nm=1.0)]],
    )

    assert (await lookup(rest, "&window=10"))["items"] == []
    assert ids_of(await lookup(rest, "&window=30")) == [sighting_id]


# ------------------------------------------------------- the bounded decode


async def test_the_bounded_search_decodes_less_and_answers_the_same(
    live_app: LiveApp,
) -> None:
    """Sightings whose recorded closest approach cannot beat the answer are never decoded."""
    count = 40
    rows = [
        closed(
            f"b{n:05x}",
            AT_MS - MINUTE_MS,
            AT_MS + MINUTE_MS,
            closest_approach_nm=float(n + 1),
        )
        for n in range(count)
    ]
    paths = [[point(AT_MS, north_nm=float(n + 1), altitude_ft=None)] for n in range(count)]
    ids = await seed(live_app, rows, paths)
    repository = OverheadRepository(live_app.app.state.database)

    result = await repository.closest_passes(
        receiver=SEATTLE, from_ms=AT_MS - MINUTE_MS, to_ms=AT_MS + MINUTE_MS, limit=3
    )

    assert [item.sighting_id for item in result.passes] == ids[:3]
    assert result.candidates == count
    assert result.decoded < count


async def test_the_candidate_cap_keeps_the_best_bounds_and_says_so(
    live_app: LiveApp, rest: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(overhead_module, "MAX_CANDIDATES", 2)
    rows = [
        closed(f"c0000{n}", AT_MS - MINUTE_MS, AT_MS + MINUTE_MS, closest_approach_nm=float(n))
        for n in (3, 1, 2)
    ]
    paths = [[point(AT_MS, north_nm=float(n), altitude_ft=None)] for n in (3, 1, 2)]
    ids = await seed(live_app, rows, paths)

    body = await lookup(rest)

    assert body["truncated"] is True
    assert body["candidates"] == 2
    assert ids_of(body) == [ids[1], ids[2]]


async def test_an_undecodable_track_is_skipped_not_fatal(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    ids = await seed(
        live_app,
        [
            closed("ae1463", AT_MS - MINUTE_MS, AT_MS + MINUTE_MS),
            closed("ae1464", AT_MS - MINUTE_MS, AT_MS + MINUTE_MS),
        ],
        [[], [point(AT_MS, north_nm=2.0)]],
    )
    async with live_app.app.state.database.writer_session() as session:
        session.add(
            SightingTrack(
                sighting_id=ids[0],
                encoding_version=99,
                point_count=1,
                started_ms=AT_MS,
                points_blob=b"\x63\x01\x00\x00\x00",
            )
        )

    body = await lookup(rest)

    assert ids_of(body) == [ids[1]]
