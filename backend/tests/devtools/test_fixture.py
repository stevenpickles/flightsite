"""``.fsrec.gz`` fixture format: round-trip fidelity, header, determinism."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flightsite.devtools.fixture import (
    FORMAT_VERSION,
    Fixture,
    FixtureError,
    read_fixture,
    write_fixture,
)
from flightsite.ingest.types import AircraftStateBatch

from .conftest import T0, make_batches, make_update


def test_round_trip_reproduces_identical_batches(tmp_path: Path) -> None:
    batches = make_batches(3)
    out = tmp_path / "session.fsrec.gz"

    write_fixture(out, batches=batches, source="test", duration_s=2.0, created_at=T0)
    fixture = read_fixture(out)

    assert [record.batch for record in fixture.records] == batches


def test_round_trip_preserves_skip_counters(tmp_path: Path) -> None:
    batch = AircraftStateBatch(
        timestamp=T0, updates=(make_update(),), skipped=2, skipped_non_icao=1
    )
    out = tmp_path / "skips.fsrec.gz"

    write_fixture(out, batches=[batch], source="test", duration_s=1.0, created_at=T0)
    fixture = read_fixture(out)

    assert fixture.records[0].batch == batch


def test_fixture_header_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        write_fixture(
            "unused.fsrec.gz",
            batches=[],
            source="test",
            duration_s=0.0,
            created_at=datetime(2026, 1, 1),  # deliberately naive
        )


def test_round_trip_preserves_every_optional_field(tmp_path: Path) -> None:
    # A minimal update (only the required fields) alongside a fully populated
    # one, so both "field present" and "field omitted" paths round-trip.
    minimal = make_update(
        "000001",
        position=None,
        callsign=None,
        squawk=None,
        altitude_ft=None,
        altitude_geometric_ft=None,
        ground_speed_kt=None,
        track_deg=None,
        vertical_rate_fpm=None,
        on_ground=None,
        rssi_db=None,
        messages=None,
        seen_s=None,
        seen_pos_s=None,
    )
    full = make_update("4ca87c")
    batch = AircraftStateBatch(timestamp=T0, updates=(minimal, full))
    out = tmp_path / "fields.fsrec.gz"

    write_fixture(out, batches=[batch], source="test", duration_s=1.0, created_at=T0)
    fixture = read_fixture(out)

    assert fixture.records[0].batch == batch


def test_header_records_counts_and_metadata(tmp_path: Path) -> None:
    batches = make_batches(4)
    out = tmp_path / "session.fsrec.gz"

    written = write_fixture(
        out, batches=batches, source="readsb@decoder.test", duration_s=12.5, created_at=T0
    )
    header = read_fixture(out).header

    assert written == header
    assert header.format_version == FORMAT_VERSION
    assert header.source == "readsb@decoder.test"
    assert header.duration_s == 12.5
    assert header.batch_count == 4
    assert header.update_count == 8
    assert header.created_at == T0


def test_batch_relative_offsets_are_seconds_since_created_at(tmp_path: Path) -> None:
    batches = make_batches(3, interval_s=1.5)
    out = tmp_path / "session.fsrec.gz"

    write_fixture(out, batches=batches, source="test", duration_s=3.0, created_at=T0)
    fixture = read_fixture(out)

    assert [record.relative_s for record in fixture.records] == [0.0, 1.5, 3.0]


def test_empty_capture_is_a_valid_fixture(tmp_path: Path) -> None:
    out = tmp_path / "empty.fsrec.gz"

    header = write_fixture(out, batches=[], source="test", duration_s=5.0, created_at=T0)
    fixture = read_fixture(out)

    assert header.batch_count == 0
    assert header.update_count == 0
    assert fixture.records == ()


def test_output_is_gzip_compressed(tmp_path: Path) -> None:
    out = tmp_path / "session.fsrec.gz"
    write_fixture(out, batches=make_batches(1), source="test", duration_s=1.0, created_at=T0)

    with gzip.open(out, "rt", encoding="utf-8") as gz:
        lines = gz.read().splitlines()

    header = json.loads(lines[0])
    assert header["format_version"] == FORMAT_VERSION
    assert len(lines) == 2  # header + one batch


def test_writing_is_deterministic(tmp_path: Path) -> None:
    batches = make_batches(5)
    first = tmp_path / "a.fsrec.gz"
    second = tmp_path / "b.fsrec.gz"

    write_fixture(first, batches=batches, source="test", duration_s=4.0, created_at=T0)
    write_fixture(second, batches=batches, source="test", duration_s=4.0, created_at=T0)

    assert first.read_bytes() == second.read_bytes()


def test_created_at_defaults_to_the_first_batch_timestamp(tmp_path: Path) -> None:
    batches = make_batches(2)
    out = tmp_path / "session.fsrec.gz"

    header = write_fixture(out, batches=batches, source="test", duration_s=1.0)

    assert header.created_at == batches[0].timestamp


def test_created_at_defaults_to_now_for_an_empty_capture(tmp_path: Path) -> None:
    before = datetime.now(UTC)
    out = tmp_path / "empty.fsrec.gz"

    header = write_fixture(out, batches=[], source="test", duration_s=0.0)

    assert before <= header.created_at <= datetime.now(UTC)


def test_reading_an_unsupported_format_version_raises(tmp_path: Path) -> None:
    out = tmp_path / "bad.fsrec.gz"
    write_fixture(out, batches=[], source="test", duration_s=0.0, created_at=T0)
    fixture = read_fixture(out)
    corrupted = json.dumps({**_as_header_dict(fixture), "format_version": 999})

    with gzip.open(out, "wt", encoding="utf-8") as gz:
        gz.write(corrupted + "\n")

    with pytest.raises(FixtureError, match="format_version"):
        read_fixture(out)


def _as_header_dict(fixture: Fixture) -> dict[str, object]:
    header = fixture.header
    return {
        "format_version": header.format_version,
        "created_at": header.created_at.isoformat(),
        "source": header.source,
        "duration_s": header.duration_s,
        "batch_count": header.batch_count,
        "update_count": header.update_count,
        "generator": header.generator,
    }


def test_reading_an_empty_file_raises(tmp_path: Path) -> None:
    out = tmp_path / "empty_file.fsrec.gz"
    with gzip.open(out, "wt", encoding="utf-8"):
        pass

    with pytest.raises(FixtureError, match="empty"):
        read_fixture(out)


def test_write_fixture_creates_parent_directories(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "dir" / "session.fsrec.gz"

    write_fixture(out, batches=[], source="test", duration_s=0.0, created_at=T0)

    assert out.exists()
