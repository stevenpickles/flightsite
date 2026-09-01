"""The OurAirports adapter: download, validation gate, and the type filter.

No socket is opened anywhere in this module. Downloads run over an
``httpx.MockTransport``, so the provider's request building and its streaming
size cap are exercised for real (``docs/TEST_STRATEGY.md`` §"No external network
in tests").

Rows are built from :data:`COLUMNS` rather than written out by hand, because
*columns are located by name*: a test that removes a column has to remove it
from the header and the rows together, or it tests a broken fixture instead of
testing the reader.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from io import StringIO
from pathlib import Path

import httpx
import pytest

from flightsite.airports.ourairports import (
    ARTIFACT_FILENAME,
    MAX_ARTIFACT_BYTES,
    MIN_ARTIFACT_BYTES,
    MIN_EXPECTED_ROWS,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    OurAirportsDownloadError,
    OurAirportsProvider,
)
from flightsite.metadata.records import SourceArtifact

#: Upstream's nineteen columns, in upstream's order.
COLUMNS: tuple[str, ...] = (
    "id",
    "ident",
    "type",
    "name",
    "latitude_deg",
    "longitude_deg",
    "elevation_ft",
    "continent",
    "iso_country",
    "iso_region",
    "municipality",
    "scheduled_service",
    "icao_code",
    "iata_code",
    "gps_code",
    "local_code",
    "home_link",
    "wikipedia_link",
    "keywords",
)

#: One airport of each kind that matters: an imported type with every optional
#: field, an imported type with almost none, and one of each excluded type.
FIXTURE_ROWS: tuple[dict[str, str], ...] = (
    {
        "id": "3411",
        "ident": "KBFI",
        "type": "large_airport",
        "name": "Boeing Field",
        "latitude_deg": "47.53",
        "longitude_deg": "-122.3018",
        "elevation_ft": "21",
        "iso_country": "US",
        "iata_code": "BFI",
    },
    {
        "id": "6523",
        "ident": "00A",
        "type": "heliport",
        "name": "Total RF Heliport",
        "latitude_deg": "40.070985",
        "longitude_deg": "-74.933689",
        "elevation_ft": "11",
        "iso_country": "US",
    },
    {
        "id": "323361",
        "ident": "00AA",
        "type": "small_airport",
        "name": "Aero B Ranch Airport",
        "latitude_deg": "38.704022",
        "longitude_deg": "-101.473911",
        "elevation_ft": "3435",
        "iso_country": "US",
    },
    {
        "id": "9999",
        "ident": "KOLD",
        "type": "closed",
        "name": "Long Gone Field",
        "latitude_deg": "40.0",
        "longitude_deg": "-75.0",
    },
    {
        "id": "8888",
        "ident": "WATER",
        "type": "seaplane_base",
        "name": "Lake Landing Area",
        "latitude_deg": "47.6",
        "longitude_deg": "-122.2",
    },
    {
        "id": "7777",
        "ident": "BALLO",
        "type": "balloonport",
        "name": "Balloon Field",
        "latitude_deg": "40.0",
        "longitude_deg": "-105.0",
    },
)

#: Filler rows needed to clear the artifact-size floor. Generated in one pass,
#: so a two-megabyte fixture costs milliseconds rather than a quadratic join.
PAD_ROWS = MIN_ARTIFACT_BYTES // 50


def _filler(index: int) -> dict[str, str]:
    return {
        "id": str(500_000 + index),
        "ident": f"PAD{index:05d}",
        "type": "small_airport",
        "name": f"Filler Field {index}",
        "latitude_deg": "10.0",
        "longitude_deg": "10.0",
        "iso_country": "US",
    }


def csv_bytes(
    rows: Sequence[dict[str, str]] = FIXTURE_ROWS,
    *,
    columns: Sequence[str] = COLUMNS,
    pad: bool = False,
) -> bytes:
    """A CSV payload in upstream's shape, optionally padded past the size floor."""
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows({name: row.get(name, "") for name in columns} for row in rows)
    if pad:
        writer.writerows(
            {name: _filler(index).get(name, "") for name in columns} for index in range(PAD_ROWS)
        )
    return buffer.getvalue().encode("utf-8")


def without(column: str) -> tuple[str, ...]:
    """Upstream's columns with one removed, as a dropped column would leave them."""
    return tuple(name for name in COLUMNS if name != column)


def artifact(tmp_path: Path, payload: bytes) -> SourceArtifact:
    """An artifact on disk, as ``download`` would have left one."""
    path = tmp_path / ARTIFACT_FILENAME
    path.write_bytes(payload)
    return SourceArtifact(path=path, version="fixture", size_bytes=len(payload))


