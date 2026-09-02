"""The OpenSky aircraft database adapter (slice 059, ADR-0013).

Three things this suite is really about, beyond the ordinary parse checks:

* **The fields this source refuses to claim.** ``registration`` and
  ``type_code`` are present in the upstream file and deliberately dropped, so
  that even a precedence misconfiguration could not let a crowdsourced
  designator fragment FlightSite's type statistics. That is a guarantee worth a
  test, not a comment.
* **Placeholders are not names.** ``"Private"`` in an owner column would land in
  a field the higher-precedence sources left empty on purpose.
* **Malformed input is refused rather than half-imported** (``docs/SECURITY.md``
  §4), including the fuzz-style pass at the bottom of this file: whatever bytes
  go in, ``validate`` returns a verdict and ``transform`` either yields
  records or raises something the importer already catches — it never hangs and
  never emits a record the ADR-0006 boundary would have to guess about.
"""

from __future__ import annotations

import random
from pathlib import Path

import httpx
import pytest

from flightsite.metadata.records import SourceArtifact
from flightsite.metadata.sources import opensky
from flightsite.metadata.sources.opensky import OpenSkyDownloadError, OpenSkyProvider

from .conftest import OPENSKY_CONTRIBUTING_ICAOS, OPENSKY_SKIPPED_ICAOS


def _artifact(path: Path, *, size_bytes: int | None = None) -> SourceArtifact:
    """A :class:`SourceArtifact` over ``path``, clearing the size floor."""
    return SourceArtifact(
        path=path,
        version="test",
        content_hash="",
        size_bytes=opensky.MIN_ARTIFACT_BYTES if size_bytes is None else size_bytes,
    )


def _write(path: Path, text: str) -> SourceArtifact:
    path.write_text(text, encoding="utf-8", newline="")
    return _artifact(path)


HEADER = (
    '"icao24","registration","manufacturericao","manufacturername","model","typecode",'
    '"serialnumber","linenumber","icaoaircrafttype","operator","operatorcallsign",'
    '"operatoricao","operatoriata","owner","testreg","registered","reguntil","status",'
    '"built","firstflightdate","seatconfiguration","engines","modes","adsb","acars",'
    '"notes","categoryDescription"'
)


def _row(**overrides: str) -> str:
    """One CSV row with every column empty except those named."""
    columns = [name.strip('"') for name in HEADER.split(",")]
    values = dict.fromkeys(columns, "")
    values.update(overrides)
    return ",".join(f'"{values[name]}"' for name in columns)


# ------------------------------------------------------------------- transform


def test_transform_maps_a_real_row_onto_the_normalized_record(
    opensky_artifact: SourceArtifact,
) -> None:
    records = {record.icao24: record for record in OpenSkyProvider().transform(opensky_artifact)}

    fedex = records["ad4b72"]
    assert fedex.operator_name == "Federal Express"
    assert fedex.owner == "Federal Express Corp"
    assert fedex.model == "Boeing 757-236"
    assert fedex.manufacture_year == 1998


def test_transform_yields_exactly_the_contributing_rows(
    opensky_artifact: SourceArtifact,
) -> None:
    """Rows with nothing to contribute are skipped, not rejected.

    A skipped row must not reach the importer's reject-ratio tolerance: it is
    silent, not malformed, and counting it would make a healthy snapshot look
    like a failing one.
    """
    yielded = {record.icao24 for record in OpenSkyProvider().transform(opensky_artifact)}

    assert yielded == OPENSKY_CONTRIBUTING_ICAOS
    assert yielded.isdisjoint(OPENSKY_SKIPPED_ICAOS)


def test_transform_never_claims_a_registration_or_type_code(
    opensky_artifact: SourceArtifact,
) -> None:
    """The deliberate omission — see the module docstring of the adapter.

    The fixture's rows all carry both fields upstream, so this passing means
    they were dropped, not merely absent.
    """
    records = list(OpenSkyProvider().transform(opensky_artifact))

    assert records, "fixture should yield records"
    assert all(record.registration is None for record in records)
    assert all(record.type_code is None for record in records)


def test_transform_drops_a_placeholder_owner_but_keeps_the_rest_of_the_row(
    opensky_artifact: SourceArtifact,
) -> None:
    records = {record.icao24: record for record in OpenSkyProvider().transform(opensky_artifact)}

    private = records["3fee2c"]
    assert private.owner is None, "'Private' is a placeholder, not an owner name"
    assert private.model == "Flight Design CT 2K"


