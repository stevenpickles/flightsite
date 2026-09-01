"""The activity service's place in the application lifespan.

Tested against the real app rather than a service built by hand, because what
these claims are about is the *wiring*: which seams are attached, in which
order things start and stop, and what a failed migration or a first run does to
any of it.

Three of them are the subtle ones and get their own tests. The service is
stopped *after* the persistence worker, so its final pass sees the sightings
that worker's shutdown closed. Readiness is untouched, because a feed is
history and a receiver serving the live picture must never be reported unready
because a milestone is late. And a first-run install with no decoder gets a
health probe that answers ``None`` rather than one that reports an outage.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flightsite.activity import ActivityService
from flightsite.app import create_app
from flightsite.db import Database
from flightsite.metadata import MetadataService
from flightsite.sightings import PersistenceWorker


def test_the_service_is_constructed_without_touching_anything(
    isolated_data_dir: Path,
) -> None:
    """Building an app subscribes to nothing and opens no connection."""
    app = create_app(isolated_data_dir)

    service: ActivityService = app.state.activity
    assert isinstance(service, ActivityService)
    assert service.running is False
    assert service.watermark == 0
    assert service.milestones == frozenset()


def test_the_service_runs_across_the_lifespan(isolated_data_dir: Path) -> None:
    """Started on a healthy schema, stopped before the engines close."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert app.state.activity.running is True

    assert app.state.activity.running is False


def test_the_service_is_attached_to_the_persistence_worker_s_seam(
    isolated_data_dir: Path,
) -> None:
    """Closes are only findable here, so this subscription is not decoration."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        client.get("/api/v1/health")
        worker = app.state.persistence
        service: ActivityService = app.state.activity
        assert service.record_lifecycle in worker._lifecycle_listeners

    assert service.record_lifecycle not in worker._lifecycle_listeners


def test_the_service_is_attached_to_the_post_import_seam(isolated_data_dir: Path) -> None:
    """SPEC §27's per-source outcomes reach the feed through the same listener
    list slice 027's airport index rebuild uses — one seam, two consumers.
    """
    app = create_app(isolated_data_dir)

    metadata: MetadataService = app.state.metadata
    assert len(metadata._listeners) == 2


def test_new_events_are_published_onto_the_websocket(isolated_data_dir: Path) -> None:
    """The §4.4 frame's source. Without this subscription the feed is REST-only."""
    app = create_app(isolated_data_dir)

    service: ActivityService = app.state.activity
    assert len(service._listeners) == 1


def test_readiness_is_untouched_by_the_activity_service(isolated_data_dir: Path) -> None:
    """A feed is history, not a dependency: it cannot gate ``/ready``."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        ready = client.get("/api/v1/ready")

    assert ready.status_code == 200
    # The exact set, not a "not in": a new subsystem appearing here would be a
    # new way for the backend to report itself unready, and this slice adds none.
    assert ready.json() == {"ready": True, "subsystems": {"database": True}}


def test_a_first_run_install_has_no_decoder_to_report_on(isolated_data_dir: Path) -> None:
    """No ``config.yaml`` means ingestion never starts, so the probe answers ``None``.

    That is a different fact from "the decoder is down", and the feed has to
    tell them apart: an install nobody has configured yet has no outage to
    announce.
    """
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        client.get("/api/v1/health")
        service: ActivityService = app.state.activity
        probe = service._health
        assert probe is not None
        assert probe() is None


def test_the_service_stops_after_the_persistence_worker(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its final pass has to see the sightings that worker's shutdown closed.

    Asserted by recording the order the two ``stop`` coroutines actually run in
    during the lifespan's teardown, rather than by reading the source — the
    ordering is a comment in ``app.py`` and comments do not fail.
    """
    app = create_app(isolated_data_dir)
    order: list[str] = []
    worker_stop = PersistenceWorker.stop
    activity_stop = ActivityService.stop

    async def record_worker(worker: PersistenceWorker) -> None:
        order.append("persistence")
        await worker_stop(worker)

    async def record_activity(service: ActivityService) -> None:
        order.append("activity")
        await activity_stop(service)

    monkeypatch.setattr(PersistenceWorker, "stop", record_worker)
    monkeypatch.setattr(ActivityService, "stop", record_activity)

    with TestClient(app) as client:
        client.get("/api/v1/health")

    assert order == ["persistence", "activity"]


def test_the_feed_endpoint_answers_on_a_fresh_install(isolated_data_dir: Path) -> None:
    """The whole path, end to end: migration, service, repository, endpoint."""
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        response = client.get("/api/v1/activity")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": None, "limit": 50, "offset": 0}


async def test_a_second_boot_over_the_same_data_directory_repeats_nothing(
    isolated_data_dir: Path,
) -> None:
    """Two successive boots leave the feed exactly as the first one left it."""
    first = create_app(isolated_data_dir)
    with TestClient(first) as client:
        client.get("/api/v1/health")

    second = create_app(isolated_data_dir)
    with TestClient(second) as client:
        assert client.get("/api/v1/activity").json()["items"] == []
        assert second.state.activity.running is True

    reopened = Database(second.state.database.path)
    try:
        assert await ActivityService(database=reopened).repository.list_events(limit=10) == ()
    finally:
        await reopened.dispose()
