"""Demo mode as the app wires it up: activation, health, and receiver defaults.

Complements ``tests/ingest/test_app_wiring.py`` (which pins the non-demo
first-run and unreachable-decoder behavior) with the slice 011 exception to
those rules: ``FLIGHTSITE_DEMO=1`` starts ingestion on a first run, and the
health payload says so.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from flightsite.app import create_app
from flightsite.config import ConfigStore, LocationSettings
from flightsite.demo.adapter import DEFAULT_CENTER
from flightsite.ingest.service import READINESS_SUBSYSTEM, IngestionService


@pytest.fixture
def configured(isolated_data_dir: Path) -> ConfigStore:
    """Write a config.yaml, so the install is no longer on its first run."""
    store = ConfigStore(isolated_data_dir)
    store.save(store.load())
    assert store.first_run is False
    return store


def test_demo_disabled_by_default(isolated_data_dir: Path) -> None:
    app = create_app()

    with TestClient(app) as client:
        assert app.state.ingestion is None
        health = client.get("/api/v1/health")

    assert health.json()["demo"] is False


def test_demo_flag_starts_ingestion_on_a_first_run(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")
    store = ConfigStore(isolated_data_dir)
    assert store.first_run is True

    app = create_app()

    with TestClient(app) as client:
        service: IngestionService | None = app.state.ingestion
        ready = client.get("/api/v1/ready")
        health = client.get("/api/v1/health")

        assert service is not None
        assert service.running is True
        assert ready.status_code == 200
        assert ready.json()["subsystems"] == {"database": True, READINESS_SUBSYSTEM: True}
        assert health.json()["demo"] is True


def test_demo_flag_starts_ingestion_even_when_configured(
    configured: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")
    app = create_app()

    with TestClient(app):
        service: IngestionService | None = app.state.ingestion

    assert service is not None


async def test_demo_injects_the_default_center_when_no_receiver_is_configured(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")
    app = create_app()

    async with app.router.lifespan_context(app):
        assert app.state.live.receiver_location == DEFAULT_CENTER


async def test_demo_uses_the_configured_receiver_location_when_present(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ConfigStore(isolated_data_dir)
    settings = store.load()
    settings.location = LocationSettings(latitude=47.4502, longitude=-122.3088)
    store.save(settings)

    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")
    app = create_app()

    async with app.router.lifespan_context(app):
        location = app.state.live.receiver_location
        assert location is not None
        assert location.latitude == pytest.approx(47.4502)
        assert location.longitude == pytest.approx(-122.3088)


async def test_demo_mode_grows_the_live_set_over_real_time(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")
    app = create_app()
    transport = ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        health = await client.get("/api/v1/health")
        assert health.json()["demo"] is True

        # The demo adapter's poll loop runs on the wall clock in production
        # wiring (no injected clock here) — a short real wait is the only way
        # to observe it actually producing traffic end to end.
        await asyncio.sleep(1.5)
        assert len(app.state.live) > 0
