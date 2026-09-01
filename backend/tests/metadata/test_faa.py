"""The FAA registry provider: download, validation, parsing, and precedence.

Fixture rows are built to match the real ``MASTER.txt``/``ACFTREF.txt``
layout byte for byte where it matters: the full 34-column header in order,
comma-delimited with a trailing empty column, every field padded with
trailing spaces the way the FAA's own export pads them. The parser has to
survive that padding, not a tidy test-only shape.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from flightsite.db import Database
from flightsite.metadata import MetadataImporter, SourceRegistry
from flightsite.metadata.precedence import DEFAULT_FIELD_PRIORITIES, PrecedenceModel, SourceClaim
from flightsite.metadata.records import SourceArtifact
from flightsite.metadata.repository import MetadataRepository
from flightsite.metadata.sources.faa import (
    ACFTREF_MEMBER,
    MASTER_MEMBER,
    FaaRegistryProvider,
    build_client,
)
from tests.metadata.conftest import record, resolved_rows
from tests.metadata.provider import InMemoryMetadataProvider

# ------------------------------------------------------------- fixture rows

#: The real MASTER.txt header, in order (``docs/LICENSES.md`` FAA row: fixed
#: CSV layout, verified against the published field list).
MASTER_FIELDS = [
    "N-NUMBER",
    "SERIAL NUMBER",
    "MFR MDL CODE",
    "ENG MFR MDL",
    "YEAR MFR",
    "TYPE REGISTRANT",
    "NAME",
    "STREET",
    "STREET2",
    "CITY",
    "STATE",
    "ZIP CODE",
    "REGION",
    "COUNTY",
    "COUNTRY",
    "LAST ACTION DATE",
    "CERT ISSUE DATE",
    "CERTIFICATION",
    "TYPE AIRCRAFT",
    "TYPE ENGINE",
    "STATUS CODE",
    "MODE S CODE",
    "FRACT OWNER",
    "AIR WORTH DATE",
    "OTHER NAMES(1)",
    "OTHER NAMES(2)",
    "OTHER NAMES(3)",
    "OTHER NAMES(4)",
    "OTHER NAMES(5)",
    "EXPIRATION DATE",
    "UNIQUE ID",
    "KIT MFR",
    "KIT MODEL",
    "MODE S CODE HEX",
]

ACFTREF_FIELDS = [
    "CODE",
    "MFR",
    "MODEL",
    "TYPE-ACFT",
    "TYPE-ENG",
    "AC-CAT",
    "BUILD-CERT-IND",
    "NO-ENG",
    "NO-SEATS",
    "AC-WEIGHT",
    "SPEED",
]

#: The width the FAA pads every field to in the real export. Wide enough that
#: none of the fixture's own values overflow it.
_PAD = 20


def _header(fields: list[str]) -> str:
    return ",".join(fields) + ",\r\n"


def master_row(**values: str) -> str:
    """One ``MASTER.txt`` data row, padded and comma-delimited like the real file."""
    cells = [values.get(name, "").ljust(_PAD) for name in MASTER_FIELDS]
    return ",".join(cells) + ",\r\n"


def acftref_row(**values: str) -> str:
    """One ``ACFTREF.txt`` data row, padded and comma-delimited."""
    cells = [values.get(name, "").ljust(_PAD) for name in ACFTREF_FIELDS]
    return ",".join(cells) + ",\r\n"


#: A join target: Cessna 172M under the code MASTER rows reference below.
ACFTREF_BODY = _header(ACFTREF_FIELDS) + acftref_row(CODE="1234567", MFR="CESSNA", MODEL="172M")

MASTER_ROWS = {
    # A complete, ordinary row: registration, year, owner, and a model join.
    "complete": master_row(
        **{
            "N-NUMBER": "12345",
            "MFR MDL CODE": "1234567",
            "YEAR MFR": "1976",
            "NAME": "JOHN Q PUBLIC",
            "MODE S CODE HEX": "A1B2C3",
        }
    ),
    # No Mode S hex at all -- most real MASTER rows -- nothing to key on.
    "blank_hex": master_row(
        **{
            "N-NUMBER": "99999",
            "MFR MDL CODE": "1234567",
            "YEAR MFR": "1990",
            "NAME": "JANE DOE",
            "MODE S CODE HEX": "",
        }
    ),
    # Year "0000" is the FAA's own spelling of "not on file".
    "zero_year": master_row(
        **{
            "N-NUMBER": "22222",
            "MFR MDL CODE": "1234567",
            "YEAR MFR": "0000",
            "NAME": "SOME OWNER",
            "MODE S CODE HEX": "AAAAAA",
        }
    ),
    # A blank NAME: withheld or simply not on file, either way unknown.
    "blank_owner": master_row(
        **{
            "N-NUMBER": "33333",
            "MFR MDL CODE": "1234567",
            "YEAR MFR": "1985",
            "NAME": "",
            "MODE S CODE HEX": "BBBBBB",
        }
    ),
    # A "sale reported" placeholder written into the NAME column itself.
    "sale_reported": master_row(
        **{
            "N-NUMBER": "44444",
            "MFR MDL CODE": "1234567",
            "YEAR MFR": "1985",
            "NAME": "SALE REPORTED",
            "MODE S CODE HEX": "CCCCCC",
        }
    ),
    # A "registration pending" placeholder, same idea, different wording.
    "registration_pending": master_row(
        **{
            "N-NUMBER": "55555",
            "MFR MDL CODE": "1234567",
            "YEAR MFR": "1985",
            "NAME": "registration pending",
            "MODE S CODE HEX": "DDDDDD",
        }
    ),
    # No ACFTREF match: the row still contributes what it does know.
    "unknown_model_code": master_row(
        **{
            "N-NUMBER": "66666",
            "MFR MDL CODE": "0000000",
            "YEAR MFR": "2001",
            "NAME": "NO MODEL OWNER",
            "MODE S CODE HEX": "EEEEEE",
        }
    ),
    # Garbage in the hex column: not blank, but not six hex digits either.
    "garbled_hex": master_row(
        **{
            "N-NUMBER": "77777",
            "MFR MDL CODE": "1234567",
            "YEAR MFR": "1985",
            "NAME": "GARBLED HEX OWNER",
            "MODE S CODE HEX": "ZZZZZZ",
        }
    ),
}


def build_master_body(*keys: str) -> str:
    return _header(MASTER_FIELDS) + "".join(MASTER_ROWS[key] for key in keys)


def build_zip_bytes(
    master_body: str = "", acftref_body: str = ACFTREF_BODY, *, extra_members: bool = True
) -> bytes:
    """A ``ReleasableAircraft.zip`` archive holding the given member bodies."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr(MASTER_MEMBER, master_body.encode("latin-1"))
        if extra_members:
            archive.writestr(ACFTREF_MEMBER, acftref_body.encode("latin-1"))
    return buffer.getvalue()