def test_transform_takes_the_year_out_of_an_iso_built_date(
    opensky_artifact: SourceArtifact,
) -> None:
    records = {record.icao24: record for record in OpenSkyProvider().transform(opensky_artifact)}

    assert records["a29bf7"].manufacture_year == 1966
    assert records["400e85"].manufacture_year == 2006
    assert records["aa3487"].manufacture_year is None, "blank 'built' is not a year"


def test_transform_skips_the_all_empty_row_a_real_snapshot_opens_with(
    opensky_artifact: SourceArtifact,
) -> None:
    assert all(record.icao24 for record in OpenSkyProvider().transform(opensky_artifact))


@pytest.mark.parametrize(
    ("manufacturer", "model", "expected"),
    [
        ("Boeing", "757-236", "Boeing 757-236"),
        ("Boeing", "Boeing 737-800", "Boeing 737-800"),
        ("", "M20E", "M20E"),
        ("Mooney", "", "Mooney"),
        ("  Cessna  ", "  172 S  ", "Cessna 172 S"),
        ("", "", None),
    ],
)
def test_manufacturer_and_model_join_the_way_the_faa_adapter_writes_them(
    tmp_path: Path, manufacturer: str, model: str, expected: str | None
) -> None:
    """``model`` holds ``"<manufacturer> <model>"``, matching ``faa.py``.

    The doubled case matters: upstream sometimes repeats the manufacturer
    inside the model string, and "Boeing Boeing 737-800" would be a visible
    defect in the aircraft detail panel.
    """
    artifact = _write(
        tmp_path / "db.csv",
        f"{HEADER}\n{_row(icao24='abc123', manufacturername=manufacturer, model=model)}\n",
    )

    records = list(OpenSkyProvider().transform(artifact))

    if expected is None:
        assert records == [], "a row contributing nothing is skipped entirely"
    else:
        assert records[0].model == expected


@pytest.mark.parametrize("placeholder", ["Private", "PRIVATE", "unknown", "N/A", "-", "  none  "])
def test_placeholder_party_names_are_dropped_from_both_owner_and_operator(
    tmp_path: Path, placeholder: str
) -> None:
    row = _row(icao24="abc123", owner=placeholder, operator=placeholder, built="1999")
    artifact = _write(tmp_path / "db.csv", f"{HEADER}\n{row}\n")

    record = next(iter(OpenSkyProvider().transform(artifact)))

    assert record.owner is None
    assert record.operator_name is None
    assert record.manufacture_year == 1999, "the rest of the row survives"


def test_a_bare_year_in_built_is_accepted(tmp_path: Path) -> None:
    artifact = _write(tmp_path / "db.csv", f"{HEADER}\n{_row(icao24='abc123', built='1977')}\n")

    assert next(iter(OpenSkyProvider().transform(artifact))).manufacture_year == 1977


@pytest.mark.parametrize("built", ["not-a-date", "", "0000-01-01", "12", "-1998"])
def test_an_unusable_built_value_is_dropped_rather_than_failing_the_row(
    tmp_path: Path, built: str
) -> None:
    """A garbled date is not a reason to discard an otherwise usable row."""
    artifact = _write(
        tmp_path / "db.csv",
        f"{HEADER}\n{_row(icao24='abc123', owner='Real Owner Ltd', built=built)}\n",
    )

    record = next(iter(OpenSkyProvider().transform(artifact)))

    assert record.manufacture_year is None
    assert record.owner == "Real Owner Ltd"


def test_transform_reads_by_column_name_not_position(tmp_path: Path) -> None:
    """An upstream that inserts a column must not shift every field.

    This is the whole reason the adapter uses ``DictReader`` over a 27-column
    file rather than indexing.
    """
    header = f'"spurious_new_column",{HEADER}'
    row = f'"junk",{_row(icao24="abc123", owner="Real Owner Ltd", built="2001-06-01")}'
    artifact = _write(tmp_path / "db.csv", f"{header}\n{row}\n")

    record = next(iter(OpenSkyProvider().transform(artifact)))

    assert record.icao24 == "abc123"
    assert record.owner == "Real Owner Ltd"
    assert record.manufacture_year == 2001


