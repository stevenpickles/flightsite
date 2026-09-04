"""``route.origin_name`` / ``route.destination_name`` — ``docs/API.md`` §2.6.

A route arrives from the enrichment provider as two idents and nothing else, so
a client that wants to show *Atlanta* rather than *KATL* has to resolve them.
Slice 070 resolves them **locally**, against the ``airports`` table slice 027
already imports and already holds in memory, and publishes the answer beside the
ident rather than in place of it.

Three properties are pinned here, because each is a way this could go wrong
without failing loudly:

* **The shape is stable.** Four keys, always, on every payload that carries a
  ``route`` — the same §2.7 bargain the two idents already keep. A name is
  ``null`` for an ident the local dataset does not carry and for an ident that
  is itself ``null``, and those two look identical on the wire on purpose.
* **The lookup is injected.** The serializer never reaches for application
  state, so these tests hand it a dictionary and a counter rather than an index.
  That is also how the "one call per ident, and none for an ident that is not
  there" claim in :func:`~flightsite.api.serializers.route_block`'s docstring
  gets checked rather than merely written down: it is the live path's cost.
* **Every surface agrees.** REST, the WebSocket's frames and the sighting detail
  all read the same block, because they call the same function with the same
  lookup.
"""

from __future__ import annotations

from typing import Any, cast

from httpx import AsyncClient
from sqlalchemy.engine import RowMapping

from flightsite.airports.records import AirportRecord
from flightsite.airports.repository import AirportRepository
from flightsite.api.schemas import AircraftView, RouteView, SightingDetail
from flightsite.api.serializers import (
    aircraft_payload,
    no_airport_names,
    route_block,
    sighting_detail_payload,
)
from flightsite.ingest import Position
from flightsite.live import LiveAircraft, appear
from flightsite.sightings.state import SightingRoute

from ..live.conftest import make_update
from .aircraft_history_fixtures import SeedAircraft
from .conftest import LiveApp, open_probe
from .test_sightings_api import BASE_MS, MINUTE_MS, closed_sighting, seed

ICAO = "ae1463"
NEARBY = Position(latitude=47.6205, longitude=-122.3493)

#: The two fields every case below routes between, and the names the local
#: dataset carries for them.
ORIGIN = "KATL"
ORIGIN_NAME = "Hartsfield Jackson Atlanta International Airport"
DESTINATION = "KSEA"
DESTINATION_NAME = "Seattle Tacoma International Airport"

#: An ident no import here ever produced — "the provider named a field this
#: install does not have", the ordinary case on a partial dataset.
UNKNOWN_IDENT = "ZZZZ"

NAMES: dict[str, str] = {ORIGIN: ORIGIN_NAME, DESTINATION: DESTINATION_NAME}

AIRCRAFT = [SeedAircraft(icao24=ICAO, first_seen_ms=BASE_MS, last_seen_ms=BASE_MS)]


def names(ident: str) -> str | None:
    """A fake :data:`~flightsite.api.serializers.AirportNameLookup`."""
    return NAMES.get(ident)


