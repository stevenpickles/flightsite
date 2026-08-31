"""Validation-error tests: bad values must be rejected with a helpful message."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from flightsite.config import (
    AlertSettings,
    EnrichmentSettings,
    LocationSettings,
    MapSettings,
    ReceiverSettings,
    RetentionSettings,
    Settings,
    SightingTimingSettings,
)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91.0, 0.0), (-90.5, 0.0), (0.0, 181.0), (0.0, -180.5)],
)
def test_out_of_range_coordinates_are_rejected(latitude: float, longitude: float) -> None:
    with pytest.raises(ValidationError) as excinfo:
        LocationSettings(latitude=latitude, longitude=longitude)

    assert excinfo.value.error_count() == 1


def test_valid_coordinates_are_accepted() -> None:
    location = LocationSettings(latitude=51.4775, longitude=-0.4614, site_name="Heathrow")

    assert location.is_configured is True


def test_half_configured_location_is_rejected() -> None:
    with pytest.raises(ValidationError, match="both latitude and longitude"):
        LocationSettings(latitude=51.5)


@pytest.mark.parametrize("timezone", ["Mars/Olympus_Mons", "Not A Zone", "", "UTC+1"])
def test_unknown_timezone_is_rejected_with_a_helpful_message(timezone: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(timezone=timezone)

    message = str(excinfo.value)
    assert "unknown IANA timezone" in message
    assert "Europe/London" in message


@pytest.mark.parametrize("timezone", ["UTC", "Europe/London", "America/New_York"])
def test_known_timezones_are_accepted(timezone: str) -> None:
    assert Settings(timezone=timezone).timezone == timezone


@pytest.mark.parametrize("radius", [0.0, -5.0, 20000.0])
def test_invalid_display_radius_is_rejected(radius: float) -> None:
    with pytest.raises(ValidationError):
        Settings(display_radius_nm=radius)


def test_alert_radius_none_means_unlimited() -> None:
    assert Settings(alert_radius_nm=None).alert_radius_nm is None


def test_zero_alert_radius_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(alert_radius_nm=0.0)


@pytest.mark.parametrize("days", [0, 6, 31, 365])
def test_retention_window_outside_7_to_30_days_is_rejected(days: int) -> None:
    with pytest.raises(ValidationError):
        RetentionSettings(high_res_metric_days=days)


@pytest.mark.parametrize("days", [7, 14, 30])
def test_retention_window_within_range_is_accepted(days: int) -> None:
    assert RetentionSettings(high_res_metric_days=days).high_res_metric_days == days


def test_unknown_unit_system_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(units="furlongs")  # type: ignore[arg-type]


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="CHATTY")  # type: ignore[arg-type]


@pytest.mark.parametrize("port", [0, -1, 70000])
def test_invalid_receiver_port_is_rejected(port: int) -> None:
    with pytest.raises(ValidationError):
        ReceiverSettings(port=port)


def test_blank_receiver_host_is_rejected() -> None:
    with pytest.raises(ValidationError, match="blank"):
        ReceiverSettings(host="   ")


def test_receiver_path_must_be_absolute() -> None:
    with pytest.raises(ValidationError, match="must start with"):
        ReceiverSettings(path="data/aircraft.json")


@pytest.mark.parametrize("interval", [0.0, -1.0, 61.0])
def test_invalid_poll_interval_is_rejected(interval: float) -> None:
    with pytest.raises(ValidationError):
        ReceiverSettings(poll_interval_s=interval)


def test_sighting_timings_must_increase() -> None:
    with pytest.raises(ValidationError, match="stale_s < remove_s < close_s"):
        SightingTimingSettings(stale_s=90.0, remove_s=60.0, close_s=600.0)


def test_sighting_timings_in_order_are_accepted() -> None:
    timing = SightingTimingSettings(stale_s=10.0, remove_s=45.0, close_s=300.0)

    assert timing.remove_s == 45.0


def test_range_rings_are_sorted_and_deduplicated_or_rejected() -> None:
    assert MapSettings(range_ring_radii_nm=[200.0, 50.0]).range_ring_radii_nm == [50.0, 200.0]

    with pytest.raises(ValidationError, match="unique"):
        MapSettings(range_ring_radii_nm=[50.0, 50.0])

    with pytest.raises(ValidationError, match="greater than 0"):
        MapSettings(range_ring_radii_nm=[0.0])

    with pytest.raises(ValidationError, match="at most 10"):
        MapSettings(range_ring_radii_nm=[float(n) for n in range(1, 13)])


def test_blank_alert_template_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        AlertSettings(enabled_templates=["military", " "])


def test_alert_template_ids_are_deduplicated() -> None:
    alerts = AlertSettings(enabled_templates=["military", "military", " police "])

    assert alerts.enabled_templates == ["military", "police"]


def test_enrichment_requires_a_key_when_enabled() -> None:
    with pytest.raises(ValidationError, match="requires an AeroDataBox API key"):
        EnrichmentSettings(aerodatabox_enabled=True)


def test_unknown_nested_key_is_rejected_by_the_model() -> None:
    with pytest.raises(ValidationError):
        ReceiverSettings(hostname="readsb.lan")  # type: ignore[call-arg]
