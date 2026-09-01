"""The confidence gates, as a table.

The service drives these through live events (``test_service.py``); here they
are exercised directly, one gate at a time, because the rules are what SPEC §23
means by *"when confidence is sufficient"* and they deserve to be readable as a
list rather than inferred from a track.

The asymmetry every case here is checking: the cost of a missing inference is a
blank field, and the cost of a wrong one is FlightSite stating something untrue
(SPEC §39). So every ambiguous input must produce ``None``.
"""

from __future__ import annotations

import pytest

from flightsite.airports.index import NearestAirport
from flightsite.airports.inference import (
    ARRIVAL_MAX_DISTANCE_NM,
    CONTEXT_CEILING_FT,
    DEPARTURE_MAX_DISTANCE_NM,
    MIN_TREND_DELTA_NM,
    MIN_VERTICAL_RATE_FPM,
    ON_GROUND_MAX_DISTANCE_NM,
    PHASE_CEILING_AGL_FT,
    TREND_WINDOW_MS,
    Kinematics,
    TrendSample,
    height_above_field,
    in_context,
    infer_phase,
    trail_window_start,
)
from flightsite.airports.model import InferredPhase
from tests.airports.conftest import airport

NOW_MS = 1_700_000_000_000

KBFI = airport("KBFI", 47.53, -122.30, elevation_ft=21)
KHIGH = airport("KHIGH", 39.0, -106.0, elevation_ft=9_000)
KNOEL = airport("KNOEL", 30.0, -90.0, elevation_ft=None)


def near(record: object = KBFI, distance_nm: float = 5.0) -> NearestAirport:
    """A nearest-airport result at a chosen range."""
    return NearestAirport(airport=record, distance_nm=distance_nm)  # type: ignore[arg-type]


def moving(
    *,
    altitude_ft: float | None = 2_000.0,
    vertical_rate_fpm: float | None = -800.0,
    on_ground: bool | None = False,
    ts_ms: int = NOW_MS,
) -> Kinematics:
    return Kinematics(
        altitude_ft=altitude_ft,
        vertical_rate_fpm=vertical_rate_fpm,
        on_ground=on_ground,
        ts_ms=ts_ms,
    )


def closing(ident: str = "KBFI", *, from_nm: float = 9.0, seconds_ago: float = 30.0):  # type: ignore[no-untyped-def]
    """A trail showing the aircraft was further out ``seconds_ago``."""
    return [TrendSample(ident=ident, distance_nm=from_nm, ts_ms=NOW_MS - int(seconds_ago * 1_000))]


def opening(ident: str = "KBFI", *, from_nm: float = 1.0, seconds_ago: float = 30.0):  # type: ignore[no-untyped-def]
    """A trail showing the aircraft was closer ``seconds_ago``."""
    return [TrendSample(ident=ident, distance_nm=from_nm, ts_ms=NOW_MS - int(seconds_ago * 1_000))]


# ----------------------------------------------------- height above the field


def test_height_is_measured_above_the_field() -> None:
    """Nine thousand feet over a nine-thousand-foot field is on the ground."""
    assert height_above_field(9_000.0, 9_000) == pytest.approx(0.0)


def test_a_field_with_no_elevation_is_read_as_sea_level() -> None:
    """The ~16% case. Documented, and deliberately not a reason to skip a field."""
    assert height_above_field(2_000.0, None) == pytest.approx(2_000.0)


def test_no_altitude_has_no_height() -> None:
    assert height_above_field(None, 21) is None


# ------------------------------------------------- gates 2 and 3: in context


def test_a_low_aircraft_near_a_field_is_in_context() -> None:
    assert in_context(near(distance_nm=5.0), moving(altitude_ft=3_000.0))


def test_a_field_beyond_the_search_radius_is_not_context() -> None:
    """Beyond this, "nearest airport" stops being context and becomes trivia."""
    from flightsite.airports.inference import NEAREST_SEARCH_NM

    far = near(distance_nm=NEAREST_SEARCH_NM + 0.1)

    assert not in_context(far, moving(altitude_ft=1_000.0))


def test_cruise_traffic_is_not_in_context() -> None:
    """The gate that keeps the whole sky out of the panel."""
    assert not in_context(near(distance_nm=0.5), moving(altitude_ft=35_000.0))


