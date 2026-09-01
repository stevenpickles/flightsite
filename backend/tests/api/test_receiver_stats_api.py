"""``GET /api/v1/receiver/{scorecard,metrics,range-by-bearing,
signal-distribution,lifetime}`` — ``docs/API.md`` §3.8, SPEC §§61-63.

Every endpoint is exercised through the real ASGI app (``tests.api.conftest``),
against data seeded directly into the tables the persistence worker and the
metrics service would eventually produce — the same approach
``test_sightings_api.py`` and ``tests/receiver_metrics/test_repository.py``
take, and for the same reason: this suite is about what the endpoint *reads
and assembles*, not about the ingestion pipeline that would otherwise take
seconds per row to drive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from httpx import AsyncClient

from flightsite.db import MetaRepository
from flightsite.db.clock import utc_now_ms
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.receiver_metrics.aggregate import local_day, local_day_start_ms
from flightsite.receiver_metrics.lifetime import LifetimeDelta
from flightsite.receiver_metrics.model import DecoderStats, MetricSample, MetricSummary, RangeRecord
from flightsite.receiver_metrics.repository import MetricsRepository, group_by_day

from .aircraft_history_fixtures import SeedAircraft
from .conftest import LiveApp
from .sighting_fixtures import SeedSighting, seed_sightings

BASE_MS = 1_756_000_000_000

#: The default settings' timezone (``docs/API.md`` §3.2's default), used to
#: bucket "today" the same way the app's own settings do.
UTC_ZONE = ZoneInfo("UTC")


def today_day() -> str:
    """The receiver-local day the running app's default (UTC) settings would
    compute "today" as, right now — so a test needs no fixed clock injection
    to seed a row the scorecard's ``local_day(utc_now_ms(), ...)`` call
    will actually land on."""
    return local_day(utc_now_ms(), UTC_ZONE)


@dataclass(slots=True)
class FakeMetricsService:
    """A duck-typed stand-in for ``ReceiverMetricsService`` — only the two
    attributes the scorecard reads (``docs/API.md`` §3.8's decoder uptime and
    health cue), so a test can set them directly instead of driving a real
    stats poll through the service's background tasks."""

    latest_stats: object | None = None
    stats_supported: bool | None = None


def decoder_stats(uptime_s: float) -> object:
    return DecoderStats(uptime_s=uptime_s)


# ------------------------------------------------------------------ scorecard


