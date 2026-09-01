"""Merge semantics, derived fields, provenance, and ground-state conservatism.

These are the rules that decide what the live picture actually says, so they
are asserted directly against :func:`~flightsite.live.aircraft.appear` and
:func:`~flightsite.live.aircraft.merge` rather than only through the store.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from flightsite.ingest import Position
from flightsite.live.aircraft import (
    AIRBORNE_INFERENCE_ALTITUDE_FT,
    GroundState,
    LiveAircraft,
    Provenance,
    appear,
    merge,
)

from .conftest import BASE_TIME, SEATTLE, ManualClock, make_update

#: Roughly 110 nm north-north-east of the Seattle receiver.
AIRBORNE_POSITION = Position(latitude=49.0, longitude=-121.0)


def first(**fields: Any) -> LiveAircraft:
    """One aircraft's first observation, with a configured receiver."""
    return appear(make_update(**fields), now=0.0, receiver=SEATTLE)


# --------------------------------------------------------------- merge rules


def test_a_partial_update_does_not_erase_known_fields() -> None:
    clock = ManualClock()
    current = first(callsign="RCH492", squawk="4521", altitude_ft=25_000.0, on_ground=False)

    merged, _ = merge(current, make_update(offset_s=1.0, rssi_db=-12.1), now=clock(), receiver=None)

    assert merged.callsign == "RCH492"
    assert merged.squawk == "4521"
    assert merged.altitude_ft == 25_000.0
    assert merged.rssi_db == -12.1


def test_a_position_survives_an_update_that_carries_none() -> None:
    # An aircraft that drops to Mode S-only keeps its last known position and
    # that position's source; position_seen records how old it now is.
    current = first(position=AIRBORNE_POSITION, position_source="mlat")

    merged, _ = merge(current, make_update(offset_s=5.0), now=5.0, receiver=SEATTLE)

    assert merged.position == AIRBORNE_POSITION
    assert merged.position_source == "mlat"
    assert merged.position_seen == BASE_TIME
    assert merged.last_seen > merged.position_seen
    assert merged.position_age_s(5.0) == 5.0


def test_a_callsign_change_is_reported_as_a_changed_field() -> None:
    current = first(callsign="RCH492")

    merged, changed = merge(
        current, make_update(offset_s=1.0, callsign="RCH493"), now=1.0, receiver=None
    )

    assert merged.callsign == "RCH493"
    assert "callsign" in changed


def test_per_poll_bookkeeping_is_not_reported_as_a_change() -> None:
    # seen_s changes on literally every poll; including it would make the hint
    # set constant and therefore useless.
    current = first(callsign="RCH492", seen_s=0.1)

    _, changed = merge(
        current, make_update(offset_s=1.0, callsign="RCH492", seen_s=0.4), now=1.0, receiver=None
    )

    assert changed == frozenset()


def test_identity_fields_carry_their_own_timestamps() -> None:
    current = first(callsign="RCH492")

    merged, _ = merge(current, make_update(offset_s=30.0, squawk="4521"), now=30.0, receiver=None)

    assert merged.callsign_seen == BASE_TIME
    assert merged.squawk_seen == BASE_TIME + timedelta(seconds=30)
    assert merged.last_seen == merged.squawk_seen


def test_observations_are_counted() -> None:
    current = first()

    merged, _ = merge(current, make_update(offset_s=1.0), now=1.0, receiver=None)

    assert current.observations == 1
    assert merged.observations == 2


def test_merging_leaves_the_previous_record_untouched() -> None:
    # Records are immutable, which is what makes a snapshot safe to hold.
    current = first(callsign="RCH492")

    merge(current, make_update(offset_s=1.0, callsign="RCH493"), now=1.0, receiver=None)

    assert current.callsign == "RCH492"


# ------------------------------------------------------------ non-positioned


def test_a_never_positioned_aircraft_is_a_first_class_record() -> None:
    aircraft = first(callsign="N12345", squawk="1200")

    assert aircraft.has_position is False
    assert aircraft.position is None
    assert aircraft.position_source == "none"
    assert aircraft.position_seen is None
    assert aircraft.position_age_s(10.0) is None
    assert aircraft.callsign == "N12345"


def test_a_non_positioned_aircraft_has_no_derived_range() -> None:
    aircraft = first(callsign="N12345")

    assert aircraft.distance_nm is None
    assert aircraft.bearing_deg is None
    assert "distance_nm" not in aircraft.provenance


# ------------------------------------------------------------ derived fields


def test_distance_and_bearing_are_derived_from_the_receiver() -> None:
    aircraft = first(position=AIRBORNE_POSITION)

    assert aircraft.distance_nm is not None
    assert aircraft.bearing_deg is not None
    assert aircraft.distance_nm == pytest.approx(106.76, abs=0.05)
    assert aircraft.bearing_deg == pytest.approx(28.88, abs=0.05)
    assert aircraft.provenance["distance_nm"] is Provenance.DERIVED
    assert aircraft.provenance["bearing_deg"] is Provenance.DERIVED


