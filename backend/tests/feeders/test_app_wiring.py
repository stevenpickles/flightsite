"""How the application wires the feeder service — slice 077.

Two groups. The first drives the wiring with a stand-in service injected into
``app.state``: the hot-apply on config save, the lifespan's start and stop,
and the ``on_transition`` hook into the activity feed. Those are claims about
``app.py`` and ``api/internal.py`` and hold whatever the service does inside.

The second makes the roadmap's two *negative* claims about the real service
the app builds — no entries means no task, no socket means no Docker client —
and so needs :mod:`flightsite.feeders` to be present.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flightsite.activity import FeederEpisode
from flightsite.app import _record_feeder_episode, create_app
from flightsite.config import FeederSettings

ENTRY = {
    "name": "fr24",
    "label": "FlightRadar24",
    "kind": "fr24",
    "url": "http://host.docker.internal:8754/monitor.json",
}


class FakeFeeders:
    """Records what the application asks of it, and nothing else."""

    def __init__(self, app: FastAPI | None = None, *, fail: bool = False) -> None:
        self.app = app
        self.fail = fail
        self.calls: list[str] = []
        self.applied: list[FeederSettings] = []
        self.activity_running_at_stop: bool | None = None

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")
        if self.app is not None:
            self.activity_running_at_stop = self.app.state.activity.running

    def apply_settings(self, settings: FeederSettings) -> None:
        if self.fail:
            raise RuntimeError("probe rebuild failed")
        self.calls.append("apply")
        self.applied.append(settings)


class AsyncFakeFeeders(FakeFeeders):
    async def apply_settings(self, settings: FeederSettings) -> None:  # type: ignore[override]
        super().apply_settings(settings)


@pytest.fixture
def app(isolated_data_dir: Path) -> FastAPI:
    return create_app(isolated_data_dir)


# ------------------------------------------------------ stand-in service


def test_a_config_save_hot_applies_the_feeder_section(app: FastAPI) -> None:
    fake = FakeFeeders()
    app.state.feeders = fake
    with TestClient(app) as client:
        response = client.put(
            "/api/internal/config",
            json={"feeders": {"poll_interval_s": 30, "entries": [ENTRY]}},
        )

    assert response.status_code == 200, response.text
    (applied,) = fake.applied
    assert applied.poll_interval_s == 30
    assert [entry.name for entry in applied.entries] == ["fr24"]


def test_an_async_apply_is_awaited(app: FastAPI) -> None:
    fake = AsyncFakeFeeders()
    app.state.feeders = fake
    with TestClient(app) as client:
        assert client.put("/api/internal/config", json={"units": "metric"}).status_code == 200

    assert len(fake.applied) == 1


def test_entries_are_replaced_wholesale_and_persisted(
    app: FastAPI, isolated_data_dir: Path
) -> None:
    app.state.feeders = FakeFeeders()
    second = dict(ENTRY, name="flightaware", label="FlightAware", kind="piaware")
    with TestClient(app) as client:
        client.put("/api/internal/config", json={"feeders": {"entries": [ENTRY, second]}})
        body = client.put("/api/internal/config", json={"feeders": {"entries": [second]}}).json()

    assert [entry["name"] for entry in body["config"]["feeders"]["entries"]] == ["flightaware"]
    on_disk = (isolated_data_dir / "config.yaml").read_text(encoding="utf-8")
    assert "flightaware" in on_disk
    assert "monitor.json" in on_disk  # the piaware entry kept the URL it was given
    assert "name: fr24" not in on_disk


def test_an_invalid_entry_is_rejected_per_field_and_nothing_is_applied(app: FastAPI) -> None:
    fake = FakeFeeders()
    app.state.feeders = fake
    bad = {"name": "adsbx", "label": "ADS-B Exchange", "kind": "ultrafeeder"}
    with TestClient(app) as client:
        response = client.put("/api/internal/config", json={"feeders": {"entries": [bad]}})

    assert response.status_code == 422
    locs = {tuple(error["loc"]) for error in response.json()["detail"]}
    assert locs == {("feeders", "entries", 0, "url"), ("feeders", "entries", 0, "host")}
    assert fake.applied == []


def test_a_failing_apply_does_not_fail_the_save(app: FastAPI) -> None:
    app.state.feeders = FakeFeeders(fail=True)
    with TestClient(app) as client:
        response = client.put("/api/internal/config", json={"feeders": {"entries": [ENTRY]}})

    assert response.status_code == 200
    assert response.json()["config"]["feeders"]["entries"][0]["name"] == "fr24"


def test_demo_mode_keeps_its_stand_ins(app: FastAPI) -> None:
    fake = FakeFeeders()
    app.state.feeders = fake
    app.state.demo_enabled = True
    with TestClient(app) as client:
        assert client.put("/api/internal/config", json={"units": "metric"}).status_code == 200

    assert fake.applied == []


def test_the_lifespan_starts_and_stops_the_service_before_the_feed(app: FastAPI) -> None:
    fake = FakeFeeders(app)
    app.state.feeders = fake
    with TestClient(app):
        assert fake.calls == ["start"]

    assert fake.calls == ["start", "stop"]
    # Stopped while the activity service still runs, so a last transition
    # still reaches the feed's final pass.
    assert fake.activity_running_at_stop is True


def test_no_service_is_tolerated_by_every_seam(app: FastAPI) -> None:
    app.state.feeders = None
    with TestClient(app) as client:
        assert client.put("/api/internal/config", json={"units": "metric"}).status_code == 200
        assert client.get("/api/v1/diagnostics").status_code == 200


def test_the_transition_hook_feeds_the_activity_queue() -> None:
    received: list[FeederEpisode] = []
    app = SimpleNamespace(
        state=SimpleNamespace(activity=SimpleNamespace(record_feeder_episode=received.append))
    )
    episode = FeederEpisode(
        feeder="fr24", label="FR24", kind="fr24", offline=True, since_ms=1, at_ms=1
    )

    _record_feeder_episode(app)(episode)  # type: ignore[arg-type]

    assert received == [episode]


# ------------------------------------------------------- the real service


@pytest.fixture
async def migrated(isolated_data_dir: Path) -> AsyncIterator[FastAPI]:
    """An app whose database is at head, without running the lifespan."""
    app = create_app(isolated_data_dir)
    await app.state.database.upgrade_to("head")
    try:
        yield app
    finally:
        await app.state.database.dispose()


def _service(app: FastAPI) -> Any:
    service = app.state.feeders
    assert service is not None, "flightsite.feeders is not present in this tree"
    return service


async def test_no_entries_means_no_task(migrated: FastAPI) -> None:
    service = _service(migrated)
    before = asyncio.all_tasks()

    await service.start()
    started = asyncio.all_tasks() - before
    await service.stop()

    assert started == set()


async def test_no_socket_means_no_docker_client(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_data_dir / "config.yaml").write_text(
        "feeders:\n"
        "  entries:\n"
        "    - {name: opensky, label: OpenSky, kind: opensky_logs, container: opensky}\n"
        "    - {name: backstop, label: Backstop, kind: docker_health, container: piaware}\n",
        encoding="utf-8",
    )
    sockets: list[object] = []
    original = httpx.AsyncHTTPTransport.__init__

    def spy(self: httpx.AsyncHTTPTransport, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("uds") is not None:
            sockets.append(kwargs["uds"])
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "__init__", spy)

    app = create_app(isolated_data_dir)
    await app.state.database.upgrade_to("head")
    try:
        service = _service(app)
        await service.start()
        poll_once = getattr(service, "poll_once", None)
        if poll_once is not None:
            await poll_once()
        await service.stop()
    finally:
        await app.state.database.dispose()

    assert sockets == []
