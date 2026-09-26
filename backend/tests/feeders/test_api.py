"""``GET /api/v1/feeders``, its history, and the internal stats-link redirect.

The routes are mounted on a bare app carrying only a feeder service, so these
tests exercise exactly the contract of ``docs/API.md`` §3.12 — shapes,
statuses, and the absence of every secret — independent of how the
application factory wires the service in.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from flightsite.api.feeders_internal import router as feeders_internal_router
from flightsite.api.v1 import router as v1_router
from flightsite.app import create_app
from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.feeders import FeederService
from flightsite.feeders.model import FeederState, MlatStatus, Observability, ProbeResult
from flightsite.feeders.protocol import FeederEntryLike, FeederProbe, ProbeContext

from .conftest import SECRET_STATS_URL, Entry, ManualClock, Page, Settings

FALLBACK_URL = "https://www.flightaware.com/adsb/stats/user/SENTINEL-FA-USER"


class Probe:
    def __init__(self, name: str, kind: str, result: ProbeResult) -> None:
        self.name = name
        self.kind = kind
        self._result = result
        self.stats_fallback = FALLBACK_URL if kind == "piaware" else None

    async def probe(self, now_ms: int) -> ProbeResult:
        return self._result


def factory(entry: FeederEntryLike, context: ProbeContext) -> FeederProbe:
    result = ProbeResult(
        state=FeederState.UP,
        observability=Observability.HTTP,
        mlat=MlatStatus(peers=7) if entry.kind == "ultrafeeder" else None,
        detail={"host": "feed.example"},
        metrics={"peers": 7},
    )
    return Probe(entry.name, str(entry.kind), result)


SETTINGS = Settings(
    entries=(
        Entry(name="flightaware", label="FlightAware", kind="piaware", web_url="http://fa/"),
        Entry(name="adsbx", label="ADS-B Exchange", kind="ultrafeeder"),
        Entry(name="opensky", label="OpenSky", kind="opensky_logs"),
    ),
    local_pages=(Page(label="tar1090", url="http://fermi.local:8080/"),),
    stats_urls={"adsbx": SecretStr(SECRET_STATS_URL)},
)


@pytest.fixture
async def service(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> AsyncIterator[FeederService]:
    instance = FeederService(
        database=database, settings=SETTINGS, probe_factory=factory, clock=clock, counters=counters
    )
    await instance.poll_once()
    clock.advance(60)
    await instance.poll_once()
    yield instance
    await instance.stop()


@pytest.fixture
async def api(service: FeederService) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(v1_router, prefix="/api/v1")
    app.include_router(feeders_internal_router, prefix="/api/internal")
    app.state.feeders = service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_feeders_payload_matches_the_published_shape(api: AsyncClient) -> None:
    response = await api.get("/api/v1/feeders")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "generated_at",
        "poll_interval_s",
        "docker_socket",
        "receiver",
        "feeders",
        "local_pages",
    }
    assert body["docker_socket"] == "unset"
    assert body["receiver"] is None
    assert body["local_pages"] == [{"label": "tar1090", "url": "http://fermi.local:8080/"}]
    flightaware, adsbx, _opensky = body["feeders"]
    assert set(adsbx) == {
        "name",
        "label",
        "kind",
        "state",
        "observability",
        "since",
        "last_polled_at",
        "last_success_at",
        "last_data_sent_at",
        "message",
        "mlat",
        "adsb_out",
        "detail",
        "web_url",
        "stats_link",
    }
    assert adsbx["state"] == "up"
    assert adsbx["mlat"]["peers"] == 7
    assert adsbx["adsb_out"] is None  # nullable, never absent
    assert flightaware["web_url"] == "http://fa/"
    assert [f["stats_link"] for f in body["feeders"]] == [True, True, False]


async def test_no_stats_url_ever_appears_in_api_v1(api: AsyncClient) -> None:
    feeders = (await api.get("/api/v1/feeders")).text
    histories = [
        (await api.get(f"/api/v1/feeders/{name}/history", params={"window": window})).text
        for name in ("flightaware", "adsbx", "opensky")
        for window in ("24h", "7d", "30d")
    ]

    for body in (feeders, *histories):
        assert SECRET_STATS_URL not in body
        assert "SENTINEL" not in body


async def test_history_windows_and_errors(api: AsyncClient) -> None:
    ok = await api.get("/api/v1/feeders/adsbx/history", params={"window": "7d"})
    default = await api.get("/api/v1/feeders/adsbx/history")
    missing = await api.get("/api/v1/feeders/nope/history")
    bad_window = await api.get("/api/v1/feeders/adsbx/history", params={"window": "1y"})

    assert ok.status_code == 200
    body = ok.json()
    assert set(body) == {"episodes", "samples", "availability_pct"}
    assert body["episodes"][0]["state"] == "up"
    assert body["episodes"][0]["ended_at"] is None
    assert body["samples"][0]["metrics"] == {"peers": 7}
    assert body["availability_pct"] == 100.0
    assert default.status_code == 200
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert bad_window.status_code == 422


async def test_stats_link_redirects_to_the_secret_or_the_fallback(api: AsyncClient) -> None:
    configured = await api.get("/api/internal/feeders/adsbx/stats-link")
    fallback = await api.get("/api/internal/feeders/flightaware/stats-link")
    none = await api.get("/api/internal/feeders/opensky/stats-link")
    unknown = await api.get("/api/internal/feeders/nope/stats-link")

    assert configured.status_code == 302
    assert configured.headers["location"] == SECRET_STATS_URL
    assert configured.headers["cache-control"] == "no-store"
    assert configured.headers["referrer-policy"] == "no-referrer"
    assert SECRET_STATS_URL not in configured.text
    assert fallback.status_code == 302
    assert fallback.headers["location"] == FALLBACK_URL
    assert none.status_code == 404
    assert unknown.status_code == 404


async def test_an_app_without_a_feeder_service_answers_empty_not_500() -> None:
    app = FastAPI()
    app.include_router(v1_router, prefix="/api/v1")
    app.include_router(feeders_internal_router, prefix="/api/internal")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        feeders = await client.get("/api/v1/feeders")
        history = await client.get("/api/v1/feeders/x/history")
        link = await client.get("/api/internal/feeders/x/stats-link")

    assert feeders.status_code == 200
    assert feeders.json()["feeders"] == []
    assert feeders.json()["docker_socket"] == "unset"
    assert history.status_code == 404
    assert link.status_code == 404


def test_the_feeder_endpoints_are_in_the_published_schema() -> None:
    with TestClient(create_app()) as client:
        document = client.get("/api/v1/openapi.json").json()

    assert "/api/v1/feeders" in document["paths"]
    assert "/api/v1/feeders/{name}/history" in document["paths"]
    assert "FeedersResponse" in document["components"]["schemas"]
    assert not any("stats-link" in path for path in document["paths"])
