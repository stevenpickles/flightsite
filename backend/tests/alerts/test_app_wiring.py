"""Alerting's place in the application (``flightsite.app.create_app``).

Four claims, and each one is a wiring mistake that would be invisible in a unit
test: the service is constructed inertly; it is wired to the *same* live store,
metadata cache and watchlist matcher everything else uses; its matches reach
the activity feed through the listener the factory registers; and the
configured alert radius is read late rather than captured, so ``PUT
/api/internal/config`` can change it on a running app.

The end-to-end case is an emergency squawk on a first-run install with no
configuration at all, because that is roadmap slice 038's own acceptance
criterion and it is the one path that must work before a user has done
anything.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from flightsite.activity import ActivityService, AlertMatchFact
from flightsite.alerts import AlertService
from flightsite.api.context import LiveApiContext
from flightsite.app import create_app
from flightsite.config import Settings
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.metadata import MetadataService
from flightsite.watchlists import WatchlistService


def test_the_service_is_constructed_without_touching_anything(isolated_data_dir: Path) -> None:
    app = create_app(isolated_data_dir)

    service: AlertService = app.state.alerts
    assert isinstance(service, AlertService)
    assert not service.engine.running
    assert service.engine.rules == ()
    assert service.engine.tracked == 0


def test_the_engine_reads_the_same_in_memory_inputs_everything_else_does(
    isolated_data_dir: Path,
) -> None:
    """A subject is built from the live store, the metadata cache and the
    watchlist matcher; an engine wired to different objects would evaluate a
    picture nothing else can see."""
    app = create_app(isolated_data_dir)

    service: AlertService = app.state.alerts
    metadata: MetadataService = app.state.metadata
    watchlists: WatchlistService = app.state.watchlists
    live: LiveStore = app.state.live
    assert service.engine._live is live
    assert service.engine._metadata is metadata.cache
    assert service.engine._watchlists is watchlists.matcher
    assert service.engine._persistence is app.state.persistence


def test_the_api_context_reads_the_engine_the_app_holds(isolated_data_dir: Path) -> None:
    app = create_app(isolated_data_dir)

    context: LiveApiContext = app.state.api_context
    service: AlertService = app.state.alerts
    assert context.alerts is service.engine


def test_created_matches_are_pushed_into_the_activity_feed(isolated_data_dir: Path) -> None:
    """The listener the factory registers is what turns a match into a feed
    event — on the feed's own pass and its own transaction."""
    app = create_app(isolated_data_dir)
    activity: ActivityService = app.state.activity
    service: AlertService = app.state.alerts
    fact = AlertMatchFact(
        match_id=1,
        matched_ms=0,
        severity="critical",
        reason="Emergency squawk 7700 (general emergency)",
        aircraft_id=1,
        sighting_id=1,
        icao24="ae1463",
        builtin_key="emergency_7700",
    )

    service.engine._publish([fact])

    assert activity._pending_alerts == [fact]


def test_the_alert_radius_is_read_late_rather_than_captured(isolated_data_dir: Path) -> None:
    """``PUT /api/internal/config`` replaces ``app.state.settings`` on a running
    app, so a captured radius would keep bounding alerts by a setting the user
    has since changed."""
    app = create_app(isolated_data_dir)
    settings: Settings = app.state.settings
    assert settings.alert_radius_nm is None

    app.state.settings = settings.model_copy(update={"alert_radius_nm": 42.0})
    service: AlertService = app.state.alerts

    assert service._alert_radius is not None
    assert service._alert_radius() == 42.0


def test_the_shipped_templates_come_from_the_configuration(isolated_data_dir: Path) -> None:
    (isolated_data_dir / "config.yaml").write_text(
        "alerts:\n  enabled_templates:\n    - military\n    - watchlist\n", encoding="utf-8"
    )
    app = create_app(isolated_data_dir)

    service: AlertService = app.state.alerts
    assert service._template_keys == ("military", "watchlist")


@pytest.fixture
async def app(isolated_data_dir: Path) -> FastAPI:
    """The real app, wired exactly as ``create_app`` leaves it.

    ``app.state.live`` is not replaced, for the reason
    ``tests/watchlists/test_app_wiring.py`` gives: the metadata service and the
    alert engine are both bound to that exact object at construction time, so
    swapping it afterwards would leave them watching a store this test never
    feeds. A first-run install starts no ingestion, so nothing else writes to
    it while the test drives it by hand.
    """
    return create_app(isolated_data_dir)


async def settle(cycles: int = 6) -> None:
    for _ in range(cycles):
        await asyncio.sleep(0)


async def test_an_emergency_squawk_alerts_on_a_first_run_install_with_no_configuration(
    app: FastAPI,
) -> None:
    """Roadmap slice 038's acceptance criterion, through the whole real
    application: no config file, no rules, no templates enabled — and a 7700
    reaches the §3.3 block, the §3.4 list and the §3.9 history."""
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        service: AlertService = app.state.alerts
        assert await service.list_rules() == ()

        live: LiveStore = app.state.live
        live.apply_updates(
            [
                AircraftStateUpdate(
                    icao="ae1463",
                    timestamp=datetime.now(UTC),
                    position=Position(latitude=47.6, longitude=-122.3),
                    position_source="adsb",
                    altitude_ft=25_000.0,
                    squawk="7700",
                    on_ground=False,
                )
            ]
        )
        await settle()
        await app.state.metadata.cache.wait_idle()
        # The sighting has to be committed before a match has ids to cite, and
        # the engine's own loop is running: one worker cycle, then a settle for
        # the engine to notice on its next wake.
        await app.state.persistence.process_pending()
        await service.engine.process_pending()

        listed = (await client.get("/api/v1/aircraft/interesting")).json()
        history = (await client.get("/api/v1/alerts/matches")).json()

    assert listed["total"] == 1
    assert listed["items"][0]["interesting"]["severity"] == "critical"
    assert [match["builtin_key"] for match in history["items"]] == ["emergency_7700"]


async def test_the_engine_stops_before_the_persistence_worker(app: FastAPI) -> None:
    """It applies ``max_alert_severity`` *through* that worker, so a severity
    applied after the worker's final flush would land on an accumulator nobody
    will write again. The shutdown order is what prevents it; this asserts the
    engine is genuinely stopped when the lifespan exits."""
    async with app.router.lifespan_context(app):
        service: AlertService = app.state.alerts
        assert service.engine.running

    assert not service.engine.running
