"""Decoder polling starting on the config save that ends the first-run state.

The defect this pins (issue #122): a fresh install starts no ingestion — it
has no configuration, so there is no receiver to poll — and *nothing ever
started it afterwards*. ``app.state.ingestion`` stayed ``None`` for the life
of the process, so a user who completed the setup wizard watched an empty map
until they restarted the backend. ``docs/INSTALL.md`` documented the restart
as a known limitation rather than a bug, which is exactly how a wart survives.

What is pinned here is deliberately narrow: **nothing → running**, on the save
that first configures the install. Changing the endpoint of an adapter that is
*already* running stays restart-required, and
:func:`test_a_second_save_constructs_no_second_service` is the test that keeps
it that way — it is the difference between "start what is not running" and
"reconfigure what is", and only the first is safe to do under a live map.

The receiver-metrics service reads the same decoder, through its own
``stats.json`` poller, and was built empty on a first run for the same reason.
Issue #129 is that half: after slice 056 the map filled but the
decoder-supplied metric columns stayed ``NULL`` until the backend was
restarted. The tests under *"the statistics poller"* below pin the same
nothing → running property for it.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flightsite.api.internal import _apply_ingestion_start
from flightsite.app import create_app
from flightsite.config import ConfigStore
from flightsite.ingest import DecoderEndpoint, Position
from flightsite.ingest import build_ingestion_service as real_build
from flightsite.ingest.service import READINESS_SUBSYSTEM, IngestionService
from flightsite.live import LiveStore
from flightsite.receiver_metrics import (
    ReceiverMetricsService,
    StatsJsonPoller,
    stats_url_for,
)

from .conftest import CountingClientFactory, ScriptedTransport, json_response

#: The real implementations, captured before any test monkeypatches them.
real_start = IngestionService.start

#: The document a first-run setup wizard save sends: a receiver endpoint and a
#: location, which between them are everything ingestion needs to start.
FIRST_RUN_SAVE: dict[str, Any] = {
    "location": {"latitude": 51.5, "longitude": -0.12, "site_name": "London"},
    "receiver": {
        "host": "decoder.test",
        "port": 8080,
        "path": "/data/aircraft.json",
        "poll_interval_s": 0.05,
    },
}


def point_decoder_at(
    monkeypatch: pytest.MonkeyPatch, entry: httpx.Response | Exception
) -> CountingClientFactory:
    """Make every adapter client the app builds talk to a mock transport."""
    factory = CountingClientFactory(ScriptedTransport([entry]))
    monkeypatch.setattr(
        "flightsite.ingest.readsb.build_client", lambda *_args, **_kwargs: factory()
    )
    return factory


def wait_for_aircraft(live: LiveStore, *, timeout_s: float = 5.0) -> int:
    """Block the test thread until the store fills, or the timeout expires.

    ``TestClient`` runs the app on its own event loop in another thread, so a
    blocking wait here is what lets the ingestion poll actually happen. This
    waits on an *outcome* and never asserts how long anything took, so it
    cannot flake into a false pass or a timing-dependent failure.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if len(live) > 0:
            break
        time.sleep(0.01)
    return len(live)


def emitted_events(output: str) -> list[dict[str, Any]]:
    """Every structured log line the app printed, decoded.

    Read from the process's own output rather than through ``caplog``, because
    :func:`~flightsite.logging.configure_logging` runs inside ``create_app``
    and would reconfigure structlog out from under a fixture that had already
    redirected it. The JSON line is also what an operator actually sees.
    """
    events = []
    for line in output.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue  # interleaved non-JSON output, e.g. a traceback
    return events


