"""Tests for the FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flightsite import __version__
from flightsite.app import create_app
from flightsite.readiness import ReadinessRegistry


def test_create_app_returns_configured_fastapi_instance() -> None:
    app = create_app()

    assert isinstance(app, FastAPI)
    assert app.title == "FlightSite"
    assert app.version == __version__


def test_create_app_registers_v1_routes() -> None:
    app = create_app()

    with TestClient(app) as client:
        health_response = client.get("/api/v1/health")
        ready_response = client.get("/api/v1/ready")

    assert health_response.status_code == 200
    assert ready_response.status_code == 200


def test_create_app_initializes_readiness_and_start_time() -> None:
    app = create_app()

    assert isinstance(app.state.readiness, ReadinessRegistry)
    assert isinstance(app.state.start_time, float)