@pytest.fixture
def zip_path(tmp_path: Path) -> Path:
    """Where a built archive is written for validate()/transform() tests."""
    return tmp_path / "ReleasableAircraft.zip"


def write_zip(path: Path, *row_keys: str) -> SourceArtifact:
    """A full, well-formed archive with the given fixture rows, on disk."""
    data = build_zip_bytes(master_body=build_master_body(*row_keys))
    path.write_bytes(data)
    return SourceArtifact(path=path, version="test", size_bytes=len(data))


# ------------------------------------------------------------------ download


async def test_build_client_returns_a_usable_async_client() -> None:
    """The default factory :class:`FaaRegistryProvider` falls back to."""
    client = build_client()
    try:
        assert isinstance(client, httpx.AsyncClient)
        assert client.follow_redirects is True
    finally:
        await client.aclose()


async def test_download_streams_hashes_and_labels_the_snapshot(tmp_path: Path) -> None:
    body = build_zip_bytes(master_body=build_master_body("complete"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://faa.test/ReleasableAircraft.zip"
        return httpx.Response(
            200, content=body, headers={"last-modified": "Mon, 31 Aug 2026 05:30:00 GMT"}
        )

    provider = FaaRegistryProvider(
        url="https://faa.test/ReleasableAircraft.zip",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    artifact = await provider.download(tmp_path)

    assert artifact.path.read_bytes() == body
    assert artifact.size_bytes == len(body)
    assert artifact.version == "Mon, 31 Aug 2026 05:30:00 GMT"
    assert artifact.content_hash.startswith("sha256:")


async def test_download_falls_back_to_a_timestamp_version_with_no_headers(
    tmp_path: Path,
) -> None:
    body = build_zip_bytes(master_body=build_master_body("complete"))
    provider = FaaRegistryProvider(
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=body))
        ),
    )

    artifact = await provider.download(tmp_path)

    assert artifact.version  # non-empty; a real timestamp, not asserted exactly