def test_a_row_with_more_fields_than_the_header_is_handled_not_crashed(
    tmp_path: Path,
) -> None:
    """Regression: ``DictReader`` files surplus fields in a *list*.

    A row longer than the header puts the extras under the reader's ``restkey``
    as a ``list``, not a ``str`` — so any code doing ``.strip()`` on the
    mapping's values dies with ``AttributeError`` on a corrupt artifact. Found
    by the fuzz pass below; pinned here so it stays fixed.
    """
    long_row = f'{_row(icao24="abc123", owner="Real Owner Ltd")},"surplus","more surplus"'
    artifact = _write(tmp_path / "db.csv", f"{HEADER}\n{long_row}\n")

    assert OpenSkyProvider().validate(artifact).ok
    record = next(iter(OpenSkyProvider().transform(artifact)))
    assert record.icao24 == "abc123"
    assert record.owner == "Real Owner Ltd"


def test_a_row_with_fewer_fields_than_the_header_reads_the_rest_as_absent(
    tmp_path: Path,
) -> None:
    """A truncated row leaves later columns missing, not ``None``-typed."""
    artifact = _write(tmp_path / "db.csv", f'{HEADER}\n"abc123","N1","MAKER","Maker","Model"\n')

    records = list(OpenSkyProvider().transform(artifact))

    assert records[0].icao24 == "abc123"
    assert records[0].model == "Maker Model"
    assert records[0].owner is None


# -------------------------------------------------------------------- validate


def test_validate_accepts_a_real_format_sample(opensky_artifact: SourceArtifact) -> None:
    assert OpenSkyProvider().validate(opensky_artifact).ok


def test_validate_rejects_a_truncated_download(opensky_artifact: SourceArtifact) -> None:
    """The size floor stands in for a row-count floor without a full scan."""
    small = SourceArtifact(
        path=opensky_artifact.path, version="test", content_hash="", size_bytes=4096
    )

    report = OpenSkyProvider().validate(small)

    assert not report.ok
    assert "below the" in report.reason()


def test_validate_rejects_a_file_missing_a_required_column(tmp_path: Path) -> None:
    header = HEADER.replace('"owner",', "")
    artifact = _write(tmp_path / "db.csv", f"{header}\n")

    report = OpenSkyProvider().validate(artifact)

    assert not report.ok
    assert "owner" in report.reason()


def test_validate_tolerates_an_upstream_that_adds_a_column(tmp_path: Path) -> None:
    """Only the columns the adapter reads are required; extras are ignored."""
    row = f'{_row(icao24="abc123", owner="Real Owner Ltd")},"extra"'
    artifact = _write(tmp_path / "db.csv", f'{HEADER},"spurious_new_column"\n{row}\n')

    assert OpenSkyProvider().validate(artifact).ok


def test_validate_rejects_a_header_only_file(tmp_path: Path) -> None:
    artifact = _write(tmp_path / "db.csv", f"{HEADER}\n")

    report = OpenSkyProvider().validate(artifact)

    assert not report.ok
    assert "no rows" in report.reason()


def test_validate_rejects_a_garbage_body_even_when_large_enough(tmp_path: Path) -> None:
    """A wrong file that clears the size floor must still be caught."""
    artifact = _write(tmp_path / "db.csv", "<!DOCTYPE html>\n<html><body>Not here</body></html>\n")

    assert not OpenSkyProvider().validate(artifact).ok


def test_validate_rejects_an_implausible_icao_rate(tmp_path: Path) -> None:
    rows = "\n".join(_row(icao24=f"not-hex-{index}", owner="Some Owner") for index in range(50))
    artifact = _write(tmp_path / "db.csv", f"{HEADER}\n{rows}\n")

    report = OpenSkyProvider().validate(artifact)

    assert not report.ok
    assert "plausible ICAO" in report.reason()


def test_validate_rejects_an_unreadable_artifact(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "does-not-exist.csv")

    report = OpenSkyProvider().validate(artifact)

    assert not report.ok
    assert "could not read" in report.reason()


def test_validate_does_not_read_the_whole_file(tmp_path: Path) -> None:
    """``validate`` runs on the event loop, so its cost must not scale.

    Sampling stops at :data:`VALIDATE_SAMPLE_ROWS`; the sentinel row past that
    bound would fail the plausibility check if it were ever read.
    """
    good = "\n".join(
        _row(icao24=f"{index:06x}", owner="Some Owner")
        for index in range(opensky.VALIDATE_SAMPLE_ROWS)
    )
    poison = "\n".join(_row(icao24="not-hex", owner="Some Owner") for _ in range(5_000))
    artifact = _write(tmp_path / "db.csv", f"{HEADER}\n{good}\n{poison}\n")

    assert OpenSkyProvider().validate(artifact).ok


# -------------------------------------------------------------------- download


def _client_factory(handler: object) -> opensky.ClientFactory:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": opensky.USER_AGENT},
        )

    return factory