def test_a_first_run_save_starts_ingestion_and_aircraft_flow(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """The whole point of the slice: finish the wizard, see aircraft."""
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        assert app.state.ingestion is None

        response = client.put("/api/internal/config", json=FIRST_RUN_SAVE)

        assert response.status_code == 200
        assert response.json()["first_run"] is False

        service: IngestionService | None = app.state.ingestion
        assert service is not None
        assert service.running is True
        assert wait_for_aircraft(app.state.live) > 0


def test_the_hot_start_polls_the_endpoint_that_was_just_saved(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """Hot-start and the next boot must not be two ways to decide what to poll.

    The endpoint comes from the settings the save installed, so a request
    actually reaches the host the wizard collected — not the model default the
    app booted with.
    """
    factory = point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        client.put("/api/internal/config", json=FIRST_RUN_SAVE)
        wait_for_aircraft(app.state.live)

    transport = factory.handler
    assert isinstance(transport, ScriptedTransport)
    assert transport.requests, "the hot-started adapter never polled"
    assert transport.requests[0].url.host == "decoder.test"
    assert transport.requests[0].url.path == "/data/aircraft.json"


def test_a_second_save_constructs_no_second_service(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """Endpoint *changes* stay restart-required, so a later save must leave the
    running service — its adapter, its task, its readiness registration —
    exactly where it is, not build a second one beside it."""
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        client.put("/api/internal/config", json=FIRST_RUN_SAVE)
        started: IngestionService | None = app.state.ingestion

        moved = {"receiver": {**FIRST_RUN_SAVE["receiver"], "host": "other.test"}}
        response = client.put("/api/internal/config", json=moved)

        assert response.status_code == 200
        # Identity, not equality: a second service would be a second adapter
        # polling in parallel with the first.
        assert app.state.ingestion is started
        assert app.state.settings.receiver.host == "other.test"


async def test_two_saves_arriving_together_start_one_service(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """A double-clicked Finish button must not start two adapters.

    Both requests observe "nothing running" unless the claim on
    ``app.state.ingestion`` is made in the same synchronous block as the check
    — assigning after ``start()`` leaves a window across the adapter's own
    startup, and two adapters polling the same decoder into the same live
    store is the kind of thing that is only ever noticed in production.

    ``start()`` is given a suspension point deliberately. Today's readsb
    adapter happens to reach its first ``await`` without yielding, which hides
    the race rather than removing it; this pins the ordering that stays
    correct when that stops being true.
    """
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app(isolated_data_dir)

    built: list[IngestionService] = []

    def counting_build(*args: Any, **kwargs: Any) -> IngestionService:
        service = real_build(*args, **kwargs)
        built.append(service)
        return service

    async def suspending_start(service: IngestionService) -> None:
        await asyncio.sleep(0)
        await real_start(service)

    monkeypatch.setattr("flightsite.api.ingestion.build_ingestion_service", counting_build)
    monkeypatch.setattr(IngestionService, "start", suspending_start)

    async with app.router.lifespan_context(app):
        assert app.state.ingestion is None
        # End the first-run state the way the endpoint does, then run the
        # apply step twice concurrently — which is what two overlapping
        # requests reach.
        store: ConfigStore = app.state.config_store
        app.state.settings = store.apply_update(FIRST_RUN_SAVE)

        await asyncio.gather(_apply_ingestion_start(app), _apply_ingestion_start(app))

        assert len(built) == 1
        assert app.state.ingestion is built[0]


def test_a_failed_hot_start_still_saves_the_configuration(
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The configuration is validated, written and live before ingestion is
    touched, so a failure starting it can only turn a save that succeeded into
    a 500 about it. Same rule as the alerts entry beside it."""
    monkeypatch.setattr(
        "flightsite.api.ingestion.build_ingestion_service",
        _raising("decoder went up in smoke"),
    )
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        response = client.put("/api/internal/config", json=FIRST_RUN_SAVE)

        assert response.status_code == 200
        assert response.json()["first_run"] is False
        assert app.state.ingestion is None
        # And the save that failed to start it is still on disk.
        assert app.state.settings.receiver.host == "decoder.test"

    captured = capsys.readouterr()
    failures = [
        event
        for event in emitted_events(captured.out + captured.err)
        if event.get("event") == "config_apply_failed"
    ]
    assert failures, "a swallowed failure must still be reported"
    assert failures[0]["action"] == "start_ingestion"
    assert failures[0]["error_type"] == "RuntimeError"
    # The reason is reported without echoing the configuration that provoked it.
    assert "decoder.test" not in json.dumps(failures[0])


def test_ingestion_can_still_start_on_a_later_save_after_a_failure(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """A failed hot-start leaves ``app.state.ingestion`` unassigned rather than
    poisoned, so the guard lets the next save try again."""
    monkeypatch.setattr(
        "flightsite.api.ingestion.build_ingestion_service", _raising("not this time")
    )
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        client.put("/api/internal/config", json=FIRST_RUN_SAVE)
        assert app.state.ingestion is None

        monkeypatch.undo()
        point_decoder_at(monkeypatch, json_response(readsb_document))
        client.put("/api/internal/config", json=FIRST_RUN_SAVE)

        service: IngestionService | None = app.state.ingestion
        assert service is not None
        assert service.running is True


def test_ready_stays_ready_across_the_mid_life_registration(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """``IngestionService.start`` registers its readiness subsystem, and on this
    path that happens after ``mark_startup_complete()``.

    ``register`` seeds a subsystem *not*-ready, so the question is whether
    ``/ready`` can be observed in the window between registering and marking
    ready. It cannot: the two calls run in one synchronous block with no
    ``await`` between them and the handler is a coroutine on the same loop.
    This pins the outcome — a first-run install answers 200 before the save,
    200 after it, and reports the new subsystem once it is there.
    """
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        before = client.get("/api/v1/ready")
        assert before.status_code == 200
        assert before.json()["subsystems"] == {"database": True}

        client.put("/api/internal/config", json=FIRST_RUN_SAVE)

        after = client.get("/api/v1/ready")
        assert after.status_code == 200
        assert after.json()["ready"] is True
        assert after.json()["subsystems"] == {"database": True, READINESS_SUBSYSTEM: True}


def test_the_saved_location_anchors_the_live_store(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """Starting ingestion without this would fill the map with aircraft whose
    distance and bearing are ``null``: the store is built with the location
    that was effective at construction, and on a first run there is none."""
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        live: LiveStore = app.state.live
        assert live.receiver_location is None

        client.put("/api/internal/config", json=FIRST_RUN_SAVE)

        assert live.receiver_location == Position(latitude=51.5, longitude=-0.12)


def test_a_save_never_moves_a_location_the_store_already_has(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """Filling in a blank is not the same as changing a value.

    Moving the anchor under a running store would leave every already-observed
    aircraft carrying a distance measured from somewhere else until it is seen
    again, which is why a location *change* is restart-required and says so on
    its Settings badge. Only the first-run blank is filled here.
    """
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        client.put("/api/internal/config", json=FIRST_RUN_SAVE)
        live: LiveStore = app.state.live
        assert live.receiver_location == Position(latitude=51.5, longitude=-0.12)

        client.put(
            "/api/internal/config",
            json={"location": {"latitude": -33.86, "longitude": 151.2, "site_name": "Sydney"}},
        )

        assert live.receiver_location == Position(latitude=51.5, longitude=-0.12)
        assert app.state.settings.location.latitude == -33.86


# ------------------------------------------------ the statistics poller (#129)


def stats_poller_of(app: FastAPI) -> StatsJsonPoller | None:
    """The receiver-metrics service's poller, or ``None`` if it has none."""
    metrics: ReceiverMetricsService = app.state.receiver_metrics
    return metrics._poller


def test_a_first_run_save_attaches_the_statistics_poller(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """The other half of the same first-run story (issue #129).

    Without this the metrics service kept the ``poller=None`` it was built
    with for the life of the process, so a fresh install recorded every
    FlightSite-computed metric and left messages, positions, RSSI and decoder
    uptime ``NULL`` until someone restarted the backend.
    """
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        assert stats_poller_of(app) is None
        assert app.state.receiver_metrics.running is True

        client.put("/api/internal/config", json=FIRST_RUN_SAVE)

        poller = stats_poller_of(app)
        assert poller is not None
        # Derived from the endpoint the save wrote, not from the model default
        # the app booted with.
        assert poller.url == stats_url_for(
            DecoderEndpoint(host="decoder.test", port=8080, path="/data/aircraft.json")
        )
        # Opened rather than merely held: the sampling loop is already ticking.
        assert poller._client is not None


def test_a_second_save_leaves_the_attached_poller_alone(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    """Repointing a *running* poller is restart-required, exactly as
    repointing the ingestion adapter beside it is."""
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        client.put("/api/internal/config", json=FIRST_RUN_SAVE)
        attached = stats_poller_of(app)

        moved = {"receiver": {**FIRST_RUN_SAVE["receiver"], "host": "other.test"}}
        client.put("/api/internal/config", json=moved)

        assert stats_poller_of(app) is attached


def test_demo_mode_attaches_no_statistics_poller(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demo mode has no decoder to ask, and a config save must not invent one
    (SPEC §76) — the same guard that keeps its simulated traffic."""
    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        response = client.put("/api/internal/config", json=FIRST_RUN_SAVE)

        assert response.status_code == 200
        assert stats_poller_of(app) is None


def test_demo_mode_keeps_its_own_ingestion(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config save must not swap simulated traffic for a real decoder poll
    under a user who asked for demo mode (SPEC §76)."""
    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")
    app = create_app(isolated_data_dir)

    with TestClient(app) as client:
        demo_service: IngestionService | None = app.state.ingestion
        assert demo_service is not None

        response = client.put("/api/internal/config", json=FIRST_RUN_SAVE)

        assert response.status_code == 200
        assert app.state.ingestion is demo_service


def _raising(message: str) -> Any:
    """A stand-in that fails the way a broken hot-start would."""

    def fail(*_args: Any, **_kwargs: Any) -> IngestionService:
        raise RuntimeError(message)

    return fail
