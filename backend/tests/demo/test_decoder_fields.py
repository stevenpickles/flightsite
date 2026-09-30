"""What demo aircraft say about themselves (roadmap slice 086).

Demo mode is what the e2e suite and the visual baselines run against, so the
three fields slice 086 captures have to appear in it: emitter categories on
most traffic, a selected altitude on airliners, one rotorcraft that no
metadata describes (the icon acceptance criterion) and one aircraft declaring
``nordo`` with an ordinary squawk (the emergency acceptance criterion).
"""

from __future__ import annotations

from typing import Final

from flightsite.demo import DEFAULT_CENTER, Category, build_roster
from flightsite.demo.adapter import DEFAULT_POPULATION, DEFAULT_SEED
from flightsite.demo.airframes import demo_metadata_records
from flightsite.demo.roster import EARLY_SPAWN_WINDOW_S, PERIOD_S, AircraftProfile
from flightsite.demo.scenario import update_at
from flightsite.sightings.vocabulary import EMERGENCY_SQUAWKS

ROSTER: Final = build_roster(
    seed=DEFAULT_SEED, population=DEFAULT_POPULATION, center=DEFAULT_CENTER
)


def _decoder_emergency_profile() -> AircraftProfile:
    (profile,) = [
        p for p in ROSTER if p.emergency is not None and p.emergency.decoder_emergency is not None
    ]
    return profile


def test_there_is_one_rotorcraft_with_no_metadata() -> None:
    (helicopter,) = [p for p in ROSTER if p.category is Category.ROTORCRAFT]
    described = {record.icao24 for record in demo_metadata_records(ROSTER)}

    assert helicopter.emitter_category == "A7"
    assert helicopter.icao not in described
    # Observable early, like every other scenario category.
    assert helicopter.spawn_tick <= EARLY_SPAWN_WINDOW_S


def test_the_rotorcraft_transmits_its_category_on_every_update() -> None:
    (helicopter,) = [p for p in ROSTER if p.category is Category.ROTORCRAFT]

    update = update_at(helicopter, helicopter.spawn_tick + 10)

    assert update is not None
    assert update.emitter_category == "A7"
    assert update.position is not None


def test_categories_follow_the_scenario_category() -> None:
    by_category = {p.category: p.emitter_category for p in ROSTER}

    assert by_category[Category.COMMERCIAL] == "A3"
    assert by_category[Category.POLICE] == "A7"
    # Heard without ADS-B, so no category: the demo keeps "unknown" visible.
    assert by_category[Category.MODE_S] is None
    assert by_category[Category.MLAT] is None


def test_airliners_report_a_selected_altitude_rounded_to_a_thousand_feet() -> None:
    airliners = [p for p in ROSTER if p.category is Category.COMMERCIAL and p.emergency is None]

    assert airliners
    for profile in airliners:
        assert profile.selected_altitude_ft is not None
        assert profile.selected_altitude_ft % 1_000 == 0
        update = update_at(profile, profile.spawn_tick)
        assert update is not None
        assert update.selected_altitude_ft == profile.selected_altitude_ft


def test_one_aircraft_declares_nordo_while_squawking_an_ordinary_code() -> None:
    profile = _decoder_emergency_profile()
    event = profile.emergency
    assert event is not None
    during = profile.spawn_tick + int(event.start_offset_s) + 10
    before = profile.spawn_tick + int(event.start_offset_s) - 10
    after = profile.spawn_tick + int(event.start_offset_s + event.duration_s) + 10

    in_event = update_at(profile, during)
    assert in_event is not None
    assert in_event.decoder_emergency == "nordo"
    assert in_event.squawk not in EMERGENCY_SQUAWKS

    for tick in (before, after):
        update = update_at(profile, tick)
        assert update is not None
        assert update.decoder_emergency is None


def test_the_decoder_emergency_happens_in_the_first_ten_minutes() -> None:
    profile = _decoder_emergency_profile()
    event = profile.emergency
    assert event is not None

    assert profile.spawn_tick + event.start_offset_s < 600
    assert (
        profile.spawn_tick + event.start_offset_s + event.duration_s
        <= profile.spawn_tick + profile.active_ticks
    )
    assert profile.spawn_tick + profile.active_ticks <= PERIOD_S
