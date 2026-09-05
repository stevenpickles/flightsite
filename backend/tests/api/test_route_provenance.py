"""``provenance.route`` — which source named this route (``docs/API.md`` §2.6).

Until slice 071 there was one possible value, so the entry said little more
than "enrichment ran". There are now two, and the difference is the thing a
client renders: ``vrs`` is the offline Virtual Radar Server directory the
install imported and can see the version of, ``aerodatabox`` is a live lookup
against a third party. Both are *reported* routes, and both are distinct from
the locally inferred airport context beside them (SPEC §28).

The serializer does not choose between them — it publishes what the sighting
column holds — so what these tests pin is that the value survives every surface
unchanged, and that the vocabulary the API can publish is the same one the
schema will accept.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from sqlalchemy.engine import RowMapping

from flightsite.api.serializers import aircraft_payload, sighting_detail_payload
from flightsite.db.models import ROUTE_SOURCE_CHECK
from flightsite.enrichment.model import (
    ROUTE_SOURCE_AERODATABOX,
    ROUTE_SOURCE_VRS,
    ROUTE_SOURCES,
)
from flightsite.ingest import Position
from flightsite.live import LiveAircraft, appear
from flightsite.sightings.state import SightingRoute

from ..live.conftest import make_update
from .test_sightings_api import BASE_MS, MINUTE_MS

ICAO = "ae1463"
NEARBY = Position(latitude=47.6205, longitude=-122.3493)

ORIGIN = "EGLL"
DESTINATION = "KJFK"


def record() -> LiveAircraft:
    """One positioned live record to hang a route on."""
    update = make_update(ICAO, position=NEARBY, callsign="BAW1", altitude_ft=31_000)
    return appear(update, now=1_000.0, receiver=NEARBY)


def detail_row(**overrides: Any) -> RowMapping:
    """The columns :func:`sighting_detail_payload` reads, as a plain mapping."""
    row: dict[str, Any] = {
        "id": 1,
        "icao24": ICAO,
        "callsign_last": "BAW1",
        "squawk_last": "1200",
        "started_ms": BASE_MS,
        "ended_ms": BASE_MS + MINUTE_MS,
        "duration_ms": MINUTE_MS,
        "closure_reason": "gap_timeout",
        "origin_ident": ORIGIN,
        "destination_ident": DESTINATION,
        "route_source": ROUTE_SOURCE_VRS,
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


@pytest.mark.parametrize("source", ROUTE_SOURCES)
def test_the_live_payload_publishes_the_source_that_answered(source: str) -> None:
    route = SightingRoute(origin_ident=ORIGIN, destination_ident=DESTINATION, source=source)

    payload = aircraft_payload(record(), route=route)

    assert payload["provenance"]["route"] == source
    assert payload["route"]["origin"] == ORIGIN


@pytest.mark.parametrize("source", ROUTE_SOURCES)
def test_the_sighting_detail_publishes_the_source_that_answered(source: str) -> None:
    payload = sighting_detail_payload(detail_row(route_source=source), events=(), path=())

    assert payload["provenance"]["route"] == source


def test_a_route_with_no_source_publishes_no_route_provenance() -> None:
    """§2.6 entries name the source of a *value*; two nulls have no source."""
    payload = sighting_detail_payload(
        detail_row(origin_ident=None, destination_ident=None, route_source=None),
        events=(),
        path=(),
    )

    assert "route" not in payload["provenance"]


def test_the_two_published_values_are_the_two_the_schema_accepts() -> None:
    """The API vocabulary and the ``CHECK`` cannot drift apart unnoticed.

    :data:`~flightsite.enrichment.model.ROUTE_SOURCES` is what enrichment can
    write and what ``docs/API.md`` §2.8 documents;
    :data:`~flightsite.db.models.ROUTE_SOURCE_CHECK` is what the column will
    store. A value in one and not the other is either a route that cannot be
    saved or a stored value nothing can explain.
    """
    assert set(ROUTE_SOURCES) == {ROUTE_SOURCE_VRS, ROUTE_SOURCE_AERODATABOX}
    for source in ROUTE_SOURCES:
        assert f"'{source}'" in ROUTE_SOURCE_CHECK
    assert ROUTE_SOURCE_CHECK.count("'") == 2 * len(ROUTE_SOURCES)
