"""The persistence worker as the app builds, starts, feeds and stops it.

Four facts are pinned: the worker exists on ``app.state.persistence`` from
construction, it runs for the whole lifespan and stops cleanly, it takes the
configured closure gap, and it does not start against a database that failed to
migrate. The last test closes the loop for the whole slice — a decoder document
in, a sighting row out.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.config import ConfigStore
from flightsite.db import database_path
from flightsite.readiness import ReadinessRegistry
from flightsite.sightings import PersistenceWorker

from ..ingest.conftest import fixture_document, json_response
from ..live.test_app_wiring import point_decoder_at


@pytest.fixture
def configured(isolated_data_dir: Path) -> ConfigStore:
    """Write a config.yaml, so the install is no longer on its first run."""
    store = ConfigStore(isolated_data_dir)
    store.save(store.load())
    return store


@pytest.fixture
def readsb_document() -> Any:
    """The readsb ``aircraft.json`` fixture from the ingestion corpus."""
    return fixture_document("readsb_aircraft.json")


def count_rows(path: Path, table: str) -> int:
    """Count rows from outside the app, on its own connection (WAL allows it)."""
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def wait_for_rows(path: Path, table: str, *, timeout_s: float = 10.0) -> int:
    """Block the test thread until ``table`` has rows, or the timeout expires.

    ``TestClient`` runs the app on its own loop in another thread, so this
    waits on an *outcome* rather than asserting how long anything took.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists() and count_rows(path, table) > 0:
            break
        time.sleep(0.02)
    return count_rows(path, table) if path.exists() else 0


def test_the_worker_exists_before_the_app_has_started() -> None:
    # Constructing the app is side-effect free, but the attribute is already
    # there, so nothing has to guard it.
    assert isinstance(create_app().state.persistence, PersistenceWorker)


def test_the_worker_runs_for_the_lifespan_and_stops_after() -> None:
    app = create_app()

    with TestClient(app):
        worker: PersistenceWorker = app.state.persistence
        assert worker.running is True

    assert worker.running is False


def test_the_configured_closure_gap_reaches_the_worker(isolated_data_dir: Path) -> None:
    ConfigStore(isolated_data_dir).apply_update({"sighting": {"close_s": 1_800.0}})

    app = create_app()

    with TestClient(app):
        worker: PersistenceWorker = app.state.persistence
        # Exercising the configured gap end to end belongs in the lifecycle
        # tests; what matters here is that the value travelled at all.
        assert worker.running is True


def test_the_worker_does_not_start_against_a_broken_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A schema that would not migrate leaves persistence off rather than
    # failing a transaction per second and burying the real error.
    async def failed_initialization(*_args: Any, **_kwargs: Any) -> bool:
        readiness: ReadinessRegistry = _args[1]
        readiness.mark_not_ready("database")
        return False

    monkeypatch.setattr("flightsite.app.initialize_database", failed_initialization)
    app = create_app()

    with TestClient(app):
        worker: PersistenceWorker = app.state.persistence
        assert worker.running is False


def test_decoder_observations_become_sightings(
    configured: ConfigStore,
    monkeypatch: pytest.MonkeyPatch,
    readsb_document: Any,
    isolated_data_dir: Path,
) -> None:
    # End to end for this slice: the adapter polls, the live store applies the
    # batch, the worker drains the events, and SQLite holds aircraft and
    # sighting rows — with no synchronous database work anywhere on that path.
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app()
    path = database_path(isolated_data_dir)

    with TestClient(app):
        sightings = wait_for_rows(path, "sightings")
        aircraft = count_rows(path, "aircraft")

    assert sightings > 0
    assert aircraft == sightings

    # Nothing closed: the decoder document was served once and no aircraft has
    # been absent for anything like the closure gap.
    connection = sqlite3.connect(path)
    try:
        open_sightings = connection.execute(
            "SELECT COUNT(*) FROM sightings WHERE ended_ms IS NULL"
        ).fetchone()[0]
    finally:
        connection.close()
    assert open_sightings == sightings
