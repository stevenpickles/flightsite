"""Malformed-input hardening.

Roadmap slice 007 acceptance: *"malformed payload fuzz tests pass without
exceptions escaping the adapter"*. The corpus in ``fixtures/malformed/`` is a
collection of things a decoder endpoint has actually been observed to serve —
an nginx 404 page, a half-written file, a JSON object where an array belongs —
plus values no decoder should ever emit.

The contract under test has two halves:

* a *document* that is not a usable aircraft feed fails the poll cleanly with
  :class:`DecoderParseError` and nothing else;
* a *field* that is missing, mistyped or absurd is dropped while the rest of
  the aircraft, and the rest of the document, survive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from flightsite.ingest.protocol import DecoderParseError
from flightsite.ingest.readsb import decode_json, parse_document
from flightsite.ingest.types import AircraftStateBatch

from .conftest import MALFORMED_DIR, malformed_paths

RECEIVED_AT = datetime(2030, 1, 1, tzinfo=UTC)

#: Corpus members that are not a usable aircraft document at all.
UNUSABLE_DOCUMENTS = {
    "empty.json",
    "whitespace_only.json",
    "html_error_page.json",
    "truncated.json",
    "trailing_garbage.json",
    "top_level_null.json",
    "top_level_array.json",
    "top_level_string.json",
    "top_level_number.json",
    "missing_aircraft_key.json",
    "aircraft_is_object.json",
    "aircraft_is_string.json",
    "aircraft_is_null.json",
}


def parse_path(path: Path) -> AircraftStateBatch:
    return parse_document(decode_json(path.read_bytes()), received_at=RECEIVED_AT)


def test_corpus_is_not_empty() -> None:
    assert len(malformed_paths()) >= 20


@pytest.mark.parametrize("path", malformed_paths(), ids=lambda path: path.name)
def test_nothing_but_decoder_parse_error_escapes(path: Path) -> None:
    """Every corpus member either parses or fails as a DecoderParseError."""
    try:
        parse_path(path)
    except DecoderParseError:
        pass
    except Exception as exc:  # pragma: no cover - the failure this test exists for
        pytest.fail(f"{path.name} raised {type(exc).__name__}: {exc}")


@pytest.mark.parametrize("name", sorted(UNUSABLE_DOCUMENTS))
def test_unusable_documents_fail_the_poll(name: str) -> None:
    with pytest.raises(DecoderParseError):
        parse_path(MALFORMED_DIR / name)


def test_junk_entries_are_skipped_and_counted() -> None:
    batch = parse_path(MALFORMED_DIR / "junk_entries.json")

    # Exactly one entry in that document carries a usable ICAO address.
    assert [update.icao for update in batch] == ["4ca87c"]
    assert batch.skipped == 12
    assert batch.skipped_non_icao == 0


def test_absurd_values_are_dropped_field_by_field() -> None:
    batch = parse_path(MALFORMED_DIR / "absurd_values.json")
    (update,) = batch.updates

    # The aircraft survives; every implausible field is simply absent.
    assert update.icao == "4ca87c"
    assert update.position is None  # lat 91.5 / lon 400.2
    assert update.position_source == "none"
    assert update.altitude_ft is None  # 200,000 ft
    assert update.altitude_geometric_ft is None  # -99,000 ft
    assert update.ground_speed_kt is None  # negative
    assert update.track_deg is None  # 400 degrees
    assert update.vertical_rate_fpm is None  # 999,999 fpm
    assert update.squawk is None  # "9999" is not octal
    assert update.rssi_db is None  # +5000 dBFS
    assert update.messages is None  # negative counter
    assert update.seen_s is None  # negative age
    assert update.seen_pos_s is None  # a day and a half


def test_wrong_types_are_dropped_without_guessing() -> None:
    batch = parse_path(MALFORMED_DIR / "wrong_types.json")
    (update,) = batch.updates

    assert update.icao == "406a3d"
    assert update.callsign is None  # a list
    assert update.altitude_ft is None  # an object
    assert update.ground_speed_kt is None  # a numeric *string* is still wrong
    assert update.track_deg is None  # a bool is not a number
    assert update.position is None  # lat as a string, lon null
    assert update.squawk is None  # a number, not a string
    assert update.rssi_db is None
    assert update.messages is None
    assert update.seen_s is None
    # "now" was unusable, so the batch falls back to FlightSite's clock.
    assert batch.timestamp == RECEIVED_AT


def test_non_finite_numbers_are_rejected() -> None:
    batch = parse_path(MALFORMED_DIR / "non_finite_numbers.json")
    (update,) = batch.updates

    # NaN/Infinity decode fine as JSON but would poison every comparison
    # downstream, so they are treated as absent.
    assert update.position is None
    assert update.altitude_ft is None
    assert update.ground_speed_kt is None
    assert update.rssi_db is None
    assert update.seen_s is None


def test_unset_decoder_clock_falls_back_to_local_time() -> None:
    batch = parse_path(MALFORMED_DIR / "unset_decoder_clock.json")

    # A decoder that booted without an RTC reports 1970; dating a whole batch
    # to the Unix epoch would corrupt every downstream timestamp.
    assert batch.timestamp == RECEIVED_AT
    (update,) = batch.updates
    assert update.on_ground is True


def test_ground_sentinel_is_matched_case_and_space_insensitively() -> None:
    batch = parse_path(MALFORMED_DIR / "ground_sentinel_variants.json")
    states = {update.icao: update.on_ground for update in batch}

    assert states["4008f6"] is True  # "GROUND"
    assert states["4008f7"] is True  # " ground "
    assert states["4008f8"] is None  # an unrecognized string says nothing


def test_empty_aircraft_array_is_a_valid_poll() -> None:
    batch = parse_path(MALFORMED_DIR / "empty_aircraft.json")

    # A quiet sky is not a failure.
    assert len(batch) == 0
    assert batch.skipped == 0


def test_duplicate_addresses_are_both_kept_for_the_live_store_to_resolve() -> None:
    batch = parse_path(MALFORMED_DIR / "duplicate_hex.json")

    # The adapter normalizes; deciding which observation wins is the live
    # store's job (slice 008), so both are passed through in document order.
    assert [update.altitude_ft for update in batch] == [3000.0, 4000.0]


def test_nested_junk_in_provenance_arrays_is_ignored() -> None:
    batch = parse_path(MALFORMED_DIR / "deeply_nested_junk.json")
    (update,) = batch.updates

    # mlat/tisb arrays holding non-strings must not crash classification.
    assert update.position_source == "adsb"


def test_an_entry_the_domain_type_rejects_is_skipped_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # AircraftStateUpdate enforces its own invariants, so a classifier bug
    # shows up as a rejected entry. Losing that one aircraft is acceptable;
    # losing the poll — and every other aircraft in it — is not.
    monkeypatch.setattr(
        "flightsite.ingest.readsb._classify_position_source",
        lambda entry, *, has_position: "adsb",
    )

    batch = parse_path(MALFORMED_DIR / "duplicate_hex.json")

    assert len(batch) == 0
    assert batch.skipped == 2


def test_unicode_fields_do_not_break_normalization() -> None:
    batch = parse_path(MALFORMED_DIR / "unicode_fields.json")
    (update,) = batch.updates

    assert update.callsign == "✈️"
    assert update.squawk is None  # Arabic-Indic digits are not an octal code
