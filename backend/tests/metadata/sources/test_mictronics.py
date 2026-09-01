"""The Mictronics/tar1090 provider: parsing, validation and download.

:mod:`tests.metadata.sources.conftest` documents the real-format sample this
suite parses; the assertions below cross-check specific rows against what
was independently observed in a real snapshot (see the module docstring in
``flightsite.metadata.sources.mictronics``).
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import httpx
import pytest

from flightsite.metadata.records import NormalizedAircraftRecord, SourceArtifact
from flightsite.metadata.sources import mictronics
from flightsite.metadata.sources.mictronics import (
    MIN_ARTIFACT_BYTES,
    MictronicsDownloadError,
    MictronicsProvider,
)
from tests.metadata.sources.conftest import SAMPLE_AIRCRAFT_ICAOS, SAMPLE_MARKER_ICAOS

# --------------------------------------------------------------------- transform


def _records(artifact: SourceArtifact) -> dict[str, NormalizedAircraftRecord]:
    provider = MictronicsProvider()
    return {record.icao24: record for record in provider.transform(artifact)}


def test_transform_drops_icao_block_bookkeeping_rows(sample_artifact: SourceArtifact) -> None:
    """Rows with no registration and no type code name no aircraft."""
    records = _records(sample_artifact)

    assert not (SAMPLE_MARKER_ICAOS & records.keys())
    assert records.keys() == SAMPLE_AIRCRAFT_ICAOS


def test_transform_maps_a_complete_row(sample_artifact: SourceArtifact) -> None:
    record = _records(sample_artifact)["A1BCCA"]

    assert record == NormalizedAircraftRecord(
        icao24="A1BCCA",
        registration="N21065",
        type_code="P28A",
        model="PIPER PA-28-140/150/160/180",
        manufacture_year=1978,
        operator_name="OMNI MANAGEMENT LLC",
        owner=None,
        military_flag=False,
        flags={"interesting": False, "pia": False, "ladd": False},
    )


def test_transform_never_populates_owner(sample_artifact: SourceArtifact) -> None:
    """This upstream's one free-text field maps to operator, never owner (FAA's job, slice 023)."""
    records = _records(sample_artifact)

    assert all(record.owner is None for record in records.values())


def test_transform_treats_a_type_only_row_as_a_real_aircraft(
    sample_artifact: SourceArtifact,
) -> None:
    """Either field populated is enough — a blank *registration* alone never filters a row."""
    record = _records(sample_artifact)["0000BA"]

    assert record.registration is None
    assert record.type_code == "BALL"
    assert record.operator_name == "Miscode - VARIOUS"


@pytest.mark.parametrize(
    ("icao", "military", "interesting", "pia", "ladd"),
    [
        ("A1BCCA", False, False, False, False),
        ("006015", True, False, False, False),
        ("AE49E0", True, True, False, False),  # dbFlags "11000": a spare, currently-unused bit
        ("00AEC9", True, True, False, False),
        ("0AC164", True, False, False, True),
        ("05E0BB", False, True, False, True),
        ("15407B", False, True, False, False),
        ("ABAFE1", False, False, False, True),
    ],
)
def test_transform_decodes_db_flags_character_by_character(
    sample_artifact: SourceArtifact,
    icao: str,
    military: bool,
    interesting: bool,
    pia: bool,
    ladd: bool,
) -> None:
    record = _records(sample_artifact)[icao]

    assert record.military_flag is military
    assert record.flags == {"interesting": interesting, "pia": pia, "ladd": ladd}


def test_transform_blank_fields_are_none_never_empty_string(
    sample_artifact: SourceArtifact,
) -> None:
    record = _records(sample_artifact)["45F042"]  # year and ownop both blank in the fixture

    assert record.manufacture_year is None
    assert record.operator_name is None
    assert "" not in (record.manufacture_year, record.operator_name)


def test_transform_passes_through_a_real_data_oddity_verbatim(
    sample_artifact: SourceArtifact,
) -> None:
    """A real row where upstream's own registration field holds a stray dbFlags-shaped value.

    The provider does not second-guess upstream content; it is not this
    module's place to decide a value looks wrong.
    """
    record = _records(sample_artifact)["3B7770"]

    assert record.registration == "0010"
    assert record.type_code == "A400"
    assert record.military_flag is True


def test_transform_rejects_a_line_with_too_few_fields(tmp_path: Path) -> None:
    """A structurally short line becomes an unusable-address record.

    The ADR-0006 boundary's own re-normalization (not this provider) is what
    turns that into a counted rejection — see ``_to_record``'s docstring.
    """
    path = tmp_path / "aircraft.csv.gz"
    path.write_bytes(gzip.compress(b"AABBCC;N1\n"))
    artifact = SourceArtifact(
        path=path, version="t", content_hash="", size_bytes=path.stat().st_size
    )

    records = list(MictronicsProvider().transform(artifact))

    assert len(records) == 1
    assert records[0].icao24 == ""


# ---------------------------------------------------------------------- validate


def test_validate_accepts_a_real_format_sample(
    sample_artifact: SourceArtifact, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The curated fixture is far smaller than a real snapshot; drop the size floor to match."""
    monkeypatch.setattr(mictronics, "MIN_ARTIFACT_BYTES", 10)

    report = MictronicsProvider().validate(sample_artifact)

    assert report.ok
    assert report.errors == ()


