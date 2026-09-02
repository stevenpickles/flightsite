"""Ingestion starting on the config save that ends the first-run state.

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
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.ingest import Position
from flightsite.ingest.service import READINESS_SUBSYSTEM, IngestionService
from flightsite.live import LiveStore

from .conftest import CountingClientFactory, ScriptedTransport, json_response

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