async def test_download_raises_the_transport_failure(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    provider = FaaRegistryProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )

    with pytest.raises(httpx.ConnectError):
        await provider.download(tmp_path)


async def test_download_raises_on_an_http_error_status(tmp_path: Path) -> None:
    provider = FaaRegistryProvider(
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(503))
        ),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await provider.download(tmp_path)


# ------------------------------------------------------------------ validate


def test_validate_accepts_a_well_formed_archive(zip_path: Path) -> None:
    artifact = write_zip(zip_path, "complete", "blank_hex", "zero_year")
    provider = FaaRegistryProvider(min_master_rows=2)

    report = provider.validate(artifact)

    assert report.ok
    assert report.errors == ()


def test_validate_rejects_bytes_that_are_not_a_zip(tmp_path: Path) -> None:
    path = tmp_path / "not-a-zip.zip"
    path.write_bytes(b"<html>captive portal</html>")
    artifact = SourceArtifact(path=path, version="test")
    provider = FaaRegistryProvider()

    report = provider.validate(artifact)

    assert not report.ok
    assert "not a valid zip" in report.reason()


def test_validate_rejects_a_missing_member(tmp_path: Path) -> None:
    path = tmp_path / "ReleasableAircraft.zip"
    data = build_zip_bytes(master_body=build_master_body("complete"), extra_members=False)
    path.write_bytes(data)
    artifact = SourceArtifact(path=path, version="test")
    provider = FaaRegistryProvider(min_master_rows=1)

    report = provider.validate(artifact)

    assert not report.ok
    assert ACFTREF_MEMBER in report.reason()


def test_validate_rejects_a_corrupt_member(tmp_path: Path) -> None:
    path = tmp_path / "ReleasableAircraft.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr(MASTER_MEMBER, build_master_body("complete").encode("latin-1"))
        archive.writestr(ACFTREF_MEMBER, ACFTREF_BODY.encode("latin-1"))
    data = bytearray(buffer.getvalue())
    # Flip bytes in the middle of the archive to corrupt a member's data
    # without touching the central directory, so it opens but fails testzip().
    midpoint = len(data) // 2
    data[midpoint : midpoint + 8] = b"\x00" * 8
    path.write_bytes(bytes(data))
    artifact = SourceArtifact(path=path, version="test")
    provider = FaaRegistryProvider(min_master_rows=1)

    report = provider.validate(artifact)

    assert not report.ok


def test_validate_rejects_a_row_count_below_the_floor(zip_path: Path) -> None:
    artifact = write_zip(zip_path, "complete")
    provider = FaaRegistryProvider(min_master_rows=100)

    report = provider.validate(artifact)

    assert not report.ok
    assert "below" in report.reason()