def test_validate_rejects_an_unreadable_artifact(tmp_path: Path) -> None:
    """A path that vanished between download and validate is still handled cleanly."""
    missing = tmp_path / "gone.csv.gz"
    artifact = SourceArtifact(
        path=missing, version="t", content_hash="", size_bytes=MIN_ARTIFACT_BYTES
    )

    report = MictronicsProvider().validate(artifact)

    assert not report.ok
    assert "could not read" in report.reason()


def test_sample_rows_stops_at_the_limit(sample_csv_bytes: bytes, tmp_path: Path) -> None:
    """Sampling reads no more of the file than the requested limit."""
    path = tmp_path / "aircraft.csv.gz"
    path.write_bytes(gzip.compress(sample_csv_bytes))

    sample = mictronics._sample_rows(path, 3)

    assert len(sample) == 3


def test_validate_rejects_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "aircraft.csv.gz"
    path.write_bytes(b"")
    artifact = SourceArtifact(path=path, version="t", content_hash="", size_bytes=0)

    report = MictronicsProvider().validate(artifact)

    assert not report.ok
    assert "byte" in report.reason()


def test_validate_rejects_a_garbage_header_even_when_large_enough(tmp_path: Path) -> None:
    """A captive-portal page or error body padded past the byte floor is still not gzip."""
    path = tmp_path / "aircraft.csv.gz"
    garbage = b"<html>not the aircraft database</html>" * 40_000  # well past the 1 MB floor
    path.write_bytes(garbage)
    artifact = SourceArtifact(path=path, version="t", content_hash="", size_bytes=len(garbage))

    report = MictronicsProvider().validate(artifact)

    assert not report.ok
    assert "gzip" in report.reason()


def test_validate_rejects_a_truncated_download(
    sample_csv_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connection that died mid-transfer leaves a gzip stream with a valid header but no end."""
    monkeypatch.setattr(mictronics, "MIN_ARTIFACT_BYTES", 10)
    whole = gzip.compress(sample_csv_bytes * 50)  # large enough that truncation lands mid-stream
    truncated = whole[: len(whole) * 2 // 3]
    path = tmp_path / "aircraft.csv.gz"
    path.write_bytes(truncated)
    artifact = SourceArtifact(path=path, version="t", content_hash="", size_bytes=len(truncated))

    report = MictronicsProvider().validate(artifact)

    assert not report.ok


def test_validate_rejects_rows_with_too_few_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mictronics, "MIN_ARTIFACT_BYTES", 10)
    body = (b"AABBCC;N1\n") * 100
    path = tmp_path / "aircraft.csv.gz"
    path.write_bytes(gzip.compress(body))
    artifact = SourceArtifact(
        path=path, version="t", content_hash="", size_bytes=path.stat().st_size
    )

    report = MictronicsProvider().validate(artifact)

    assert not report.ok
    assert "fields" in report.reason()


def test_validate_rejects_an_implausible_icao_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mictronics, "MIN_ARTIFACT_BYTES", 10)
    body = (b"ZZZZZZ;N1;B738;00;;;;\n") * 100
    path = tmp_path / "aircraft.csv.gz"
    path.write_bytes(gzip.compress(body))
    artifact = SourceArtifact(
        path=path, version="t", content_hash="", size_bytes=path.stat().st_size
    )

    report = MictronicsProvider().validate(artifact)

    assert not report.ok
    assert "ICAO" in report.reason()


def test_validate_rejects_a_file_with_no_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mictronics, "MIN_ARTIFACT_BYTES", 10)
    path = tmp_path / "aircraft.csv.gz"
    path.write_bytes(gzip.compress(b"\n\n\n"))
    artifact = SourceArtifact(
        path=path, version="t", content_hash="", size_bytes=path.stat().st_size
    )

    report = MictronicsProvider().validate(artifact)

    assert not report.ok
    assert "no rows" in report.reason()


# ----------------------------------------------------------------------- download


async def test_download_writes_bytes_and_hashes_them(
    sample_gzip_bytes: bytes, tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(mictronics.DEFAULT_ARTIFACT_URL)
        return httpx.Response(200, content=sample_gzip_bytes)

    provider = MictronicsProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    artifact = await provider.download(tmp_path)

    assert artifact.path.read_bytes() == sample_gzip_bytes
    assert artifact.size_bytes == len(sample_gzip_bytes)
    digest = hashlib.sha256(sample_gzip_bytes).hexdigest()
    assert artifact.content_hash == f"sha256:{digest}"
    assert artifact.version == f"sha256:{digest[:16]}"


async def test_download_raises_on_an_http_error_status(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"upstream unavailable")

    provider = MictronicsProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(httpx.HTTPStatusError):
        await provider.download(tmp_path)


async def test_download_enforces_the_size_cap(
    sample_gzip_bytes: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mictronics, "MAX_ARTIFACT_BYTES", 10)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sample_gzip_bytes)

    provider = MictronicsProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(MictronicsDownloadError):
        await provider.download(tmp_path)


async def test_download_uses_the_overridden_artifact_url(tmp_path: Path) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=gzip.compress(b"AABBCC;N1;B738;00;;;;\n"))

    provider = MictronicsProvider(
        artifact_url="https://example.test/custom.csv.gz",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    await provider.download(tmp_path)

    assert requested == ["https://example.test/custom.csv.gz"]


def test_build_client_returns_a_real_async_client() -> None:
    """The production default a bare ``MictronicsProvider()`` resolves to."""
    client = mictronics.build_client()

    assert isinstance(client, httpx.AsyncClient)
    assert client.follow_redirects is True
