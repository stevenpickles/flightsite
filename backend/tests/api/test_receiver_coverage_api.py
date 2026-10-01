"""``GET /api/v1/receiver/coverage`` — ``docs/API.md`` §3.8, roadmap slice 087.

Through the real ASGI app, against rows seeded straight into
``range_by_bearing_band_daily`` with the repository the metrics service
writes through — the same approach ``test_receiver_stats_api.py`` takes for
the unbanded polar plot. What is under test is the contract: the window
parameter and its validation, three bands of 72 sectors with ``null`` for
the unheard ones, the horizon and share from the configured antenna height
(and their absence without one), and findings only with enough evidence.
"""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from flightsite.api.schemas import ReceiverCoverage
from flightsite.db.clock import utc_now_ms
from flightsite.receiver_metrics.aggregate import local_day
from flightsite.receiver_metrics.coverage import (
    MIN_FINDING_DAYS,
    MIN_FINDING_SAMPLES,
    BandRange,
    band_horizons,
)
from flightsite.receiver_metrics.lifetime import LifetimeDelta
from flightsite.receiver_metrics.model import RangeRecord
from flightsite.receiver_metrics.repository import MetricsRepository

from .conftest import LiveApp

HIGH = 2
ANTENNA_FT = 25.0


def today() -> str:
    """Today in the running app's default (UTC) receiver zone."""
    return local_day(utc_now_ms(), ZoneInfo("UTC"))


def days_ago(count: int) -> str:
    return (date.fromisoformat(today()) - timedelta(days=count)).isoformat()


def set_antenna_height(live_app: LiveApp, height_ft: float | None) -> None:
    settings = live_app.app.state.settings
    location = settings.location.model_copy(update={"antenna_height_ft": height_ft})
    live_app.app.state.settings = settings.model_copy(update={"location": location})


async def seed(
    live_app: LiveApp,
    *,
    day: str,
    band: int,
    buckets: range | tuple[int, ...],
    nm: float,
    samples: int,
) -> None:
    repository = MetricsRepository(live_app.app.state.database)
    cells = [
        BandRange(
            band=band,
            record=RangeRecord(
                bearing_deg=bucket * 5.0 + 1.0,
                max_range_nm=nm,
                at_ms=1_759_000_000_000,
                icao24="abc123",
            ),
            samples=samples,
        )
        for bucket in buckets
    ]
    await repository.record((), {}, LifetimeDelta(), at_ms=1, band_ranges={day: cells})


