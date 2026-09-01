"""The metadata subsystem's place in the application lifespan."""

from __future__ import annotations

import gzip
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.metadata import MetadataService, SourceStatus
from flightsite.metadata.sources import mictronics

#: A tiny real-format snapshot: one ordinary airframe, one military one.
#: Compressed fresh per test so nothing here depends on network access.
_SAMPLE_CSV = (
    "A1BCCA;N21065;P28A;00;PIPER PA-28-140/150/160/180;1978;OMNI MANAGEMENT LLC;\n"
    "006015;FAM-002;H25B;10;HAWKER BEECHCRAFT Hawker 750/850;;;\n"
)


def _mock_mictronics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the registered provider at an in-process transport, not the network.

    ``app.py`` constructs :class:`~flightsite.metadata.sources.mictronics.MictronicsProvider`
    with no override, so it resolves its HTTP client through the module-level
    ``build_client`` at call time (mirroring
    :mod:`flightsite.ingest.readsb`'s ``client_factory`` seam) — patching that
    name here, before ``create_app`` constructs the provider, is what lets a
    real end-to-end import run in a test without ever reaching GitHub. The
    artifact-size floor is dropped to match a fixture far smaller than a real
    ~8 MB snapshot.
    """
    payload = gzip.compress(_SAMPLE_CSV.encode("utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    monkeypatch.setattr(
        mictronics,
        "build_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(mictronics, "MIN_ARTIFACT_BYTES", 10)


def test_the_service_is_constructed_without_touching_anything(
    isolated_data_dir: Path,
) -> None:
    """Building an app stays side-effect free (no connection, no directory)."""
    app = create_app(isolated_data_dir)

    service = app.state.metadata
    assert isinstance(service, MetadataService)
    assert not service.cache.running
    assert len(service.registry) == 1


def test_the_registry_ships_mictronics(isolated_data_dir: Path) -> None:
    """Slice 022 registers the offline primary source; 023 adds FAA."""
    app = create_app(isolated_data_dir)

    assert app.state.metadata.registry.names == ("mictronics",)


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
    """The orchestration entrypoint slice 025 will call, on a real app."""
    _mock_mictronics(monkeypatch)
    app = create_app(isolated_data_dir)

    with TestClient(app):
        service: MetadataService = app.state.metadata
        run = await service.update()

        assert [result.source for result in run.results] == ["mictronics"]
        assert run.results[0].ok
        assert run.results[0].rows_imported == 2

        statuses = await service.statuses()
        assert [status.source for status in statuses] == ["mictronics"]
        assert statuses[0].status == SourceStatus.OK


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
