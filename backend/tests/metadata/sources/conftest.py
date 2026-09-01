"""Fixtures for the Mictronics provider tests."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from flightsite.metadata.records import SourceArtifact

#: A curated real-format sample: rows taken verbatim from a real
#: ``aircraft.csv.gz`` snapshot (32 airframes, including military-, PIA- and
#: LADD-flagged rows and a real data oddity) plus 8 real ICAO-block
#: bookkeeping rows the provider must filter out (see
#: ``flightsite.metadata.sources.mictronics``'s module docstring).
SAMPLE_CSV_PATH = Path(__file__).parent / "fixtures" / "aircraft_sample.csv"

#: ICAO addresses of the fixture's 8 block-bookkeeping rows (both
#: registration and type code blank) — never real aircraft.
SAMPLE_MARKER_ICAOS = frozenset(
    {"000001", "000011", "000FFF", "100000", "053977", "3E8057", "A00599", "A005E3"}
)

#: ICAO addresses of the fixture's 32 real airframe rows.
SAMPLE_AIRCRAFT_ICAOS = frozenset(
    {
        "0000BA",
        "00D3FC",
        "00D588",
        "A1BCCA",
        "A1BCCD",
        "A06D0B",
        "A1BCCB",
        "AB6F50",
        "A1A3FD",
        "A3E16A",
        "A73A47",
        "AD5D5F",
        "505610",
        "A0010A",
        "45F042",
        "45E4C1",
        "01028D",
        "478755",
        "3B7770",
        "006015",
        "006037",
        "AE49E0",
        "A08DAA",
        "0AC164",
        "0ACB7E",
        "00AEC9",
        "0703FA",
        "05E0BB",
        "15407B",
        "ABAFE1",
        "4B38FF",
        "A15463",
    }
)


@pytest.fixture
def sample_csv_bytes() -> bytes:
    """The fixture file's raw bytes, uncompressed."""
    return SAMPLE_CSV_PATH.read_bytes()


@pytest.fixture
def sample_gzip_bytes(sample_csv_bytes: bytes) -> bytes:
    """The fixture, gzip-compressed the way the real artifact is served."""
    return gzip.compress(sample_csv_bytes)


@pytest.fixture
def sample_artifact(tmp_path: Path, sample_gzip_bytes: bytes) -> SourceArtifact:
    """A :class:`SourceArtifact` over the compressed fixture, on disk."""
    path = tmp_path / "aircraft.csv.gz"
    path.write_bytes(sample_gzip_bytes)
    return SourceArtifact(
        path=path, version="test-snapshot", content_hash="", size_bytes=len(sample_gzip_bytes)
    )