async def test_an_empty_install_is_three_bands_of_null_sectors(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/receiver/coverage")

    assert response.status_code == 200
    body = response.json()
    ReceiverCoverage.model_validate(body)
    assert body["window"] == "30d"
    assert body["to_day"] == today()
    assert body["from_day"] == days_ago(29)
    assert body["sector_width_deg"] == 5.0
    assert [band["key"] for band in body["bands"]] == ["below_10k", "10k_25k", "above_25k"]
    for band in body["bands"]:
        assert len(band["sectors"]) == 72
        assert band["sectors"][0]["bearing_deg"] == 2.5
        for sector in band["sectors"]:
            # Never a fabricated zero: no data is null range and zero counts.
            assert sector["max_range_nm"] is None
            assert sector["at"] is None and sector["icao"] is None
            assert sector["share_of_horizon"] is None
            assert (sector["samples"], sector["days"]) == (0, 0)
    assert body["findings"] == []
    assert body["criteria"] == {
        "share_below": 0.6,
        "min_samples": MIN_FINDING_SAMPLES,
        "min_days": MIN_FINDING_DAYS,
    }


async def test_an_unset_antenna_height_leaves_the_horizon_unknown_and_finds_nothing(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    set_antenna_height(live_app, None)
    for offset in range(5):
        await seed(
            live_app, day=days_ago(offset), band=HIGH, buckets=range(72), nm=20.0, samples=50
        )

    body = (await rest.get("/api/v1/receiver/coverage")).json()

    assert body["antenna_height_ft"] is None
    assert all(band["horizon_nm"] is None for band in body["bands"])
    high = body["bands"][HIGH]["sectors"]
    assert high[0]["max_range_nm"] == 20.0
    assert high[0]["share_of_horizon"] is None
    assert body["findings"] == []


async def test_the_horizon_and_share_follow_the_antenna_height(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    set_antenna_height(live_app, ANTENNA_FT)
    horizon = band_horizons(ANTENNA_FT)[HIGH]
    assert horizon is not None
    await seed(live_app, day=today(), band=HIGH, buckets=(8,), nm=horizon / 2, samples=7)

    body = (await rest.get("/api/v1/receiver/coverage")).json()

    band = body["bands"][HIGH]
    assert body["antenna_height_ft"] == ANTENNA_FT
    assert band["reference_ft"] == 25_000.0
    assert band["horizon_nm"] == pytest.approx(horizon)
    sector = band["sectors"][8]
    assert sector["share_of_horizon"] == pytest.approx(0.5)
    assert (sector["samples"], sector["days"]) == (7, 1)
    assert sector["icao"] == "abc123"
    assert sector["at"].endswith("Z")
    assert band["sectors"][9]["max_range_nm"] is None


async def test_findings_need_enough_days_in_the_band(live_app: LiveApp, rest: AsyncClient) -> None:
    set_antenna_height(live_app, ANTENNA_FT)
    horizon = band_horizons(ANTENNA_FT)[HIGH]
    assert horizon is not None

    open_sky = tuple(bucket for bucket in range(72) if not 8 <= bucket <= 11)

    async def seed_day(offset: int) -> None:
        day = days_ago(offset)
        await seed(live_app, day=day, band=HIGH, buckets=open_sky, nm=horizon * 0.9, samples=20)
        await seed(live_app, day=day, band=HIGH, buckets=range(8, 12), nm=horizon * 0.5, samples=20)

    # Plenty of samples, but on one day too few: no finding yet.
    for offset in range(MIN_FINDING_DAYS - 1):
        await seed_day(offset)
    assert (await rest.get("/api/v1/receiver/coverage")).json()["findings"] == []

    await seed_day(MIN_FINDING_DAYS - 1)
    [finding] = (await rest.get("/api/v1/receiver/coverage")).json()["findings"]

    assert finding["band"] == "above_25k"
    assert (finding["start_deg"], finding["end_deg"]) == (40.0, 60.0)
    assert finding["compass"] == "NE"
    assert finding["share_of_horizon"] == pytest.approx(0.5)
    assert finding["samples"] == 4 * 20 * MIN_FINDING_DAYS
    assert finding["days"] == MIN_FINDING_DAYS
    assert finding["horizon_nm"] == pytest.approx(horizon)
    assert finding["message"].endswith("of the radio horizon above 25,000 ft — likely obstruction")
    assert finding["message"].startswith("NE 40")


async def test_the_window_bounds_which_days_count(live_app: LiveApp, rest: AsyncClient) -> None:
    await seed(live_app, day=days_ago(10), band=HIGH, buckets=(0,), nm=150.0, samples=3)
    await seed(live_app, day=days_ago(2), band=HIGH, buckets=(0,), nm=90.0, samples=4)

    week = (await rest.get("/api/v1/receiver/coverage", params={"window": "7d"})).json()
    month = (await rest.get("/api/v1/receiver/coverage", params={"window": "30d"})).json()
    ever = (await rest.get("/api/v1/receiver/coverage", params={"window": "all"})).json()

    assert week["from_day"] == days_ago(6)
    assert week["bands"][HIGH]["sectors"][0]["max_range_nm"] == 90.0
    assert month["bands"][HIGH]["sectors"][0]["max_range_nm"] == 150.0
    assert month["bands"][HIGH]["sectors"][0]["samples"] == 7
    assert ever["from_day"] == days_ago(10)
    assert ever["bands"][HIGH]["sectors"][0]["days"] == 2


@pytest.mark.parametrize("window", ["1d", "365d", "ALL", ""])
async def test_an_unknown_window_is_rejected(
    live_app: LiveApp, rest: AsyncClient, window: str
) -> None:
    response = await rest.get("/api/v1/receiver/coverage", params={"window": window})

    assert response.status_code == 422


async def test_the_endpoint_is_in_the_openapi_schema(live_app: LiveApp, rest: AsyncClient) -> None:
    schema = (await rest.get("/api/v1/openapi.json")).json()

    assert "/api/v1/receiver/coverage" in schema["paths"]
    assert "ReceiverCoverage" in schema["components"]["schemas"]
