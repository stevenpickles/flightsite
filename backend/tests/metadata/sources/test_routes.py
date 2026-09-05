"""The VRS standing-data adapter: the archive, the CSVs, and the validation gate.

No socket is opened anywhere in this module. Downloads run over an
``httpx.MockTransport``, so the provider's request building and its streaming
size cap are exercised for real (``docs/TEST_STRATEGY.md`` §"No external network
in tests").

Fixtures are built as real zip archives from :data:`COLUMNS` rather than written
out by hand, for ``test_ourairports.py``'s reason: columns are located *by name*,
so a test that removes one has to remove it from the header and the rows
together or it tests a broken fixture instead of testing the reader. The member
paths mirror upstream's — ``standing-data-main/routes/schema-01/<letter>/`` —
including the branch-named top-level directory the provider must not depend on.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import httpx
import pytest

from flightsite.enrichment.directory import RouteDirectoryRecord
from flightsite.metadata.records import SourceArtifact
from flightsite.metadata.sources.routes import (
    ARTIFACT_FILENAME,
    MAX_ARTIFACT_BYTES,
    MIN_ARTIFACT_BYTES,
    MIN_EXPECTED_ROWS,
    MIN_ROUTE_FILES,
    REQUIRED_COLUMNS,
    StandingDataDownloadError,
    VrsRoutesProvider,
    route_members,
)

#: Upstream's five columns, in upstream's order.
COLUMNS: tuple[str, ...] = ("Callsign", "Code", "Number", "AirlineCode", "AirportCodes")

#: The archive's top-level directory. Named for the branch upstream publishes,
#: which is exactly why the provider anchors on the ``routes`` segment instead.
ROOT = "standing-data-main"


def row(callsign: str, airline: str, path: str) -> dict[str, str]:
    """One CSV row, with ``Code``/``Number`` split out of the callsign."""
    return {
        "Callsign": callsign,
        "Code": callsign[:3],
        "Number": callsign[3:],
        "AirlineCode": airline,
        "AirportCodes": path,
    }


#: One file per shape that matters: a plain airline, an airline whose routes
#: upstream split across numbered files, a multi-leg route, a row with a
#: callsign no lookup could ever ask for, and a row with a broken path.
#: Deliberately eight ordinary rows rather than two. The pipeline's
#: reject-ratio tolerance is 10 %, so a fixture carrying one broken row has to
#: carry at least nine good ones for the import tests next door to exercise a
#: *healthy* import that still counts a rejection.
BAW_ROWS: tuple[dict[str, str], ...] = (
    row("BAW1", "BAW", "EGLL-KJFK"),
    row("BAW10", "BAW", "VTBS-EGLL"),
    row("BAW101", "BAW", "EGPF-EGLL"),
    row("BAW1011", "BAW", "EGLL-WSSS"),
    row("BAW112", "BAW", "EGLL-KJFK"),
    row("BAW117", "BAW", "EGLL-VIDP"),
    row("BAW212", "BAW", "EGLL-KBOS"),
    row("BAW295", "BAW", "EGLL-KORD"),
)
AFR_1_ROWS: tuple[dict[str, str], ...] = (row("AFR11", "AFR", "LFPG-KJFK"),)
AFR_2_ROWS: tuple[dict[str, str], ...] = (row("AFR22", "AFR", "LFPG-OMDB"),)
AAE_ROWS: tuple[dict[str, str], ...] = (
    # Three legs: origin is the first code, destination the last, and the
    # middle stop is the thing the `path` extra exists to keep.
    row("AAE124", "AAE", "VHHH-UACC-EBLG"),
    # Not the ICAO flight-identification form: deliberately skipped, never
    # counted as a rejected row.
    row("N523GB", "", "KSEA-KPDX"),
    # The form, but the path is unusable: this one *is* a rejected row.
    row("AAE900", "AAE", ""),
)

#: Which callsigns a healthy import of the fixture yields.
IMPORTED_CALLSIGNS = frozenset(
    {entry["Callsign"] for entry in (*BAW_ROWS, *AFR_1_ROWS, *AFR_2_ROWS)} | {"AAE124"}
)


def csv_bytes(rows: Sequence[Mapping[str, str]], columns: Sequence[str] = COLUMNS) -> bytes:
    """``rows`` as an upstream-shaped CSV member."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for entry in rows:
        writer.writerow({name: entry.get(name, "") for name in columns})
    return buffer.getvalue().encode("utf-8")


