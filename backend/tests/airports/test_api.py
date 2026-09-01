"""The ``nearest_airport`` block on the §3.3 aircraft object.

Two things are being pinned. The **shape**: an always-present key whose value is
``null`` until there is something to say, and whose members are exactly
``ident``/``name``/``distance_nm``/``phase``. And the **separation**: it is a
different field from ``route``, carries a different provenance, and neither can
reach the other — which is what SPEC §41's *"clearly labeled as inferred"*
means once the labelling has to survive a schema, a serializer and a client.

The Pydantic models in :mod:`flightsite.api.schemas` are validated against the
serializer's own output, so the published OpenAPI document and the WebSocket
payload cannot describe two different shapes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from flightsite.airports import AirportRepository
from flightsite.airports.model import AirportContext, InferredPhase
from flightsite.api.schemas import AircraftView, NearestAirportView
from flightsite.api.serializers import NEAREST_AIRPORT_PROVENANCE, aircraft_payload
from flightsite.app import create_app
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.live import LiveAircraft, LiveStore, appear
from flightsite.sightings.state import SightingRoute
from tests.airports.conftest import (
    BASE_TIME,
    BOEING_FIELD,
    FIXTURE_AIRPORTS,
    ICAO,
    SimulatedTime,
    approach_track,
    fly,
    north_of,
    seed_index,
)

KBFI = AirportContext(
    ident="KBFI", name="Boeing Field", distance_nm=4.123456, phase=InferredPhase.ARRIVING
)


def record() -> LiveAircraft:
    """A positioned live record, near Boeing Field."""
    update = AircraftStateUpdate(
        icao=ICAO,
        timestamp=BASE_TIME,
        position=north_of(BOEING_FIELD, 4.0),
        position_source="adsb",
        callsign="N12345",
        altitude_ft=1_500,
    )
    return appear(update, now=1_000.0, receiver=Position(latitude=47.6, longitude=-122.3))


# ------------------------------------------------------------------- shape


def test_the_block_carries_the_field_its_range_and_the_phase() -> None:
    payload = aircraft_payload(record(), airport=KBFI)

    assert payload["nearest_airport"] == {
        "ident": "KBFI",
        "name": "Boeing Field",
        "distance_nm": 4.123,
        "phase": "arriving",
    }


def test_the_key_is_present_and_null_when_there_is_nothing_to_say() -> None:
    """§2.7: unknown is a null value under a stable key, never a missing key."""
    payload = aircraft_payload(record())

    assert "nearest_airport" in payload
    assert payload["nearest_airport"] is None


def test_the_phase_is_null_when_the_kinematics_were_ambiguous() -> None:
    """A field can be certain while intent is not; that is a member, not a block."""
    payload = aircraft_payload(
        record(), airport=AirportContext(ident="KSEA", name="Sea-Tac", distance_nm=1.0)
    )

    block = payload["nearest_airport"]
    assert block is not None
    assert block["ident"] == "KSEA"
    assert block["phase"] is None


def test_the_range_is_rounded_like_every_other_distance() -> None:
    """Full float precision here would be payload weight at 500 aircraft, 1 Hz."""
    payload = aircraft_payload(
        record(),
        airport=AirportContext(ident="KBFI", name="Boeing Field", distance_nm=1.0 / 3.0),
    )

    block = payload["nearest_airport"]
    assert block is not None
    assert block["distance_nm"] == 0.333


# -------------------------------------------------------------- provenance


def test_the_block_is_attributed_to_the_heuristic() -> None:
    """``docs/API.md`` §2.6 names exactly this key and this value."""
    payload = aircraft_payload(record(), airport=KBFI)

    assert payload["provenance"]["nearest_airport"] == "heuristic"
    assert NEAREST_AIRPORT_PROVENANCE == "heuristic"


def test_there_is_no_provenance_entry_for_a_block_that_is_not_there() -> None:
    """§2.6 entries name the source of a value; a null has no source."""
    payload = aircraft_payload(record())

    assert "nearest_airport" not in payload["provenance"]


# -------------------------------------------------------------- separation


def test_the_inference_and_the_reported_route_are_different_fields() -> None:
    """SPEC §28, §41: what somebody told FlightSite and what it guessed stay apart."""
    payload = aircraft_payload(
        record(),
        route=SightingRoute(origin_ident="KATL", destination_ident="KSLC", source="aerodatabox"),
        airport=KBFI,
    )

    assert payload["route"] == {"origin": "KATL", "destination": "KSLC"}
    assert payload["nearest_airport"]["ident"] == "KBFI"
    assert payload["provenance"]["route"] == "aerodatabox"
    assert payload["provenance"]["nearest_airport"] == "heuristic"


def test_an_inference_never_becomes_a_route() -> None:
    """The failure mode the two fields exist to make impossible."""
    payload = aircraft_payload(record(), airport=KBFI)

    assert payload["route"] == {"origin": None, "destination": None}
    assert "route" not in payload["provenance"]


def test_a_reported_route_never_becomes_an_inference() -> None:
    payload = aircraft_payload(
        record(),
        route=SightingRoute(origin_ident="KATL", destination_ident="KSLC", source="aerodatabox"),
    )

    assert payload["nearest_airport"] is None
    assert "nearest_airport" not in payload["provenance"]


# ------------------------------------------------------------------ schema


@pytest.mark.parametrize("airport", [None, KBFI])
def test_the_payload_validates_against_the_published_model(
    airport: AirportContext | None,
) -> None:
    """The serializer and the OpenAPI document describe one shape, not two."""
    view = AircraftView.model_validate(aircraft_payload(record(), airport=airport))

    if airport is None:
        assert view.nearest_airport is None
    else:
        assert view.nearest_airport == NearestAirportView(
            ident="KBFI", name="Boeing Field", distance_nm=4.123, phase="arriving"
        )


@pytest.mark.parametrize("phase", ["landing", "taxiing", ""])
def test_the_model_refuses_a_phase_outside_the_vocabulary(phase: str) -> None:
    """``docs/DATA_MODEL.md`` §2.3 constrains the column to two values."""
    with pytest.raises(ValueError, match="phase"):
        NearestAirportView(ident="KBFI", name="Boeing Field", distance_nm=1.0, phase=phase)  # type: ignore[arg-type]


def test_the_model_refuses_an_extra_member() -> None:
    """The key set is a contract (§6 lets v1 add fields, not invent them here)."""
    with pytest.raises(ValueError, match="runway"):
        NearestAirportView.model_validate(
            {"ident": "KBFI", "name": "Boeing Field", "distance_nm": 1.0, "runway": "13R"}
        )


def test_the_published_schema_documents_the_block() -> None:
    """A client codes against ``/api/v1/openapi.json``, so it has to be in it."""
    schema = AircraftView.model_json_schema()

    assert "nearest_airport" in schema["properties"]
    assert "NearestAirportView" in schema["$defs"]
    members = schema["$defs"]["NearestAirportView"]["properties"]
    assert set(members) == {"ident", "name", "distance_nm", "phase"}


# ---------------------------------------------------------------- end to end


async def test_the_live_endpoint_serves_the_inference(isolated_data_dir: Path) -> None:
    """Through the real app: an approach flown into the live store comes back
    out of ``GET /api/v1/aircraft/current`` as an inferred arrival."""
    app = create_app(isolated_data_dir)
    clock = SimulatedTime()

    async with app.router.lifespan_context(app):
        live: LiveStore = app.state.live
        live.set_receiver_location(Position(latitude=BOEING_FIELD[0], longitude=BOEING_FIELD[1]))
        service = app.state.airports
        await seed_index(AirportRepository(app.state.database), service, FIXTURE_AIRPORTS)

        await fly(service, live, clock, approach_track(), worker=app.state.persistence)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            body = (await client.get("/api/v1/aircraft/current")).json()

    aircraft = {item["icao"]: item for item in body["items"]}
    block = aircraft[ICAO]["nearest_airport"]

    assert block["ident"] == "KBFI"
    assert block["name"] == "Boeing Field"
    assert block["phase"] == "arriving"
    assert aircraft[ICAO]["provenance"]["nearest_airport"] == "heuristic"
    # And the enrichment half stays empty on an install with no provider.
    assert aircraft[ICAO]["route"] == {"origin": None, "destination": None}


async def test_the_live_endpoint_is_null_on_an_install_with_no_dataset(
    isolated_data_dir: Path,
) -> None:
    """A stock install: no import has run, so every aircraft's block is null."""
    app = create_app(isolated_data_dir)
    clock = SimulatedTime()

    async with app.router.lifespan_context(app):
        live: LiveStore = app.state.live
        live.set_receiver_location(Position(latitude=BOEING_FIELD[0], longitude=BOEING_FIELD[1]))
        await fly(app.state.airports, live, clock, approach_track())

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            body = (await client.get("/api/v1/aircraft/current")).json()

    aircraft = {item["icao"]: item for item in body["items"]}
    assert aircraft[ICAO]["nearest_airport"] is None
