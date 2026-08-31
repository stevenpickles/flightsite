"""Startup: migrate, integrity-check, readiness — and how failures are surfaced.

The slice-005 acceptance criterion is that a startup integrity failure is
"surfaced, not silently ignored". Concretely, for every failure mode: a
structured error log an operator can actually find, a ``db_errors`` increment,
the ``database`` subsystem left not-ready so ``/api/v1/ready`` answers 503 —
and a process that is still up and answering ``/api/v1/health``.

Log assertions read the JSON lines the process emits rather than pytest's
``caplog``, because the JSON line is what an operator (and, from slice 042, the
diagnostics surface) actually sees.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.counters import CounterRegistry
from flightsite.db import Database, MetaRepository, database_path, initialize_database
from flightsite.db.startup import DATABASE_SUBSYSTEM
from flightsite.logging import configure_logging
from flightsite.readiness import ReadinessRegistry
from tests.db.harness import table_names

CORRUPTION_BYTE = 0xA5
SQLITE_PAGE_SIZE = 4096
FILLER_ROWS = 400


@pytest.fixture
def readiness() -> ReadinessRegistry:
    registry = ReadinessRegistry()
    registry.register(DATABASE_SUBSYSTEM)
    return registry


@pytest.fixture
def isolated_counters() -> CounterRegistry:
    """A private counter registry — the module-level one is process-global."""
    return CounterRegistry()


def _write_garbage(path: Path) -> None:
    """Replace the database with bytes that are not a SQLite file at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a sqlite database" * 200)


def _smash_data_pages(path: Path) -> None:
    """Overwrite everything after page 2 of an existing database file.

    Page 1 (the schema) and the ``alembic_version`` row stay readable, so the
    migration step still succeeds and it is the integrity check that catches
    the damage — the failure mode this slice exists to surface.
    """
    raw = bytearray(path.read_bytes())
    assert len(raw) > SQLITE_PAGE_SIZE * 4, "fixture database is too small to corrupt"
    for offset in range(SQLITE_PAGE_SIZE * 2, len(raw)):
        raw[offset] = CORRUPTION_BYTE
    path.write_bytes(bytes(raw))


async def _build_then_corrupt(path: Path) -> None:
    """Build a real migrated database with data pages, then corrupt them.

    Disposing the database first checkpoints the WAL into the main file, so the
    bytes being rewritten are the bytes SQLite will later read back.
    """
    database = Database(path)
    meta = MetaRepository(database)
    await database.upgrade_to("head")
    for index in range(FILLER_ROWS):
        await meta.set(f"filler-{index:04d}", "x" * 200)
    await database.dispose()

    _smash_data_pages(path)