def archive_bytes(members: Mapping[str, bytes] | None = None, *, padding: int = 0) -> bytes:
    """A zip archive holding ``members``, plus a padding member if asked.

    ``padding`` exists because two of the provider's gates are about *size*,
    and a fixture that met the real floors honestly would be a megabyte of
    generated filler in every test that does not care about them.
    """
    entries = dict(members if members is not None else default_members())
    if padding:
        entries[f"{ROOT}/aircraft/filler.csv"] = b"x" * padding
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def default_members() -> dict[str, bytes]:
    """The fixture archive: four route files and one non-route file."""
    return {
        f"{ROOT}/LICENSE": b"CC0 1.0 Universal",
        f"{ROOT}/routes/schema-01/B/BAW-all.csv": csv_bytes(BAW_ROWS),
        f"{ROOT}/routes/schema-01/A/AFR-1.csv": csv_bytes(AFR_1_ROWS),
        f"{ROOT}/routes/schema-01/A/AFR-2.csv": csv_bytes(AFR_2_ROWS),
        f"{ROOT}/routes/schema-01/A/AAE-all.csv": csv_bytes(AAE_ROWS),
        # Not a route file: a same-named CSV in the airports tree, which the
        # member filter must not pick up.
        f"{ROOT}/airports/schema-01/A/AAE-all.csv": csv_bytes(AAE_ROWS),
    }


def healthy_members() -> dict[str, bytes]:
    """A fixture with no odd rows at all, for the tests about the sample gate.

    :func:`default_members` deliberately carries a skipped row and a rejected
    one — two of seven — which is a proportion no real snapshot comes close to
    and which the sample ratio is right to refuse. These tests are about a file
    the reader *understands*, so they use one.
    """
    return {
        f"{ROOT}/routes/schema-01/B/BAW-all.csv": csv_bytes(BAW_ROWS),
        f"{ROOT}/routes/schema-01/A/AFR-1.csv": csv_bytes(AFR_1_ROWS),
        f"{ROOT}/routes/schema-01/A/AAE-all.csv": csv_bytes(AAE_ROWS[:1]),
    }


