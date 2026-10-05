"""What a window held: its counts, its distinct aircraft, its distinct types.

Slice 098's three analytics endpoints, and the ``preset`` the sightings log
gained with them. They share :func:`tests.analytics.test_api.seed`, whose
figures can be read off its source:

========  ===========  ==========  =========================================
airframe  type         first seen  sightings
========  ===========  ==========  =========================================
a00001    B738         yesterday   yesterday, today, today  (3 lifetime)
a00002    C130 (mil)   today       today
a00003    (no type)    yesterday   yesterday
a00004    (no type)    long ago    long ago
========  ===========  ==========  =========================================
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from flightsite.db import DailyStats, MetaRepository

from ..api.aircraft_history_fixtures import SeedAircraft
from ..api.sighting_fixtures import SeedSighting, seed_sightings
from .test_api import Harness, build_harness, get, seed


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


# ------------------------------------------------------------------ counts


async def test_counts_today_are_live_and_count_types_and_new_aircraft(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/counts", preset="today")

    assert body["window"]["preset"] == "today"
    assert body["sightings"] == 3
    assert body["unique_aircraft"] == 2
    assert body["unique_types"] == 2  # B738 and C130
    assert body["new_aircraft"] == 1  # only a00002 was first heard today


async def test_counts_over_a_week_and_over_the_whole_history(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    week = await get(rest, "/api/v1/analytics/counts", preset="7d")
    ever = await get(rest, "/api/v1/analytics/counts", preset="t0")

    assert (week["sightings"], week["unique_aircraft"], week["new_aircraft"]) == (5, 3, 3)
    assert (ever["sightings"], ever["unique_aircraft"], ever["new_aircraft"]) == (6, 4, 4)
    # The untyped airframes are aircraft but belong to no type, in any window.
    assert week["unique_types"] == ever["unique_types"] == 2


async def test_counts_on_an_empty_install_are_zeros(rest: AsyncClient) -> None:
    body = await get(rest, "/api/v1/analytics/counts", preset="today")

    assert (
        body["sightings"],
        body["unique_aircraft"],
        body["unique_types"],
        body["new_aircraft"],
    ) == (0, 0, 0, 0)


async def test_counts_do_not_wait_for_the_rollup(harness: Harness, rest: AsyncClient) -> None:
    """``summary`` reads ``daily_stats``; this must not, or the heading would
    trail the log it sits above by a rollup pass."""
    await seed(harness)
    async with harness.database.writer_session() as session:
        await session.execute(delete(DailyStats))

    body = await get(rest, "/api/v1/analytics/counts", preset="today")

    assert body["sightings"] == 3
    assert body["unique_aircraft"] == 2


# ---------------------------------------------------------------- aircraft


async def test_aircraft_lists_each_distinct_airframe_of_the_window_once(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/aircraft", preset="today")

    assert body["total"] == 2
    assert [(row["icao"], row["sightings"]) for row in body["items"]] == [
        ("a00001", 2),  # twice today, though three times ever
        ("a00002", 1),
    ]
    first = body["items"][0]
    assert first["registration"] == "N00001"
    assert first["model"] == "Boeing 737-800"
    assert first["operator"] == "Alpha Airlines"
    assert first["owner"] == "Alpha Leasing Trust"


async def test_aircraft_marks_the_airframes_first_heard_in_the_window(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    today = await get(rest, "/api/v1/analytics/aircraft", preset="today")
    week = await get(rest, "/api/v1/analytics/aircraft", preset="7d")

    assert {row["icao"]: row["new"] for row in today["items"]} == {
        "a00001": False,  # first heard yesterday
        "a00002": True,
    }
    assert all(row["new"] for row in week["items"])  # all three first heard this week


async def test_aircraft_over_the_whole_history_is_every_airframe_ever_heard(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/aircraft", preset="t0")

    assert body["total"] == 4
    assert [(row["icao"], row["sightings"]) for row in body["items"]] == [
        ("a00001", 3),
        ("a00002", 1),
        ("a00003", 1),
        ("a00004", 1),
    ]
    # "New" would be true of every row here, so it is true of none.
    assert not any(row["new"] for row in body["items"])


async def test_aircraft_pages_through_the_ranking_with_an_exact_total(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    page = await get(rest, "/api/v1/analytics/aircraft", preset="t0", limit=2, offset=2)

    assert (page["total"], page["limit"], page["offset"]) == (4, 2, 2)
    assert [row["icao"] for row in page["items"]] == ["a00003", "a00004"]
    beyond = await get(rest, "/api/v1/analytics/aircraft", preset="t0", limit=2, offset=10)
    assert beyond["items"] == []
    assert beyond["total"] == 4


async def test_aircraft_narrows_to_one_type_in_either_form(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    today = await get(rest, "/api/v1/analytics/aircraft", preset="today", type="c130")
    ever = await get(rest, "/api/v1/analytics/aircraft", preset="t0", type="B738")
    none = await get(rest, "/api/v1/analytics/aircraft", preset="t0", type="ZZZZ")

    assert ([row["icao"] for row in today["items"]], today["total"]) == (["a00002"], 1)
    assert ([row["icao"] for row in ever["items"]], ever["total"]) == (["a00001"], 1)
    assert (none["items"], none["total"]) == ([], 0)


async def test_aircraft_rejects_a_type_that_is_not_a_designator(rest: AsyncClient) -> None:
    response = await rest.get("/api/v1/analytics/aircraft", params={"type": "not a type"})

    assert response.status_code == 422


# ------------------------------------------------------------------- types


async def test_types_lists_each_distinct_type_of_the_window(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/types", preset="today")

    assert body["total"] == 2
    rows = {row["type"]: row for row in body["items"]}
    assert [row["type"] for row in body["items"]] == ["B738", "C130"]  # busiest first
    assert (rows["B738"]["sightings"], rows["B738"]["unique_aircraft"]) == (2, 1)
    assert (rows["C130"]["sightings"], rows["C130"]["unique_aircraft"]) == (1, 1)
    assert rows["B738"]["description"] == "Boeing 737-800"
    assert rows["C130"]["description"] == "Lockheed C-130"


async def test_types_marks_a_type_the_receiver_had_never_heard_before_the_window(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    today = await get(rest, "/api/v1/analytics/types", preset="today")
    week = await get(rest, "/api/v1/analytics/types", preset="7d")

    assert {row["type"]: row["new"] for row in today["items"]} == {
        "B738": False,  # a B738 was heard yesterday
        "C130": True,
    }
    assert {row["type"]: row["new"] for row in week["items"]} == {"B738": True, "C130": True}
    # First seen is the type's first-ever observation, not its first in the window.
    b738_today = next(row for row in today["items"] if row["type"] == "B738")
    b738_week = next(row for row in week["items"] if row["type"] == "B738")
    assert b738_today["first_seen_at"] == b738_week["first_seen_at"]
    assert b738_today["first_seen_at"] < today["window"]["from"]


async def test_types_over_the_whole_history_is_every_type_ever_heard(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    body = await get(rest, "/api/v1/analytics/types", preset="t0")

    assert body["total"] == 2
    assert [(row["type"], row["sightings"], row["unique_aircraft"]) for row in body["items"]] == [
        ("B738", 3, 1),
        ("C130", 1, 1),
    ]
    assert not any(row["new"] for row in body["items"])


async def test_types_pages_with_an_exact_total(harness: Harness, rest: AsyncClient) -> None:
    await seed(harness)

    page = await get(rest, "/api/v1/analytics/types", preset="t0", limit=1, offset=1)

    assert (page["total"], page["limit"], page["offset"]) == (2, 1, 1)
    assert [row["type"] for row in page["items"]] == ["C130"]


async def test_the_three_lists_agree_with_the_counts(harness: Harness, rest: AsyncClient) -> None:
    """One window, four figures, three lists — and they must tell one story."""
    await seed(harness)

    for preset in ("today", "7d", "30d", "ytd", "t0"):
        counts = await get(rest, "/api/v1/analytics/counts", preset=preset)
        aircraft = await get(rest, "/api/v1/analytics/aircraft", preset=preset)
        types = await get(rest, "/api/v1/analytics/types", preset=preset)

        assert aircraft["total"] == counts["unique_aircraft"], preset
        assert types["total"] == counts["unique_types"], preset
        assert sum(row["sightings"] for row in aircraft["items"]) == counts["sightings"], preset


# ------------------------------------------------------ a young install


async def test_on_a_day_old_install_everything_heard_today_is_new_today(
    harness: Harness, rest: AsyncClient
) -> None:
    """When T0 is today, the "today" window reaches back over the whole
    history. That must not silence the flag the way the ``t0`` preset does:
    the counts say every aircraft is new, and the rows must agree with them.
    """
    first = harness.inside(harness.today, 0.5)
    await seed_sightings(
        harness.database,
        [
            SeedAircraft(
                icao24="a00001",
                first_seen_ms=first,
                last_seen_ms=first,
                type_code="B738",
                model="Boeing 737-800",
            )
        ],
        [SeedSighting(icao24="a00001", started_ms=first)],
    )
    await MetaRepository(harness.database).set_t0_once(first)

    counts = await get(rest, "/api/v1/analytics/counts", preset="today")
    aircraft = await get(rest, "/api/v1/analytics/aircraft", preset="today")
    types = await get(rest, "/api/v1/analytics/types", preset="today")
    ever_aircraft = await get(rest, "/api/v1/analytics/aircraft", preset="t0")
    ever_types = await get(rest, "/api/v1/analytics/types", preset="t0")

    assert counts["new_aircraft"] == counts["unique_aircraft"] == 1
    assert [row["new"] for row in aircraft["items"]] == [True]
    assert [row["new"] for row in types["items"]] == [True]
    # The same rows, asked for as "everything": the flag would mark them all.
    assert [row["new"] for row in ever_aircraft["items"]] == [False]
    assert [row["new"] for row in ever_types["items"]] == [False]


# ---------------------------------------------------------- sightings log


async def test_the_sightings_log_takes_the_same_presets(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    today = await get(rest, "/api/v1/sightings", preset="today")
    week = await get(rest, "/api/v1/sightings", preset="7d")
    ever = await get(rest, "/api/v1/sightings", preset="t0")
    unbounded = await get(rest, "/api/v1/sightings")

    assert len(today["items"]) == 3
    assert len(week["items"]) == 5
    assert len(ever["items"]) == len(unbounded["items"]) == 6
    assert {row["icao"] for row in today["items"]} == {"a00001", "a00002"}


async def test_explicit_bounds_win_over_a_preset_on_the_sightings_log(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)
    week = await get(rest, "/api/v1/analytics/counts", preset="7d")

    body = await get(
        rest,
        "/api/v1/sightings",
        preset="today",
        **{"from": week["window"]["from"], "to": week["window"]["to"]},
    )

    assert len(body["items"]) == 5


async def test_a_sighting_row_says_when_it_is_the_airframes_first(
    harness: Harness, rest: AsyncClient
) -> None:
    await seed(harness)

    week = await get(rest, "/api/v1/sightings", preset="7d", sort="started_at", order="asc")

    firsts = [(row["icao"], row["first_sighting"]) for row in week["items"]]
    # a00001: first heard yesterday, then twice more today.
    assert [flag for icao, flag in firsts if icao == "a00001"] == [True, False, False]
    assert [flag for icao, flag in firsts if icao == "a00002"] == [True]
    assert [flag for icao, flag in firsts if icao == "a00003"] == [True]
