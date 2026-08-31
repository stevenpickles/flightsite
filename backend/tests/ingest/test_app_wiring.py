"""Ingestion as the app starts and stops it.

Two decisions are pinned here, because both are easy to regress and expensive
to get wrong in production:

* a first-run install starts no ingestion at all, so a machine that has never
  been configured does not spend its first boot logging connection failures
  against a receiver nobody chose;
* a decoder that is unreachable does **not** fail ``/ready``. The app is fully
  usable without one, and an orchestrator restarting the backend because
  something outside it went offline would take away the very UI that explains
  the outage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.config import ConfigStore
from flightsite.ingest.service import READINESS_SUBSYSTEM, IngestionService

from .conftest import CountingClientFactory, ScriptedTransport, json_response


@pytest.fixture
def configured(isolated_data_dir: Path) -> ConfigStore:
    """Write a config.yaml, so the install is no longer on its first run."""
    store = ConfigStore(isolated_data_dir)
    store.save(store.load())
    assert store.first_run is False
    return store


def point_decoder_at(
    monkeypatch: pytest.MonkeyPatch, entry: httpx.Response | Exception
) -> CountingClientFactory:
    """Make every adapter client the app builds talk to a mock transport."""
    factory = CountingClientFactory(ScriptedTransport([entry]))
    monkeypatch.setattr(
        "flightsite.ingest.readsb.build_client", lambda *_args, **_kwargs: factory()
    )
    return factory


def test_first_run_starts_no_ingestion() -> None:
    app = create_app()

    with TestClient(app) as client:
        ready = client.get("/api/v1/ready")

        assert app.state.ingestion is None
        assert ready.status_code == 200
        assert ready.json()["subsystems"] == {"database": True}


def test_a_configured_install_starts_ingestion(
    configured: ConfigStore, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app()

    with TestClient(app) as client:
        service: IngestionService | None = app.state.ingestion
        ready = client.get("/api/v1/ready")

        assert service is not None
        assert service.running is True
        assert ready.status_code == 200
        assert ready.json()["subsystems"] == {"database": True, READINESS_SUBSYSTEM: True}


def test_an_unreachable_decoder_keeps_the_app_ready(
    configured: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_decoder_at(monkeypatch, httpx.ConnectError("connection refused"))
    app = create_app()

    with TestClient(app) as client:
        ready = client.get("/api/v1/ready")
        health = client.get("/api/v1/health")

    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert health.status_code == 200


def test_shutdown_stops_ingestion(
    configured: ConfigStore, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app()

    with TestClient(app):
        service: IngestionService | None = app.state.ingestion

    assert service is not None
    assert service.running is False
