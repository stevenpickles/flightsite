"""Tests for GET /api/v1/ready: started-but-not-ready vs ready transitions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from flightsite.app import create_app


def test_ready_after_startup_with_no_registered_subsystems() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["subsystems"] == {}


def test_ready_returns_503_while_registered_subsystem_not_ready() -> None:
    app = create_app()
    app.state.readiness.register("fake_subsystem")

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["subsystems"]["fake_subsystem"] is False


def test_ready_returns_200_once_registered_subsystem_marked_ready() -> None:
    app = create_app()
    app.state.readiness.register("fake_subsystem")
    app.state.readiness.mark_ready("fake_subsystem")

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["subsystems"]["fake_subsystem"] is True
