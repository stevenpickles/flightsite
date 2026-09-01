"""The demo scenario's aircraft roster: who flies, and how.

:func:`build_roster` is the *only* place randomness enters demo mode. It
consumes a single seeded :class:`random.Random` in a fixed, deterministic
order and produces a tuple of immutable :class:`AircraftProfile` values —
identity, callsign, category and flight-model parameters. Everything after
that (:mod:`flightsite.demo.scenario`) is arithmetic on ``age_s``, so the same
seed always builds the same roster and the same roster always produces the
same batches.

Population and rotation
------------------------

``population`` is the *target concurrent count* the caller asks for, not the
roster size. Aircraft do not stay live forever — a rotating population is
part of the product requirement (SPEC §76) — so the roster is built larger
than ``population`` by :data:`ROSTER_MULTIPLIER`, and each profile is only
"on the air" for a fraction of :data:`~flightsite.demo.scenario.PERIOD_S`.
With the category duty cycles below, the *expected* number of simultaneously
transmitting aircraft lands close to ``population``; it is a deliberately
approximate target (the roadmap calls for "~40-80"), not a hard bound.

Category coverage
------------------

Every :class:`Category` gets at least one profile scheduled to spawn within
the scenario's first :data:`EARLY_SPAWN_WINDOW_S` seconds, so the "all
scenario types observable within the first simulated 10 minutes" acceptance
criterion holds regardless of population size or random chance. The bulk of
the roster (mostly :attr:`Category.COMMERCIAL`) spawns throughout the whole
period, which is what gives the population its ongoing rotation.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from flightsite.demo.motion import offset_position
from flightsite.ingest.types import Position, PositionSource

#: How much larger the roster is than the requested concurrent population, to
#: account for aircraft that are only transmitting part of the time. See the
#: module docstring.
ROSTER_MULTIPLIER: Final = 1.7

#: Aircraft guaranteed to cover every required category spawn within this
#: many simulated seconds, satisfying "all types within the first 10
#: simulated minutes" (SPEC §76) independent of population size.
EARLY_SPAWN_WINDOW_S: Final = 420

#: The rotation period: profiles repeat with this cadence forever. 30 minutes
#: is long enough that a profile's active window (a few minutes to half an
#: hour) and its off-air gap both read as a real aircraft's visit rather than
#: a loop, while ``EARLY_SPAWN_WINDOW_S`` keeps category coverage in the
#: first 10 minutes of *every* period, not just the first.
PERIOD_S: Final = 1800

#: Receiver-relative distance band cruise traffic starts within (nm) — far
#: enough out to look like it is genuinely crossing the display area.
CRUISE_START_RANGE_NM: Final = (60.0, 230.0)

#: Distance band low-altitude local traffic (police, ground) starts within.
LOCAL_START_RANGE_NM: Final = (1.0, 12.0)


class Category(StrEnum):
    """The scenario's aircraft categories — SPEC §76's coverage list."""

    COMMERCIAL = "commercial"
    MILITARY = "military"
    GOVERNMENT = "government"
    POLICE = "police"
    # The value below deliberately avoids readsb's own `type` vocabulary
    # (ADR-0003, tests/ingest/test_no_field_leakage.py), which is reserved to
    # ingest/readsb.py even for an unrelated domain value spelled the same.
    MODE_S = "mode_s_only"
    MLAT = "mlat"
    GROUND = "ground"
    RARE = "rare"
    FIRST_EVER = "first_ever"


@dataclass(frozen=True, slots=True)
class EmergencyEvent:
    """A temporary squawk override applied within an aircraft's active window."""

    squawk: str
    start_offset_s: float
    duration_s: float


