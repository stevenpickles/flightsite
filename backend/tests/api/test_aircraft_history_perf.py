"""Query-time sanity for the Aircraft page over a several-thousand-row fixture.

Roadmap slice 029's acceptance criterion: "sorting/pagination correct on a
multi-thousand-aircraft fixture DB with responsive queries." This is not a
micro-benchmark — it is the guard that a future change (a lost index, a join
that turns quadratic, an N+1) would trip, with a bound generous enough that a
loaded CI runner does not fail it on noise alone (``docs/TEST_STRATEGY.md``
§3's "sanity, not a benchmark" style, matching ``tests/live/test_perf.py`` and
``tests/metadata/test_hot_path.py``).

Rows are bulk-inserted the same way :mod:`tests.api.aircraft_history_fixtures`
always does — SQLAlchemy Core ``insert()`` against the ORM models — because
driving several thousand aircraft through the live→sighting→persistence
pipeline would itself take longer than the budget this test checks.
"""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient

from .aircraft_history_fixtures import SeedAircraft, seed_aircraft, seed_operator_groups
from .conftest import LiveApp

pytestmark = pytest.mark.perf

#: Comfortably into "multi-thousand" per the acceptance criterion, and large
#: enough that an accidentally-quadratic query would be obvious rather than
#: hidden in noise.
AIRCRAFT_COUNT = 4_000
BASE_MS = 1_756_000_000_000
DAY_MS = 86_400_000

#: Generous wall-clock budget per request. The point is catching a
#: pathological plan (a full unindexed scan repeated per row, an N+1 on the
#: join), not asserting a tight latency figure a slow CI runner would flake
#: on.
QUERY_BUDGET_S = 2.0

TYPE_CODES = ("B738", "A320", "C172", "EC35", "B77W")
OPERATORS = ("Alpha Airlines", "Beta Cargo", "Charlie Charters", "Delta Jets")


def _row(index: int) -> SeedAircraft:
    return SeedAircraft(
        icao24=f"{index:06x}",
        first_seen_ms=BASE_MS - (index % 365) * DAY_MS,
        last_seen_ms=BASE_MS - (index % 30) * DAY_MS,
        sighting_count=1 + index % 200,
        total_observed_ms=60_000 + index * 137,
        closest_approach_nm=0.5 + (index % 400) / 10,
        max_range_nm=10.0 + (index % 2500) / 5,
        lowest_alt_ft=500 + index % 3000,
        highest_alt_ft=10_000 + index % 40_000,
        registration=f"N{index:05d}",
        type_code=TYPE_CODES[index % len(TYPE_CODES)],
        model=f"Model {TYPE_CODES[index % len(TYPE_CODES)]}",
        operator_name=OPERATORS[index % len(OPERATORS)],
        mission_category="military" if index % 11 == 0 else "commercial_passenger",
        military=index % 11 == 0,
    )


@pytest.fixture
async def populated(live_app: LiveApp) -> LiveApp:
    rows = [_row(index) for index in range(AIRCRAFT_COUNT)]
    await seed_operator_groups(live_app.app.state.database, [])
    await seed_aircraft(live_app.app.state.database, rows)
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
        # An indexed sort (`ix_aircraft_last_seen`) and the documented default.
        "/api/v1/aircraft?sort=last_seen&order=desc&limit=50",
        # An unindexed sort — the module docstring's documented cost.
        "/api/v1/aircraft?sort=closest_approach_nm&order=asc&limit=50",
        "/api/v1/aircraft?sort=max_range_nm&order=desc&limit=50",
        # Deep pagination: the last page of a 4,000-row result.
        "/api/v1/aircraft?sort=icao&order=asc&limit=50&offset=3950",
        # A filtered read, which pays for the extra joins on every row.
        "/api/v1/aircraft?classification=military&sort=last_seen&limit=50",
        "/api/v1/aircraft?type=B738&sort=registration&limit=50",
    ],
)
async def test_a_page_of_the_list_answers_inside_the_budget(
    populated: LiveApp, rest: AsyncClient, path: str
) -> None:
    elapsed, body = await _timed_get(rest, path)

    print(f"{path}: {elapsed * 1000:.1f} ms for {AIRCRAFT_COUNT} aircraft")
    assert elapsed < QUERY_BUDGET_S
    assert len(body["items"]) > 0  # type: ignore[arg-type]


async def test_the_total_count_is_exact_against_the_full_fixture(
    populated: LiveApp, rest: AsyncClient
) -> None:
    elapsed, body = await _timed_get(rest, "/api/v1/aircraft?limit=1")

    assert body["total"] == AIRCRAFT_COUNT
    assert elapsed < QUERY_BUDGET_S


async def test_detail_answers_inside_the_budget_regardless_of_table_size(
    populated: LiveApp, rest: AsyncClient
) -> None:
    icao = f"{AIRCRAFT_COUNT // 2:06x}"

    elapsed, body = await _timed_get(rest, f"/api/v1/aircraft/{icao}")

    assert elapsed < QUERY_BUDGET_S
    assert body["icao"] == icao
