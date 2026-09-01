"""Realism sanity: plausible numbers, and tracks that move rather than jump.

Iterates :func:`~flightsite.demo.scenario.update_at` directly (a pure
function), rather than driving a live store — these are properties of the
motion model and the roster's generated ranges, independent of ingestion or
lifecycle behavior, which the other test modules in this package cover.
"""

from __future__ import annotations

from typing import Final

from flightsite.demo import build_roster
from flightsite.demo.adapter import DEFAULT_CENTER, DEFAULT_SEED
from flightsite.demo.roster import AircraftProfile
from flightsite.demo.scenario import update_at
from flightsite.live.geo import distance_nm

POPULATION: Final = 60

#: Generous "did not teleport" bound: even a 500 kt airliner moves under
#: 0.14 nm in one second, and the fastest demo category (commercial, up to
#: 490 kt) stays comfortably under this per-tick step.
MAX_STEP_NM_PER_TICK: Final = 0.5

#: Plausible barometric altitude band across every category the roster
#: generates (SPEC §76's "realistic ... altitudes").
MIN_PLAUSIBLE_ALTITUDE_FT: Final = -1_000.0
MAX_PLAUSIBLE_ALTITUDE_FT: Final = 46_000.0

MAX_PLAUSIBLE_GROUND_SPEED_KT: Final = 600.0
MAX_PLAUSIBLE_VERTICAL_RATE_FPM: Final = 2_000.0


def _roster() -> tuple[AircraftProfile, ...]:
    return build_roster(seed=DEFAULT_SEED, population=POPULATION, center=DEFAULT_CENTER)


def test_altitudes_speeds_and_vertical_rates_stay_within_plausible_bounds() -> None:
    checked = 0
    for profile in _roster():
        window = range(profile.spawn_tick, profile.spawn_tick + profile.active_ticks, 5)
        for tick in window:
            update = update_at(profile, tick)
            assert update is not None
            if update.altitude_ft is not None:
                assert MIN_PLAUSIBLE_ALTITUDE_FT <= update.altitude_ft <= MAX_PLAUSIBLE_ALTITUDE_FT
                checked += 1
            if update.ground_speed_kt is not None:
                assert 0.0 <= update.ground_speed_kt <= MAX_PLAUSIBLE_GROUND_SPEED_KT
            if update.vertical_rate_fpm is not None:
                assert abs(update.vertical_rate_fpm) <= MAX_PLAUSIBLE_VERTICAL_RATE_FPM

    assert checked > 0


def test_positions_move_smoothly_with_no_teleporting() -> None:
    checked_steps = 0
    for profile in _roster():
        if profile.start is None:
            continue  # Mode S: never positioned, nothing to check.

        previous_position = None
        for tick in range(profile.spawn_tick, profile.spawn_tick + profile.active_ticks):
            update = update_at(profile, tick)
            assert update is not None
            if update.position is None:
                continue
            if previous_position is not None:
                step_nm = distance_nm(previous_position, update.position)
                assert step_nm <= MAX_STEP_NM_PER_TICK, (
                    f"{profile.icao} jumped {step_nm:.3f} nm in one tick at {tick=}"
                )
                checked_steps += 1
            previous_position = update.position

    assert checked_steps > 0


def test_squawks_are_well_formed_four_digit_octal() -> None:
    for profile in _roster():
        for tick in (profile.spawn_tick, profile.spawn_tick + profile.active_ticks - 1):
            update = update_at(profile, tick)
            assert update is not None
            squawk = update.squawk
            assert squawk is not None
            assert len(squawk) == 4
            assert all(digit in "01234567" for digit in squawk)


def test_callsigns_are_stable_for_the_life_of_an_aircraft() -> None:
    """A single aircraft's callsign never changes mid-session — SPEC §76's
    "callsigns consistent per aircraft per session".
    """
    for profile in _roster():
        callsigns: set[str | None] = set()
        for tick in range(profile.spawn_tick, profile.spawn_tick + profile.active_ticks, 11):
            update = update_at(profile, tick)
            assert update is not None
            callsigns.add(update.callsign)
        assert len(callsigns) == 1