@pytest.fixture(autouse=True)
def _small_floors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scale the archive floors down to fixture size.

    They are floors on a *genuine* snapshot — a megabyte of zip, four hundred
    route files, a quarter-million routes. The tests below that are about the
    floors set them back explicitly; everywhere else they are scenery.
    """
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_ARTIFACT_BYTES", 1)
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_ROUTE_FILES", 1)
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_EXPECTED_ROWS", 1)


def provider_over(payload: bytes, *, status_code: int = 200) -> VrsRoutesProvider:
    """A provider whose client answers with ``payload`` and never opens a socket."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=payload)

    return VrsRoutesProvider(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def prepared(workdir: Path) -> Path:
    """``workdir``, created — what the import pipeline does before a download."""
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


async def artifact_for(payload: bytes, workdir: Path) -> tuple[VrsRoutesProvider, SourceArtifact]:
    """Download ``payload`` into ``workdir`` and hand back both halves."""
    provider = provider_over(payload)
    return provider, await provider.download(prepared(workdir))


def callsigns(records: Iterable[RouteDirectoryRecord]) -> list[str]:
    return [record.callsign for record in records]


# ---------------------------------------------------------------- the archive


async def test_the_download_lands_in_the_workdir_hashed(tmp_path: Path) -> None:
    """The artifact is written where the pipeline deletes it, and identified."""
    payload = archive_bytes()

    _provider, artifact = await artifact_for(payload, tmp_path)

    assert artifact.path == tmp_path / ARTIFACT_FILENAME
    assert artifact.path.read_bytes() == payload
    assert artifact.size_bytes == len(payload)
    assert artifact.version.startswith("sha256:")
    assert artifact.content_hash.startswith("sha256:")


async def test_the_version_is_the_content_hash_so_a_no_op_update_is_visible(
    tmp_path: Path,
) -> None:
    """Upstream publishes no tag; identical bytes must re-import identically."""
    first = await artifact_for(archive_bytes(), tmp_path / "a")
    second = await artifact_for(archive_bytes(), tmp_path / "b")

    assert first[1].version == second[1].version


async def test_a_changed_archive_changes_the_version(tmp_path: Path) -> None:
    members = default_members()
    members[f"{ROOT}/routes/schema-01/B/BAW-all.csv"] = csv_bytes(
        (*BAW_ROWS, row("BAW99", "BAW", "EGLL-LEMD"))
    )

    unchanged = await artifact_for(archive_bytes(), tmp_path / "a")
    changed = await artifact_for(archive_bytes(members), tmp_path / "b")

    assert unchanged[1].version != changed[1].version


async def test_an_oversized_download_is_refused_rather_than_buffered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The streaming cap: a misbehaving endpoint cannot fill a Pi's memory."""
    monkeypatch.setattr("flightsite.metadata.sources.routes.MAX_ARTIFACT_BYTES", 64)
    provider = provider_over(archive_bytes(padding=4096))

    with pytest.raises(StandingDataDownloadError, match="exceeds"):
        await provider.download(tmp_path)


async def test_an_http_error_propagates_as_this_source_s_failure(tmp_path: Path) -> None:
    provider = provider_over(b"nope", status_code=503)

    with pytest.raises(httpx.HTTPStatusError):
        await provider.download(tmp_path)


def test_the_real_size_cap_is_generous_against_the_measured_archive() -> None:
    """6.7 MiB measured, an order of magnitude of headroom, still bounded."""
    assert MAX_ARTIFACT_BYTES > 10 * 7_063_160
    assert MIN_ARTIFACT_BYTES < 7_063_160


# ------------------------------------------------------------ member selection


def test_only_the_route_tree_is_read(tmp_path: Path) -> None:
    """The filter is on the path, not on the filename or the top directory."""
    path = tmp_path / "archive.zip"
    path.write_bytes(archive_bytes())

    with zipfile.ZipFile(path) as archive:
        members = route_members(archive)

    assert members == [
        f"{ROOT}/routes/schema-01/A/AAE-all.csv",
        f"{ROOT}/routes/schema-01/A/AFR-1.csv",
        f"{ROOT}/routes/schema-01/A/AFR-2.csv",
        f"{ROOT}/routes/schema-01/B/BAW-all.csv",
    ]


def test_a_renamed_top_level_directory_is_still_read(tmp_path: Path) -> None:
    """Upstream owns the branch name; the provider must not depend on it."""
    members = {
        "standing-data-v2/routes/schema-01/B/BAW-all.csv": csv_bytes(BAW_ROWS),
    }
    path = tmp_path / "archive.zip"
    path.write_bytes(archive_bytes(members))

    with zipfile.ZipFile(path) as archive:
        assert len(route_members(archive)) == 1


# ------------------------------------------------------------------ transform


async def test_the_transform_reads_every_route_file(tmp_path: Path) -> None:
    """Both spellings — ``<code>-all.csv`` and the split ``<code>-N.csv``."""
    provider, artifact = await artifact_for(archive_bytes(), tmp_path)

    records = list(provider.transform(artifact))

    assert set(callsigns(records)) - {""} == IMPORTED_CALLSIGNS
    assert {"AFR11", "AFR22"} <= IMPORTED_CALLSIGNS


async def test_a_multi_leg_route_keeps_its_whole_path(tmp_path: Path) -> None:
    """Origin is the first code, destination the last, stops kept in between."""
    provider, artifact = await artifact_for(archive_bytes(), tmp_path)

    found = {record.callsign: record for record in provider.transform(artifact)}
    leg = found["AAE124"]

    assert leg.airport_codes == "VHHH-UACC-EBLG"
    assert leg.path == ("VHHH", "UACC", "EBLG")
    assert (leg.origin_ident, leg.destination_ident) == ("VHHH", "EBLG")


async def test_an_ineligible_callsign_is_skipped_rather_than_rejected(
    tmp_path: Path,
) -> None:
    """A registration flown as a callsign is not a broken row; it is not a
    flight number, so nothing could ever look it up."""
    provider, artifact = await artifact_for(archive_bytes(), tmp_path)

    assert "N523GB" not in callsigns(provider.transform(artifact))


async def test_a_malformed_row_is_yielded_unusable_so_the_pipeline_counts_it(
    tmp_path: Path,
) -> None:
    """A good callsign with no path *is* a rejected row, and must look like one."""
    provider, artifact = await artifact_for(archive_bytes(), tmp_path)

    unusable = [record for record in provider.transform(artifact) if not record.callsign]

    assert len(unusable) == 1


async def test_a_byte_order_mark_does_not_hide_the_header(tmp_path: Path) -> None:
    """Upstream writes a BOM on some files; ``Callsign`` must still be found."""
    members = {
        f"{ROOT}/routes/schema-01/B/BAW-all.csv": b"\xef\xbb\xbf" + csv_bytes(BAW_ROWS),
    }
    provider, artifact = await artifact_for(archive_bytes(members), tmp_path)

    assert set(callsigns(provider.transform(artifact))) == {entry["Callsign"] for entry in BAW_ROWS}


# ------------------------------------------------------------------- validate


async def test_a_healthy_archive_validates_and_carries_a_row_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_EXPECTED_ROWS", 3)
    provider, artifact = await artifact_for(archive_bytes(healthy_members()), tmp_path)

    report = provider.validate(artifact)

    assert report.ok
    assert report.expected_rows == 3


async def test_the_sample_gate_refuses_a_file_it_mostly_cannot_read(
    tmp_path: Path,
) -> None:
    """Two odd rows in seven is not a snapshot this build understands.

    The fixture's proportions are deliberately nothing like upstream's — 58
    skipped rows in 619,828 — so a ratio this low is exactly the signal the
    gate exists to catch.
    """
    provider, artifact = await artifact_for(archive_bytes(), tmp_path)

    report = provider.validate(artifact)

    assert not report.ok
    assert "usable callsign" in report.reason()


async def test_a_short_download_is_rejected_on_size_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A captive-portal page or a transfer that died partway."""
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_ARTIFACT_BYTES", 10_000_000)
    provider, artifact = await artifact_for(archive_bytes(healthy_members()), tmp_path)

    report = provider.validate(artifact)

    assert not report.ok
    assert "floor" in report.reason()


async def test_a_response_that_is_not_a_zip_is_rejected(tmp_path: Path) -> None:
    provider, artifact = await artifact_for(b"<html>login required</html>" * 10, tmp_path)

    report = provider.validate(artifact)

    assert not report.ok
    assert "not a zip archive" in report.reason()


async def test_an_archive_with_too_few_route_files_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reorganized repository must not silently import as one airline."""
    monkeypatch.setattr("flightsite.metadata.sources.routes.MIN_ROUTE_FILES", 10)
    provider, artifact = await artifact_for(archive_bytes(healthy_members()), tmp_path)

    report = provider.validate(artifact)

    assert not report.ok
    assert "route files" in report.reason()


async def test_a_renamed_column_is_rejected_rather_than_imported_as_nulls(
    tmp_path: Path,
) -> None:
    renamed = tuple(name if name != "AirportCodes" else "Airports" for name in COLUMNS)
    members = {
        f"{ROOT}/routes/schema-01/B/BAW-all.csv": csv_bytes(
            [{**entry, "Airports": entry["AirportCodes"]} for entry in BAW_ROWS],
            columns=renamed,
        )
    }
    provider, artifact = await artifact_for(archive_bytes(members), tmp_path)

    report = provider.validate(artifact)

    assert not report.ok
    assert "AirportCodes" in report.reason()


async def test_rows_that_do_not_parse_at_all_are_rejected(tmp_path: Path) -> None:
    """The sample-ratio gate: a file with this header and nothing usable in it."""
    members = {
        f"{ROOT}/routes/schema-01/B/BAW-all.csv": csv_bytes(
            [row("BAW1", "BAW", ""), row("BAW10", "BAW", "")]
        )
    }
    provider, artifact = await artifact_for(archive_bytes(members), tmp_path)

    report = provider.validate(artifact)

    assert not report.ok
    assert "usable callsign" in report.reason()


async def test_an_archive_with_no_route_rows_is_rejected(tmp_path: Path) -> None:
    members = {f"{ROOT}/routes/schema-01/B/BAW-all.csv": csv_bytes(())}
    provider, artifact = await artifact_for(archive_bytes(members), tmp_path)

    report = provider.validate(artifact)

    assert not report.ok
    assert "no route rows" in report.reason()


def test_the_required_columns_are_the_ones_the_reader_uses() -> None:
    """``Code`` and ``Number`` are derivable from ``Callsign`` and not required."""
    assert set(REQUIRED_COLUMNS) == {"Callsign", "AirlineCode", "AirportCodes"}
    assert set(REQUIRED_COLUMNS) <= set(COLUMNS)


def test_the_real_row_floor_is_under_half_the_measured_snapshot() -> None:
    """619,770 importable rows measured; the floor catches truncation, not churn."""
    assert MIN_EXPECTED_ROWS < 619_770 / 2
    assert MIN_ROUTE_FILES < 1_576 / 2