def test_the_ceiling_is_measured_above_the_field_not_the_sea() -> None:
    """At a 9 000 ft field, 15 000 ft indicated is 6 000 ft above the runway."""
    assert in_context(near(KHIGH, distance_nm=4.0), moving(altitude_ft=15_000.0))
    # The same indicated altitude over a sea-level field is not.
    assert not in_context(near(KNOEL, distance_nm=4.0), moving(altitude_ft=15_000.0))


def test_the_context_ceiling_is_the_ceiling() -> None:
    assert in_context(near(), moving(altitude_ft=CONTEXT_CEILING_FT + 21.0))
    assert not in_context(near(), moving(altitude_ft=CONTEXT_CEILING_FT + 22.0))


def test_an_aircraft_with_no_altitude_and_no_ground_state_is_not_in_context() -> None:
    """It might be at circuit height or at FL400; §2.7 says say nothing."""
    assert not in_context(near(), moving(altitude_ft=None, on_ground=None))


def test_an_aircraft_on_the_ground_at_a_field_is_in_context() -> None:
    """The most certain thing the module ever says, and it needs no altitude."""
    kinematics = moving(altitude_ft=None, vertical_rate_fpm=None, on_ground=True)

    assert in_context(near(distance_nm=ON_GROUND_MAX_DISTANCE_NM - 0.1), kinematics)


def test_an_aircraft_on_the_ground_far_from_a_field_is_not_at_it() -> None:
    """A helicopter on a hospital pad eight miles away is not at the airport."""
    kinematics = moving(altitude_ft=None, vertical_rate_fpm=None, on_ground=True)

    assert not in_context(near(distance_nm=ON_GROUND_MAX_DISTANCE_NM + 0.1), kinematics)


# ------------------------------------------------------------ gate 5: ground


def test_an_aircraft_on_the_ground_gets_no_phase() -> None:
    """Parked is neither arriving nor departing, and guessing would be fabrication."""
    kinematics = moving(altitude_ft=None, vertical_rate_fpm=None, on_ground=True)

    assert infer_phase(near(distance_nm=0.5), kinematics, closing()) is None


# ------------------------------------------------------- gate 6: level flight


@pytest.mark.parametrize("rate", [None, 0.0, 64.0, -64.0, MIN_VERTICAL_RATE_FPM - 1])
def test_level_flight_gets_no_phase(rate: float | None) -> None:
    """A transit, a hold, a circuit or a helicopter — all the same from here."""
    found = infer_phase(near(), moving(vertical_rate_fpm=rate), closing())

    assert found is None


# -------------------------------------------------------- gate 7: too high


def test_a_descent_far_above_the_field_gets_no_phase() -> None:
    """Descending through 8 000 ft over a field is descending *over* it."""
    kinematics = moving(altitude_ft=PHASE_CEILING_AGL_FT + 2_000.0, vertical_rate_fpm=-1_500.0)

    assert infer_phase(near(), kinematics, closing()) is None


def test_the_phase_ceiling_is_measured_above_the_field() -> None:
    """At a 9 000 ft field the same indicated altitude is inside the gate."""
    kinematics = moving(altitude_ft=12_000.0, vertical_rate_fpm=-900.0)

    high = infer_phase(near(KHIGH, distance_nm=6.0), kinematics, closing("KHIGH"))
    sea_level = infer_phase(near(KNOEL, distance_nm=6.0), kinematics, closing("KNOEL"))

    assert high is InferredPhase.ARRIVING
    assert sea_level is None


# ------------------------------------------------------ gate 8: too far out


def test_a_descent_beyond_the_arrival_gate_gets_no_phase() -> None:
    kinematics = moving(altitude_ft=3_000.0, vertical_rate_fpm=-900.0)
    far = near(distance_nm=ARRIVAL_MAX_DISTANCE_NM + 0.1)

    assert infer_phase(far, kinematics, closing(from_nm=25.0)) is None


def test_a_climb_beyond_the_departure_gate_gets_no_phase() -> None:
    """Tighter than the arrival gate: a departure is a fact about where it *was*."""
    kinematics = moving(altitude_ft=3_000.0, vertical_rate_fpm=1_500.0)
    far = near(distance_nm=DEPARTURE_MAX_DISTANCE_NM + 0.1)

    assert infer_phase(far, kinematics, opening(from_nm=1.0)) is None


# ------------------------------------------------------------ gate 9: trend


