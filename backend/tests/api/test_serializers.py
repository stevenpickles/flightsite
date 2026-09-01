"""The §3.3 and §3.2 payload shapes, field by field.

These are the contract tests for what FlightSite says about an aircraft: that
unknown is ``null`` rather than a guess or an absent key, that the canonical
vocabulary is spelled the way ``docs/API.md`` §2.8 spells it, that timestamps
are §2.2 UTC, and that derived values — and only derived values — carry
provenance (§2.6).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from flightsite.api.schemas import AircraftView, ReceiverInfo
from flightsite.api.serializers import aircraft_payload, iso_utc, receiver_payload
from flightsite.config import ConfigStore, LocationSettings, Settings
from flightsite.ingest import Position
from flightsite.live import LiveAircraft, LiveState, appear, mark_stale, merge

from ..live.conftest import SEATTLE, ManualClock, make_update

NEARBY = Position(latitude=47.6205, longitude=-122.3493)


def positioned_record(**fields: Any) -> LiveAircraft:
    """A live record for an aircraft with a position, seen from Seattle."""
    return appear(make_update(position=NEARBY, **fields), now=1_000.0, receiver=SEATTLE)


def mode_s_record(**fields: Any) -> LiveAircraft:
    """A live record for an aircraft tracked without a position (SPEC §20)."""
    return appear(make_update(**fields), now=1_000.0, receiver=SEATTLE)


# --------------------------------------------------------------- timestamps


def test_iso_utc_uses_millisecond_precision_and_a_z_suffix() -> None:
    moment = datetime(2026, 8, 31, 14, 3, 22, 418_912, tzinfo=UTC)

    assert iso_utc(moment) == "2026-08-31T14:03:22.418Z"


def test_iso_utc_converts_a_non_utc_offset_to_utc() -> None:
    moment = datetime(2026, 8, 31, 16, 3, 22, tzinfo=timezone(timedelta(hours=2)))

    assert iso_utc(moment) == "2026-08-31T14:03:22.000Z"


def test_iso_utc_refuses_a_naive_datetime() -> None:
    # A naive datetime would silently adopt the host's zone, which is the
    # exact ambiguity SPEC §15's UTC rule exists to remove.
    with pytest.raises(ValueError, match="naive"):
        iso_utc(datetime(2026, 8, 31, 14, 3, 22))


def test_last_seen_is_the_decoders_timestamp_not_the_servers() -> None:
    record = positioned_record()

    assert aircraft_payload(record)["last_seen"] == iso_utc(record.last_seen)


# ----------------------------------------------------------------- the shape


def test_the_payload_validates_against_the_published_model() -> None:
    # The response model forbids extra keys, so this fails if the serializer
    # grows a field the OpenAPI schema does not promise.
    payload = aircraft_payload(positioned_record(callsign="RCH492", squawk="4521"))

    assert AircraftView.model_validate(payload).icao == payload["icao"]


def test_every_documented_key_is_present_even_when_unknown() -> None:
    payload = aircraft_payload(mode_s_record())

    assert set(payload) == set(AircraftView.model_fields)


def test_a_positioned_aircraft_reports_lat_lon_and_its_source() -> None:
    payload = aircraft_payload(positioned_record())

    assert payload["position"] == {"lat": NEARBY.latitude, "lon": NEARBY.longitude}
    assert payload["position_source"] == "adsb"


def test_a_non_positioned_aircraft_is_a_first_class_entry() -> None:
    # SPEC §20: Mode S-only aircraft are live entries, not discards.
    payload = aircraft_payload(mode_s_record(callsign="SWA1234"))

    assert payload["position"] is None
    assert payload["position_source"] == "none"
    assert payload["callsign"] == "SWA1234"


def test_mlat_positions_keep_their_source() -> None:
    record = positioned_record(position_source="mlat")

    assert aircraft_payload(record)["position_source"] == "mlat"


def test_unreported_fields_are_null_rather_than_zero() -> None:
    payload = aircraft_payload(mode_s_record())

    for field in ("callsign", "squawk", "altitude_ft", "ground_speed_kt", "track_deg"):
        assert payload[field] is None, field
    for field in ("vertical_rate_fpm", "on_ground", "rssi_db", "message_count"):
        assert payload[field] is None, field


def test_metadata_fields_are_null_when_the_cache_has_not_resolved_the_aircraft() -> None:
    # The normal state for the first sub-second of a new aircraft's life, and
    # the permanent state on an install with no metadata database. §2.7 says
    # the honest answer is null, and the keys stay so clients can rely on them.
    payload = aircraft_payload(positioned_record())

    for field in ("registration", "aircraft_type", "model", "operator", "operator_group"):
        assert payload[field] is None, field
    assert payload["classification"] is None
    # Alert matching (slice 038) has not landed.
    assert payload["interesting"] is None


def test_watchlists_defaults_to_an_empty_list_not_a_missing_key() -> None:
    """§2.7's null-stable pattern extended to a list field (slice 037)."""
    payload = aircraft_payload(positioned_record())

    assert payload["watchlists"] == []