@dataclass(frozen=True, slots=True)
class AircraftProfile:
    """Everything :mod:`flightsite.demo.scenario` needs to compute one
    aircraft's state at any tick — built once, read many times.
    """

    icao: str
    callsign: str | None
    category: Category
    position_source: PositionSource

    #: Tick within :data:`PERIOD_S` at which this aircraft starts transmitting.
    spawn_tick: int
    #: How many ticks it stays on the air before falling silent.
    active_ticks: int
    #: Only active on periods where ``loop % rare_loop_modulus == 0``; ``1``
    #: means every period.
    rare_loop_modulus: int
    #: Only active during the scenario's first period (``loop == 0``) —
    #: the "appears once, ever" first-contact aircraft.
    once: bool

    #: ``None`` for aircraft that never report a position (Mode S only).
    start: Position | None
    heading_deg: float
    speed_kt: float
    turn_rate_deg_s: float
    reports_speed_and_track: bool

    #: ``None`` for on-ground aircraft, which report no barometric altitude.
    base_altitude_ft: float | None
    climb_fpm: float
    min_altitude_ft: float
    max_altitude_ft: float

    on_ground: bool
    squawk: str
    rssi_db: float
    emergency: EmergencyEvent | None = None


AIRLINE_CALLSIGN_PREFIXES: Final[tuple[str, ...]] = (
    "DAL",
    "UAL",
    "AAL",
    "SWA",
    "JBU",
    "ASA",
    "FFT",
    "NKS",
    "BAW",
    "DLH",
    "AFR",
    "KLM",
    "UAE",
    "ACA",
    "QFA",
    "VIR",
)

MILITARY_CALLSIGN_PREFIXES: Final[tuple[str, ...]] = (
    "RCH",
    "CNV",
    "HAWG",
    "VIPER",
    "REDEYE",
    "TOGA",
    "GRZLY",
    "SENTRY",
)

#: Realistic Air Force / heavy-lift altitude blocks (SPEC §76: "blocks at
#: varied altitudes").
MILITARY_ALTITUDE_BLOCKS_FT: Final[tuple[float, ...]] = (
    3_000.0,
    5_000.0,
    8_000.0,
    12_000.0,
    18_000.0,
    25_000.0,
    33_000.0,
    41_000.0,
)

GOVERNMENT_CALLSIGN_PREFIXES: Final[tuple[str, ...]] = ("CBP", "NASA", "USFS", "EXEC", "GLEX")

POLICE_CALLSIGN_PREFIXES: Final[tuple[str, ...]] = ("METRO", "AIR", "SHERIFF", "STAR", "EAGLE")

GENERAL_AVIATION_SUFFIXES: Final[tuple[str, ...]] = ("", "A", "B", "CJ", "QS", "XP", "TV", "MD")


def _airline_callsign(rng: random.Random) -> str:
    prefix = rng.choice(AIRLINE_CALLSIGN_PREFIXES)
    return f"{prefix}{rng.randint(1, 3999)}"


def _military_callsign(rng: random.Random) -> str:
    prefix = rng.choice(MILITARY_CALLSIGN_PREFIXES)
    return f"{prefix}{rng.randint(1, 999)}"


def _government_callsign(rng: random.Random) -> str:
    prefix = rng.choice(GOVERNMENT_CALLSIGN_PREFIXES)
    return f"{prefix}{rng.randint(1, 99)}"


def _police_callsign(rng: random.Random) -> str:
    prefix = rng.choice(POLICE_CALLSIGN_PREFIXES)
    return f"{prefix}{rng.randint(1, 20)}"


def _general_aviation_callsign(rng: random.Random) -> str:
    suffix = rng.choice(GENERAL_AVIATION_SUFFIXES)
    return f"N{rng.randint(1, 999)}{suffix}"


def _octal_squawk(rng: random.Random) -> str:
    if rng.random() < 0.4:
        return "1200"
    return f"{rng.randint(0, 7)}{rng.randint(0, 7)}{rng.randint(0, 7)}{rng.randint(0, 7)}"


def _unique_icao(rng: random.Random, used: set[str]) -> str:
    while True:
        candidate = f"{rng.getrandbits(24):06x}"
        if candidate not in used:
            used.add(candidate)
            return candidate


