"""Receiver metrics' place in the application lifespan.

Three claims, each tested against the real app rather than against a service
built by hand: it is constructed inertly, it is started and stopped on the same
edges as every other database consumer, and it does not touch readiness — a
receiver with no statistics endpoint is a fully ready FlightSite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.db import Database
from flightsite.ingest import DecoderEndpoint
from flightsite.receiver_metrics import ReceiverMetricsService
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.statsjson import stats_url_for


def write_config(data_dir: Path, **overrides: object) -> None:
    """Write a ``config.yaml`` so the install is no longer a first run."""
    document: dict[str, object] = {
        "receiver": {"host": "decoder.test", "port": 8080, "path": "/data/aircraft.json"},
        **overrides,
    }
    (data_dir / "config.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")


def test_the_service_is_constructed_without_touching_anything(
    isolated_data_dir: Path,
) -> None:
    """Building an app opens no socket, no session and no task."""
    app = create_app(isolated_data_dir)

    service: ReceiverMetricsService = app.state.receiver_metrics
    assert isinstance(service, ReceiverMetricsService)
    assert service.running is False
    assert service.pending_samples == 0
    assert service.latest_stats is None


def test_a_configured_receiver_gets_a_statistics_poller(isolated_data_dir: Path) -> None:
    """The statistics URL is derived from the one configured decoder endpoint."""
    write_config(isolated_data_dir)

    app = create_app(isolated_data_dir)

    poller = app.state.receiver_metrics._poller
    assert poller is not None
    assert poller.url == stats_url_for(
        DecoderEndpoint(host="decoder.test", port=8080, path="/data/aircraft.json")
    )


def test_a_first_run_install_polls_no_decoder_at_all(isolated_data_dir: Path) -> None:
    """No ``config.yaml`` means no receiver the user actually chose.

    The same rule ingestion follows: polling model defaults would produce a
    stream of connection failures before the setup wizard has been opened.
    Metrics still run — they simply have only FlightSite's own to record.
    """
    app = create_app(isolated_data_dir)

    assert app.state.receiver_metrics._poller is None


def test_demo_mode_records_metrics_without_a_decoder(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demo mode has no decoder to ask, and needs none (SPEC §76)."""
    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")

    app = create_app(isolated_data_dir)

    assert app.state.receiver_metrics._poller is None
    assert isinstance(app.state.receiver_metrics, ReceiverMetricsService)


def test_the_configured_retention_window_and_timezone_reach_the_service(
    isolated_data_dir: Path,
) -> None:
    """``retention.high_res_metric_days`` and ``timezone`` are this slice's inputs."""
    write_config(
        isolated_data_dir, retention={"high_res_metric_days": 30}, timezone="Europe/London"
    )

    service: ReceiverMetricsService = create_app(isolated_data_dir).state.receiver_metrics

    assert service._window_ms == 30 * 24 * 3_600_000
    assert str(service._zone) == "Europe/London"


def test_the_service_runs_across_the_lifespan(isolated_data_dir: Path) -> None:
    """Started on a healthy schema, stopped before the engines close."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert app.state.receiver_metrics.running is True

    assert app.state.receiver_metrics.running is False


def test_readiness_is_untouched_by_receiver_metrics(isolated_data_dir: Path) -> None:
    """Metrics are observability, not a dependency: they cannot gate ``/ready``.

    A decoder with no statistics endpoint, or a metrics subsystem that is
    degraded, must never make an orchestrator restart a backend that is serving
    the live picture perfectly well.
    """
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        ready = client.get("/api/v1/ready")

    assert ready.status_code == 200
    # The exact set, not a "not in": a new subsystem appearing here would be a
    # new way for the backend to report itself unready, and this slice adds none.
    assert ready.json() == {"ready": True, "subsystems": {"database": True}}


async def test_shutdown_flushes_the_interval_the_service_was_holding(
    isolated_data_dir: Path,
) -> None:
    """A clean stop must not drop the samples buffered since the last flush.

    The sample is taken by hand — the app's own poller runs on a fifteen-second
    cadence this test is not going to wait for — but the flush is the lifespan's
    own, so what is asserted is that shutdown performs it.
    """
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        client.get("/api/v1/health")
        service: ReceiverMetricsService = app.state.receiver_metrics
        await service.sample_once()
        assert service.pending_samples == 1

    assert service.pending_samples == 0
    # And it reached the disk: the lifespan's engines are disposed by now, so
    # the count is read through a fresh connection to the same file.
    reopened = Database(app.state.database.path)
    try:
        assert await MetricsRepository(reopened).raw_count() == 1
    finally:
        await reopened.dispose()
