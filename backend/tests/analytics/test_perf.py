"""Query-time sanity for the analytics endpoints over a multi-year fixture.

Roadmap slice 031's acceptance criterion: *"multi-year fixture queries within
budget"*, where the budget is *"target <500ms on dev hardware; Pi validated in
049"*. This is not a micro-benchmark — it is the guard that a future change (a
rollup read that quietly became a ``sightings`` scan, a lost whole-history
shortcut, an N+1 on the metadata join) would trip.

The asserted bound is the documented budget times
:data:`CI_HEADROOM`, matching the "sanity, not a benchmark" style of
``tests/api/test_aircraft_history_perf.py``: a loaded CI runner must not fail
this on noise, while a pathological plan is still an order of magnitude clear
of it. Every case prints its own measured time, so the real figure is visible
in the run output rather than hidden behind the generous assertion.

The fixture is two years of daily rollup rows over a realistic sighting volume,
bulk-inserted the way :mod:`tests.api.sighting_fixtures` always does — driving
a hundred thousand sightings through the live→worker pipeline would itself take
far longer than everything this test measures.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from flightsite.analytics.backfill import AnalyticsBackfill
from flightsite.analytics.bucketing import day_bounds_ms, local_day, shift_days
from flightsite.analytics.repository import AnalyticsRepository
from flightsite.app import create_app
from flightsite.db import Database, MetaRepository, ReceiverMetricDaily
from flightsite.db.clock import utc_now_ms

from ..api.aircraft_history_fixtures import SeedAircraft, seed_operator_groups
from ..api.sighting_fixtures import SeedSighting, seed_sightings
from .conftest import NEW_YORK

pytestmark = pytest.mark.perf

#: Two years of history — the "multi-year fixture" the criterion names.
FIXTURE_DAYS = 730

#: Sightings per local day. A home receiver on a moderately busy patch of sky;
#: ``docs/DATA_MODEL.md`` §6.5 sizes a *busy* one at ~1,500/day, and the
#: queries here scale with the window's row count rather than with history, so
#: this is chosen to keep the fixture build itself from dominating the test.
SIGHTINGS_PER_DAY = 250

#: Distinct airframes across the whole fixture.
AIRFRAMES = 6_000

#: The documented dev-hardware budget (roadmap slice 031).
QUERY_BUDGET_S = 0.5

#: Multiplier applied to the budget for the asserted bound — the established
#: allowance for a shared CI runner.
CI_HEADROOM = 5

ASSERT_BUDGET_S = QUERY_BUDGET_S * CI_HEADROOM

TYPE_CODES = ("B738", "A320", "C172", "EC35", "B77W", "PC12", "SR22", None)
OPERATOR_GROUPS = (("alpha", "Alpha Airlines"), ("beta", "Beta Cargo"), ("gamma", "Gamma Jets"))
SLUGS = ("alpha", "beta", "gamma", None)

PATHS = (
    "/api/v1/analytics/summary",
    "/api/v1/analytics/daily",
    "/api/v1/analytics/classification-activity",
    "/api/v1/analytics/top-aircraft",
    "/api/v1/analytics/top-types",
    "/api/v1/analytics/top-operators",
    "/api/v1/analytics/rarity",
)
PRESETS = ("today", "7d", "30d", "ytd", "t0")


class Fixture:
    """Two years of sightings, their rollups, and the app serving them."""

    def __init__(self, app: object, zone: ZoneInfo, now_ms: int) -> None:
        self.app = app
        self.zone = zone
        self.now_ms = now_ms
        self.today = local_day(now_ms, zone)


def _build_rows(
    zone: ZoneInfo, today: str, now_ms: int
) -> tuple[list[SeedAircraft], list[SeedSighting]]:
    """Deterministic rows: no RNG, so the fixture is identical every run."""
    first_seen: dict[str, int] = {}
    last_seen: dict[str, int] = {}
    counts: dict[str, int] = {}
    sightings: list[SeedSighting] = []

    for day_offset in range(FIXTURE_DAYS - 1, -1, -1):
        day = shift_days(today, -day_offset)
        start_ms, end_ms = day_bounds_ms(day, zone)
        ceiling = min(end_ms, now_ms)
        span = max(1, ceiling - start_ms)
        for index in range(SIGHTINGS_PER_DAY):
            # Airframes drift slowly across the history, so early days share
            # few airframes with late ones and every window has to do real work.
            icao = f"a{((day_offset * 7 + index * 13) % AIRFRAMES):05x}"
            started_ms = start_ms + (index * span) // SIGHTINGS_PER_DAY
            first_seen.setdefault(icao, started_ms)
            first_seen[icao] = min(first_seen[icao], started_ms)
            last_seen[icao] = max(last_seen.get(icao, started_ms), started_ms)
            counts[icao] = counts.get(icao, 0) + 1
            sightings.append(
                SeedSighting(
                    icao24=icao,
                    started_ms=started_ms,
                    ended_ms=started_ms + 300_000,
                    max_range_nm=10.0 + (index % 230),
                    max_alert_severity="interesting" if index % 37 == 0 else None,
                )
            )

    aircraft = []
    for position, icao in enumerate(sorted(first_seen)):
        type_code = TYPE_CODES[position % len(TYPE_CODES)]
        slug = SLUGS[position % len(SLUGS)]
        aircraft.append(
            SeedAircraft(
                icao24=icao,
                first_seen_ms=first_seen[icao],
                last_seen_ms=last_seen[icao],
                sighting_count=counts[icao],
                max_range_nm=10.0 + (position % 240),
                registration=None if type_code is None else f"N{position:05d}",
                type_code=type_code,
                model=None if type_code is None else f"Model {type_code}",
                operator_name=None if slug is None else slug.title(),
                operator_group_slug=slug,
                military=position % 17 == 0,
                government=position % 41 == 0,
                law_enforcement=position % 53 == 0,
                mission_category="military" if position % 17 == 0 else "unknown",
            )
        )
    return aircraft, sightings


async def _seed(database: Database, zone: ZoneInfo, today: str, now_ms: int) -> int:
    aircraft, sightings = _build_rows(zone, today, now_ms)
    group_ids = await seed_operator_groups(database, list(OPERATOR_GROUPS))
    await seed_sightings(database, aircraft, sightings, group_ids=group_ids)
    await MetaRepository(database).set_t0_once(min(row.started_ms for row in sightings))
    async with database.writer_session() as session:
        session.add_all(
            [
                ReceiverMetricDaily(
                    day=shift_days(today, -offset),
                    messages_total=4_000_000 + offset,
                    positions_total=300_000 + offset,
                    aircraft_max=200 + offset % 90,
                    sample_count=5_760,
                )
                for offset in range(FIXTURE_DAYS)
            ]
        )
    return len(sightings)


@pytest.fixture
async def populated(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Fixture]:
    """A started app over two years of seeded, fully rolled-up history."""
    monkeypatch.setenv("FLIGHTSITE_TIMEZONE", NEW_YORK)
    app = create_app()
    database: Database = app.state.database
    await database.upgrade_to("head")
    zone = ZoneInfo(NEW_YORK)
    now_ms = utc_now_ms()
    today = local_day(now_ms, zone)

    started = time.perf_counter()
    rows = await _seed(database, zone, today, now_ms)
    seeded_s = time.perf_counter() - started

    # The backfill is timed too: rebuilding two years of rollups is what an
    # install upgrading into this slice pays once, and a regression that made
    # it quadratic would show up here long before it showed up on a Pi.
    started = time.perf_counter()
    job = AnalyticsBackfill(
        repository=AnalyticsRepository(database), meta=MetaRepository(database), zone=zone
    )
    result = await job.run_startup_repair(now_ms=now_ms)
    backfill_s = time.perf_counter() - started
    await database.dispose()

    print(
        f"\nfixture: {rows} sightings over {FIXTURE_DAYS} days seeded in {seeded_s:.1f} s; "
        f"backfill rebuilt {result.rebuilt} days in {backfill_s:.1f} s "
        f"({backfill_s / max(result.rebuilt, 1) * 1000:.1f} ms/day)"
    )

    async with app.router.lifespan_context(app):
        yield Fixture(app, zone, now_ms)


async def test_every_endpoint_answers_every_preset_inside_the_budget(
    populated: Fixture,
) -> None:
    """The acceptance criterion, measured across the whole §3.7 surface."""
    slowest: list[tuple[float, str]] = []
    async with AsyncClient(
        transport=ASGITransport(app=populated.app), base_url="http://testserver"
    ) as client:
        for path in PATHS:
            for preset in PRESETS:
                started = time.perf_counter()
                response = await client.get(path, params={"preset": preset})
                elapsed = time.perf_counter() - started
                assert response.status_code == 200, response.text
                slowest.append((elapsed, f"{path}?preset={preset}"))

        # And the largest answer the surface can be asked for: the deepest
        # ranking over the whole history.
        for path in ("top-aircraft", "top-types", "top-operators", "rarity"):
            started = time.perf_counter()
            response = await client.get(
                f"/api/v1/analytics/{path}", params={"preset": "t0", "limit": 100}
            )
            elapsed = time.perf_counter() - started
            assert response.status_code == 200, response.text
            slowest.append((elapsed, f"/api/v1/analytics/{path}?preset=t0&limit=100"))

    for elapsed, label in sorted(slowest, reverse=True):
        print(f"{elapsed * 1000:8.1f} ms  {label}")
    worst, label = max(slowest)
    assert worst < ASSERT_BUDGET_S, f"{label} took {worst * 1000:.0f} ms"


async def test_maintaining_the_current_day_stays_cheap_at_multi_year_scale(
    populated: Fixture,
) -> None:
    """The incremental path's own cost: one flush rebuilds today, not history."""
    service = populated.app.state.analytics  # type: ignore[attr-defined]
    service.mark_dirty(populated.today)

    started = time.perf_counter()
    result = await service.flush()
    elapsed = time.perf_counter() - started

    print(f"{elapsed * 1000:8.1f} ms  incremental flush of {result.rebuilt} day(s)")
    assert result.rebuilt == 1
    assert elapsed < ASSERT_BUDGET_S
