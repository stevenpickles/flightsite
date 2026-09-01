"""``GET /api/v1/analytics/*`` — ``docs/API.md`` §3.7, across the five presets.

The app is built and started through its real lifespan, so these tests exercise
the wiring as well as the queries: the analytics service is running, its
startup backfill has been through, and every response is validated by the
Pydantic model FastAPI publishes in the OpenAPI document (§2.10).

Time, and why it is not faked here
-----------------------------------

Preset resolution against a hand-driven clock is exhaustively covered in
:mod:`tests.analytics.test_bucketing`. What these tests need instead is the
*real* seam a request takes, so they seed against the receiver's actual current
local day — and place every fixture sighting strictly inside that day's bounds
rather than at a fixed offset from now, so a run that happens to start a minute
after local midnight asserts exactly what a run at noon does.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from flightsite.activity import (
    ActivityBatch,
    ActivityEventType,
    ActivityRepository,
    NewActivityEvent,
)
from flightsite.analytics.bucketing import day_bounds_ms, local_day, local_hour, shift_days
from flightsite.analytics.service import AnalyticsService
from flightsite.api.serializers import iso_utc
from flightsite.app import create_app
from flightsite.db import (
    Database,
    MetaRepository,
    ReceiverMetricDaily,
    ReceiverMetricHourly,
    from_epoch_ms,
)
from flightsite.db.clock import utc_now_ms
from flightsite.receiver_metrics.aggregate import hour_start_ms

from ..api.aircraft_history_fixtures import SeedAircraft, seed_operator_groups
from ..api.sighting_fixtures import SeedSighting, seed_sightings
from .conftest import KOLKATA, MS_PER_HOUR, NEW_YORK

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

OPERATOR_GROUPS = (("alpha", "Alpha Airlines"), ("beta", "Beta Cargo"))

#: How far back the fixture's oldest sighting sits — past ``30d`` so the
#: whole-history query forms answer something the rolling presets do not.
LONG_AGO_DAYS = 40


class Harness:
    """A started app plus the fixture data seeded into it."""

    def __init__(self, app: FastAPI, zone: ZoneInfo, now_ms: int) -> None:
        self.app = app
        self.zone = zone
        self.now_ms = now_ms
        self.today = local_day(now_ms, zone)
        self.yesterday = shift_days(self.today, -1)
        #: Comfortably outside the 7d and 30d presets.
        self.long_ago = shift_days(self.today, -LONG_AGO_DAYS)
        self.oldest_ms = now_ms

    @property
    def database(self) -> Database:
        database: Database = self.app.state.database
        return database

    @property
    def analytics(self) -> AnalyticsService:
        service: AnalyticsService = self.app.state.analytics
        return service

    def inside(self, day: str, fraction: float) -> int:
        """An instant strictly inside ``day``'s local bounds, and before now.

        ``fraction`` picks a point through the day. For today the point is
        clamped into the part of the day that has already happened, so a test
        run seconds after local midnight still places its sightings in today.
        """
        start_ms, end_ms = day_bounds_ms(day, self.zone)
        ceiling = min(end_ms, self.now_ms)
        return start_ms + int((ceiling - start_ms) * fraction)

    async def rebuild(self, *days: str) -> None:
        """Rebuild the named days plus ``type_stats``, as the service would."""
        await self.analytics.backfill.rebuild_days(list(days), now_ms=self.now_ms)
        await self.analytics.backfill.refresh_type_stats()


async def build_harness(
    monkeypatch: pytest.MonkeyPatch, timezone: str = NEW_YORK
) -> AsyncIterator[Harness]:
    monkeypatch.setenv("FLIGHTSITE_TIMEZONE", timezone)
    app = create_app()
    async with app.router.lifespan_context(app):
        yield Harness(app, ZoneInfo(timezone), utc_now_ms())


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Harness]:
    async for value in build_harness(monkeypatch):
        yield value


@pytest.fixture
async def rest(harness: Harness) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=harness.app), base_url="http://testserver"
    ) as client:
        yield client


async def seed(harness: Harness) -> None:
    """Two days of traffic: a repeat visitor, a military airframe, a rarity.

    Deliberately small and hand-written rather than randomized — the
    correctness properties are asserted against brute force elsewhere, and what
    these tests need is a fixture whose every expected figure can be read off
    the source.
    """
    today, yesterday, long_ago = harness.today, harness.yesterday, harness.long_ago
    group_ids = await seed_operator_groups(harness.database, list(OPERATOR_GROUPS))
    frequent_first = harness.inside(yesterday, 0.2)
    oldest = harness.inside(long_ago, 0.5)
    aircraft = [
        SeedAircraft(
            icao24="a00001",
            first_seen_ms=frequent_first,
            last_seen_ms=harness.inside(today, 0.6),
            sighting_count=3,
            max_range_nm=120.0,
            registration="N00001",
            type_code="B738",
            model="Boeing 737-800",
            operator_name="Alpha Airlines",
            operator_group_slug="alpha",
            mission_category="commercial_passenger",
        ),
        SeedAircraft(
            icao24="a00002",
            first_seen_ms=harness.inside(today, 0.3),
            last_seen_ms=harness.inside(today, 0.35),
            sighting_count=1,
            max_range_nm=205.0,
            registration="N00002",
            type_code="C130",
            model="Lockheed C-130",
            operator_name="Beta Cargo",
            operator_group_slug="beta",
            military=True,
            mission_category="military",
        ),
        SeedAircraft(
            icao24="a00003",
            first_seen_ms=harness.inside(yesterday, 0.5),
            last_seen_ms=harness.inside(yesterday, 0.5),
            sighting_count=1,
            max_range_nm=40.0,
        ),
        # Well outside every rolling preset, so the ``t0`` and ``ytd`` windows
        # are provably wider than ``7d``/``30d`` and the whole-history query
        # forms are actually exercised as *different* answers.
        SeedAircraft(
            icao24="a00004",
            first_seen_ms=harness.inside(long_ago, 0.5),
            last_seen_ms=harness.inside(long_ago, 0.5),
            sighting_count=1,
            max_range_nm=15.0,
        ),
    ]
    sightings = [
        SeedSighting(icao24="a00001", started_ms=frequent_first, max_range_nm=90.0),
        SeedSighting(icao24="a00003", started_ms=harness.inside(yesterday, 0.5), max_range_nm=40.0),
        SeedSighting(icao24="a00001", started_ms=harness.inside(today, 0.4), max_range_nm=120.0),
        SeedSighting(icao24="a00001", started_ms=harness.inside(today, 0.6), max_range_nm=60.0),
        SeedSighting(
            icao24="a00002",
            started_ms=harness.inside(today, 0.3),
            max_range_nm=205.0,
            max_alert_severity="interesting",
        ),
        SeedSighting(icao24="a00004", started_ms=oldest, max_range_nm=15.0),
    ]
    await seed_sightings(harness.database, aircraft, sightings, group_ids=group_ids)
    # One millisecond before the oldest sighting, so an explicit window opening
    # *at* that sighting is provably not a whole-history window and the two
    # query forms can be compared against each other.
    await MetaRepository(harness.database).set_t0_once(oldest - 1)
    harness.oldest_ms = oldest
    await harness.rebuild(harness.long_ago, harness.yesterday, harness.today)


async def get(rest: AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await rest.get(path, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# ------------------------------------------------------------ every endpoint


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("preset", PRESETS)
async def test_every_endpoint_answers_every_preset(
    harness: Harness, rest: AsyncClient, path: str, preset: str
) -> None:
    """The acceptance criterion: all §58 analytics across all five presets."""
    await seed(harness)

    body = await get(rest, path, preset=preset)

    assert body["window"]["preset"] == preset
    assert body["window"]["timezone"] == NEW_YORK


@pytest.mark.parametrize("path", PATHS)
async def test_every_endpoint_answers_an_empty_install(rest: AsyncClient, path: str) -> None:
    """No sightings, no T0: empty results, never a 500 and never a guess."""
    body = await get(rest, path, preset="t0")

    assert body["window"]["preset"] == "t0"
    # `daily` always returns a row per day in the window so a chart has a
    # continuous series; every other endpoint returns an empty list.
    assert all(row["sightings"] == 0 for row in body.get("items", []))
    assert body.get("summary", {"sightings": 0})["sightings"] == 0


@pytest.mark.parametrize("path", PATHS)
async def test_every_endpoint_accepts_explicit_bounds(
    harness: Harness, rest: AsyncClient, path: str
) -> None:
    await seed(harness)
    start, end = day_bounds_ms(harness.yesterday, harness.zone)

    body = await get(
        rest,
        path,
        **{"from": _iso(start), "to": _iso(end)},
    )

    assert body["window"]["preset"] is None
    assert body["window"]["first_day"] == harness.yesterday


def _iso(epoch_ms: int) -> str:
    """An epoch-millisecond instant as the §2.2 bound a client would send."""
    return iso_utc(from_epoch_ms(epoch_ms))


# ---------------------------------------------------------------- summary


async def test_the_summary_counts_today_in_receiver_local_time(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    summary = (await get(rest, "/api/v1/analytics/summary", preset="today"))["summary"]

    assert summary["sightings"] == 3
    assert summary["unique_aircraft"] == 2
    assert summary["new_aircraft"] == 1
    assert summary["military"] == 1
    assert summary["interesting"] == 1
    assert summary["max_range_nm"] == pytest.approx(205.0)


async def test_the_summary_counts_distinct_airframes_not_a_sum_of_days(
    harness: Harness, rest: AsyncClient
) -> None:
    """a00001 flies on both days; a two-day window must count it once."""
    await seed(harness)

    summary = (await get(rest, "/api/v1/analytics/summary", preset="7d"))["summary"]

    assert summary["sightings"] == 5
    assert summary["unique_aircraft"] == 3
    assert summary["new_aircraft"] == 3


async def test_the_since_t0_summary_agrees_with_the_windowed_one(
    harness: Harness, rest: AsyncClient
) -> None:
    """The whole-history shortcut reads ``aircraft``; it must not disagree.

    The comparison window opens one millisecond after T0, which covers exactly
    the same sightings while taking the ordinary ``COUNT(DISTINCT)`` path.
    """
    await seed(harness)

    whole = (await get(rest, "/api/v1/analytics/summary", preset="t0"))["summary"]
    windowed = (
        await get(
            rest,
            "/api/v1/analytics/summary",
            **{"from": _iso(harness.oldest_ms), "to": _iso(harness.now_ms + 1_000)},
        )
    )["summary"]

    assert whole["unique_aircraft"] == windowed["unique_aircraft"] == 4
    assert whole["sightings"] == windowed["sightings"] == 6


async def test_the_in_progress_day_takes_its_busiest_hour_from_the_hourly_metrics(
    harness: Harness, rest: AsyncClient
) -> None:
    """``docs/DATA_MODEL.md`` §6.5's dual source, from the slice-033 side."""
    await seed(harness)
    peak_ms = harness.inside(harness.today, 0.5)
    async with harness.database.writer_session() as session:
        session.add_all(
            [
                ReceiverMetricHourly(
                    hour_start_ms=hour_start_ms(harness.inside(harness.today, 0.1)),
                    aircraft_max=4,
                    sample_count=10,
                ),
                ReceiverMetricHourly(
                    hour_start_ms=hour_start_ms(peak_ms), aircraft_max=41, sample_count=10
                ),
            ]
        )

    summary = (await get(rest, "/api/v1/analytics/summary", preset="today"))["summary"]

    assert summary["busiest_hour_source"] == "receiver_metrics_hourly"
    assert summary["busiest_hour"] == _local_hour(peak_ms, harness.zone)


