"""``GET /api/v1/aircraft/current`` and ``GET /api/v1/receiver`` over HTTP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from flightsite.api.schemas import AircraftView, ReceiverInfo
from flightsite.app import create_app
from flightsite.config import ConfigStore
from flightsite.db import MetaRepository
from flightsite.ingest import Position

from ..live.conftest import make_update
from .conftest import LiveApp

NEARBY = Position(latitude=47.6205, longitude=-122.3493)


def icaos(body: dict[str, Any]) -> list[str]:
    return [item["icao"] for item in body["items"]]


# --------------------------------------------------------- aircraft/current


async def test_an_empty_sky_is_an_empty_list_not_an_error(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/aircraft/current")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


async def test_the_live_set_is_returned_in_the_documented_shape(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY, callsign="RCH492", altitude_ft=24_975.0))

    body = (await rest.get("/api/v1/aircraft/current")).json()

    assert body["total"] == 1
    aircraft = AircraftView.model_validate(body["items"][0])
    assert aircraft.icao == "ae1463"
    assert aircraft.callsign == "RCH492"
    assert aircraft.altitude_ft == 24_975.0
    assert aircraft.position is not None


async def test_non_positioned_aircraft_are_part_of_the_live_picture(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    # SPEC §20: the endpoint returns positioned *and* non-positioned aircraft.
    live_app.feed(make_update("ae1463", position=NEARBY), make_update("a9c2f0"))

    body = (await rest.get("/api/v1/aircraft/current")).json()

    assert icaos(body) == ["a9c2f0", "ae1463"]
    assert body["total"] == 2


async def test_the_positioned_filter_selects_aircraft_with_a_position(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY), make_update("a9c2f0"))

    with_position = (await rest.get("/api/v1/aircraft/current?positioned=true")).json()
    without = (await rest.get("/api/v1/aircraft/current?positioned=false")).json()

    assert icaos(with_position) == ["ae1463"]
    assert icaos(without) == ["a9c2f0"]
    assert with_position["total"] == 1


async def test_an_unparseable_filter_is_a_validation_error(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    response = await rest.get("/api/v1/aircraft/current?positioned=perhaps")

    assert response.status_code == 422


async def test_the_result_is_ordered_by_icao(live_app: LiveApp, rest: AsyncClient) -> None:
    # Deterministic order is what lets a REST read and a WebSocket snapshot of
    # the same instant be compared as documents rather than as sets.
    live_app.feed(
        make_update("ff0011", position=NEARBY),
        make_update("00aabb"),
        make_update("a9c2f0", position=NEARBY),
    )

    body = (await rest.get("/api/v1/aircraft/current")).json()

    assert icaos(body) == ["00aabb", "a9c2f0", "ff0011"]


async def test_a_removed_aircraft_leaves_the_live_picture(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY))
    live_app.advance(live_app.live.remove_s + 1.0)
    live_app.sweep()

    body = (await rest.get("/api/v1/aircraft/current")).json()

    assert body == {"items": [], "total": 0}


async def test_a_stale_aircraft_stays_in_the_picture_and_says_so(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY))
    live_app.advance(live_app.live.stale_s + 1.0)
    live_app.sweep()

    body = (await rest.get("/api/v1/aircraft/current")).json()

    assert body["items"][0]["state"] == "stale"


async def test_the_open_sighting_id_reaches_the_payload(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY))
    # One persistence cycle commits the sighting row and assigns its id; until
    # it does, `sighting_id` is null, which is also a documented state.
    before = (await rest.get("/api/v1/aircraft/current")).json()
    await live_app.app.state.persistence.process_pending()
    after = (await rest.get("/api/v1/aircraft/current")).json()

    assert before["items"][0]["sighting_id"] is None
    assert (
        after["items"][0]["sighting_id"]
        == live_app.app.state.persistence.sighting_for("ae1463").sighting_id
    )


# ------------------------------------------------------------------ receiver


async def test_receiver_on_a_first_run_reports_nulls_not_an_error() -> None:
    # No config.yaml, no setup wizard yet: no location, and nothing persisted,
    # so no T0. Both are ordinary states (§2.7), not failures. Built from the
    # unmodified factory, because a first run is precisely an app nobody has
    # configured anything on.
    app = create_app()

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        response = await client.get("/api/v1/receiver")

    assert response.status_code == 200
    info = ReceiverInfo.model_validate(response.json())
    assert info.site_name is None
    assert info.latitude is None
    assert info.longitude is None
    assert info.t0 is None
    assert info.demo_mode is False


async def test_receiver_reports_the_configured_site(isolated_data_dir: Path) -> None:
    ConfigStore(isolated_data_dir).apply_update(
        {
            "location": {
                "latitude": 47.6205,
                "longitude": -122.3493,
                "site_name": "Rooftop Pi",
                "antenna_height_ft": 120.0,
            },
            "timezone": "America/Los_Angeles",
            "display_radius_nm": 180.0,
        }
    )
    app = create_app()

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        body = (await client.get("/api/v1/receiver")).json()

    assert body["site_name"] == "Rooftop Pi"
    assert body["latitude"] == pytest.approx(47.6205)
    assert body["timezone"] == "America/Los_Angeles"
    assert body["display_radius_nm"] == pytest.approx(180.0)


async def test_receiver_reports_t0_once_an_observation_is_persisted(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    live_app.feed(make_update("ae1463", position=NEARBY))
    await live_app.app.state.persistence.process_pending()

    body = (await rest.get("/api/v1/receiver")).json()

    assert body["t0"] is not None
    assert body["t0"].endswith("Z")


async def test_receiver_never_returns_a_secret(live_app: LiveApp, rest: AsyncClient) -> None:
    # SPEC §29: secrets must not reach /api/v1 at all. The response model's
    # field set is the enforcement; this pins the intent.
    body = (await rest.get("/api/v1/receiver")).json()

    assert set(body) == set(ReceiverInfo.model_fields)


async def test_an_unreadable_t0_does_not_take_the_receiver_endpoint_down(
    live_app: LiveApp, rest: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A database that failed to migrate already makes /ready answer 503; it
    # must not also take down a payload that is otherwise pure configuration.
    async def unavailable(self: MetaRepository) -> int | None:
        raise RuntimeError("database is unavailable")

    monkeypatch.setattr(MetaRepository, "get_t0", unavailable)

    response = await rest.get("/api/v1/receiver")

    assert response.status_code == 200
    assert response.json()["t0"] is None