async def test_scorecard_of_an_empty_install_is_the_never_data_state(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/receiver/scorecard")

    assert response.status_code == 200
    body = response.json()
    assert body["current_visible"] == 0
    assert body["current_positioned"] == 0
    assert body["messages_per_sec"] is None
    assert body["positions_per_sec"] is None
    assert body["max_range_today_nm"] is None
    assert body["max_range_ever_nm"] is None
    assert body["unique_aircraft_today"] == 0
    assert body["unique_aircraft_since_t0"] == 0
    assert body["decoder_uptime_s"] is None
    assert body["flightsite_uptime_s"] >= 0
    assert body["health"] == "unknown"


async def test_scorecard_current_counts_come_from_the_live_store(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(
        AircraftStateUpdate(
            icao="ae1463",
            timestamp=datetime.now(UTC),
            position=Position(latitude=47.6, longitude=-122.3),
            position_source="adsb",
        ),
        AircraftStateUpdate(
            icao="bbb222", timestamp=datetime.now(UTC), position=None, position_source="none"
        ),
    )

    body = (await rest.get("/api/v1/receiver/scorecard")).json()

    assert body["current_visible"] == 2
    assert body["current_positioned"] == 1


async def test_scorecard_reports_the_latest_samples_own_rate(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    repository = MetricsRepository(live_app.app.state.database)
    await repository.record(
        (
            MetricSample(ts_ms=BASE_MS, messages_per_sec=100.0, positions_per_sec=10.0),
            MetricSample(ts_ms=BASE_MS + 15_000, messages_per_sec=250.0, positions_per_sec=25.0),
        ),
        {},
        LifetimeDelta(),
        at_ms=BASE_MS,
    )

    body = (await rest.get("/api/v1/receiver/scorecard")).json()

    assert body["messages_per_sec"] == 250.0
    assert body["positions_per_sec"] == 25.0


async def test_scorecard_max_range_today_is_the_max_across_sectors(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    repository = MetricsRepository(live_app.app.state.database)
    day = today_day()
    await repository.record(
        (),
        group_by_day(
            [
                (day, RangeRecord(bearing_deg=42.5, max_range_nm=87.3, at_ms=BASE_MS)),
                (day, RangeRecord(bearing_deg=222.5, max_range_nm=140.9, at_ms=BASE_MS)),
            ]
        ),
        LifetimeDelta(),
        at_ms=BASE_MS,
    )

    body = (await rest.get("/api/v1/receiver/scorecard")).json()

    assert body["max_range_today_nm"] == 140.9


async def test_scorecard_max_range_ever_reads_the_lifetime_record(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    repository = MetricsRepository(live_app.app.state.database)
    await repository.record(
        (),
        {},
        LifetimeDelta(max_range=RangeRecord(bearing_deg=87.5, max_range_nm=241.6, at_ms=BASE_MS)),
        at_ms=BASE_MS,
    )

    body = (await rest.get("/api/v1/receiver/scorecard")).json()

    assert body["max_range_ever_nm"] == 241.6


async def test_scorecard_unique_aircraft_today_and_since_t0(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    day_start = local_day_start_ms(today_day(), UTC_ZONE)
    aircraft = [
        SeedAircraft(icao24="ae1463", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
        SeedAircraft(icao24="bbb222", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
    ]
    await seed_sightings(
        live_app.app.state.database,
        aircraft,
        [
            SeedSighting(icao24="ae1463", started_ms=day_start + 1_000, ended_ms=day_start + 2_000),
            SeedSighting(
                icao24="bbb222", started_ms=day_start - 172_800_000, ended_ms=day_start - 86_400_000
            ),
        ],
    )

    body = (await rest.get("/api/v1/receiver/scorecard")).json()

    assert body["unique_aircraft_today"] == 1
    assert body["unique_aircraft_since_t0"] == 2


async def test_scorecard_health_states(live_app: LiveApp, rest: AsyncClient) -> None:
    live_app.app.state.receiver_metrics = FakeMetricsService(
        latest_stats=decoder_stats(12_345.0), stats_supported=True
    )
    body = (await rest.get("/api/v1/receiver/scorecard")).json()
    assert body["health"] == "ok"
    assert body["decoder_uptime_s"] == 12_345.0

    live_app.app.state.receiver_metrics = FakeMetricsService(
        latest_stats=None, stats_supported=False
    )
    body = (await rest.get("/api/v1/receiver/scorecard")).json()
    assert body["health"] == "no_stats"
    assert body["decoder_uptime_s"] is None

    live_app.app.state.demo_enabled = True
    body = (await rest.get("/api/v1/receiver/scorecard")).json()
    assert body["health"] == "demo"


# ------------------------------------------------------------------- metrics


async def test_series_high_resolution_reads_raw_samples(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    repository = MetricsRepository(live_app.app.state.database)
    await repository.record(
        (
            MetricSample(ts_ms=BASE_MS, messages_per_sec=100.0),
            MetricSample(ts_ms=BASE_MS + 15_000, messages_per_sec=200.0),
        ),
        {},
        LifetimeDelta(),
        at_ms=BASE_MS,
    )

    response = await rest.get(
        "/api/v1/receiver/metrics",
        params={
            "metric": "messages_per_sec",
            "resolution": "high",
            "from": datetime.fromtimestamp(BASE_MS / 1000, tz=UTC).isoformat(),
            "to": datetime.fromtimestamp((BASE_MS + 20_000) / 1000, tz=UTC).isoformat(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolution"] == "high"
    assert [point["value"] for point in body["points"]] == [100.0, 200.0]


async def test_series_hourly_resolution_reads_the_avg_summary_column(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    repository = MetricsRepository(live_app.app.state.database)
    await repository.write_summaries(
        {BASE_MS: MetricSummary(sample_count=10, msgs_per_sec_avg=333.3)}, {}, at_ms=1
    )

    body = (
        await rest.get(
            "/api/v1/receiver/metrics",
            params={
                "metric": "messages_per_sec",
                "resolution": "hourly",
                "from": datetime.fromtimestamp(BASE_MS / 1000, tz=UTC).isoformat(),
                "to": datetime.fromtimestamp(BASE_MS / 1000, tz=UTC).isoformat(),
            },
        )
    ).json()

    assert body["points"] == [
        {
            "t": datetime.fromtimestamp(BASE_MS / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "value": 333.3,
        }
    ]


async def test_series_daily_resolution_reads_the_daily_summary(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    repository = MetricsRepository(live_app.app.state.database)
    day = today_day()
    await repository.write_summaries(
        {}, {day: MetricSummary(sample_count=10, messages_total=42_000)}, at_ms=1
    )

    body = (
        await rest.get(
            "/api/v1/receiver/metrics",
            params={"metric": "messages_total", "resolution": "daily"},
        )
    ).json()

    values = [point["value"] for point in body["points"] if point["value"] is not None]
    assert 42_000.0 in values


async def test_series_unique_aircraft_ignores_a_non_daily_resolution_with_400(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get(
        "/api/v1/receiver/metrics",
        params={"metric": "unique_aircraft", "resolution": "hourly"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_resolution"


async def test_series_unique_aircraft_at_daily_resolution_succeeds(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    day_start = local_day_start_ms(today_day(), UTC_ZONE)
    aircraft = [
        SeedAircraft(icao24="ae1463", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
        SeedAircraft(icao24="bbb222", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS),
    ]
    await seed_sightings(
        live_app.app.state.database,
        aircraft,
        [
            SeedSighting(icao24="ae1463", started_ms=day_start + 1_000, ended_ms=day_start + 2_000),
            SeedSighting(icao24="bbb222", started_ms=day_start + 3_000, ended_ms=day_start + 4_000),
        ],
    )

    body = (
        await rest.get(
            "/api/v1/receiver/metrics",
            params={"metric": "unique_aircraft", "resolution": "daily"},
        )
    ).json()

    assert body["resolution"] == "daily"
    values = [point["value"] for point in body["points"] if point["value"]]
    assert 2.0 in values


async def test_series_summary_only_metric_at_high_resolution_is_400(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get(
        "/api/v1/receiver/metrics",
        params={"metric": "messages_total", "resolution": "high"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_resolution"


async def test_series_from_after_to_is_400(live_app: LiveApp, rest: AsyncClient) -> None:
    response = await rest.get(
        "/api/v1/receiver/metrics",
        params={
            "metric": "messages_per_sec",
            "resolution": "hourly",
            "from": "2026-08-31T00:00:00Z",
            "to": "2026-08-01T00:00:00Z",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_range"


async def test_series_of_an_empty_install_is_an_empty_points_list(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    body = (
        await rest.get(
            "/api/v1/receiver/metrics",
            params={"metric": "max_range_nm", "resolution": "daily"},
        )
    ).json()

    assert body["points"] == []


# ------------------------------------------------------------ range-by-bearing


async def test_range_by_bearing_always_returns_72_sectors_in_bucket_order(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    body = (await rest.get("/api/v1/receiver/range-by-bearing")).json()

    assert body["sector_width_deg"] == 5.0
    assert len(body["today"]) == 72
    assert len(body["ever"]) == 72
    # Bucket 0 = North (bearing 0..5), its midpoint is 2.5 degrees. Bucket 1's
    # midpoint (7.5) is greater, confirming ascending, clockwise order.
    assert body["ever"][0]["bearing_deg"] == 2.5
    assert body["ever"][1]["bearing_deg"] == 7.5
    assert body["ever"][71]["bearing_deg"] == 357.5
    assert [sector["bearing_deg"] for sector in body["ever"]] == sorted(
        sector["bearing_deg"] for sector in body["ever"]
    )


async def test_range_by_bearing_unset_sectors_are_null_not_zero(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    body = (await rest.get("/api/v1/receiver/range-by-bearing")).json()

    assert all(sector["max_range_nm"] is None for sector in body["ever"])
    assert all(sector["at"] is None and sector["icao"] is None for sector in body["ever"])


async def test_range_by_bearing_ever_is_the_max_across_every_stored_day(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    repository = MetricsRepository(live_app.app.state.database)
    await repository.record(
        (),
        group_by_day(
            [
                ("2026-01-01", RangeRecord(bearing_deg=42.5, max_range_nm=90.0, at_ms=1)),
                ("2026-01-02", RangeRecord(bearing_deg=42.5, max_range_nm=180.0, at_ms=2)),
            ]
        ),
        LifetimeDelta(),
        at_ms=1,
    )

    body = (await rest.get("/api/v1/receiver/range-by-bearing")).json()

    bucket_8 = next(sector for sector in body["ever"] if sector["bearing_deg"] == 42.5)
    assert bucket_8["max_range_nm"] == 180.0


async def test_range_by_bearing_today_reflects_only_todays_rows(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    repository = MetricsRepository(live_app.app.state.database)
    await repository.record(
        (),
        group_by_day(
            [
                ("2020-01-01", RangeRecord(bearing_deg=42.5, max_range_nm=90.0, at_ms=1)),
                (today_day(), RangeRecord(bearing_deg=42.5, max_range_nm=55.0, at_ms=2)),
            ]
        ),
        LifetimeDelta(),
        at_ms=1,
    )

    body = (await rest.get("/api/v1/receiver/range-by-bearing")).json()

    bucket_8 = next(sector for sector in body["today"] if sector["bearing_deg"] == 42.5)
    assert bucket_8["max_range_nm"] == 55.0


# -------------------------------------------------------- signal-distribution


async def test_signal_distribution_uses_per_sighting_rssi_not_raw_samples(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    # A raw sample with a wildly different RSSI — must not influence the result.
    repository = MetricsRepository(live_app.app.state.database)
    await repository.record(
        (MetricSample(ts_ms=BASE_MS, rssi_avg_db=-99.0),), {}, LifetimeDelta(), at_ms=BASE_MS
    )
    await seed_sightings(
        live_app.app.state.database,
        [SeedAircraft(icao24="ae1463", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS)],
        [
            SeedSighting(icao24="ae1463", started_ms=BASE_MS, rssi_avg_db=-14.0),
            SeedSighting(icao24="ae1463", started_ms=BASE_MS + 1_000, rssi_avg_db=-16.0),
        ],
    )

    body = (await rest.get("/api/v1/receiver/signal-distribution")).json()

    assert body["sample_count"] == 2
    assert body["min_db"] == -16.0
    assert body["max_db"] == -14.0


async def test_signal_distribution_window_filters_by_sighting_start(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    await seed_sightings(
        live_app.app.state.database,
        [SeedAircraft(icao24="ae1463", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS)],
        [
            SeedSighting(icao24="ae1463", started_ms=BASE_MS, rssi_avg_db=-14.0),
            SeedSighting(icao24="ae1463", started_ms=BASE_MS + 86_400_000, rssi_avg_db=-30.0),
        ],
    )

    from_iso = datetime.fromtimestamp(BASE_MS / 1000, tz=UTC).isoformat()
    to_iso = datetime.fromtimestamp(BASE_MS / 1000, tz=UTC).isoformat()
    body = (
        await rest.get(
            "/api/v1/receiver/signal-distribution", params={"from": from_iso, "to": to_iso}
        )
    ).json()

    assert body["sample_count"] == 1
    assert body["min_db"] == -14.0


async def test_signal_distribution_bucket_width_param(live_app: LiveApp, rest: AsyncClient) -> None:
    await seed_sightings(
        live_app.app.state.database,
        [SeedAircraft(icao24="ae1463", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS)],
        [SeedSighting(icao24="ae1463", started_ms=BASE_MS, rssi_avg_db=-14.0)],
    )

    body = (
        await rest.get("/api/v1/receiver/signal-distribution", params={"bucket_width_db": 5})
    ).json()

    assert body["bucket_width_db"] == 5.0


async def test_signal_distribution_of_an_empty_install_is_the_never_data_state(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    body = (await rest.get("/api/v1/receiver/signal-distribution")).json()

    assert body == {
        "from_ts": None,
        "to_ts": None,
        "bucket_width_db": 3.0,
        "buckets": [],
        "sample_count": 0,
        "min_db": None,
        "max_db": None,
        "avg_db": None,
    }


# -------------------------------------------------------------------- lifetime


async def test_lifetime_of_an_empty_install_is_the_never_data_state(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    body = (await rest.get("/api/v1/receiver/lifetime")).json()

    assert body == {
        "since": None,
        "unique_aircraft": 0,
        "total_sightings": 0,
        "total_positions": None,
        "total_messages": None,
        "max_range": None,
        "peak_message_rate_per_sec": None,
        "peak_position_rate_per_sec": None,
        "max_simultaneous_aircraft": None,
        "busiest_day": None,
        "most_frequent_aircraft": None,
        "common_type": None,
        "common_model": None,
        "common_operator": None,
    }


async def test_lifetime_assembles_every_documented_field(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    database = live_app.app.state.database
    await MetaRepository(database).set_t0_once(BASE_MS)

    repository = MetricsRepository(database)
    await repository.record(
        (),
        {},
        LifetimeDelta(
            messages=1_000,
            positions=200,
            max_range=RangeRecord(
                bearing_deg=87.5, max_range_nm=241.6, at_ms=BASE_MS, icao24="ae1463"
            ),
            max_simultaneous=61,
            peak_msg_rate=512.4,
            peak_pos_rate=44.1,
        ),
        at_ms=BASE_MS,
    )
    await repository.write_summaries(
        {}, {"2026-07-04": MetricSummary(sample_count=1, messages_total=5_100_000)}, at_ms=BASE_MS
    )

    aircraft = [
        SeedAircraft(
            icao24="ae1463",
            first_seen_ms=BASE_MS,
            last_seen_ms=BASE_MS,
            sighting_count=812,
            registration="N123AB",
            type_code="B738",
            model="Boeing 737-800",
            operator_name="Delta Air Lines",
        ),
        SeedAircraft(
            icao24="bbb222", first_seen_ms=BASE_MS, last_seen_ms=BASE_MS, sighting_count=1
        ),
    ]
    await seed_sightings(
        database,
        aircraft,
        [
            SeedSighting(icao24="ae1463", started_ms=BASE_MS, ended_ms=BASE_MS + 1_000),
            SeedSighting(icao24="bbb222", started_ms=BASE_MS, ended_ms=BASE_MS + 1_000),
        ],
    )

    body = (await rest.get("/api/v1/receiver/lifetime")).json()

    assert body["since"] is not None
    assert body["unique_aircraft"] == 2
    assert body["total_sightings"] == 2
    assert body["total_messages"] == 1_000
    assert body["total_positions"] == 200
    assert body["max_range"] == {
        "nm": 241.6,
        "at": body["max_range"]["at"],
        "bearing_deg": 87.5,
        "icao": "ae1463",
    }
    assert body["peak_message_rate_per_sec"] == 512.4
    assert body["peak_position_rate_per_sec"] == 44.1
    assert body["max_simultaneous_aircraft"] == 61
    assert body["busiest_day"] == {"day": "2026-07-04", "message_count": 5_100_000}
    assert body["most_frequent_aircraft"] == {
        "icao": "ae1463",
        "registration": "N123AB",
        "sighting_count": 812,
    }
    assert body["common_type"] == {"value": "B738", "aircraft_count": 1}
    assert body["common_model"] == {"value": "Boeing 737-800", "aircraft_count": 1}
    assert body["common_operator"] == {"value": "Delta Air Lines", "aircraft_count": 1}
