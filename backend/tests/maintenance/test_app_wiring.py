"""How the maintenance service is wired into the application.

Three things are asserted here rather than in the unit tests: that the service
exists and runs across the lifespan; that it is handed the one prunable domain
it is responsible for and no others; and that adding a sixth background task
did not add a sixth way for the backend to report itself unready.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.db.startup import DATABASE_SUBSYSTEM
from flightsite.maintenance import (
    DEFAULT_CYCLE_INTERVAL_S,
    ROUTE_CACHE_TASK,
    MaintenanceService,
    RouteCachePruner,
)
from tests.db.harness import write_garbage


def test_the_service_is_constructed_without_touching_anything(
    isolated_data_dir: Path,
) -> None:
    """Building an app stays side-effect free: no task, no connection, no file."""
    service: MaintenanceService = create_app(isolated_data_dir).state.maintenance

    assert isinstance(service, MaintenanceService)
    assert service.running is False
    assert service.report.cycles == 0
    assert (isolated_data_dir / "flightsite.sqlite3").exists() is False


def test_the_service_runs_across_the_lifespan(isolated_data_dir: Path) -> None:
    """Started on a healthy schema, stopped before the engines close."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert app.state.maintenance.running is True

    assert app.state.maintenance.running is False


def test_the_service_does_not_start_on_a_broken_schema(isolated_data_dir: Path) -> None:
    """Nothing to verify, prune or optimize until the migration succeeds."""
    write_garbage(isolated_data_dir / "flightsite.sqlite3")
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        assert client.get("/api/v1/ready").status_code == 503
        assert app.state.maintenance.running is False


def test_the_route_cache_is_the_only_prunable_domain_wired(isolated_data_dir: Path) -> None:
    """The documented boundary, asserted rather than merely written down.

    Receiver metrics prune their own raw tier in ADR-0009's required order, and
    track checkpoints are deleted transactionally at sighting close and swept
    by recovery. Wiring either of them here as well would mean two schedulers
    pruning one table — see :mod:`flightsite.maintenance.retention`.
    """
    service: MaintenanceService = create_app(isolated_data_dir).state.maintenance

    tasks = service._retention
    assert [task.name for task in tasks] == [ROUTE_CACHE_TASK]
    assert isinstance(tasks[0], RouteCachePruner)


def test_the_wired_pruner_shares_the_enrichment_service_s_repository(
    isolated_data_dir: Path,
) -> None:
    """One repository, so pruning and reading cannot disagree about expiry."""
    app = create_app(isolated_data_dir)

    pruner = app.state.maintenance._retention[0]
    assert pruner.repository is app.state.enrichment._cache


def test_the_service_uses_the_documented_defaults(isolated_data_dir: Path) -> None:
    """SPEC §70's *no routine user babysitting*: nothing here is configurable."""
    app = create_app(isolated_data_dir)
    service: MaintenanceService = app.state.maintenance

    assert service._cycle_interval_s == DEFAULT_CYCLE_INTERVAL_S
    # The live store is read for one thing only: the VACUUM pressure heuristic.
    assert service._live is app.state.live
    assert service._database is app.state.database


def test_this_slice_adds_no_configuration_key(isolated_data_dir: Path) -> None:
    """The settings model is unchanged, so an install has nothing to tune."""
    settings = create_app(isolated_data_dir).state.settings
    names = type(settings).model_fields

    assert not [name for name in names if "maintenance" in name]
    assert not [name for name in names if "vacuum" in name]


def test_readiness_is_untouched_by_maintenance(isolated_data_dir: Path) -> None:
    """Housekeeping is not a dependency: it cannot gate ``/ready``."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        ready = client.get("/api/v1/ready")

    assert ready.status_code == 200
    # The exact set, not a "not in": a new subsystem appearing here would be a
    # new way for the backend to report itself unready, and this slice adds none.
    assert ready.json() == {"ready": True, "subsystems": {DATABASE_SUBSYSTEM: True}}