def test_watchlists_carries_whatever_the_matcher_reports() -> None:
    payload = aircraft_payload(positioned_record(), watchlists=("Police Helicopters", "Rare Types"))

    assert payload["watchlists"] == ["Police Helicopters", "Rare Types"]


def test_decoder_values_are_passed_through_unrounded() -> None:
    record = positioned_record(altitude_ft=24_975.0, ground_speed_kt=442.0, rssi_db=-12.1)
    payload = aircraft_payload(record)

    assert payload["altitude_ft"] == 24_975.0
    assert payload["ground_speed_kt"] == 442.0
    assert payload["rssi_db"] == -12.1


def test_message_count_carries_the_decoders_message_total() -> None:
    assert aircraft_payload(positioned_record(messages=4812))["message_count"] == 4812


# ------------------------------------------------------------------- states


def test_state_is_the_canonical_lifecycle_word() -> None:
    live = positioned_record()

    assert aircraft_payload(live)["state"] == "live"
    assert aircraft_payload(mark_stale(live))["state"] == "stale"
    assert mark_stale(live).state is LiveState.STALE


@pytest.mark.parametrize("squawk", ["7500", "7600", "7700"])
def test_an_emergency_squawk_is_restated_as_emergency(squawk: str) -> None:
    payload = aircraft_payload(positioned_record(squawk=squawk))

    assert payload["squawk"] == squawk
    assert payload["emergency"] == squawk


def test_an_ordinary_squawk_declares_no_emergency() -> None:
    assert aircraft_payload(positioned_record(squawk="4521"))["emergency"] is None


def test_ground_state_comes_from_the_decoder_only() -> None:
    on_ground = aircraft_payload(positioned_record(on_ground=True))
    airborne = aircraft_payload(positioned_record(on_ground=False))
    unstated = aircraft_payload(positioned_record())

    assert on_ground["on_ground"] is True
    assert airborne["on_ground"] is False
    assert unstated["on_ground"] is None


# --------------------------------------------------------------- provenance


def test_derived_range_and_bearing_carry_derived_provenance() -> None:
    payload = aircraft_payload(positioned_record())

    assert payload["provenance"] == {"distance_nm": "derived", "bearing_deg": "derived"}


def test_an_unconfigured_receiver_yields_no_range_and_no_provenance() -> None:
    # The first-run state: no receiver position, so no receiver-relative fields
    # and nothing to attribute. Everything else still works.
    record = appear(make_update(position=NEARBY), now=1_000.0, receiver=None)
    payload = aircraft_payload(record)

    assert payload["distance_nm"] is None
    assert payload["bearing_deg"] is None
    assert payload["provenance"] == {}


def test_ground_state_provenance_is_not_published_as_a_field() -> None:
    # The live layer attributes its `ground_state` inference, but the API
    # publishes `on_ground` — the decoder's own word — so there is no derived
    # value here to attribute and no entry for one.
    record = positioned_record(on_ground=True)

    assert "ground_state" in record.provenance
    assert "ground_state" not in aircraft_payload(record)["provenance"]
    assert "on_ground" not in aircraft_payload(record)["provenance"]


