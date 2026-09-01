"""The metadata subsystem's place in the application lifespan."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.metadata import MetadataService


def _refuse_connection(request: httpx.Request) -> httpx.Response:
    """A transport handler standing in for "no network in tests"."""
    raise httpx.ConnectError("no network in tests", request=request)


def test_the_service_is_constructed_without_touching_anything(
    isolated_data_dir: Path,
) -> None:
    """Building an app stays side-effect free (no connection, no directory).

    Registering the ``faa`` source is itself side-effect free — it is an
    in-memory dict entry, not I/O — so it belongs in this same assertion.
    """
    app = create_app(isolated_data_dir)

    service = app.state.metadata
    assert isinstance(service, MetadataService)
    assert not service.cache.running
    assert len(service.registry) == 1


def test_the_registry_carries_the_faa_source(isolated_data_dir: Path) -> None:
    """Slice 021 shipped no concrete provider; 023 registers the FAA one.

    (022's Mictronics provider is not on this branch, so ``faa`` is the whole
    registry here; the two land together once both slices are merged.)
    """
    app = create_app(isolated_data_dir)

    assert app.state.metadata.registry.names == ("faa",)


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


async def test_an_import_runs_through_the_started_app(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The orchestration entrypoint slice 025 will call, on a real app.

    The registered ``faa`` source talks real HTTP by default, which a unit
    test must not do; its client factory is monkeypatched to a transport that
    refuses the connection, so this exercises the full registry -> importer ->
    repository path (including a recorded failure) without leaving the
    process.
    """
    monkeypatch.setattr(
        "flightsite.metadata.sources.faa.build_client",
        lambda *_args, **_kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(_refuse_connection)
        ),
    )
    app = create_app(isolated_data_dir)

    with TestClient(app):
        service: MetadataService = app.state.metadata
        run = await service.update()

        assert [result.source for result in run.results] == ["faa"]
        assert run.failed == ("faa",)
        statuses = await service.statuses()
        assert [status.source for status in statuses] == ["faa"]


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
