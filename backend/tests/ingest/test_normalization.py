"""Normalization of real-shaped readsb and dump1090-fa documents.

Roadmap slice 007 acceptance: *"fixtures from real readsb and dump1090-fa
outputs normalize correctly, including MLAT and non-positioned aircraft"*.
The three fixtures cover the two field vocabularies the decoders use — modern
(readsb / dump1090-fa 4+) and legacy (dump1090-fa 3.x, dump1090-mutability) —
and each carries the awkward cases: MLAT, a Mode S aircraft with no position,
an aircraft on the ground, an emergency squawk, and a TIS-B rebroadcast.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flightsite.ingest.readsb import parse_document, probe_document
from flightsite.ingest.types import AircraftStateBatch, AircraftStateUpdate, DecoderFlavor

RECEIVED_AT = datetime(2030, 1, 1, tzinfo=UTC)

READSB_DOCUMENT_TIME = datetime(2025, 9, 17, 16, 0, 0, 100_000, tzinfo=UTC)
DUMP1090FA_DOCUMENT_TIME = datetime(2025, 9, 17, 16, 0, 12, 500_000, tzinfo=UTC)
LEGACY_DOCUMENT_TIME = datetime(2025, 9, 17, 16, 0, 30, 250_000, tzinfo=UTC)


def by_icao(batch: AircraftStateBatch) -> dict[str, AircraftStateUpdate]:
    return {update.icao: update for update in batch}


# --------------------------------------------------------------- readsb


def test_readsb_batch_shape(readsb_document: Any) -> None:
    batch = parse_document(readsb_document, received_at=RECEIVED_AT)

    assert batch.timestamp == READSB_DOCUMENT_TIME
    assert len(batch) == 6
    assert batch.skipped == 0
    # The "~"-prefixed TIS-B trackfile is dropped, and says so.
    assert batch.skipped_non_icao == 1
    assert "4b1f2e" not in by_icao(batch)


def test_readsb_batch_is_a_sequence_of_updates(readsb_document: Any) -> None:
    batch = parse_document(readsb_document, received_at=RECEIVED_AT)

    # docs/ARCHITECTURE.md §3.5 types the adapter stream as a
    # Sequence[AircraftStateUpdate]; the batch satisfies that directly.
    assert list(batch) == list(batch.updates)
    assert batch[0] is batch.updates[0]
    assert batch[0:2] == batch.updates[0:2]
    assert all(isinstance(update, AircraftStateUpdate) for update in batch)


def test_readsb_normalizes_a_cruising_adsb_aircraft(readsb_document: Any) -> None:
    update = by_icao(parse_document(readsb_document, received_at=RECEIVED_AT))["4ca87c"]

    assert update.callsign == "RYR52QW"
    assert update.squawk == "3623"
    assert update.position is not None
    assert update.position.latitude == 51.804688
    assert update.position.longitude == -0.437622
    assert update.position_source == "adsb"
    assert update.altitude_ft == 36000.0
    assert update.altitude_geometric_ft == 36725.0
    assert update.ground_speed_kt == 442.6
    assert update.track_deg == 118.3
    assert update.vertical_rate_fpm == 0.0
    assert update.on_ground is False
    assert update.rssi_db == -18.4
    assert update.messages == 18422
    assert update.seen_s == 0.2
    assert update.seen_pos_s == 0.3


def test_observation_is_dated_from_the_decoder_clock_minus_its_age(
    readsb_document: Any,
) -> None:
    update = by_icao(parse_document(readsb_document, received_at=RECEIVED_AT))["4ca87c"]

    # now = 16:00:00.1, seen = 0.2 s ago.
    assert update.timestamp == datetime(2025, 9, 17, 15, 59, 59, 900_000, tzinfo=UTC)
    assert update.timestamp != RECEIVED_AT


def test_readsb_mlat_aircraft_is_classified_mlat(readsb_document: Any) -> None:
    update = by_icao(parse_document(readsb_document, received_at=RECEIVED_AT))["406a3d"]

    assert update.position_source == "mlat"
    assert update.has_position
    assert update.altitude_ft == 4275.0
    assert update.vertical_rate_fpm == -1088.0


def test_readsb_non_positioned_mode_s_aircraft_is_kept(readsb_document: Any) -> None:
    update = by_icao(parse_document(readsb_document, received_at=RECEIVED_AT))["3c6444"]

    # SPEC §20: non-positioned aircraft are first-class, not discarded.
    assert update.position is None
    assert update.position_source == "none"
    assert update.callsign == "DLH8LK"
    assert update.altitude_ft == 24000.0
    assert update.seen_pos_s is None


def test_readsb_ground_aircraft_has_no_altitude(readsb_document: Any) -> None:
    update = by_icao(parse_document(readsb_document, received_at=RECEIVED_AT))["4008f6"]

    assert update.on_ground is True
    # A ground sentinel means "no altitude", never a fabricated zero.
    assert update.altitude_ft is None
    assert update.has_position
    assert update.ground_speed_kt == 12.5


def test_readsb_emergency_squawk_survives_normalization(readsb_document: Any) -> None:
    update = by_icao(parse_document(readsb_document, received_at=RECEIVED_AT))["a7c3f1"]

    assert update.squawk == "7700"
    assert update.position_source == "adsb"


def test_readsb_tisb_position_is_classified_other(readsb_document: Any) -> None:
    update = by_icao(parse_document(readsb_document, received_at=RECEIVED_AT))["ac82ec"]

    assert update.position_source == "other"
    assert update.has_position


# ---------------------------------------------------- dump1090-fa (modern)


def test_dump1090fa_batch_shape(dump1090fa_document: Any) -> None:
    batch = parse_document(dump1090fa_document, received_at=RECEIVED_AT)

    assert batch.timestamp == DUMP1090FA_DOCUMENT_TIME
    assert len(batch) == 5
    assert batch.skipped == 0
    assert batch.skipped_non_icao == 0


def test_dump1090fa_modern_fields_normalize_like_readsb(dump1090fa_document: Any) -> None:
    update = by_icao(parse_document(dump1090fa_document, received_at=RECEIVED_AT))["a0f1b4"]

    assert update.callsign == "UAL2145"
    assert update.position_source == "adsb"
    assert update.altitude_ft == 27000.0
    assert update.altitude_geometric_ft == 27575.0
    assert update.ground_speed_kt == 401.2
    assert update.vertical_rate_fpm == 1728.0
    assert update.on_ground is False


def test_dump1090fa_mlat_and_ground_and_mode_s(dump1090fa_document: Any) -> None:
    updates = by_icao(parse_document(dump1090fa_document, received_at=RECEIVED_AT))

    assert updates["ab34d9"].position_source == "mlat"
    assert updates["a2b9c7"].on_ground is True
    assert updates["a2b9c7"].altitude_ft is None
    assert updates["ad4e21"].position_source == "none"
    assert updates["ad4e21"].callsign is None
    assert updates["ad4e21"].on_ground is False


def test_geometric_rate_is_used_when_no_barometric_rate(dump1090fa_document: Any) -> None:
    update = by_icao(parse_document(dump1090fa_document, received_at=RECEIVED_AT))["a91d05"]

    assert update.vertical_rate_fpm == -512.0
    assert update.squawk == "7600"


# ---------------------------------------------------- dump1090-fa (legacy)


def test_legacy_field_names_are_understood(dump1090fa_legacy_document: Any) -> None:
    batch = parse_document(dump1090fa_legacy_document, received_at=RECEIVED_AT)
    updates = by_icao(batch)

    assert batch.timestamp == LEGACY_DOCUMENT_TIME
    assert len(batch) == 4

    cruising = updates["3949e8"]
    assert cruising.altitude_ft == 18000.0  # "altitude", not "alt_baro"
    assert cruising.ground_speed_kt == 324.0  # "speed", not "gs"
    assert cruising.vertical_rate_fpm == 1216.0  # "vert_rate", not "baro_rate"
    assert cruising.position_source == "adsb"


def test_legacy_ground_sentinel_and_padded_callsign(dump1090fa_legacy_document: Any) -> None:
    updates = by_icao(parse_document(dump1090fa_legacy_document, received_at=RECEIVED_AT))

    assert updates["3c4b26"].on_ground is True
    assert updates["3c4b26"].altitude_ft is None
    assert updates["407f2b"].callsign == "BAW56"
    assert updates["407f2b"].squawk == "7700"


def test_legacy_aircraft_without_position_or_altitude(dump1090fa_legacy_document: Any) -> None:
    update = by_icao(parse_document(dump1090fa_legacy_document, received_at=RECEIVED_AT))["484ba9"]

    assert update.position_source == "none"
    assert update.altitude_ft is None
    # No altitude field at all means the decoder said nothing about ground
    # state — that is "unknown", not "airborne".
    assert update.on_ground is None


# ------------------------------------------------------------ flavor guess


def test_probe_identifies_readsb_from_its_own_fields(readsb_document: Any) -> None:
    probe = probe_document(readsb_document, received_at=RECEIVED_AT)

    assert probe.flavor is DecoderFlavor.READSB
    assert "dbFlags" in probe.markers
    assert probe.aircraft_count == 7
    assert probe.positioned_count == 6
    assert probe.timestamp == READSB_DOCUMENT_TIME


def test_probe_identifies_legacy_dump1090fa(dump1090fa_legacy_document: Any) -> None:
    probe = probe_document(dump1090fa_legacy_document, received_at=RECEIVED_AT)

    assert probe.flavor is DecoderFlavor.DUMP1090_FA
    assert set(probe.markers) >= {"altitude", "speed", "vert_rate"}


def test_probe_admits_it_cannot_tell_modern_decoders_apart(dump1090fa_document: Any) -> None:
    probe = probe_document(dump1090fa_document, received_at=RECEIVED_AT)

    # Modern readsb and dump1090-fa serve a deliberately compatible document.
    # "unknown" is the honest answer, not a failure.
    assert probe.flavor is DecoderFlavor.UNKNOWN
    assert probe.markers == ()
    assert probe.aircraft_count == 5
    assert probe.positioned_count == 4