async def test_a_closed_day_takes_its_busiest_hour_from_the_rollup(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)
    start, end = day_bounds_ms(harness.yesterday, harness.zone)

    summary = (
        await get(rest, "/api/v1/analytics/summary", **{"from": _iso(start), "to": _iso(end)})
    )["summary"]

    assert summary["busiest_hour_source"] == "daily_stats"
    assert summary["busiest_hour"] is not None


# ------------------------------------------------------- new_milestones (036)


async def test_every_summary_response_carries_a_new_milestones_key(
    rest: AsyncClient,
) -> None:
    """§59's null-stable key: present and zero even on an empty install."""
    summary = (await get(rest, "/api/v1/analytics/summary", preset="today"))["summary"]

    assert summary["new_milestones"] == 0


async def test_new_milestones_counts_milestone_and_record_events_today(
    harness: Harness, rest: AsyncClient
) -> None:
    """Milestone and record event types count; routine ones do not."""
    await seed(harness)
    database: Database = harness.database
    today_ms = harness.inside(harness.today, 0.4)
    await ActivityRepository(database).record(
        ActivityBatch(
            events=(
                NewActivityEvent(
                    type=ActivityEventType.FIRST_EVER_AIRCRAFT,
                    ts_ms=today_ms,
                    dedupe_key="first_ever_aircraft:a00002",
                ),
                NewActivityEvent(
                    type=ActivityEventType.NEW_TYPE,
                    ts_ms=today_ms,
                    dedupe_key="new_type:C130",
                ),
                NewActivityEvent(
                    type=ActivityEventType.RANGE_RECORD,
                    ts_ms=today_ms,
                    dedupe_key="range_record:205.000",
                ),
                NewActivityEvent(
                    type=ActivityEventType.RECEIVER_RECORD,
                    ts_ms=today_ms,
                    dedupe_key="receiver_record:max_simultaneous:5",
                ),
                NewActivityEvent(
                    type=ActivityEventType.MILESTONE,
                    ts_ms=today_ms,
                    dedupe_key="unique_aircraft_100",
                ),
                # Routine events, and events outside the window: neither counts.
                NewActivityEvent(
                    type=ActivityEventType.METADATA_UPDATED,
                    ts_ms=today_ms,
                    dedupe_key="metadata_updated:a00001:1",
                ),
                NewActivityEvent(
                    type=ActivityEventType.MILESTONE,
                    ts_ms=harness.inside(harness.yesterday, 0.5),
                    dedupe_key="unique_aircraft_500",
                ),
            )
        )
    )

    summary = (await get(rest, "/api/v1/analytics/summary", preset="today"))["summary"]

    assert summary["new_milestones"] == 5


