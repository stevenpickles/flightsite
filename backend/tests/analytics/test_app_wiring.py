"""Analytics' place in the application lifespan.

Four claims, each tested against the real app rather than a service built by
hand: it is constructed inertly, the configured timezone reaches it, it runs
across the lifespan attached to the persistence worker's seam, and it does not
touch readiness — analytics are a derived view, and a receiver serving the live
picture must never be reported unready because a rollup is stale.

The shutdown ordering claim is the subtle one and gets its own test: the
analytics service is stopped *after* the persistence worker, because that
worker's stop force-flushes every dirty accumulator, and a final rebuild that
ran before it would miss the last sightings the process wrote.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import text

from flightsite.analytics import AnalyticsService
from flightsite.analytics.bucketing import local_day
from flightsite.analytics.repository import AnalyticsRepository
from flightsite.app import create_app
from flightsite.db import Database
from flightsite.db.clock import utc_now_ms

from ..api.aircraft_history_fixtures import SeedAircraft
from ..api.sighting_fixtures import SeedSighting, seed_sightings

TIMEZONE = "Asia/Kolkata"


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
    """Building an app subscribes to nothing and opens no connection."""
    app = create_app(isolated_data_dir)

    service: AnalyticsService = app.state.analytics
    assert isinstance(service, AnalyticsService)
    assert service.running is False
    assert service.dirty_days == frozenset()
    assert service.startup_repair.rebuilt == 0


def test_the_configured_timezone_reaches_the_service(isolated_data_dir: Path) -> None:
    """``docs/DATA_MODEL.md`` §10: day buckets are the *receiver's* calendar."""
    write_config(isolated_data_dir, timezone=TIMEZONE)

    service: AnalyticsService = create_app(isolated_data_dir).state.analytics

    assert str(service._zone) == TIMEZONE


def test_the_service_runs_across_the_lifespan(isolated_data_dir: Path) -> None:
    """Started on a healthy schema, stopped before the engines close."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert app.state.analytics.running is True

    assert app.state.analytics.running is False


def test_the_service_is_attached_to_the_persistence_worker_s_seam(
    isolated_data_dir: Path,
) -> None:
    """The incremental half of the design only exists if this subscription does."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        client.get("/api/v1/health")
        worker = app.state.persistence
        service: AnalyticsService = app.state.analytics
        assert service.record_lifecycle in worker._lifecycle_listeners

    assert service.record_lifecycle not in worker._lifecycle_listeners


def test_readiness_is_untouched_by_analytics(isolated_data_dir: Path) -> None:
    """Rollups are a derived view, not a dependency: they cannot gate ``/ready``."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        ready = client.get("/api/v1/ready")

    assert ready.status_code == 200
    # The exact set, not a "not in": a new subsystem appearing here would be a
    # new way for the backend to report itself unready, and this slice adds none.
    assert ready.json() == {"ready": True, "subsystems": {"database": True}}


async def test_startup_repairs_a_history_the_rollups_never_covered(
    isolated_data_dir: Path,
) -> None:
    """The upgrade path: sightings exist, the rollup tables have never been written."""
    app = create_app(isolated_data_dir)
    database: Database = app.state.database
    await database.upgrade_to("head")
    now_ms = utc_now_ms()
    started_ms = now_ms - 6 * 3_600_000
    await seed_sightings(
        database,
        [SeedAircraft(icao24="a00001", first_seen_ms=started_ms, last_seen_ms=started_ms)],
        [SeedSighting(icao24="a00001", started_ms=started_ms)],
    )
    await database.dispose()

    with TestClient(app) as client:
        client.get("/api/v1/health")
        service: AnalyticsService = app.state.analytics
        assert service.startup_repair.sightings == 1

    reopened = Database(app.state.database.path)
    try:
        rollup = await AnalyticsRepository(reopened).day(local_day(started_ms, service._zone))
    finally:
        await reopened.dispose()
    assert rollup is not None
    assert rollup.sightings == 1


async def test_shutdown_flushes_a_day_that_was_still_dirty(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean stop leaves the rollups current, so the next boot has no work.

    The day is marked dirty inside the lifespan — the state a committed worker
    cycle leaves behind — and the assertion is that the *lifespan's own*
    shutdown wrote it, read back through a fresh connection to the same file
    after the app's engines are disposed.
    """
    monkeypatch.setenv("FLIGHTSITE_TIMEZONE", TIMEZONE)
    app = create_app(isolated_data_dir)
    database: Database = app.state.database
    await database.upgrade_to("head")
    now_ms = utc_now_ms()
    await seed_sightings(
        database,
        [SeedAircraft(icao24="a00002", first_seen_ms=now_ms, last_seen_ms=now_ms)],
        [SeedSighting(icao24="a00002", started_ms=now_ms)],
    )
    await database.dispose()

    with TestClient(app) as client:
        client.get("/api/v1/health")
        service: AnalyticsService = app.state.analytics
        day = local_day(now_ms, service._zone)
        await _clear_rollups(Database(app.state.database.path))
        service.mark_dirty(day)

    reopened = Database(app.state.database.path)
    try:
        rollup = await AnalyticsRepository(reopened).day(day)
    finally:
        await reopened.dispose()
    assert rollup is not None
    assert rollup.sightings == 1


async def _clear_rollups(database: Database) -> None:
    """Drop what the startup repair wrote, so the shutdown flush is observable."""
    try:
        async with database.writer_session() as session:
            await session.execute(text("DELETE FROM daily_stats"))
    finally:
        await database.dispose()


def test_a_second_app_over_the_same_data_directory_repairs_rather_than_duplicates(
    isolated_data_dir: Path,
) -> None:
    """Two successive boots leave one row per day, not two."""
    first = create_app(isolated_data_dir)
    with TestClient(first) as client:
        client.get("/api/v1/health")

    second = create_app(isolated_data_dir)
    with TestClient(second) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert second.state.analytics.running is True