def test_validate_leaves_expected_rows_unset(zip_path: Path) -> None:
    """Most MASTER rows have no hex code, so the raw count is not a floor
    on what ``transform`` yields -- setting it would fail good imports."""
    artifact = write_zip(zip_path, "complete", "blank_hex")
    provider = FaaRegistryProvider(min_master_rows=1)

    report = provider.validate(artifact)

    assert report.ok
    assert report.expected_rows is None


# ------------------------------------------------------------------ transform


def test_transform_yields_one_record_per_hex_bearing_row(zip_path: Path) -> None:
    artifact = write_zip(zip_path, "complete", "blank_hex", "garbled_hex")
    provider = FaaRegistryProvider()

    records = list(provider.transform(artifact))

    assert [r.icao24 for r in records] == ["a1b2c3"]


def test_transform_normalizes_registration_year_owner_and_model(zip_path: Path) -> None:
    artifact = write_zip(zip_path, "complete")
    provider = FaaRegistryProvider()

    [result] = list(provider.transform(artifact))

    assert result.icao24 == "a1b2c3"
    assert result.registration == "N12345"
    assert result.manufacture_year == 1976
    assert result.owner == "JOHN Q PUBLIC"
    assert result.model == "CESSNA 172M"
    # FAA does not lead on these; the provider must not fabricate them.
    assert result.type_code is None
    assert result.operator_name is None


def test_transform_nulls_a_zero_manufacture_year(zip_path: Path) -> None:
    artifact = write_zip(zip_path, "zero_year")
    provider = FaaRegistryProvider()

    [result] = list(provider.transform(artifact))

    assert result.manufacture_year is None


def test_transform_treats_a_blank_name_as_unknown(zip_path: Path) -> None:
    artifact = write_zip(zip_path, "blank_owner")
    provider = FaaRegistryProvider()

    [result] = list(provider.transform(artifact))

    assert result.owner is None


@pytest.mark.parametrize("row_key", ["sale_reported", "registration_pending"])
def test_transform_treats_status_placeholders_as_unknown_never_speculated(
    zip_path: Path, row_key: str
) -> None:
    """ "Sale Reported" / "Registration Pending" are workflow notes written
    into the NAME column, not registrant names -- never surfaced as one."""
    artifact = write_zip(zip_path, row_key)
    provider = FaaRegistryProvider()

    [result] = list(provider.transform(artifact))

    assert result.owner is None


def test_transform_still_yields_a_row_with_no_acftref_match(zip_path: Path) -> None:
    artifact = write_zip(zip_path, "unknown_model_code")
    provider = FaaRegistryProvider()

    [result] = list(provider.transform(artifact))

    assert result.model is None
    assert result.owner == "NO MODEL OWNER"
    assert result.manufacture_year == 2001


def test_transform_skips_acftref_rows_with_no_code_or_no_text(zip_path: Path) -> None:
    """A blank ``CODE`` row and a row with a code but no MFR/MODEL text are
    both real shapes in the published file; neither should poison the join
    table or crash the load."""
    acftref = _header(ACFTREF_FIELDS) + acftref_row(CODE="", MFR="NOBODY", MODEL="NOTHING")
    acftref += acftref_row(CODE="7654321")  # a code with no MFR/MODEL text at all
    acftref += acftref_row(CODE="1234567", MFR="CESSNA", MODEL="172M")
    body = build_zip_bytes(
        master_body=build_master_body("complete", "unknown_model_code"), acftref_body=acftref
    )
    path = zip_path
    path.write_bytes(body)
    artifact = SourceArtifact(path=path, version="test", size_bytes=len(body))
    provider = FaaRegistryProvider()

    results = {r.icao24: r for r in provider.transform(artifact)}

    assert results["a1b2c3"].model == "CESSNA 172M"
    assert results["eeeeee"].model is None  # references code "0000000", never defined


