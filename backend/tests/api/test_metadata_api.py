"""Internal metadata API tests: ``POST``/``GET /api/internal/metadata/*`` (slice 025).

The app the fixtures build here keeps everything else ``create_app`` wires up
(config, live store, persistence, broadcaster) but swaps ``app.state.metadata``
for a fresh :class:`~flightsite.metadata.MetadataService` over an empty
:class:`~flightsite.metadata.SourceRegistry` each test fills with
:class:`~tests.metadata.provider.InMemoryMetadataProvider` doubles — the same
substitution ``tests/api/conftest.py``'s live-app harness makes for
``app.state.live``, and for the same reason: nothing here should ever reach
the network.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from flightsite.api.internal import _log_update_task_result
from flightsite.app import create_app
from flightsite.live import LiveStore
from flightsite.logging import configure_logging
from flightsite.metadata import ImportRun, MetadataService, SourceRegistry
from flightsite.metadata.registry import ImportPhase

from ..metadata.conftest import record
from ..metadata.provider import InMemoryMetadataProvider

METADATA_STATUS_PATH = "/api/internal/metadata/status"
METADATA_UPDATE_PATH = "/api/internal/metadata/update"

RECORD_A = record("a00001", registration="N1AA", type_code="B738")


@pytest.fixture
def registry() -> SourceRegistry:
    """An empty registry each test fills with in-memory providers."""
    return SourceRegistry()


@pytest.fixture
async def app(isolated_data_dir: Path, registry: SourceRegistry) -> AsyncIterator[FastAPI]:
    """A started app whose metadata service runs over the test's own registry."""
    application = create_app(isolated_data_dir)
    application.state.metadata = MetadataService(
        database=application.state.database,
        live=LiveStore(clock=lambda: 0.0),
        data_dir=isolated_data_dir,
        registry=registry,
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as async_client:
        yield async_client


#: Generous relative to how fast this actually resolves (microseconds of
#: in-thread work): a slow CI runner should never turn scheduling jitter into
#: a flaky failure.
_STARTED_TIMEOUT_S = 2.0


async def _wait_started(provider: InMemoryMetadataProvider) -> None:
    """Wait until ``provider.download`` has actually been entered.

    Genuine cross-thread synchronization, not a flaky-assertion workaround:
    the importer's download stage runs on the same loop, but there is real
    ``asyncio.to_thread`` work (preparing the run's working directory)
    between scheduling a background run and it reaching a controlled hold, so
    a fixed number of loop yields is not a reliable wait.
    """
    async with asyncio.timeout(_STARTED_TIMEOUT_S):
        await provider.started.wait()


async def _status_by_name(client: AsyncClient) -> dict[str, dict[str, object]]:
    response = await client.get(METADATA_STATUS_PATH)
    assert response.status_code == 200
    body = response.json()
    return {entry["name"]: entry for entry in body["sources"]}


# --------------------------------------------------------------- POST /update


async def test_trigger_returns_before_the_run_completes(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    hold = asyncio.Event()
    provider = InMemoryMetadataProvider([RECORD_A], version="mict-1", hold=hold)
    registry.register("mictronics", provider)

    response = await client.post(METADATA_UPDATE_PATH)

    assert response.status_code == 202
    body = response.json()
    assert body["started"] is True
    assert body["already_running"] is False
    assert isinstance(body["started_ms"], int)

    # The request already answered, but the run is still blocked on `hold`:
    # proof that the trigger did not wait for the import to finish.
    await _wait_started(provider)
    statuses = await _status_by_name(client)
    assert statuses["mictronics"]["status"] == "running"

    hold.set()
    await app.state.metadata_update_task

    statuses = await _status_by_name(client)
    assert statuses["mictronics"]["status"] == "ok"
    assert statuses["mictronics"]["dataset_version"] == "mict-1"
    assert statuses["mictronics"]["row_count"] == 1
    assert statuses["mictronics"]["last_success_ms"] is not None
    assert statuses["mictronics"]["last_error"] is None


async def test_concurrent_trigger_coalesces_onto_the_running_run(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    hold = asyncio.Event()
    provider = InMemoryMetadataProvider([RECORD_A], hold=hold)
    registry.register("mictronics", provider)

    first = await client.post(METADATA_UPDATE_PATH)
    assert first.status_code == 202
    first_body = first.json()
    assert first_body["started"] is True

    await _wait_started(provider)

    second = await client.post(METADATA_UPDATE_PATH)

    assert second.status_code == 202
    second_body = second.json()
    assert second_body["started"] is False
    assert second_body["already_running"] is True
    assert second_body["started_ms"] == first_body["started_ms"]
    # The coalesced trigger did not start a second import of the same source.
    assert provider.downloads == 1

    hold.set()
    await app.state.metadata_update_task
    assert provider.downloads == 1


async def test_a_second_trigger_after_completion_starts_a_new_run(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    provider = InMemoryMetadataProvider([RECORD_A])
    registry.register("mictronics", provider)

    first = await client.post(METADATA_UPDATE_PATH)
    await app.state.metadata_update_task
    assert first.json()["started"] is True

    second = await client.post(METADATA_UPDATE_PATH)

    assert second.json()["started"] is True
    assert second.json()["already_running"] is False
    await app.state.metadata_update_task
    assert provider.downloads == 2


# ---------------------------------------------------------------- GET /status


async def test_status_reports_never_run_for_a_fresh_source(
    client: AsyncClient, registry: SourceRegistry
) -> None:
    registry.register("mictronics", InMemoryMetadataProvider([RECORD_A]))

    statuses = await _status_by_name(client)

    assert statuses["mictronics"] == {
        "name": "mictronics",
        "status": "never-run",
        "last_success_ms": None,
        "dataset_version": None,
        "row_count": None,
        "last_error": None,
    }


async def test_one_source_failing_does_not_affect_the_others_status(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    """SPEC §27 independence, at the API layer: each source's own outcome."""
    registry.register("mictronics", InMemoryMetadataProvider([RECORD_A], version="mict-1"))
    # An empty snapshot: the importer rejects it at STAGING ("produced no
    # usable rows"), which is a source failing on its own — no injected fault
    # needed to exercise the independence guarantee at this layer.
    registry.register("faa", InMemoryMetadataProvider([]))

    response = await client.post(METADATA_UPDATE_PATH)
    assert response.status_code == 202
    await app.state.metadata_update_task

    statuses = await _status_by_name(client)

    assert statuses["mictronics"]["status"] == "ok"
    assert statuses["mictronics"]["dataset_version"] == "mict-1"
    assert statuses["mictronics"]["row_count"] == 1
    assert statuses["mictronics"]["last_error"] is None

    assert statuses["faa"]["status"] == "failed"
    assert statuses["faa"]["last_success_ms"] is None
    assert statuses["faa"]["dataset_version"] is None
    assert statuses["faa"]["last_error"] is not None


async def test_a_later_failure_leaves_an_earlier_success_reported_intact(
    app: FastAPI, client: AsyncClient, registry: SourceRegistry
) -> None:
    provider = InMemoryMetadataProvider([RECORD_A], version="mict-1")
    registry.register("mictronics", provider)

    await client.post(METADATA_UPDATE_PATH)
    await app.state.metadata_update_task

    provider.fail_at = ImportPhase.DOWNLOAD
    await client.post(METADATA_UPDATE_PATH)
    await app.state.metadata_update_task

    statuses = await _status_by_name(client)
    assert statuses["mictronics"]["status"] == "failed"
    # The previous dataset's facts (SPEC §27's "leaves the previous working
    # dataset intact") still describe what is actually installed.
    assert statuses["mictronics"]["dataset_version"] == "mict-1"
    assert statuses["mictronics"]["row_count"] == 1
    assert statuses["mictronics"]["last_error"] is not None


async def test_status_is_not_in_the_published_openapi_schema(client: AsyncClient) -> None:
    schema = (await client.get("/api/v1/openapi.json")).json()

    assert not any("metadata" in path for path in schema["paths"])


async def test_shutdown_cancels_an_in_flight_update_task(isolated_data_dir: Path) -> None:
    """A run outlives its request; shutdown must not abandon it mid-write."""
    registry = SourceRegistry()
    provider = InMemoryMetadataProvider([RECORD_A], hold=asyncio.Event())
    registry.register("mictronics", provider)

    application = create_app(isolated_data_dir)
    application.state.metadata = MetadataService(
        database=application.state.database,
        live=LiveStore(clock=lambda: 0.0),
        data_dir=isolated_data_dir,
        registry=registry,
    )

    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://testserver"
        ) as async_client:
            response = await async_client.post(METADATA_UPDATE_PATH)
            assert response.status_code == 202
            await _wait_started(provider)
        task = application.state.metadata_update_task

    assert task is not None
    assert task.cancelled()


# ------------------------------------------------- _log_update_task_result


async def _never() -> ImportRun:
    await asyncio.sleep(10)
    raise AssertionError("unreachable: cancelled before this returns")


async def test_log_update_task_result_ignores_a_cancelled_task() -> None:
    task: asyncio.Task[ImportRun] = asyncio.create_task(_never())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    _log_update_task_result(task)  # must not raise


async def test_log_update_task_result_logs_an_unretrieved_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(level="INFO")

    async def _boom() -> ImportRun:
        raise RuntimeError("cache invalidation exploded")

    task: asyncio.Task[ImportRun] = asyncio.create_task(_boom())
    with pytest.raises(RuntimeError):
        await task

    _log_update_task_result(task)

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "metadata_update_task_failed" in output
    assert "cache invalidation exploded" in output
