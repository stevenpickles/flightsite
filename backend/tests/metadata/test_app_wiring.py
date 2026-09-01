"""The metadata subsystem's place in the application lifespan."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from flightsite.app import create_app
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.metadata import MetadataService, SourceStatus
from flightsite.metadata.sources import mictronics
from tests.metadata.conftest import settle

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


def _refuse_connection(request: httpx.Request) -> httpx.Response:
    """A transport handler standing in for "no network in tests"."""
    raise httpx.ConnectError("no network in tests", request=request)


def _refuse_network(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    """Point a provider's client factory at a transport that always refuses.

    Every registered source has to be pointed somewhere in a test that calls
    ``update()`` with no argument — that runs *all* of them, and one left
    unpatched would reach the internet from the test suite.
    """
    monkeypatch.setattr(
        target,
        lambda *_args, **_kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(_refuse_connection)
        ),
    )


def test_the_service_is_constructed_without_touching_anything(
    isolated_data_dir: Path,
) -> None:
    """Building an app stays side-effect free (no connection, no directory).

    Registering a source is itself side-effect free — it is an in-memory dict
    entry, not I/O — so it belongs in this same assertion.
    """
    app = create_app(isolated_data_dir)

    service = app.state.metadata
    assert isinstance(service, MetadataService)
    assert not service.cache.running
    assert len(service.registry) == 3


def test_the_registry_ships_every_dataset_this_build_imports(isolated_data_dir: Path) -> None:
    """Slice 022 registers the offline primary source, 023 adds FAA, 027 airports."""
    app = create_app(isolated_data_dir)

    assert app.state.metadata.registry.names == ("airports", "faa", "mictronics")


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

    Mictronics is mocked to a tiny successful dataset; the FAA source's client
    factory is monkeypatched to a transport that refuses the connection, so
    one run exercises both the success and the recorded-failure paths of the
    registry -> importer -> repository pipeline without leaving the process.
    """
    _mock_mictronics(monkeypatch)
    _refuse_network(monkeypatch, "flightsite.metadata.sources.faa.build_client")
    _refuse_network(monkeypatch, "flightsite.airports.ourairports.build_client")
    app = create_app(isolated_data_dir)

    with TestClient(app):
        service: MetadataService = app.state.metadata
        run = await service.update()

        by_result = {result.source: result for result in run.results}
        assert set(by_result) == {"mictronics", "faa", "airports"}
        assert by_result["mictronics"].ok
        assert by_result["mictronics"].rows_imported == 2
        assert set(run.failed) == {"faa", "airports"}

        statuses = await service.statuses()
        assert {status.source for status in statuses} == {"mictronics", "faa", "airports"}
        by_source = {status.source: status for status in statuses}
        assert by_source["mictronics"].status == SourceStatus.OK
        assert by_source["airports"].status == SourceStatus.FAILED


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


async def test_the_live_api_publishes_metadata_and_classification_end_to_end(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The slice's activation, through the real app rather than a harness.

    An import runs, the live store hears the two airframes the snapshot
    describes, the cache resolves and classifies them on its own task, and
    ``GET /api/v1/aircraft/current`` serves the ``docs/API.md`` §3.3 object with
    its metadata half filled in. Nothing between the decoder and the response
    reads the database.
    """
    _mock_mictronics(monkeypatch)
    app = create_app(isolated_data_dir)

    async with app.router.lifespan_context(app):
        service: MetadataService = app.state.metadata
        run = await service.update(["mictronics"])
        assert run.failed == ()

        app.state.live.apply_updates(
            [
                AircraftStateUpdate(
                    icao=icao,
                    timestamp=datetime.now(tz=UTC),
                    position_source="adsb",
                    position=Position(latitude=47.6, longitude=-122.3),
                    callsign=callsign,
                )
                for icao, callsign in (("a1bcca", "N21065"), ("006015", None))
            ]
        )
        await settle(service.cache)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            body = (await client.get("/api/v1/aircraft/current")).json()

    aircraft = {item["icao"]: item for item in body["items"]}

    civil = aircraft["a1bcca"]
    assert civil["registration"] == "N21065"
    assert civil["aircraft_type"] == "P28A"
    assert civil["operator"] == "OMNI MANAGEMENT LLC"
    assert civil["operator_group"] is None
    assert civil["classification"]["mission"] == "general_aviation"
    assert civil["classification"]["icon_category"] == "light_aircraft"
    assert civil["provenance"]["aircraft_type"] == "mictronics"

    military = aircraft["006015"]
    assert military["classification"] == {
        "military": True,
        "government": False,
        "law_enforcement": False,
        "mission": "military",
        "icon_category": "military",
        "confidence": "high",
    }
    assert military["provenance"]["classification"] == "mictronics"