def test_transform_handles_a_master_file_with_no_header_row(zip_path: Path) -> None:
    """An entirely empty ``MASTER.txt`` (no header) yields nothing, not a crash."""
    body = build_zip_bytes(master_body="")
    zip_path.write_bytes(body)
    artifact = SourceArtifact(path=zip_path, version="test", size_bytes=len(body))
    provider = FaaRegistryProvider()

    assert list(provider.transform(artifact)) == []


def test_transform_streams_without_building_a_row_list_up_front(zip_path: Path) -> None:
    """``transform`` is a generator: nothing is read before the first pull."""
    artifact = write_zip(zip_path, "complete", "blank_hex")
    provider = FaaRegistryProvider()

    iterator = provider.transform(artifact)

    assert next(iterator).icao24 == "a1b2c3"
    with pytest.raises(StopIteration):
        next(iterator)


# --------------------------------------------------------- precedence & e2e


async def test_faa_supplements_year_and_owner_without_clobbering_identity(
    importer: MetadataImporter,
    registry: SourceRegistry,
    database: Database,
    zip_path: Path,
) -> None:
    """The acceptance criterion, run through the real pipeline.

    Mictronics-style identity (registration, type, model, operator) must
    survive an FAA import for the same airframe untouched, while FAA fills in
    the year and owner Mictronics left blank -- exactly the "supplements,
    does not clobber" rule ``precedence.py`` documents.
    """
    icao = "a1b2c3"
    registry.register(
        "mictronics",
        InMemoryMetadataProvider(
            [
                record(
                    icao,
                    registration="N999ZZ",
                    type_code="C172",
                    model="Skyhawk (Mictronics)",
                    operator_name="Private",
                )
            ]
        ),
    )
    artifact = write_zip(zip_path, "complete")
    registry.register(
        "faa",
        FaaRegistryProvider(
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _r: httpx.Response(200, content=artifact.path.read_bytes())
                )
            ),
            min_master_rows=1,
        ),
    )

    run = await importer.run()

    assert set(run.succeeded) == {"mictronics", "faa"}
    resolved = await resolved_rows(MetadataRepository(database), [icao])
    row = resolved[icao]
    # Mictronics wins the identity triple -- FAA's differing claims lose.
    assert row.registration == "N999ZZ"
    assert row.registration_src == "mictronics"
    assert row.type_code == "C172"
    assert row.type_code_src == "mictronics"
    assert row.operator_name == "Private"
    assert row.operator_src == "mictronics"
    # FAA is the only claim on year/owner -- it wins by default, not by rank.
    assert row.manufacture_year == 1976
    assert row.year_src == "faa"
    assert row.owner == "JOHN Q PUBLIC"
    assert row.owner_src == "faa"


def test_precedence_model_ranks_faa_below_mictronics_on_identity_fields(
    zip_path: Path,
) -> None:
    """A pure precedence-table check: the provider's real output against
    ``PrecedenceModel`` directly, no database in the loop."""
    icao = "a1b2c3"
    mictronics = SourceClaim(
        source="mictronics",
        record=record(icao, registration="N1AA", type_code="B738"),
    )
    artifact = write_zip(zip_path, "complete")
    [faa_record] = list(FaaRegistryProvider().transform(artifact))
    faa = SourceClaim(source="faa", record=faa_record)

    model = PrecedenceModel(dict(DEFAULT_FIELD_PRIORITIES))
    resolved = model.resolve(icao, [mictronics, faa], updated_ms=1)

    # Mictronics' identity claim wins even though FAA also has an opinion.
    assert resolved.registration == "N1AA"
    assert resolved.registration_src == "mictronics"
    assert resolved.type_code == "B738"
    assert resolved.type_code_src == "mictronics"
    # Only FAA claims year/owner; it wins those by being the sole bidder.
    assert resolved.manufacture_year == 1976
    assert resolved.year_src == "faa"
    assert resolved.owner == "JOHN Q PUBLIC"
    assert resolved.owner_src == "faa"
