"""The live store as the app builds, starts, feeds and stops it.

Three facts are pinned: the store exists on ``app.state.live`` from the moment
the app is constructed (so a handler never has to guard the attribute), the
lifecycle sweep runs whether or not a decoder is configured, and decoder
batches land in the store rather than in the null sink.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from flightsite.app import create_app
from flightsite.config import ConfigStore
from flightsite.ingest import Position
from flightsite.live import LiveStore

from ..ingest.conftest import (
    CountingClientFactory,
    ScriptedTransport,
    fixture_document,
    json_response,
)


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
    blocking wait here lets the ingestion poll actually happen. This waits on
    an *outcome*, never asserting how long anything took, so it cannot flake
    into a false pass or a timing-dependent failure.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if len(live) > 0:
            break
        time.sleep(0.01)
    return len(live)


def test_a_first_run_install_still_has_a_live_store() -> None:
    app = create_app()

    with TestClient(app):
        live: LiveStore = app.state.live

        assert live.sweeping is True
        assert len(live) == 0
        assert live.receiver_location is None


def test_the_store_exists_before_the_app_has_started() -> None:
    # Constructing the app is side-effect free, but `app.state.live` is already
    # there, so request handlers never have to guard the attribute.
    assert isinstance(create_app().state.live, LiveStore)


def test_shutdown_stops_the_lifecycle_sweep() -> None:
    app = create_app()

    with TestClient(app):
        live: LiveStore = app.state.live

    assert live.sweeping is False


def test_the_configured_receiver_location_reaches_the_store(isolated_data_dir: Path) -> None:
    ConfigStore(isolated_data_dir).apply_update(
        {"location": {"latitude": 47.4502, "longitude": -122.3088}}
    )

    live: LiveStore = create_app().state.live

    assert live.receiver_location == Position(latitude=47.4502, longitude=-122.3088)


def test_the_configured_lifecycle_timings_reach_the_store(isolated_data_dir: Path) -> None:
    ConfigStore(isolated_data_dir).apply_update({"sighting": {"stale_s": 20.0, "remove_s": 90.0}})

    live: LiveStore = create_app().state.live

    assert live.stale_s == 20.0
    assert live.remove_s == 90.0


def test_decoder_batches_land_in_the_live_store(
    configured: ConfigStore, monkeypatch: pytest.MonkeyPatch, readsb_document: Any
) -> None:
    # End to end for this slice: the adapter polls, the service dispatches, and
    # the live registry — not a null sink — holds the result.
    point_decoder_at(monkeypatch, json_response(readsb_document))
    app = create_app()

    with TestClient(app):
        live: LiveStore = app.state.live
        wait_for_aircraft(live)
        counts = live.counts()

    assert counts.total > 0
    assert counts.positioned > 0
    # The readsb fixture includes Mode S-only trackfiles; they must be live
    # entries, not discards (SPEC §20).
    assert counts.non_positioned > 0


def test_an_unreachable_decoder_leaves_an_empty_but_working_store(
    configured: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    point_decoder_at(monkeypatch, httpx.ConnectError("connection refused"))
    app = create_app()

    with TestClient(app):
        live: LiveStore = app.state.live

        assert live.sweeping is True
        assert live.counts().total == 0
