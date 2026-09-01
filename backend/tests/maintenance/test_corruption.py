"""The corruption drill: a genuinely smashed database, met loudly and survived.

SPEC §70 asks for *useful diagnostics*; the roadmap's acceptance criterion is
that "the corruption drill produces actionable diagnostics; a healthy DB passes
untouched". The database here is corrupted the same way slice 005's startup
drill corrupts one — real bytes overwritten in a real file, with the schema
deliberately spared so it is the integrity check and not the connection that
finds the damage (``tests/db/harness.py``).

Three things must hold at once, and each is a test below: the damage is
reported with enough detail and enough direction to act on; the process keeps
running and keeps cycling; and a healthy database is not touched by any of it.

Log assertions read the JSON lines the process emits rather than ``caplog``,
because the JSON line is what an operator — and, from slice 042, the
diagnostics surface — actually sees.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from flightsite.counters import CounterRegistry
from flightsite.db import Database
from flightsite.logging import configure_logging
from flightsite.maintenance.model import (
    CHECKPOINT_JOB,
    QUICK_CHECK_JOB,
    RETENTION_JOB,
    JobOutcome,
)
from flightsite.maintenance.service import CORRUPTION_REMEDIATION, MaintenanceService
from tests.db.harness import build_then_corrupt
from tests.maintenance.conftest import ManualClock, fixed_stats, make_stats


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


class _WorkingTask:
    """A retention task that cannot fail, so "healthy jobs continue" is testable."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "healthy"

    async def prune(self, *, now_ms: int) -> int:
        self.calls += 1
        return 0


async def test_the_drill_reports_corruption_loudly_and_actionably(
    db_path: Path, clock: ManualClock, counters: CounterRegistry, capsys: pytest.CaptureFixture[str]
) -> None:
    await build_then_corrupt(db_path)
    configure_logging(level="INFO")
    database = Database(db_path)
    service = MaintenanceService(
        database=database, clock=clock, counters=counters, stats=fixed_stats(make_stats())
    )

    try:
        report = await service.run_cycle()
    finally:
        await database.dispose()

    assert report.jobs[QUICK_CHECK_JOB].outcome is JobOutcome.FAILED
    assert counters.snapshot()["db_errors"] >= 1

    failures = _events_named(_json_events(capsys), "maintenance_integrity_check_failed")
    assert failures, "the corruption was not reported"
    assert failures[0]["level"] == "error"
    assert failures[0]["db_path"] == str(db_path)
    # Actionable, not merely loud: the log says what to do about it.
    assert failures[0]["remediation"] == CORRUPTION_REMEDIATION
    assert "restore" in CORRUPTION_REMEDIATION


async def test_the_failed_check_is_retained_for_diagnostics(
    db_path: Path, clock: ManualClock, counters: CounterRegistry
) -> None:
    """On a corrupt database this record is the only description of the damage."""
    await build_then_corrupt(db_path)
    database = Database(db_path)
    service = MaintenanceService(
        database=database, clock=clock, counters=counters, stats=fixed_stats(make_stats())
    )

    try:
        report = await service.run_cycle()
    finally:
        await database.dispose()

    assert report.quick_check is not None
    assert report.quick_check.healthy is False
    assert report.quick_check.checked_ms == clock.now_ms
    # Either shape carries the evidence: rows describing the damage, or the
    # error raised by a file too damaged to answer at all.
    assert report.quick_check.rows or report.quick_check.error
    assert report.healthy is False


async def test_the_service_keeps_running_and_healthy_jobs_continue(
    db_path: Path, clock: ManualClock, counters: CounterRegistry
) -> None:
    """The whole point of the drill: a bad database is not a dead process."""
    await build_then_corrupt(db_path)
    database = Database(db_path)
    task = _WorkingTask()
    service = MaintenanceService(
        database=database,
        retention=[task],
        clock=clock,
        counters=counters,
        stats=fixed_stats(make_stats()),
    )

    try:
        first = await service.run_cycle()
        clock.advance_days(1)
        second = await service.run_cycle()
    finally:
        await database.dispose()

    # The job that does not touch the damaged pages ran, twice, unaffected.
    assert first.jobs[RETENTION_JOB].outcome is JobOutcome.OK
    assert second.jobs[RETENTION_JOB].outcome is JobOutcome.OK
    assert task.calls == 2
    # And the check was attempted again on its own cadence rather than given up on.
    assert second.jobs[QUICK_CHECK_JOB].started_ms == clock.now_ms
    assert second.jobs[QUICK_CHECK_JOB].outcome is JobOutcome.FAILED
    assert second.cycles == 2


async def test_a_healthy_database_passes_the_same_drill_untouched(
    database: Database, clock: ManualClock, counters: CounterRegistry
) -> None:
    """The other half of the criterion: no false alarm, and no rewritten file."""
    configure_logging(level="INFO")
    service = MaintenanceService(
        database=database, clock=clock, counters=counters, stats=fixed_stats(make_stats())
    )
    before = database.path.stat().st_size

    report = await service.run_cycle()

    assert report.healthy is True
    assert report.quick_check is not None
    assert report.quick_check.healthy is True
    assert counters.snapshot()["db_errors"] == 0
    assert report.jobs[CHECKPOINT_JOB].outcome is JobOutcome.SKIPPED
    # Conservative means conservative: nothing rewrote the file.
    assert database.path.stat().st_size == before