def test_derived_range_is_rounded_but_not_invented() -> None:
    record = positioned_record()
    payload = aircraft_payload(record)

    assert record.distance_nm is not None
    assert payload["distance_nm"] == pytest.approx(record.distance_nm, abs=1e-3)
    assert payload["bearing_deg"] == pytest.approx(record.bearing_deg, abs=1e-2)


# ------------------------------------------------------------- sighting ids


def test_sighting_id_is_null_until_persistence_has_opened_one() -> None:
    assert aircraft_payload(positioned_record())["sighting_id"] is None


def test_sighting_id_is_reported_when_the_row_exists() -> None:
    assert aircraft_payload(positioned_record(), sighting_id=88_213)["sighting_id"] == 88_213


# ------------------------------------------------------------------ merging


def test_a_merged_record_serializes_its_latest_values() -> None:
    clock = ManualClock()
    first = positioned_record(callsign="RCH492")
    second, _changed = merge(
        first,
        make_update(offset_s=1.0, position=NEARBY, squawk="4521"),
        now=clock.advance(1.0),
        receiver=SEATTLE,
    )
    payload = aircraft_payload(second)

    assert payload["callsign"] == "RCH492"
    assert payload["squawk"] == "4521"


# ---------------------------------------------------------------- receiver


def default_settings(store: ConfigStore) -> Settings:
    return store.load()


def test_receiver_payload_reports_an_unconfigured_location_as_null(store: ConfigStore) -> None:
    payload = receiver_payload(default_settings(store), demo_mode=False, t0=None, location=None)

    assert payload["site_name"] is None
    assert payload["latitude"] is None
    assert payload["longitude"] is None
    assert payload["antenna_height_ft"] is None
    assert payload["t0"] is None
    assert ReceiverInfo.model_validate(payload).demo_mode is False


def test_receiver_payload_reports_the_configured_site(store: ConfigStore) -> None:
    settings = store.load()
    settings.location = LocationSettings(
        latitude=47.6205, longitude=-122.3493, site_name="Rooftop Pi", antenna_height_ft=120.0
    )
    payload = receiver_payload(
        settings,
        demo_mode=True,
        t0=datetime(2026, 4, 2, 18, 11, 9, tzinfo=UTC),
        location=Position(latitude=47.6205, longitude=-122.3493),
    )

    assert payload["site_name"] == "Rooftop Pi"
    assert payload["latitude"] == pytest.approx(47.6205)
    assert payload["longitude"] == pytest.approx(-122.3493)
    assert payload["antenna_height_ft"] == pytest.approx(120.0)
    assert payload["t0"] == "2026-04-02T18:11:09.000Z"
    assert payload["demo_mode"] is True


def test_receiver_payload_carries_the_unit_and_radius_settings(store: ConfigStore) -> None:
    payload = receiver_payload(default_settings(store), demo_mode=False, t0=None, location=None)

    assert payload["units"] == "aviation"
    assert payload["timezone"] == "UTC"
    assert payload["display_radius_nm"] == pytest.approx(250.0)
    assert payload["alert_radius_nm"] is None


def test_receiver_payload_never_carries_a_secret(store: ConfigStore) -> None:
    settings = store.load()
    settings.enrichment = settings.enrichment.model_copy(
        update={"aerodatabox_api_key": None, "aerodatabox_enabled": False}
    )
    payload = receiver_payload(settings, demo_mode=False, t0=None, location=None)

    assert set(payload) == set(ReceiverInfo.model_fields)
    assert not any("key" in field or "secret" in field for field in payload)


def test_receiver_payload_reports_the_position_ranges_are_measured_from(
    store: ConfigStore,
) -> None:
    # Demo mode's shape: nothing configured, but a location injected into the
    # live store so the simulated sky has ranges. Reporting the configured
    # null there would leave a client with no marker to draw.
    payload = receiver_payload(
        default_settings(store),
        demo_mode=True,
        t0=None,
        location=Position(latitude=47.4502, longitude=-122.3088),
    )

    assert payload["latitude"] == pytest.approx(47.4502)
    assert payload["longitude"] == pytest.approx(-122.3088)
    assert payload["site_name"] is None
