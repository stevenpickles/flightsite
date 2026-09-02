"""Query-time sanity for the Sightings page over a large fixture.

Roadmap slice 030's acceptance criterion: "log paginates efficiently over
large fixture history." Sighting volume is the scale that actually matters
here — unlike the Aircraft page (bounded by unique airframes, see
:mod:`tests.api.test_aircraft_history_perf`), a sighting is retained
indefinitely (SPEC §65) and a busy receiver produces many per airframe, so
this fixture is an order of magnitude larger and spread across fewer distinct
aircraft. Same "sanity, not a benchmark" style as
:mod:`tests.api.test_aircraft_history_perf`
(``docs/TEST_STRATEGY.md`` §3): the bound is generous enough that a loaded CI
runner does not flake, and the point is catching a pathological plan (a lost
index, a join that turns quadratic) rather than asserting a tight latency.
"""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient

from .aircraft_history_fixtures import SeedAircraft
from .conftest import LiveApp
from .sighting_fixtures import SeedSighting, seed_sightings

pytestmark = pytest.mark.perf

#: Comfortably larger than the Aircraft page's fixture (4,000) — sighting
#: volume, not airframe count, is what `/sightings` has to stay responsive
#: against.
SIGHTING_COUNT = 12_000
#: A busy receiver sees far fewer distinct airframes than sightings.
AIRCRAFT_COUNT = 800
BASE_MS = 1_756_000_000_000
MINUTE_MS = 60_000

QUERY_BUDGET_S = 2.0


def _aircraft_rows() -> list[SeedAircraft]:
    return [
        SeedAircraft(
            icao24=f"{index:06x}",
            first_seen_ms=BASE_MS - SIGHTING_COUNT * MINUTE_MS,
            last_seen_ms=BASE_MS,
        )
        for index in range(AIRCRAFT_COUNT)
    ]


def _sighting_rows() -> list[SeedSighting]:
    rows = []
    for index in range(SIGHTING_COUNT):
        started_ms = BASE_MS - (SIGHTING_COUNT - index) * MINUTE_MS
        rows.append(
            SeedSighting(
                icao24=f"{index % AIRCRAFT_COUNT:06x}",
                started_ms=started_ms,
                ended_ms=started_ms + 30_000,
                duration_ms=30_000,
                closure_reason="gap_timeout",
                closest_approach_nm=0.5 + (index % 400) / 10,
                max_range_nm=10.0 + (index % 2500) / 5,
                lowest_alt_ft=500 + index % 3000,
                highest_alt_ft=10_000 + index % 40_000,
                pos_count=1 + index % 500,
                max_alert_severity="high" if index % 37 == 0 else None,
            )
        )
    return rows


@pytest.fixture
async def populated(live_app: LiveApp) -> LiveApp:
    await seed_sightings(live_app.app.state.database, _aircraft_rows(), _sighting_rows())
    return live_app


async def _timed_get(rest: AsyncClient, path: str) -> tuple[float, dict[str, object]]:
    started = time.perf_counter()
    response = await rest.get(path)
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return elapsed, body


@pytest.mark.parametrize(
    "path",
    [
        # The indexed default: `started_at` descending, first page.
        "/api/v1/sightings?sort=started_at&order=desc&limit=50",
        # Deep pagination over the full fixture.
        "/api/v1/sightings?sort=started_at&order=asc&limit=50&offset=11950",
        # An unindexed sort — the module docstring's documented cost.
        "/api/v1/sightings?sort=closest_approach_nm&order=asc&limit=50",
        # Indexed since rev 0013 (`ix_sightings_max_range`), in both
        # directions: descending reads the index backward and sorts only
        # within groups of equal ranges.
        "/api/v1/sightings?sort=max_range_nm&order=desc&limit=50",
        "/api/v1/sightings?sort=max_range_nm&order=asc&limit=50",
        # The icao filter, which leans on `ix_sightings_aircraft`.
        "/api/v1/sightings?icao=000010&sort=started_at&limit=50",
        # The open-sightings partial index.
        "/api/v1/sightings?open=true&limit=50",
        # A filtered read with no supporting index at all.
        "/api/v1/sightings?interesting=true&sort=started_at&limit=50",
    ],
)
async def test_a_page_of_the_log_answers_inside_the_budget(
    populated: LiveApp, rest: AsyncClient, path: str
) -> None:
    elapsed, body = await _timed_get(rest, path)

    print(f"{path}: {elapsed * 1000:.1f} ms for {SIGHTING_COUNT} sightings")
    assert elapsed < QUERY_BUDGET_S
    assert body["total"] is None


async def test_the_per_aircraft_log_answers_inside_the_budget(
    populated: LiveApp, rest: AsyncClient
) -> None:
    icao = f"{AIRCRAFT_COUNT // 2:06x}"

    elapsed, body = await _timed_get(rest, f"/api/v1/aircraft/{icao}/sightings?limit=50")

    assert elapsed < QUERY_BUDGET_S
    assert len(body["items"]) > 0  # type: ignore[arg-type]


async def test_detail_answers_inside_the_budget_regardless_of_table_size(
    populated: LiveApp, rest: AsyncClient
) -> None:
    elapsed, body = await _timed_get(rest, "/api/v1/sightings/1")

    assert elapsed < QUERY_BUDGET_S
    assert body["id"] == 1
