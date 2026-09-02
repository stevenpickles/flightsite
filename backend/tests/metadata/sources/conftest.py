"""Fixtures for the per-source provider tests (Mictronics, OpenSky)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from flightsite.metadata.records import SourceArtifact
from flightsite.metadata.sources import opensky

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


# --------------------------------------------------------------------- opensky

#: A curated real-format sample: the real 27-column header plus rows taken
#: verbatim from a real ``aircraftDatabase.csv`` snapshot — including the
#: addressless row a real snapshot opens with (blank *except* literal
#: ``"false"`` in its three boolean columns, which is why "every column empty"
#: is the wrong test for it), a ``"Private"`` placeholder owner, and a row that
#: carries nothing this source contributes (see
#: ``flightsite.metadata.sources.opensky``'s module docstring).
OPENSKY_SAMPLE_CSV_PATH = Path(__file__).parent / "fixtures" / "opensky_sample.csv"

#: ICAO addresses of the fixture's rows that OpenSky actually contributes
#: something for — i.e. what ``transform`` must yield.
OPENSKY_CONTRIBUTING_ICAOS = frozenset(
    {"aa3487", "ad4b72", "a79048", "3fee2c", "a29bf7", "400e85", "a4c81f"}
)

#: Fixture rows ``transform`` must skip silently rather than reject: the
#: all-empty row (no address at all) and ``e88074``, which has a registration
#: and a type code but no operator, owner, manufacturer/model or build year —
#: nothing this source is allowed to claim.
OPENSKY_SKIPPED_ICAOS = frozenset({"e88074"})


@pytest.fixture
def opensky_csv_bytes() -> bytes:
    """The OpenSky fixture file's raw bytes, as the artifact is served."""
    return OPENSKY_SAMPLE_CSV_PATH.read_bytes()


@pytest.fixture
def opensky_artifact(tmp_path: Path, opensky_csv_bytes: bytes) -> SourceArtifact:
    """A :class:`SourceArtifact` over the OpenSky fixture, on disk.

    ``size_bytes`` is reported as the real artifact's floor rather than the
    fixture's true length: the fixture is a handful of rows, and
    ``validate`` legitimately refuses anything below
    :data:`~flightsite.metadata.sources.opensky.MIN_ARTIFACT_BYTES`. Stating
    the size here keeps that floor a real check the size-specific tests
    exercise deliberately, instead of something every other test has to
    monkeypatch around.
    """
    path = tmp_path / opensky.ARTIFACT_FILENAME
    path.write_bytes(opensky_csv_bytes)
    return SourceArtifact(
        path=path,
        version="test-snapshot",
        content_hash="",
        size_bytes=opensky.MIN_ARTIFACT_BYTES,
    )