def test_a_descent_closing_on_a_field_is_an_arrival() -> None:
    kinematics = moving(altitude_ft=2_000.0, vertical_rate_fpm=-800.0)

    assert infer_phase(near(distance_nm=5.0), kinematics, closing()) is InferredPhase.ARRIVING


def test_a_climb_leaving_a_field_is_a_departure() -> None:
    kinematics = moving(altitude_ft=1_500.0, vertical_rate_fpm=1_800.0)

    assert infer_phase(near(distance_nm=4.0), kinematics, opening()) is InferredPhase.DEPARTING


def test_a_descent_moving_away_from_a_field_is_not_an_arrival() -> None:
    """Descending *past* a field. The gate the whole trend mechanism is for."""
    kinematics = moving(altitude_ft=2_000.0, vertical_rate_fpm=-1_200.0)

    assert infer_phase(near(distance_nm=8.0), kinematics, opening(from_nm=2.0)) is None


def test_a_climb_closing_on_a_field_is_not_a_departure() -> None:
    """An aircraft climbing *toward* a field did not just leave it."""
    kinematics = moving(altitude_ft=2_000.0, vertical_rate_fpm=1_500.0)

    assert infer_phase(near(distance_nm=4.0), kinematics, closing()) is None


def test_a_single_observation_never_produces_a_phase() -> None:
    """However suggestive its numbers are: one point has no direction."""
    kinematics = moving(altitude_ft=1_000.0, vertical_rate_fpm=-900.0)

    assert infer_phase(near(distance_nm=2.0), kinematics, []) is None


def test_movement_below_the_trend_floor_is_not_a_trend() -> None:
    """Comfortably above position jitter; a real approach covers it in seconds."""
    kinematics = moving(altitude_ft=2_000.0, vertical_rate_fpm=-800.0)
    barely = [
        TrendSample(
            ident="KBFI",
            distance_nm=5.0 + MIN_TREND_DELTA_NM - 0.05,
            ts_ms=NOW_MS - 30_000,
        )
    ]

    assert infer_phase(near(distance_nm=5.0), kinematics, barely) is None


def test_a_sample_older_than_the_window_does_not_count() -> None:
    """A stale sample from an earlier pass over the same field is not this pass."""
    kinematics = moving(altitude_ft=2_000.0, vertical_rate_fpm=-800.0)
    stale = [
        TrendSample(ident="KBFI", distance_nm=20.0, ts_ms=NOW_MS - TREND_WINDOW_MS - 1),
    ]

    assert infer_phase(near(distance_nm=5.0), kinematics, stale) is None


def test_a_trail_that_changed_fields_disqualifies_the_trend() -> None:
    """Crossing from one field's neighbourhood into another's.

    Neither end of the trend then describes an approach to *this* field, so the
    reading is refused rather than measured against a mixed baseline.
    """
    kinematics = moving(altitude_ft=2_000.0, vertical_rate_fpm=-800.0)
    mixed = [
        TrendSample(ident="KSEA", distance_nm=12.0, ts_ms=NOW_MS - 40_000),
        TrendSample(ident="KBFI", distance_nm=9.0, ts_ms=NOW_MS - 20_000),
    ]

    assert infer_phase(near(distance_nm=5.0), kinematics, mixed) is None


def test_a_stale_sample_for_another_field_does_not_disqualify_the_trend() -> None:
    """Only what is inside the window is evidence, for or against."""
    kinematics = moving(altitude_ft=2_000.0, vertical_rate_fpm=-800.0)
    trail = [
        TrendSample(ident="KSEA", distance_nm=12.0, ts_ms=NOW_MS - TREND_WINDOW_MS - 1),
        TrendSample(ident="KBFI", distance_nm=9.0, ts_ms=NOW_MS - 20_000),
    ]

    assert infer_phase(near(distance_nm=5.0), kinematics, trail) is InferredPhase.ARRIVING


def test_the_window_start_is_the_gate_the_service_prunes_with() -> None:
    """One definition of the window, shared, rather than two that could drift."""
    assert trail_window_start(NOW_MS) == NOW_MS - TREND_WINDOW_MS


def test_an_aircraft_with_no_altitude_but_a_rate_gets_no_phase() -> None:
    """Height above the field is not optional for a claim about that field."""
    kinematics = moving(altitude_ft=None, vertical_rate_fpm=-900.0, on_ground=False)

    assert infer_phase(near(distance_nm=3.0), kinematics, closing()) is None