def test_an_unset_receiver_yields_no_derived_range() -> None:
    # The first-run state, before the setup wizard has collected a location:
    # the live picture still works, it simply has no receiver-relative fields.
    aircraft = appear(make_update(position=AIRBORNE_POSITION), now=0.0, receiver=None)

    assert aircraft.position == AIRBORNE_POSITION
    assert aircraft.distance_nm is None
    assert aircraft.bearing_deg is None
    assert dict(aircraft.provenance) == {}


def test_range_is_recomputed_once_a_receiver_location_arrives() -> None:
    aircraft = appear(make_update(position=AIRBORNE_POSITION), now=0.0, receiver=None)

    merged, changed = merge(
        aircraft, make_update(offset_s=1.0, position=AIRBORNE_POSITION), now=1.0, receiver=SEATTLE
    )

    assert merged.distance_nm is not None
    assert "distance_nm" in changed


# ------------------------------------------------------- ground determination


def test_the_decoder_ground_flag_wins_and_is_tagged_decoder() -> None:
    aircraft = first(on_ground=True)

    assert aircraft.ground_state is GroundState.ON_GROUND
    assert aircraft.provenance["ground_state"] is Provenance.DECODER


def test_the_decoder_airborne_flag_wins_over_a_low_altitude() -> None:
    aircraft = first(on_ground=False, altitude_ft=250.0)

    assert aircraft.ground_state is GroundState.AIRBORNE
    assert aircraft.provenance["ground_state"] is Provenance.DECODER


def test_a_ground_report_clears_a_stale_cruise_altitude() -> None:
    # The decoder's ground sentinel states there is no barometric altitude to
    # report; leaving 25 000 ft attached to a parked aircraft would be wrong.
    current = first(altitude_ft=25_000.0)

    merged, changed = merge(
        current, make_update(offset_s=1.0, on_ground=True), now=1.0, receiver=None
    )

    assert merged.altitude_ft is None
    assert merged.ground_state is GroundState.ON_GROUND
    assert "altitude_ft" in changed


def test_a_high_altitude_infers_airborne_and_is_tagged_derived() -> None:
    aircraft = first(altitude_ft=AIRBORNE_INFERENCE_ALTITUDE_FT)

    assert aircraft.on_ground is None
    assert aircraft.ground_state is GroundState.AIRBORNE
    assert aircraft.provenance["ground_state"] is Provenance.DERIVED


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"altitude_ft": AIRBORNE_INFERENCE_ALTITUDE_FT - 1.0}, id="just-below-fl180"),
        pytest.param({"altitude_ft": 200.0, "ground_speed_kt": 15.0}, id="slow-and-low"),
        pytest.param({"ground_speed_kt": 0.0}, id="stationary-no-altitude"),
        pytest.param({"altitude_ft": 5_000.0, "ground_speed_kt": 120.0}, id="low-cruise"),
        pytest.param({}, id="nothing-reported"),
    ],
)
def test_ground_state_stays_unknown_without_confident_evidence(fields: dict[str, float]) -> None:
    # Deciding "on the ground" needs terrain or field elevation, which arrives
    # with the airport dataset in slice 027. Until then, unknown is the honest
    # answer and no provenance entry is recorded for it.
    aircraft = first(**fields)

    assert aircraft.ground_state is GroundState.UNKNOWN
    assert "ground_state" not in aircraft.provenance


def test_a_ground_determination_persists_until_the_decoder_revises_it() -> None:
    current = first(on_ground=True)

    merged, _ = merge(current, make_update(offset_s=1.0), now=1.0, receiver=None)

    assert merged.on_ground is True
    assert merged.ground_state is GroundState.ON_GROUND


# ------------------------------------------------------ track accumulation


def test_positions_accumulate_into_the_track_in_order() -> None:
    aircraft = first(position=Position(latitude=47.0, longitude=-122.0))
    for index in range(1, 4):
        aircraft, _ = merge(
            aircraft,
            make_update(
                offset_s=float(index),
                position=Position(latitude=47.0 + index * 0.1, longitude=-122.0),
            ),
            now=float(index),
            receiver=SEATTLE,
        )

    assert [round(p.latitude, 1) for p in aircraft.track.points()] == [47.0, 47.1, 47.2, 47.3]


def test_a_non_positioned_update_adds_no_track_point() -> None:
    aircraft = first(position=Position(latitude=47.0, longitude=-122.0))

    aircraft, _ = merge(aircraft, make_update(offset_s=1.0), now=1.0, receiver=SEATTLE)

    assert len(aircraft.track) == 1


def test_a_never_positioned_aircraft_has_an_empty_track() -> None:
    assert len(first(callsign="N12345").track) == 0


def test_the_track_is_shared_across_successive_records() -> None:
    # Successive records are new objects, but the track they carry is the one
    # append-only history of that aircraft.
    aircraft = first(position=Position(latitude=47.0, longitude=-122.0))

    merged, _ = merge(
        aircraft,
        make_update(offset_s=1.0, position=Position(latitude=47.1, longitude=-122.0)),
        now=1.0,
        receiver=SEATTLE,
    )

    assert merged.track is aircraft.track
    assert len(merged.track) == 2