def _json_events(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """Parse the structured log lines emitted so far."""
    captured = capsys.readouterr()
    events: list[dict[str, Any]] = []
    for line in (captured.err + captured.out).splitlines():
        if line.startswith("{"):
            events.append(json.loads(line))
    return events


def _events_named(events: Sequence[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event") == name]


async def _initialize(path: Path, readiness: ReadinessRegistry, counters: CounterRegistry) -> bool:
    database = Database(path)
    try:
        return await initialize_database(database, readiness, counters=counters)
    finally:
        await database.dispose()


async def test_successful_startup_marks_the_database_ready(
    db_path: Path,
    readiness: ReadinessRegistry,
    isolated_counters: CounterRegistry,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(level="INFO")

    assert await _initialize(db_path, readiness, isolated_counters) is True

    assert readiness.snapshot()[DATABASE_SUBSYSTEM] is True
    assert readiness.is_ready is False  # startup itself is not complete yet
    assert isolated_counters.snapshot()["db_errors"] == 0
    assert "meta" in table_names(db_path)

    ready_events = _events_named(_json_events(capsys), "database_ready")
    assert ready_events
    assert ready_events[0]["schema_revision"] is not None


async def test_unreadable_database_file_fails_migration_loudly(
    db_path: Path,
    readiness: ReadinessRegistry,
    isolated_counters: CounterRegistry,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(level="INFO")
    _write_garbage(db_path)

    assert await _initialize(db_path, readiness, isolated_counters) is False

    assert readiness.snapshot()[DATABASE_SUBSYSTEM] is False
    assert readiness.is_ready is False
    assert isolated_counters.snapshot()["db_errors"] == 1

    failures = _events_named(_json_events(capsys), "database_migration_failed")
    assert len(failures) == 1
    assert failures[0]["level"] == "error"
    assert failures[0]["db_path"] == str(db_path)
    assert "remediation" in failures[0]


async def test_corrupt_data_pages_fail_the_integrity_check_loudly(
    db_path: Path,
    readiness: ReadinessRegistry,
    isolated_counters: CounterRegistry,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Migration succeeds, ``quick_check`` does not — the intended detection point."""
    await _build_then_corrupt(db_path)
    configure_logging(level="INFO")

    assert await _initialize(db_path, readiness, isolated_counters) is False

    assert readiness.snapshot()[DATABASE_SUBSYSTEM] is False
    assert isolated_counters.snapshot()["db_errors"] == 1

    events = _json_events(capsys)
    integrity_failures = _events_named(events, "database_integrity_check_errored") + _events_named(
        events, "database_integrity_check_failed"
    )
    assert integrity_failures, f"corruption was not reported by the integrity check: {events}"
    assert integrity_failures[0]["db_path"] == str(db_path)
    assert not _events_named(events, "database_ready")


async def test_quick_check_reporting_problems_is_treated_as_failure(
    db_path: Path,
    readiness: ReadinessRegistry,
    isolated_counters: CounterRegistry,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``quick_check`` can *return* problems rather than raise; both must be caught."""
    problems = ["*** in database main ***", "Page 3 is never used"]

    async def failing_quick_check(self: Database) -> Sequence[str]:
        return problems

    monkeypatch.setattr(Database, "quick_check", failing_quick_check)
    configure_logging(level="INFO")

    assert await _initialize(db_path, readiness, isolated_counters) is False

    assert readiness.snapshot()[DATABASE_SUBSYSTEM] is False
    assert isolated_counters.snapshot()["db_errors"] == 1

    failures = _events_named(_json_events(capsys), "database_integrity_check_failed")
    assert len(failures) == 1
    # The quick_check output itself must reach the log, not merely "it failed".
    assert failures[0]["quick_check"] == problems


def test_app_startup_migrates_and_reports_ready(isolated_data_dir: Path) -> None:
    """Fresh start: database created in the data dir, migrated, ready."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        ready = client.get("/api/v1/ready")
        health = client.get("/api/v1/health")

    assert ready.status_code == 200
    assert ready.json()["subsystems"][DATABASE_SUBSYSTEM] is True
    assert health.status_code == 200
    assert database_path(isolated_data_dir).exists()
    assert "meta" in table_names(database_path(isolated_data_dir))


def test_app_stays_up_but_not_ready_when_the_database_is_corrupt(
    isolated_data_dir: Path,
) -> None:
    """The app keeps answering /health; /ready is 503 so an orchestrator sees it."""
    _write_garbage(database_path(isolated_data_dir))
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        ready = client.get("/api/v1/ready")
        health = client.get("/api/v1/health")

    assert ready.status_code == 503
    assert ready.json()["ready"] is False
    assert ready.json()["subsystems"][DATABASE_SUBSYSTEM] is False
    assert health.status_code == 200
    assert health.json()["counters"]["db_errors"] >= 1


def test_fresh_start_leaves_t0_unset(isolated_data_dir: Path) -> None:
    """Fresh start records nothing until the first observation: T0 stays unset."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        assert client.get("/api/v1/ready").status_code == 200

    async def read_t0() -> int | None:
        database = Database(database_path(isolated_data_dir))
        try:
            return await MetaRepository(database).get_t0()
        finally:
            await database.dispose()

    assert asyncio.run(read_t0()) is None
