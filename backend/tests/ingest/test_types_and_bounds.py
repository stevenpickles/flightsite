"""Domain-type invariants and the plausibility bounds that protect them."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from flightsite.ingest import bounds
from flightsite.ingest.types import (
    AircraftStateBatch,
    AircraftStateUpdate,
    DecoderEndpoint,
    Position,
)

MOMENT = datetime(2025, 9, 17, 16, 0, tzinfo=UTC)


# ------------------------------------------------------- domain types


def test_icao_must_be_lowercase_six_hex() -> None:
    for bad in ("4CA87C", "4ca87", "4ca87cc", "zzzzzz", "", "~4ca87c"):
        with pytest.raises(ValueError, match="icao"):
            AircraftStateUpdate(icao=bad, timestamp=MOMENT)


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        AircraftStateUpdate(icao="4ca87c", timestamp=datetime(2025, 9, 17, 16, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        AircraftStateBatch(timestamp=datetime(2025, 9, 17, 16, 0))


def test_a_position_source_other_than_none_requires_a_position() -> None:
    # "none" is the canonical value for an aircraft tracked without a position
    # (docs/API.md §2.8); claiming adsb/mlat/other without one would be a lie.
    for source in ("adsb", "mlat", "other"):
        with pytest.raises(ValueError, match="requires a position"):
            AircraftStateUpdate(icao="4ca87c", timestamp=MOMENT, position_source=source)


def test_an_update_without_a_position_defaults_to_none() -> None:
    update = AircraftStateUpdate(icao="4ca87c", timestamp=MOMENT)

    assert update.position_source == "none"
    assert update.has_position is False


def test_updates_are_frozen() -> None:
    update = AircraftStateUpdate(icao="4ca87c", timestamp=MOMENT)

    with pytest.raises(AttributeError):
        update.icao = "406a3d"  # type: ignore[misc]


def test_batch_reports_its_own_counters() -> None:
    empty = AircraftStateBatch(timestamp=MOMENT)

    assert len(empty) == 0
    assert empty.skipped == 0
    assert empty.skipped_non_icao == 0
    assert list(empty) == []


def test_endpoint_url_normalizes_a_missing_leading_slash() -> None:
    assert (
        DecoderEndpoint(host="pi.local", port=8080, path="data/aircraft.json").url
        == "http://pi.local:8080/data/aircraft.json"
    )


def test_position_is_a_value() -> None:
    assert Position(latitude=1.0, longitude=2.0) == Position(latitude=1.0, longitude=2.0)


# ------------------------------------------------------------ bounds


@pytest.mark.parametrize("value", [True, False, "3", None, [], {}, float("nan"), float("inf")])
def test_as_float_rejects_everything_that_is_not_a_finite_number(value: object) -> None:
    assert bounds.as_float(value) is None


def test_as_float_accepts_ints_and_floats() -> None:
    assert bounds.as_float(3) == 3.0
    assert bounds.as_float(-2.5) == -2.5


def test_as_int_accepts_integral_floats_only() -> None:
    assert bounds.as_int(1234.0) == 1234
    assert bounds.as_int(1234) == 1234
    assert bounds.as_int(12.5) is None


def test_as_text_strips_decoder_padding() -> None:
    assert bounds.as_text("BAW117  ") == "BAW117"
    assert bounds.as_text("        ") is None
    assert bounds.as_text(117) is None


def test_as_bool_accepts_only_real_booleans() -> None:
    assert bounds.as_bool(True) is True
    assert bounds.as_bool(1) is None


@pytest.mark.parametrize(
    ("function", "inside", "outside"),
    [
        (bounds.latitude, 51.5, 90.1),
        (bounds.longitude, -0.12, -180.5),
        (bounds.altitude_ft, 41000.0, 200000.0),
        (bounds.altitude_ft, -1500.0, -5000.0),
        (bounds.ground_speed_kt, 480.0, -1.0),
        (bounds.ground_speed_kt, 0.0, 9000.0),
        (bounds.vertical_rate_fpm, -3200.0, 120000.0),
        (bounds.rssi_db, -21.4, 99.0),
        (bounds.age_s, 12.5, -0.5),
        (bounds.unix_time_s, 1758124800.0, 0.0),
    ],
)
def test_bounds_keep_plausible_values_and_drop_the_rest(
    function: Callable[[object], float | None], inside: float, outside: float
) -> None:
    assert function(inside) == inside
    assert function(outside) is None


def test_track_360_is_folded_onto_zero() -> None:
    assert bounds.track_deg(360.0) == 0.0
    assert bounds.track_deg(359.9) == 359.9
    assert bounds.track_deg(360.1) is None


def test_message_counts_must_not_be_negative() -> None:
    assert bounds.message_count(0) == 0
    assert bounds.message_count(18422) == 18422
    assert bounds.message_count(-1) is None


def test_bounded_int_honours_an_optional_ceiling() -> None:
    assert bounds.bounded_int(5, 0, 10) == 5
    assert bounds.bounded_int(11, 0, 10) is None
    assert bounds.bounded_int(5, 6) is None