def _cruise_start(rng: random.Random, center: Position) -> tuple[Position, float]:
    """Pick a start point on the fringe of the area, heading roughly inward.

    Returns ``(start, heading_deg)``. The heading points toward the center
    plus jitter, so tracks read as crossing traffic rather than every leg
    converging on one exact point (SPEC §76: "great-circle-ish tracks
    crossing the area").
    """
    distance = rng.uniform(*CRUISE_START_RANGE_NM)
    bearing_from_center = rng.uniform(0.0, 360.0)
    start = offset_position(center, distance_nm=distance, bearing_deg=bearing_from_center)
    heading_to_center = (bearing_from_center + 180.0) % 360.0
    heading = (heading_to_center + rng.uniform(-40.0, 40.0)) % 360.0
    return start, heading


def _local_start(rng: random.Random, center: Position) -> Position:
    distance = rng.uniform(*LOCAL_START_RANGE_NM)
    bearing = rng.uniform(0.0, 360.0)
    return offset_position(center, distance_nm=distance, bearing_deg=bearing)


def _spawn_schedule(
    rng: random.Random, *, early: bool, active_range_s: tuple[int, int]
) -> tuple[int, int]:
    """Return ``(spawn_tick, active_ticks)`` within :data:`PERIOD_S`.

    ``early`` guarantees ``spawn_tick`` leaves the whole active window inside
    :data:`EARLY_SPAWN_WINDOW_S` — used for the one profile per category that
    must be observable in the first simulated 10 minutes.
    """
    active_ticks = rng.randint(*active_range_s)
    if early:
        latest_spawn = max(0, EARLY_SPAWN_WINDOW_S - active_ticks)
        spawn_tick = rng.randint(0, latest_spawn)
    else:
        spawn_tick = rng.randint(0, PERIOD_S - active_ticks)
    return spawn_tick, active_ticks


def _build_commercial(
    rng: random.Random, used_icao: set[str], center: Position, *, early: bool
) -> AircraftProfile:
    start, heading = _cruise_start(rng, center)
    spawn_tick, active_ticks = _spawn_schedule(rng, early=early, active_range_s=(480, 1400))
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=_airline_callsign(rng),
        category=Category.COMMERCIAL,
        position_source="adsb",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=1,
        once=False,
        start=start,
        heading_deg=heading,
        speed_kt=rng.uniform(380.0, 490.0),
        turn_rate_deg_s=rng.uniform(-0.05, 0.05),
        reports_speed_and_track=True,
        base_altitude_ft=rng.uniform(28_000.0, 41_000.0),
        climb_fpm=rng.uniform(-150.0, 150.0),
        min_altitude_ft=27_000.0,
        max_altitude_ft=42_000.0,
        on_ground=False,
        squawk=_octal_squawk(rng),
        rssi_db=rng.uniform(-24.0, -6.0),
    )


def _build_military(
    rng: random.Random, used_icao: set[str], center: Position, *, early: bool
) -> AircraftProfile:
    start, heading = _cruise_start(rng, center)
    spawn_tick, active_ticks = _spawn_schedule(rng, early=early, active_range_s=(300, 900))
    altitude = rng.choice(MILITARY_ALTITUDE_BLOCKS_FT)
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=_military_callsign(rng),
        category=Category.MILITARY,
        position_source="adsb",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=1,
        once=False,
        start=start,
        heading_deg=heading,
        speed_kt=rng.uniform(250.0, 500.0),
        turn_rate_deg_s=rng.uniform(-0.15, 0.15),
        reports_speed_and_track=True,
        base_altitude_ft=altitude,
        climb_fpm=rng.uniform(-100.0, 100.0),
        min_altitude_ft=max(1_000.0, altitude - 2_000.0),
        max_altitude_ft=altitude + 2_000.0,
        on_ground=False,
        squawk=_octal_squawk(rng),
        rssi_db=rng.uniform(-22.0, -4.0),
    )


def _build_government(
    rng: random.Random, used_icao: set[str], center: Position, *, early: bool
) -> AircraftProfile:
    start, heading = _cruise_start(rng, center)
    spawn_tick, active_ticks = _spawn_schedule(rng, early=early, active_range_s=(400, 1000))
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=_government_callsign(rng),
        category=Category.GOVERNMENT,
        position_source="adsb",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=1,
        once=False,
        start=start,
        heading_deg=heading,
        speed_kt=rng.uniform(300.0, 470.0),
        turn_rate_deg_s=rng.uniform(-0.08, 0.08),
        reports_speed_and_track=True,
        base_altitude_ft=rng.uniform(20_000.0, 41_000.0),
        climb_fpm=rng.uniform(-100.0, 100.0),
        min_altitude_ft=18_000.0,
        max_altitude_ft=42_000.0,
        on_ground=False,
        squawk=_octal_squawk(rng),
        rssi_db=rng.uniform(-22.0, -5.0),
    )


