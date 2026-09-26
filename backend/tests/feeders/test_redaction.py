"""No identity or secret leaves the feeders package — proven with sentinels.

The fixtures plant ``SENTINEL`` values in exactly the fields that must never
travel: FR24's sharing key, alias, legacy id and LAN addresses; FlightAware's
site URL; the receiver's coordinates. The configured stats URL is a sentinel
too. Every probe then runs for real, through the production
:func:`~flightsite.feeders.service.build_probe`, against mock transports, and
the report, the history and everything logged are searched for any of them.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.feeders import FeederService
from flightsite.feeders.docker import DockerClient
from flightsite.feeders.fr24 import REDACTED_FIELDS
from flightsite.feeders.ultrafeeder import mlat_stats_path

from .conftest import (
    SECRET_STATS_URL,
    SENTINELS,
    Entry,
    ManualClock,
    Settings,
    framed_log,
    load_json,
    load_lines,
    routes,
)

ENTRIES = (
    Entry(name="receiver", label="Receiver", kind="readsb", url="http://host.test:8080/"),
    Entry(
        name="flightaware",
        label="FlightAware",
        kind="piaware",
        url="http://host.test:8081/status.json",
    ),
    Entry(name="fr24", label="FR24", kind="fr24", url="http://host.test:8754/monitor.json"),
    Entry(
        name="adsbx",
        label="ADS-B Exchange",
        kind="ultrafeeder",
        url="http://host.test:8080/",
        host="feed.adsbexchange.com",
        mlat_port=31090,
        beast_port=30004,
        container="ultrafeeder",
    ),
    Entry(name="opensky", label="OpenSky", kind="opensky_logs", container="opensky"),
    Entry(name="backstop", label="Backstop", kind="docker_health", container="opensky"),
    Entry(name="links", label="Links", kind="link_only", web_url="http://host.test:9000/"),
)


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=routes(
            {
                "/data/status.json": load_json("readsb_status.json"),
                "/data/stats.json": load_json("readsb_stats.json"),
                "/status.json": load_json("piaware_status.json"),
                "/monitor.json": load_json("fr24_monitor.json"),
                "/" + mlat_stats_path("feed.adsbexchange.com", 31090): load_json(
                    "mlat_client_stats.json"
                ),
            }
        )
    )


def docker_client(path: str) -> DockerClient:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ultrafeeder/logs"):
            return httpx.Response(200, content=framed_log(load_lines("ultrafeeder.log")))
        if request.url.path.endswith("/opensky/logs"):
            return httpx.Response(200, content=framed_log(load_lines("opensky.log")))
        if request.url.path.endswith("/json"):
            return httpx.Response(200, json={"State": {"Status": "running", "Running": True}})
        return httpx.Response(200, text="OK")

    return DockerClient(path, transport=httpx.MockTransport(handle))


def test_the_fixture_really_carries_every_redacted_field() -> None:
    monitor = load_json("fr24_monitor.json")

    for name in REDACTED_FIELDS:
        assert "SENTINEL" in monitor[name]


async def test_no_sentinel_reaches_the_report_history_or_logs(
    database: Database,
    clock: ManualClock,
    counters: CounterRegistry,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = FeederService(
        database=database,
        settings=Settings(
            entries=ENTRIES,
            docker_socket="/var/run/docker.sock",
            stats_urls={"fr24": SecretStr(SECRET_STATS_URL)},
        ),
        client_factory=http_client,
        docker_factory=docker_client,
        clock=clock,
        counters=counters,
    )
    await service.start()
    for _ in range(3):  # inside piaware's 10-second expiry window
        await service.poll_once()
        clock.advance(3)

    report = service.report()
    rendered = json.dumps(report)
    histories = [json.dumps(await service.history(name, "24h")) for name in service.names]
    await service.stop()
    logged = capsys.readouterr()

    states = {feeder["name"]: feeder["state"] for feeder in report["feeders"]}
    assert states == {
        "receiver": "up",
        "flightaware": "up",
        "fr24": "up",
        "adsbx": "up",
        "opensky": "up",
        "backstop": "up",
        "links": "unknown",
    }
    assert {f["name"]: f["stats_link"] for f in report["feeders"]}["flightaware"] is True
    for sentinel in (*SENTINELS, SECRET_STATS_URL, "SENTINEL"):
        assert sentinel not in rendered
        assert all(sentinel not in history for history in histories)
        assert sentinel not in logged.out
        assert sentinel not in logged.err
    # The secret is still reachable — through the one method the redirect uses.
    assert service.stats_url("fr24") == SECRET_STATS_URL