async def test_download_streams_to_disk_and_records_a_content_hash(
    tmp_path: Path, opensky_csv_bytes: bytes
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=opensky_csv_bytes)

    provider = OpenSkyProvider(client_factory=_client_factory(handler))

    artifact = await provider.download(tmp_path)

    assert artifact.path.read_bytes() == opensky_csv_bytes
    assert artifact.size_bytes == len(opensky_csv_bytes)
    assert artifact.version.startswith("sha256:")
    assert artifact.content_hash.startswith("sha256:")


async def test_download_sends_an_identifying_user_agent(tmp_path: Path) -> None:
    """Basic courtesy to a donation-funded non-profit serving a 94 MB file."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, content=b"data")

    await OpenSkyProvider(client_factory=_client_factory(handler)).download(tmp_path)

    assert seen and seen[0] == opensky.USER_AGENT
    assert "FlightSite" in seen[0]
    assert "python-httpx" not in seen[0]


async def test_download_raises_on_an_http_error_status(tmp_path: Path) -> None:
    """The dataset may eventually 404 — see the adapter's "Staleness"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    provider = OpenSkyProvider(client_factory=_client_factory(handler))

    with pytest.raises(httpx.HTTPStatusError):
        await provider.download(tmp_path)


async def test_download_enforces_the_size_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(opensky, "MAX_ARTIFACT_BYTES", 64)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)

    provider = OpenSkyProvider(client_factory=_client_factory(handler))

    with pytest.raises(OpenSkyDownloadError):
        await provider.download(tmp_path)


async def test_download_follows_the_redirect_the_real_endpoint_serves(
    tmp_path: Path, opensky_csv_bytes: bytes
) -> None:
    """The documented URL 302s to the project's S3 bucket."""
    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(str(request.url))
        if len(visited) == 1:
            return httpx.Response(302, headers={"Location": "https://s3.example/aircraft.csv"})
        return httpx.Response(200, content=opensky_csv_bytes)

    provider = OpenSkyProvider(client_factory=_client_factory(handler))

    artifact = await provider.download(tmp_path)

    assert len(visited) == 2
    assert artifact.path.read_bytes() == opensky_csv_bytes


# ------------------------------------------------------------------ fuzz-style


@pytest.mark.parametrize("seed", range(24))
def test_arbitrary_bytes_never_crash_validate_or_transform(tmp_path: Path, seed: int) -> None:
    """SECURITY §4: a hostile or corrupt artifact is refused, not survived halfway.

    Deterministic per seed so a failure is reproducible. The contract asserted
    here is narrow on purpose: every record that escapes ``transform`` must
    carry a non-empty address, because a record without one is a row the
    ADR-0006 boundary would have to reject — and rows this source cannot use
    are supposed to be skipped before they ever get that far.
    """
    rng = random.Random(seed)
    alphabet = 'abcdef0123456789,"\n\r\\;\x00 äö-'
    body = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 3_000)))
    artifact = _write(tmp_path / "db.csv", rng.choice([HEADER + "\n", ""]) + body)

    report = OpenSkyProvider().validate(artifact)
    assert isinstance(report.ok, bool)
    if not report.ok:
        assert report.reason(), "a rejection must explain itself"

    try:
        records = list(OpenSkyProvider().transform(artifact))
    except (ValueError, OSError, UnicodeDecodeError):
        # Errors the importer already catches and records as this source's
        # failure, leaving the previous dataset intact.
        return

    assert all(record.icao24.strip() for record in records)
    assert all(record.registration is None and record.type_code is None for record in records)


@pytest.mark.parametrize(
    "body",
    [
        "",
        "\n",
        "\x00\x00\x00",
        '"icao24"\n"abc123"',
        f"{HEADER}\n" + '"abc123"',
        f"{HEADER}\n" + ",".join(['"x"'] * 200),
        f'{HEADER}\n"abc123","N1","M","Maker","Model","T","S","L","L1P","Op","","","","Own"',
        "﻿" + HEADER + "\n",
    ],
)
def test_structurally_broken_files_yield_a_verdict_rather_than_an_exception(
    tmp_path: Path, body: str
) -> None:
    """Short rows, long rows, empty files, a BOM — all are verdicts, not crashes."""
    artifact = _write(tmp_path / "db.csv", body)

    report = OpenSkyProvider().validate(artifact)

    assert isinstance(report.ok, bool)
    if report.ok:
        assert all(record.icao24.strip() for record in OpenSkyProvider().transform(artifact))