def _build_police(
    rng: random.Random, used_icao: set[str], center: Position, *, early: bool
) -> AircraftProfile:
    start = _local_start(rng, center)
    spawn_tick, active_ticks = _spawn_schedule(rng, early=early, active_range_s=(600, 1500))
    turn_rate = rng.uniform(2.0, 4.0) * rng.choice((-1.0, 1.0))
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=_police_callsign(rng),
        category=Category.POLICE,
        position_source="adsb",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=1,
        once=False,
        start=start,
        heading_deg=rng.uniform(0.0, 360.0),
        speed_kt=rng.uniform(60.0, 120.0),
        turn_rate_deg_s=turn_rate,
        reports_speed_and_track=True,
        base_altitude_ft=rng.uniform(500.0, 2_500.0),
        climb_fpm=0.0,
        min_altitude_ft=400.0,
        max_altitude_ft=3_000.0,
        on_ground=False,
        squawk=_octal_squawk(rng),
        rssi_db=rng.uniform(-18.0, -3.0),
    )


def _build_mode_s(rng: random.Random, used_icao: set[str], *, early: bool) -> AircraftProfile:
    spawn_tick, active_ticks = _spawn_schedule(rng, early=early, active_range_s=(300, 900))
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=None,
        category=Category.MODE_S,
        position_source="none",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=1,
        once=False,
        start=None,
        heading_deg=0.0,
        speed_kt=0.0,
        turn_rate_deg_s=0.0,
        reports_speed_and_track=False,
        base_altitude_ft=rng.uniform(2_000.0, 25_000.0),
        climb_fpm=rng.uniform(-100.0, 100.0),
        min_altitude_ft=1_500.0,
        max_altitude_ft=26_000.0,
        on_ground=False,
        squawk=_octal_squawk(rng),
        rssi_db=rng.uniform(-26.0, -8.0),
    )


def _build_mlat(
    rng: random.Random, used_icao: set[str], center: Position, *, early: bool
) -> AircraftProfile:
    start, heading = _cruise_start(rng, center)
    spawn_tick, active_ticks = _spawn_schedule(rng, early=early, active_range_s=(300, 800))
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=_general_aviation_callsign(rng),
        category=Category.MLAT,
        position_source="mlat",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=1,
        once=False,
        start=start,
        heading_deg=heading,
        speed_kt=rng.uniform(100.0, 250.0),
        turn_rate_deg_s=rng.uniform(-0.1, 0.1),
        reports_speed_and_track=True,
        base_altitude_ft=rng.uniform(2_000.0, 15_000.0),
        climb_fpm=rng.uniform(-150.0, 150.0),
        min_altitude_ft=1_000.0,
        max_altitude_ft=16_000.0,
        on_ground=False,
        squawk=_octal_squawk(rng),
        rssi_db=rng.uniform(-26.0, -8.0),
    )


def _build_ground(
    rng: random.Random, used_icao: set[str], center: Position, *, early: bool
) -> AircraftProfile:
    start = _local_start(rng, center)
    spawn_tick, active_ticks = _spawn_schedule(rng, early=early, active_range_s=(200, 700))
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=rng.choice((_airline_callsign, _general_aviation_callsign))(rng),
        category=Category.GROUND,
        position_source="adsb",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=1,
        once=False,
        start=start,
        heading_deg=rng.uniform(0.0, 360.0),
        speed_kt=rng.uniform(0.0, 20.0),
        turn_rate_deg_s=rng.uniform(-1.0, 1.0),
        reports_speed_and_track=True,
        base_altitude_ft=None,
        climb_fpm=0.0,
        min_altitude_ft=0.0,
        max_altitude_ft=0.0,
        on_ground=True,
        squawk=_octal_squawk(rng),
        rssi_db=rng.uniform(-20.0, -4.0),
    )


