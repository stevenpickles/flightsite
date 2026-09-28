"""Shared seed data for slice 083's ``q`` tests on ``/aircraft`` and ``/sightings``.

One roster, used by both endpoints' tests so "found by its callsign" means the
same airframe and the same sighting on either page.
"""

from __future__ import annotations

from typing import Any

from .aircraft_history_fixtures import SeedAircraft
from .sighting_fixtures import SeedSighting

BASE_MS = 1_756_000_000_000
DAY_MS = 86_400_000


def icaos(body: dict[str, Any]) -> list[str]:
    return [item["icao"] for item in body["items"]]


def airframe(icao24: str, *, days_ago: int = 0, **metadata: Any) -> SeedAircraft:
    return SeedAircraft(
        icao24=icao24,
        first_seen_ms=BASE_MS - 30 * DAY_MS,
        last_seen_ms=BASE_MS - days_ago * DAY_MS,
        **metadata,
    )


#: Five airframes, each findable by exactly one identifier the others do not
#: share a prefix with — so a test naming one field proves *that* field is
#: searched, rather than passing because another one happened to match.
ROSTER = (
    airframe("a1b2c3", days_ago=0, registration="N123AB", type_code="B738"),
    airframe("4ca7f1", days_ago=1, registration="G-EZTH", operator_name="easyJet"),
    airframe("7c0011", days_ago=2, registration="VH-OQA", type_code="A388"),
    airframe("3c6444", days_ago=3, registration="D-AIMA", operator_name="Lufthansa"),
    airframe("e80000", days_ago=4),
)

#: Sightings for the roster. `e80000` has no metadata at all and is findable
#: only by its callsign; `a1b2c3` flew `QFA9` long ago and `UAL1` most
#: recently, which is what the "most recent callsign" rule is about.
SIGHTINGS = (
    SeedSighting(icao24="a1b2c3", started_ms=BASE_MS - 20 * DAY_MS, callsign_last="QFA9"),
    SeedSighting(icao24="a1b2c3", started_ms=BASE_MS - 1 * DAY_MS, callsign_last="UAL1"),
    SeedSighting(icao24="4ca7f1", started_ms=BASE_MS - 2 * DAY_MS, callsign_last="EZY42"),
    SeedSighting(icao24="e80000", started_ms=BASE_MS - 4 * DAY_MS, callsign_last="RCH871"),
)


__all__ = ["BASE_MS", "DAY_MS", "ROSTER", "SIGHTINGS", "airframe", "icaos"]
