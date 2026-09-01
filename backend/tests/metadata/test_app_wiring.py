"""The metadata subsystem's place in the application lifespan."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.metadata import MetadataService


def test_the_service_is_constructed_without_touching_anything(
    isolated_data_dir: Path,
) -> None:
    """Building an app stays side-effect free (no connection, no directory)."""
    app = create_app(isolated_data_dir)

    service = app.state.metadata
    assert isinstance(service, MetadataService)
    assert not service.cache.running
    assert len(service.registry) == 0


def test_the_registry_ships_empty(isolated_data_dir: Path) -> None:
    """Slice 021 ships no concrete provider; 022 and 023 register theirs."""
    app = create_app(isolated_data_dir)

    assert app.state.metadata.registry.names == ()


def test_the_cache_runs_for_the_lifetime_of_the_app(isolated_data_dir: Path) -> None:
    app = create_app(isolated_data_dir)

    with TestClient(app):
        assert app.state.metadata.cache.running

    assert not app.state.metadata.cache.running


def test_no_http_endpoint_exposes_metadata_yet(isolated_data_dir: Path) -> None:
    """``docs/API.md`` §5 assigns ``/api/internal/metadata/*`` to slice 025."""
    app = create_app(isolated_data_dir)

    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert not any(path.startswith("/api/internal/metadata") for path in paths)
    assert not any("metadata" in path for path in paths)


async def test_an_import_runs_through_the_started_app(isolated_data_dir: Path) -> None:
    """The orchestration entrypoint slice 025 will call, on a real app."""
    app = create_app(isolated_data_dir)

    with TestClient(app):
        service: MetadataService = app.state.metadata
        run = await service.update()

        assert run.results == ()
        assert await service.statuses() == ()


@pytest.mark.parametrize("iterations", [2])
def test_starting_and_stopping_repeatedly_is_clean(
    isolated_data_dir: Path, iterations: int
) -> None:
    """A restart in the same process must not leak a task or a subscription."""
    app = create_app(isolated_data_dir)

    for _ in range(iterations):
        with TestClient(app):
            assert app.state.metadata.cache.running
        assert not app.state.metadata.cache.running
