"""Tests for GET /api/v1/health."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import flightsite.api.v1 as v1_module
from flightsite import __version__
from flightsite.app import create_app
from flightsite.counters import KNOWN_COUNTERS, CounterRegistry


def test_health_returns_ok_with_version_uptime_and_counters() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert isinstance(body["uptime_s"], int | float)
    assert body["uptime_s"] >= 0
    assert set(body["counters"]) == set(KNOWN_COUNTERS)
    assert all(count == 0 for count in body["counters"].values())


def test_health_counters_reflect_registry_state(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_registry = CounterRegistry()
    fresh_registry.increment("db_errors")
    monkeypatch.setattr(v1_module, "counters", fresh_registry)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.json()["counters"]["db_errors"] == 1