def _build_rare(
    rng: random.Random, used_icao: set[str], center: Position, *, early: bool
) -> AircraftProfile:
    start, heading = _cruise_start(rng, center)
    spawn_tick, active_ticks = _spawn_schedule(rng, early=early, active_range_s=(200, 500))
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=_general_aviation_callsign(rng),
        category=Category.RARE,
        position_source="adsb",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=3,
        once=False,
        start=start,
        heading_deg=heading,
        speed_kt=rng.uniform(420.0, 500.0),
        turn_rate_deg_s=rng.uniform(-0.05, 0.05),
        reports_speed_and_track=True,
        base_altitude_ft=rng.uniform(35_000.0, 45_000.0),
        climb_fpm=rng.uniform(-100.0, 100.0),
        min_altitude_ft=34_000.0,
        max_altitude_ft=46_000.0,
        on_ground=False,
        squawk=_octal_squawk(rng),
        rssi_db=rng.uniform(-24.0, -6.0),
    )


def _build_first_ever(rng: random.Random, used_icao: set[str], center: Position) -> AircraftProfile:
    start, heading = _cruise_start(rng, center)
    active_ticks = rng.randint(240, 420)
    spawn_tick = rng.randint(0, max(0, EARLY_SPAWN_WINDOW_S - active_ticks))
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=_general_aviation_callsign(rng),
        category=Category.FIRST_EVER,
        position_source="adsb",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=1,
        once=True,
        start=start,
        heading_deg=heading,
        speed_kt=rng.uniform(150.0, 300.0),
        turn_rate_deg_s=rng.uniform(-0.1, 0.1),
        reports_speed_and_track=True,
        base_altitude_ft=rng.uniform(8_000.0, 22_000.0),
        climb_fpm=rng.uniform(-100.0, 100.0),
        min_altitude_ft=6_000.0,
        max_altitude_ft=23_000.0,
        on_ground=False,
        squawk=_octal_squawk(rng),
        rssi_db=rng.uniform(-24.0, -6.0),
    )


def _build_emergency(
    rng: random.Random,
    used_icao: set[str],
    center: Position,
    *,
    squawk: str,
    event_offset_s: float,
) -> AircraftProfile:
    """A commercial-style aircraft that squawks an emergency code once.

    ``event_offset_s`` is measured from spawn, so the two emergency profiles
    (7700, then 7600) can be scheduled to occur one after the other within
    the first 10 simulated minutes.
    """
    start, heading = _cruise_start(rng, center)
    active_ticks = rng.randint(600, 900)
    spawn_tick = rng.randint(0, 120)
    normal_squawk = _octal_squawk(rng)
    return AircraftProfile(
        icao=_unique_icao(rng, used_icao),
        callsign=_airline_callsign(rng),
        category=Category.COMMERCIAL,
        position_source="adsb",
        spawn_tick=spawn_tick,
        active_ticks=active_ticks,
        rare_loop_modulus=1,
        once=False,
        start=start,
        heading_deg=heading,
        speed_kt=rng.uniform(380.0, 470.0),
        turn_rate_deg_s=rng.uniform(-0.05, 0.05),
        reports_speed_and_track=True,
        base_altitude_ft=rng.uniform(30_000.0, 39_000.0),
        climb_fpm=rng.uniform(-100.0, 100.0),
        min_altitude_ft=27_000.0,
        max_altitude_ft=42_000.0,
        on_ground=False,
        squawk=normal_squawk,
        rssi_db=rng.uniform(-22.0, -6.0),
        emergency=EmergencyEvent(squawk=squawk, start_offset_s=event_offset_s, duration_s=120.0),
    )


#: ``(builder, weight)`` pairs used to size the bulk of the roster. Weights
#: are relative, not percentages — see ``_category_counts``.
_WEIGHTED_CATEGORIES: Final[tuple[tuple[Category, float], ...]] = (
    (Category.COMMERCIAL, 0.58),
    (Category.MILITARY, 0.07),
    (Category.GOVERNMENT, 0.04),
    (Category.POLICE, 0.04),
    (Category.MODE_S, 0.08),
    (Category.MLAT, 0.08),
    (Category.GROUND, 0.07),
    (Category.RARE, 0.04),
)