def provider_over(payload: bytes, *, status_code: int = 200) -> OurAirportsProvider:
    """A provider whose client answers with ``payload`` and never opens a socket."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=payload)

    return OurAirportsProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


# ------------------------------------------------------------------ download


async def test_download_writes_the_artifact_and_hashes_it(tmp_path: Path) -> None:
    """The hash is the version: upstream publishes no tag reachable from the file."""
    payload = csv_bytes()

    found = await provider_over(payload).download(tmp_path)

    assert found.path == tmp_path / ARTIFACT_FILENAME
    assert found.path.read_bytes() == payload
    assert found.size_bytes == len(payload)
    # The version is the head of the full digest, so the two cannot disagree
    # about which bytes they describe.
    assert found.version.startswith("sha256:")
    assert found.content_hash.startswith(found.version)


async def test_the_same_bytes_produce_the_same_version(tmp_path: Path) -> None:
    """So a day when upstream changed nothing re-imports as a visible no-op."""
    first = await provider_over(csv_bytes()).download(tmp_path)
    second = await provider_over(csv_bytes()).download(tmp_path)

    assert first.version == second.version


async def test_different_bytes_produce_a_different_version(tmp_path: Path) -> None:
    first = await provider_over(csv_bytes()).download(tmp_path)
    second = await provider_over(csv_bytes(FIXTURE_ROWS[:2])).download(tmp_path)

    assert first.version != second.version


async def test_an_http_error_propagates(tmp_path: Path) -> None:
    """The pipeline records it against this source alone and keeps the old rows."""
    with pytest.raises(httpx.HTTPStatusError):
        await provider_over(b"nope", status_code=503).download(tmp_path)


async def test_an_oversized_download_is_refused_mid_stream(tmp_path: Path) -> None:
    """Bounds memory on a Pi against a misbehaving or compromised endpoint."""
    oversized = b"x" * (MAX_ARTIFACT_BYTES + 1)

    with pytest.raises(OurAirportsDownloadError, match="exceeds"):
        await provider_over(oversized).download(tmp_path)


# ---------------------------------------------------------------- validation


def test_a_genuine_snapshot_validates(tmp_path: Path) -> None:
    report = OurAirportsProvider().validate(artifact(tmp_path, csv_bytes(pad=True)))

    assert report.ok
    assert report.expected_rows == MIN_EXPECTED_ROWS
    assert report.warnings == ()


def test_a_short_download_is_rejected(tmp_path: Path) -> None:
    """A captive-portal page, an error body, or a transfer that died partway."""
    report = OurAirportsProvider().validate(artifact(tmp_path, csv_bytes()))

    assert not report.ok
    assert "floor" in report.reason()


@pytest.mark.parametrize("missing", REQUIRED_COLUMNS)
def test_a_missing_required_column_is_rejected(tmp_path: Path, missing: str) -> None:
    """Renamed or dropped upstream: a rejection, not an import of nulls."""
    payload = csv_bytes(columns=without(missing), pad=True)

    report = OurAirportsProvider().validate(artifact(tmp_path, payload))

    assert not report.ok
    assert missing in report.reason()


@pytest.mark.parametrize("missing", OPTIONAL_COLUMNS)
def test_a_missing_optional_column_warns_rather_than_rejects(tmp_path: Path, missing: str) -> None:
    """Each maps to a field that is legitimately ``None``; losing one degrades."""
    payload = csv_bytes(columns=without(missing), pad=True)

    report = OurAirportsProvider().validate(artifact(tmp_path, payload))

    assert report.ok
    assert any(missing in warning for warning in report.warnings)


def test_a_file_of_the_right_size_but_the_wrong_shape_is_rejected(tmp_path: Path) -> None:
    """Big enough to pass the size floor, and not remotely an airport file."""
    header = ",".join(COLUMNS)
    payload = (header + "\n" + ("garbage,rows,without,coordinates\n" * 100_000)).encode("utf-8")

    report = OurAirportsProvider().validate(artifact(tmp_path, payload))

    assert not report.ok


def test_a_file_with_a_header_and_no_rows_at_all_is_rejected(tmp_path: Path) -> None:
    """Big enough to pass the floor because the *header* is enormous."""
    padding = (f"column_{index:06d}" for index in range(MIN_ARTIFACT_BYTES // 13))
    header = ",".join((*COLUMNS, *padding))
    payload = (header + "\n").encode("utf-8")

    report = OurAirportsProvider().validate(artifact(tmp_path, payload))

    assert not report.ok
    assert "no rows" in report.reason()


def test_rows_with_no_ident_fail_the_plausibility_sample(tmp_path: Path) -> None:
    """A file of the right shape whose key column is empty is not this dataset."""
    nameless = [
        {
            "id": str(index),
            "ident": "",
            "type": "small_airport",
            "name": f"Nameless {index}",
            "latitude_deg": "10.0",
            "longitude_deg": "10.0",
        }
        for index in range(PAD_ROWS)
    ]
    payload = csv_bytes(nameless)

    report = OurAirportsProvider().validate(artifact(tmp_path, payload))

    assert not report.ok
    assert "usable ident" in report.reason()


def test_the_default_client_is_built_with_a_timeout_and_redirects(tmp_path: Path) -> None:
    """The factory a stock install uses. Constructed, never used, here."""
    from flightsite.airports.ourairports import DEFAULT_TIMEOUT_S, build_client

    client = build_client()
    try:
        assert client.timeout.read == DEFAULT_TIMEOUT_S
        assert client.follow_redirects
    finally:
        pass


def test_a_header_followed_by_junk_is_rejected(tmp_path: Path) -> None:
    """One enormous unparseable line: a header, and nothing that reads as a row."""
    header = ",".join(COLUMNS)
    payload = (header + "\n" + ("#" * (MIN_ARTIFACT_BYTES + 1))).encode("utf-8")

    report = OurAirportsProvider().validate(artifact(tmp_path, payload))

    assert not report.ok


def test_an_unreadable_artifact_is_rejected_not_raised(tmp_path: Path) -> None:
    """A rejection is a status a user can read; an exception is a traceback."""
    missing = SourceArtifact(
        path=tmp_path / "not-there.csv",
        version="fixture",
        size_bytes=MIN_ARTIFACT_BYTES + 1,
    )

    report = OurAirportsProvider().validate(missing)

    assert not report.ok
    assert "could not read" in report.reason()


def test_bytes_that_are_not_utf8_are_rejected(tmp_path: Path) -> None:
    payload = b"\xff\xfe" + b"x" * (MIN_ARTIFACT_BYTES + 1)

    report = OurAirportsProvider().validate(artifact(tmp_path, payload))

    assert not report.ok


# ----------------------------------------------------------------- transform


def test_the_transform_imports_only_the_four_documented_types(tmp_path: Path) -> None:
    """Closed fields, seaplane bases and balloonports are skipped silently.

    Silently rather than rejected: they are not malformed, and counting them
    would make a healthy snapshot look like it was failing its own tolerance.
    """
    records = list(OurAirportsProvider().transform(artifact(tmp_path, csv_bytes())))

    assert [record.ident for record in records] == ["KBFI", "00A", "00AA"]


def test_a_row_is_read_by_column_name_not_position(tmp_path: Path) -> None:
    """Upstream has added columns before and will again."""
    reordered = (
        "name",
        "type",
        "ident",
        "longitude_deg",
        "latitude_deg",
        "iata_code",
        "elevation_ft",
        "iso_country",
        "id",
        "brand_new_column",
    )
    payload = csv_bytes((FIXTURE_ROWS[0],), columns=reordered)

    records = list(OurAirportsProvider().transform(artifact(tmp_path, payload)))

    assert len(records) == 1
    found = records[0]
    assert found.ident == "KBFI"
    assert found.lat == pytest.approx(47.53)
    assert found.lon == pytest.approx(-122.3018)
    assert found.iata == "BFI"
    assert found.elevation_ft == 21
    assert found.iso_country == "US"
    assert found.upstream_id == 3411


def test_optional_fields_come_back_none_when_upstream_has_none(tmp_path: Path) -> None:
    records = {
        record.ident: record
        for record in OurAirportsProvider().transform(artifact(tmp_path, csv_bytes()))
    }

    heliport = records["00A"]
    assert heliport.iata is None
    assert heliport.name == "Total RF Heliport"
    assert heliport.type == "heliport"


def test_an_unparseable_row_of_an_imported_type_is_yielded_for_rejection(
    tmp_path: Path,
) -> None:
    """Rejected and *counted* by the pipeline, not dropped where nobody sees it."""
    broken = {
        "id": "4444",
        "ident": "KBAD",
        "type": "small_airport",
        "name": "Broken Field",
        "latitude_deg": "not-a-latitude",
        "longitude_deg": "-75.0",
    }
    payload = csv_bytes((broken,))

    records = list(OurAirportsProvider().transform(artifact(tmp_path, payload)))

    assert len(records) == 1
    assert records[0].ident == ""


def test_the_transform_streams_rather_than_materializing(tmp_path: Path) -> None:
    """An iterator, not a list: the file is ~13 MB and the pipeline batches it."""
    found = OurAirportsProvider().transform(artifact(tmp_path, csv_bytes()))

    assert next(iter(found)).ident == "KBFI"


def test_the_fixture_columns_are_the_shape_the_reader_expects() -> None:
    """Guards the fixture itself: a wrong header would make this module lie."""
    for column in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS):
        assert column in COLUMNS