class CountingNames:
    """A lookup that records every ident it was asked about."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __call__(self, ident: str) -> str | None:
        self.asked.append(ident)
        return NAMES.get(ident)


def record() -> LiveAircraft:
    """One positioned live record to hang a route on."""
    update = make_update(ICAO, position=NEARBY, callsign="DAL2401", altitude_ft=31_000)
    return appear(update, now=1_000.0, receiver=NEARBY)


def route(origin: str | None = ORIGIN, destination: str | None = DESTINATION) -> SightingRoute:
    return SightingRoute(origin_ident=origin, destination_ident=destination, source="aerodatabox")


def airport(ident: str, name: str) -> AirportRecord:
    """One row of the local dataset. Position is irrelevant here — this is the
    name lookup, not the nearest-airport inference."""
    return AirportRecord(
        ident=ident,
        name=name,
        type="large_airport",
        lat=0.0,
        lon=0.0,
        elevation_ft=None,
        iata=None,
        upstream_id=None,
    )


async def seed_airports(live_app: LiveApp, *records: AirportRecord) -> None:
    """Put ``records`` in the table and rebuild the running service's index.

    The production path — repository write, then the service's own
    :meth:`~flightsite.airports.service.AirportContextService.reload` — because
    a name that appeared only through a shortcut would prove nothing about the
    index the live path actually reads.
    """
    repository = AirportRepository(live_app.app.state.database)
    await repository.replace_all(
        list(records), source="airports", at_ms=BASE_MS, dataset_version="fixture"
    )
    await live_app.app.state.airports.reload()


# ------------------------------------------------------------------- the block


def test_a_known_ident_is_named() -> None:
    block = route_block(ORIGIN, DESTINATION, names)

    assert block == {
        "origin": ORIGIN,
        "origin_name": ORIGIN_NAME,
        "destination": DESTINATION,
        "destination_name": DESTINATION_NAME,
    }


def test_an_ident_the_local_dataset_does_not_carry_is_named_null() -> None:
    """§2.7: the ident is still published, so a client renders the code."""
    block = route_block(UNKNOWN_IDENT, DESTINATION, names)

    assert block["origin"] == UNKNOWN_IDENT
    assert block["origin_name"] is None
    assert block["destination_name"] == DESTINATION_NAME


def test_a_null_ident_has_a_null_name() -> None:
    block = route_block(None, None, names)

    assert block == {
        "origin": None,
        "origin_name": None,
        "destination": None,
        "destination_name": None,
    }


def test_the_lookup_is_never_asked_about_an_ident_that_is_not_there() -> None:
    """The hot-path claim: at most one call per ident, none for a null."""
    counting = CountingNames()

    route_block(ORIGIN, None, counting)

    assert counting.asked == [ORIGIN]


def test_an_install_with_no_airport_dataset_names_nothing() -> None:
    """The default lookup is what a stock install answers with."""
    block = route_block(ORIGIN, DESTINATION, no_airport_names)

    assert block["origin"] == ORIGIN
    assert block["origin_name"] is None
    assert block["destination_name"] is None


def test_the_published_model_carries_all_four_members() -> None:
    """A client codes against ``/api/v1/openapi.json``, so it has to be in it."""
    assert set(RouteView.model_json_schema()["properties"]) == {
        "origin",
        "origin_name",
        "destination",
        "destination_name",
    }


# ------------------------------------------------------------ the live payload


def test_the_live_payload_names_a_known_route() -> None:
    payload = aircraft_payload(record(), route=route(), airport_names=names)

    assert payload["route"]["origin_name"] == ORIGIN_NAME
    assert payload["route"]["destination_name"] == DESTINATION_NAME
    AircraftView.model_validate(payload)


def test_the_live_payload_names_an_unknown_ident_null() -> None:
    payload = aircraft_payload(record(), route=route(origin=UNKNOWN_IDENT), airport_names=names)

    assert payload["route"]["origin"] == UNKNOWN_IDENT
    assert payload["route"]["origin_name"] is None
    assert payload["route"]["destination_name"] == DESTINATION_NAME


def test_the_live_payload_has_the_keys_before_there_is_any_route() -> None:
    """§2.7 again: unknown is a null under a stable key, never a missing key."""
    payload = aircraft_payload(record(), airport_names=names)

    assert payload["route"] == {
        "origin": None,
        "origin_name": None,
        "destination": None,
        "destination_name": None,
    }


def test_a_name_is_not_attributed_separately_from_its_route() -> None:
    """§2.6: the ``route`` entry names where the route came from; a name is a
    local label for it, not a second claim with a second source."""
    payload = aircraft_payload(record(), route=route(), airport_names=names)

    assert payload["provenance"]["route"] == "aerodatabox"
    assert "origin_name" not in payload["provenance"]
    assert "destination_name" not in payload["provenance"]


# --------------------------------------------------------- the sighting detail


def detail_row(**overrides: Any) -> RowMapping:
    """The columns :func:`sighting_detail_payload` reads, as a plain mapping.

    Cast rather than queried: this is a serializer test, and the columns
    themselves are pinned by ``tests/api/test_sightings_api.py`` against the
    real query.
    """
    row: dict[str, Any] = {
        "id": 1,
        "icao24": ICAO,
        "callsign_last": "DAL2401",
        "squawk_last": "1200",
        "started_ms": BASE_MS,
        "ended_ms": BASE_MS + MINUTE_MS,
        "duration_ms": MINUTE_MS,
        "closure_reason": "gap_timeout",
        "origin_ident": ORIGIN,
        "destination_ident": DESTINATION,
        "route_source": "aerodatabox",
        "rssi_peak_db": None,
        "rssi_avg_db": None,
        "rssi_min_db": None,
        "msg_count": 1,
        "pos_count": 1,
        "pos_time_pct": None,
        "closest_approach_nm": None,
        "max_range_nm": None,
        "lowest_alt_ft": None,
        "highest_alt_ft": None,
    }
    row.update(overrides)
    return cast(RowMapping, row)


def test_the_sighting_detail_names_a_stored_route() -> None:
    payload = sighting_detail_payload(detail_row(), events=(), path=(), airport_names=names)

    assert payload["route"]["origin_name"] == ORIGIN_NAME
    assert payload["route"]["destination_name"] == DESTINATION_NAME


def test_the_sighting_detail_names_an_unknown_ident_null() -> None:
    payload = sighting_detail_payload(
        detail_row(origin_ident=UNKNOWN_IDENT), events=(), path=(), airport_names=names
    )

    assert payload["route"]["origin"] == UNKNOWN_IDENT
    assert payload["route"]["origin_name"] is None


def test_the_sighting_detail_names_nothing_for_a_sighting_with_no_route() -> None:
    payload = sighting_detail_payload(
        detail_row(origin_ident=None, destination_ident=None, route_source=None),
        events=(),
        path=(),
        airport_names=names,
    )

    assert payload["route"] == {
        "origin": None,
        "origin_name": None,
        "destination": None,
        "destination_name": None,
    }


# ---------------------------------------------------------------- end to end


async def test_the_sighting_detail_endpoint_serves_the_names(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """Through the real app: a seeded airport names a stored route ident."""
    await seed_airports(
        live_app, airport(ORIGIN, ORIGIN_NAME), airport(DESTINATION, DESTINATION_NAME)
    )
    seeded = await seed(
        live_app,
        closed_sighting(
            ICAO,
            origin_ident=ORIGIN,
            destination_ident=UNKNOWN_IDENT,
            route_source="aerodatabox",
        ),
        aircraft=AIRCRAFT,
    )

    body = (await rest.get(f"/api/v1/sightings/{seeded[0]}")).json()

    detail = SightingDetail.model_validate(body)
    assert detail.route.origin == ORIGIN
    assert detail.route.origin_name == ORIGIN_NAME
    # The provider named a field this install has not imported.
    assert detail.route.destination == UNKNOWN_IDENT
    assert detail.route.destination_name is None


async def test_the_sighting_detail_endpoint_is_unnamed_before_an_import(
    live_app: LiveApp, rest: AsyncClient
) -> None:
    """A stock install: the idents are published, the names are all null."""
    seeded = await seed(
        live_app,
        closed_sighting(
            ICAO, origin_ident=ORIGIN, destination_ident=DESTINATION, route_source="aerodatabox"
        ),
        aircraft=AIRCRAFT,
    )

    body = (await rest.get(f"/api/v1/sightings/{seeded[0]}")).json()

    assert body["route"] == {
        "origin": ORIGIN,
        "origin_name": None,
        "destination": DESTINATION,
        "destination_name": None,
    }


async def enrich_open_sighting(live_app: LiveApp) -> None:
    """Feed one aircraft, let its sighting open, and attach a route to it.

    The route reaches the live payload through the persistence worker's
    accumulator, exactly as slice 026's enrichment worker delivers one — there
    is no other way in, and a test that injected the block directly would not be
    exercising the path a running install uses.
    """
    live_app.feed(make_update(ICAO, position=NEARBY, callsign="DAL2401"))
    await live_app.app.state.persistence.process_pending()
    assert live_app.app.state.persistence.apply_route(ICAO, route(), at_ms=BASE_MS)


async def test_the_live_endpoint_serves_the_names(live_app: LiveApp, rest: AsyncClient) -> None:
    await seed_airports(
        live_app, airport(ORIGIN, ORIGIN_NAME), airport(DESTINATION, DESTINATION_NAME)
    )
    await enrich_open_sighting(live_app)

    body = (await rest.get("/api/v1/aircraft/current")).json()

    aircraft = {item["icao"]: item for item in body["items"]}
    assert aircraft[ICAO]["route"] == {
        "origin": ORIGIN,
        "origin_name": ORIGIN_NAME,
        "destination": DESTINATION,
        "destination_name": DESTINATION_NAME,
    }


async def test_a_websocket_delta_carries_the_same_named_route(live_app: LiveApp) -> None:
    """§4.3 frames are the §3.3 object, so they carry the names too."""
    await seed_airports(
        live_app, airport(ORIGIN, ORIGIN_NAME), airport(DESTINATION, DESTINATION_NAME)
    )
    probe, _snapshot = await open_probe(live_app)
    try:
        await enrich_open_sighting(live_app)
        await live_app.broadcast()

        delta = await probe.frame()
        updated = delta["data"]["updated"]
        assert updated[0]["route"]["origin_name"] == ORIGIN_NAME
        assert updated[0]["route"]["destination_name"] == DESTINATION_NAME
        AircraftView.model_validate(updated[0])
    finally:
        await probe.disconnect()


async def test_a_websocket_snapshot_carries_the_names(live_app: LiveApp) -> None:
    await seed_airports(live_app, airport(ORIGIN, ORIGIN_NAME))
    await enrich_open_sighting(live_app)

    probe, snapshot = await open_probe(live_app)
    try:
        aircraft = snapshot["data"]["aircraft"]
        assert aircraft[0]["route"]["origin_name"] == ORIGIN_NAME
        # A real ident this install has not imported: published, unnamed.
        assert aircraft[0]["route"]["destination"] == DESTINATION
        assert aircraft[0]["route"]["destination_name"] is None
    finally:
        await probe.disconnect()