def _category_counts(roster_size: int) -> dict[Category, int]:
    """Split ``roster_size`` across the weighted categories, each getting
    at least one slot (on top of the guaranteed early one built separately).
    """
    counts: dict[Category, int] = {}
    for category, weight in _WEIGHTED_CATEGORIES:
        counts[category] = max(1, round(roster_size * weight))
    return counts


def build_roster(*, seed: int, population: int, center: Position) -> tuple[AircraftProfile, ...]:
    """Build the full, deterministic aircraft roster for one demo session.

    Args:
        seed: drives every random decision below, in a fixed call order —
            the same seed always builds the same roster.
        population: the target *concurrent* aircraft count (see module
            docstring); the roster itself is larger.
        center: the point cruise and local traffic is generated around —
            normally the configured receiver location.

    Returns:
        An immutable tuple, one :class:`AircraftProfile` per category
        representative (each guaranteed to spawn within
        :data:`EARLY_SPAWN_WINDOW_S`) plus the weighted bulk population, plus
        exactly one first-ever aircraft and two dedicated emergency-squawk
        aircraft (7700 then 7600).
    """
    if population < 1:
        raise ValueError("population must be at least 1")

    rng = random.Random(seed)
    used_icao: set[str] = set()
    roster_size = max(len(_WEIGHTED_CATEGORIES), round(population * ROSTER_MULTIPLIER))

    profiles: list[AircraftProfile] = []

    # One guaranteed-early representative per required category, built first
    # so the acceptance criterion holds regardless of what the weighted bulk
    # below happens to roll.
    profiles.append(_build_commercial(rng, used_icao, center, early=True))
    profiles.append(_build_military(rng, used_icao, center, early=True))
    profiles.append(_build_government(rng, used_icao, center, early=True))
    profiles.append(_build_police(rng, used_icao, center, early=True))
    profiles.append(_build_mode_s(rng, used_icao, early=True))
    profiles.append(_build_mlat(rng, used_icao, center, early=True))
    profiles.append(_build_ground(rng, used_icao, center, early=True))
    profiles.append(_build_rare(rng, used_icao, center, early=True))
    profiles.append(_build_first_ever(rng, used_icao, center))
    profiles.append(_build_emergency(rng, used_icao, center, squawk="7700", event_offset_s=90.0))
    profiles.append(_build_emergency(rng, used_icao, center, squawk="7600", event_offset_s=240.0))

    builders: dict[Category, Callable[[], AircraftProfile]] = {
        Category.COMMERCIAL: lambda: _build_commercial(rng, used_icao, center, early=False),
        Category.MILITARY: lambda: _build_military(rng, used_icao, center, early=False),
        Category.GOVERNMENT: lambda: _build_government(rng, used_icao, center, early=False),
        Category.POLICE: lambda: _build_police(rng, used_icao, center, early=False),
        Category.MODE_S: lambda: _build_mode_s(rng, used_icao, early=False),
        Category.MLAT: lambda: _build_mlat(rng, used_icao, center, early=False),
        Category.GROUND: lambda: _build_ground(rng, used_icao, center, early=False),
        Category.RARE: lambda: _build_rare(rng, used_icao, center, early=False),
    }
    for category, count in _category_counts(roster_size).items():
        builder = builders[category]
        for _ in range(count):
            profiles.append(builder())

    return tuple(profiles)


__all__ = [
    "AIRLINE_CALLSIGN_PREFIXES",
    "EARLY_SPAWN_WINDOW_S",
    "GOVERNMENT_CALLSIGN_PREFIXES",
    "MILITARY_ALTITUDE_BLOCKS_FT",
    "MILITARY_CALLSIGN_PREFIXES",
    "PERIOD_S",
    "POLICE_CALLSIGN_PREFIXES",
    "ROSTER_MULTIPLIER",
    "AircraftProfile",
    "Category",
    "EmergencyEvent",
    "build_roster",
]