async def test_new_milestones_over_a_multi_day_window_counts_every_day(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)
    database: Database = harness.database
    await ActivityRepository(database).record(
        ActivityBatch(
            events=(
                NewActivityEvent(
                    type=ActivityEventType.MILESTONE,
                    ts_ms=harness.inside(harness.today, 0.2),
                    dedupe_key="unique_aircraft_100",
                ),
                NewActivityEvent(
                    type=ActivityEventType.MILESTONE,
                    ts_ms=harness.inside(harness.yesterday, 0.2),
                    dedupe_key="unique_aircraft_500",
                ),
            )
        )
    )

    summary = (await get(rest, "/api/v1/analytics/summary", preset="7d"))["summary"]

    assert summary["new_milestones"] == 2


def _local_hour(epoch_ms: int, zone: ZoneInfo) -> int:
    """The receiver-local hour of the UTC hour bucket ``epoch_ms`` falls in."""
    return local_hour(hour_start_ms(epoch_ms), zone)


# ------------------------------------------------------------------- daily


async def test_the_daily_series_has_a_row_for_every_day_including_quiet_ones(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/daily", preset="7d")

    assert len(body["items"]) == 7
    assert body["items"][0]["day"] == body["window"]["first_day"]
    assert body["items"][-1]["day"] == body["window"]["last_day"]
    quiet = [row for row in body["items"] if row["day"] < harness.yesterday]
    assert all(row["sightings"] == 0 for row in quiet)
    assert body["items"][-1]["sightings"] == 3


async def test_the_daily_series_carries_slice_033_receiver_activity(
    harness: Harness, rest: AsyncClient
) -> None:
    """SPEC §58's "receiver activity over time", joined where §6.2 keeps it."""
    await seed(harness)
    async with harness.database.writer_session() as session:
        session.add(
            ReceiverMetricDaily(
                day=harness.today,
                messages_total=1_234_567,
                positions_total=89_012,
                aircraft_max=57,
                sample_count=5_760,
            )
        )

    body = await get(rest, "/api/v1/analytics/daily", preset="today")

    assert body["items"][-1]["receiver_messages"] == 1_234_567
    assert body["items"][-1]["receiver_aircraft_max"] == 57


async def test_a_day_with_no_receiver_metrics_reports_null_not_zero(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/daily", preset="today")

    assert body["items"][-1]["receiver_messages"] is None


# -------------------------------------------------- classification activity


async def test_classification_activity_totals_the_series_it_returns(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/classification-activity", preset="7d")

    assert body["military"] == sum(row["military"] for row in body["series"])
    assert body["military"] == 1
    assert body["government"] == body["law_enforcement"] == 0
    assert body["interesting"] == 1


# ------------------------------------------------------------- top lists


async def test_top_aircraft_ranks_by_sightings_in_the_window(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    items = (await get(rest, "/api/v1/analytics/top-aircraft", preset="7d"))["items"]

    assert [row["icao"] for row in items] == ["a00001", "a00002", "a00003"]
    assert items[0]["sightings"] == 3
    assert items[0]["registration"] == "N00001"
    assert items[0]["operator_group"] == "Alpha Airlines"
    assert items[1]["military"] is True


async def test_top_aircraft_carries_lifetime_first_and_last_seen(
    harness: Harness, rest: AsyncClient
) -> None:
    """SPEC §58's "first-seen/last-seen information"."""
    await seed(harness)

    items = (await get(rest, "/api/v1/analytics/top-aircraft", preset="today"))["items"]

    assert items[0]["first_seen_at"] < items[0]["last_seen_at"]
    assert items[0]["first_seen_at"].endswith("Z")


async def test_the_since_t0_ranking_agrees_with_the_windowed_one(
    harness: Harness, rest: AsyncClient
) -> None:
    """§6.5's whole-history shortcut reads ``aircraft.sighting_count``."""
    await seed(harness)

    whole = (await get(rest, "/api/v1/analytics/top-aircraft", preset="t0"))["items"]
    windowed = (
        await get(
            rest,
            "/api/v1/analytics/top-aircraft",
            **{"from": _iso(harness.oldest_ms), "to": _iso(harness.now_ms + 1_000)},
        )
    )["items"]

    assert [row["icao"] for row in whole] == [row["icao"] for row in windowed]
    assert [row["sightings"] for row in whole] == [row["sightings"] for row in windowed]


async def test_top_aircraft_honours_the_limit(harness: Harness, rest: AsyncClient) -> None:
    await seed(harness)

    items = (await get(rest, "/api/v1/analytics/top-aircraft", preset="7d", limit=1))["items"]

    assert len(items) == 1


async def test_top_types_counts_sightings_and_distinct_airframes(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    items = (await get(rest, "/api/v1/analytics/top-types", preset="7d"))["items"]

    by_key = {row["key"]: row for row in items}
    assert by_key["B738"]["sightings"] == 3
    assert by_key["B738"]["unique_aircraft"] == 1
    assert by_key["B738"]["days_seen"] == 2
    assert "C130" in by_key
    # a00003 has no resolved type, so it appears in no type bucket at all.
    assert sum(row["sightings"] for row in items) == 4


async def test_the_since_t0_type_ranking_comes_from_type_stats(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    items = (await get(rest, "/api/v1/analytics/top-types", preset="t0"))["items"]

    assert [row["key"] for row in items] == ["B738", "C130"]
    assert items[0]["unique_aircraft"] == 1
    assert items[0]["first_seen_at"] is not None


async def test_top_operators_is_keyed_by_the_curated_group(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    items = (await get(rest, "/api/v1/analytics/top-operators", preset="7d"))["items"]

    assert [row["label"] for row in items] == ["Alpha Airlines", "Beta Cargo"]
    assert items[0]["sightings"] == 3
    assert items[0]["unique_aircraft"] == 1


# ------------------------------------------------------------------ rarity


async def test_rarity_counts_never_seen_before_over_the_window(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    today = await get(rest, "/api/v1/analytics/rarity", preset="today")
    week = await get(rest, "/api/v1/analytics/rarity", preset="7d")

    assert today["never_seen_before"] == 1
    assert week["never_seen_before"] == 3


async def test_rarity_lists_airframes_seen_in_the_window_with_low_lifetime_counts(
    harness: Harness, rest: AsyncClient
) -> None:
    """Receiver-relative (SPEC §44): "unusual here", not "unusual anywhere"."""
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/rarity", preset="7d")

    assert [row["icao"] for row in body["rare_aircraft"]] == ["a00002", "a00003"]
    assert body["rare_max_sightings"] == 2
    assert {row["type"] for row in body["rare_types"]} == {"B738", "C130"}


async def test_the_rare_threshold_is_a_documented_parameter(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/rarity", preset="7d", max_sightings=5)

    assert body["rare_max_sightings"] == 5
    assert len(body["rare_aircraft"]) == 3


# ------------------------------------------------------- parameters & zone


async def test_the_window_block_names_the_receiver_zone_and_its_local_days(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    window = (await get(rest, "/api/v1/analytics/daily", preset="today"))["window"]

    assert window["timezone"] == NEW_YORK
    assert window["first_day"] == window["last_day"] == harness.today
    assert window["from"].endswith("Z")


async def test_an_odd_offset_zone_resolves_today_at_its_own_midnight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """+05:30: a client that assumed whole-hour offsets would mislabel the day."""
    async for harness in build_harness(monkeypatch, KOLKATA):
        async with AsyncClient(
            transport=ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client:
            window = (await get(client, "/api/v1/analytics/daily", preset="today"))["window"]

        assert window["timezone"] == KOLKATA
        assert window["first_day"] == local_day(harness.now_ms, harness.zone)
        assert day_bounds_ms(window["first_day"], harness.zone)[0] % MS_PER_HOUR == 30 * 60_000


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({"preset": "last-week"}, 422),
        ({"limit": 0}, 422),
        ({"limit": 10_000}, 422),
        ({"from": "not-a-date"}, 422),
    ],
)
async def test_bad_parameters_are_rejected_rather_than_guessed_at(
    rest: AsyncClient, params: dict[str, Any], status: int
) -> None:
    response = await rest.get("/api/v1/analytics/top-aircraft", params=params)

    assert response.status_code == status


async def test_the_analytics_endpoints_appear_in_the_published_schema(
    rest: AsyncClient,
) -> None:
    """§2.10: the OpenAPI document describes what /api/v1 actually serves."""
    document = await get(rest, "/api/v1/openapi.json")

    assert set(PATHS) <= set(document["paths"])
    for path in PATHS:
        assert "analytics" in document["paths"][path]["get"]["tags"]
