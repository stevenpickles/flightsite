"""The Virtual Radar Server standing-data adapter (SPEC §28 as amended, slice 071).

**This module is the only place in FlightSite that knows what the VRS
standing-data repository publishes or how it spells it.** Everything it
produces crosses the ADR-0006 boundary as
:class:`~flightsite.enrichment.directory.RouteDirectoryRecord`.

Choice of artifact
------------------

The dataset is the CSV corpus behind Virtual Radar Server's flight-route
lookups, built from corrections its users submit to the SDM site and published
at ``github.com/vradarserver/standing-data`` under **CC0 1.0** (a full
``LICENSE`` file in the repository root). Three ways to get the routes were
measured from a developer machine on 2026-09-05:

======================================== ============== =========================
Candidate                                Measured       Verdict
======================================== ============== =========================
``…/archive/refs/heads/main.zip``        **7,063,160 B  **Chosen.** One request,
(the repository archive)                 in 1.3 s**     1.3 s, CC0 in the box.
``…/Files/StandingData.sqb.gz``          15,558,890 B   Rejected: 2.2x the size
(VRS's compiled SQLite database)         (``HTTP 200``, and *no data licence*.
                                         ``x-gzip``)
Per-file fetches over the GitHub API     1,576 requests Rejected on arithmetic.
======================================== ============== =========================

The archive wins on all three axes.

* **Size.** 6.7 MiB for the whole repository, of which ``routes/schema-01/**``
  is 4,644,217 B compressed and 19,056,582 B uncompressed across 1,576 CSV
  files. Extracting only the routes is not merely practical, it is what a zip
  central directory is *for*: this module reads the member index, filters it by
  path, and never inflates the aircraft, airline or airport trees at all.
  Downloading a megabyte or two of unwanted members once per update is a
  better trade than 1,576 conditional requests.
* **Licence.** The GitHub repository carries CC0 1.0 Universal, verbatim. The
  compiled ``StandingData.sqb.gz`` on ``virtualradarserver.co.uk`` is still
  served (``HTTP 200``, ``Content-Length: 15558890``,
  ``Content-Type: application/x-gzip``), but the site's only licence page
  covers *the application source* under a BSD-3-Clause grant "for the
  application", the Data and Credits pages state no terms over the database,
  and no CC0 statement appears anywhere on the site. An unstated licence is
  not the same licence, so the artifact that ships its own is the one to take
  — ``docs/LICENSES.md`` carries the whole trail.
* **Format.** ``schema-01`` is documented, plain, and versioned in its own path
  segment, so upstream can introduce ``schema-02`` beside it without silently
  changing what this module reads. The ``.sqb`` is an internal database schema
  with no such contract.

The repository README names no other published artifact; it points corrections
at the SDM site and nothing else.

CSV format
----------

``routes/schema-01/<A-Y>/<code>-all.csv``, or ``<code>-1.csv``,
``<code>-2.csv`` … where one airline's routes are split across files (65 of the
1,576 files in the measured snapshot; Air France alone takes six). Both spellings
are read the same way — the file *name* carries no information this module
needs, only the path prefix does — so nothing here has to know which airlines
upstream chose to split.

Five columns, one header row, and every row in the measured snapshot parsed
cleanly:

===================== ======================================================
Column                Meaning
===================== ======================================================
``Callsign``          The ICAO flight identification (``BAW1``, ``AAL1011``).
                      4-7 characters, ``[A-Z0-9]``, and unique across the
                      whole corpus — 619,828 rows, 619,828 distinct
                      callsigns. This is the key everything joins on.
``Code``              The airline's designator, repeated from the callsign.
``Number``            The flight number, repeated from the callsign.
``AirlineCode``       The operating airline's ICAO designator. Read; kept as
                      a diagnostic label only.
``AirportCodes``      The route, ICAO idents separated by ``-``. Two codes in
                      585,303 rows, three in 30,499, and a long tail out to
                      twelve. **This is the whole payload.**
===================== ======================================================

``Code`` and ``Number`` are deliberately not read: both are derivable from
``Callsign``, which is already the primary key, and storing a second copy of a
key is how two spellings of one flight come to exist.

Columns are located **by header name**, not by position, for
:mod:`flightsite.airports.ourairports`' reason: a positional reader starts
silently reading the wrong field the first time upstream inserts a column.

License and attribution
-----------------------

**CC0 1.0 Universal** — a dedication to the public domain, with no attribution
requirement at all. FlightSite still credits it, because the data is
volunteered and a credit costs nothing. As with every other dataset in
``docs/LICENSES.md``, the artifact is **fetched on demand, never bundled**:
this provider downloads into the running deployment's own working directory
when a user runs "Update Aircraft Metadata", and FlightSite redistributes
nothing in its source, its releases or its container images.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Final

import httpx

from flightsite.enrichment.directory import (
    RouteDirectoryRecord,
    RouteRecordError,
    normalize_route,
)
from flightsite.metadata.records import MetadataError, SourceArtifact, ValidationReport

#: The artifact this provider downloads — see the module docstring's "Choice of
#: artifact" for the measurements behind it.
DEFAULT_ARTIFACT_URL: Final = (
    "https://github.com/vradarserver/standing-data/archive/refs/heads/main.zip"
)

#: Filename the downloaded bytes are written under in the run's working
#: directory.
ARTIFACT_FILENAME: Final = "standing-data.zip"

#: Request timeout for the download. Generous relative to the decoder-polling
#: timeout elsewhere: this is a ~7 MB archive fetched once per update action,
#: not a per-second poll.
DEFAULT_TIMEOUT_S: Final = 60.0

#: Hard ceiling on the downloaded artifact. The real archive is 6.7 MiB; this
#: is an order of magnitude of headroom against upstream growth while still
#: bounding memory on a homelab Pi against a misbehaving endpoint.
MAX_ARTIFACT_BYTES: Final = 128 * 1024 * 1024

#: Floor on the downloaded size, standing in for a row-count floor without
#: opening the archive. ``validate`` runs synchronously on the event loop, so
#: it must stay cheap; a captive-portal page, an HTTP error body or a transfer
#: that died partway all land far below this.
MIN_ARTIFACT_BYTES: Final = 1_000_000

#: Fewest route files a genuine snapshot carries. The measured one has 1,576;
#: this is well under half of that, so it catches a repository that reorganized
#: without failing an import the week an airline is removed.
MIN_ROUTE_FILES: Final = 400

#: Fewest importable routes a genuine snapshot yields, checked by the pipeline
#: against what the transform actually produced
#: (:attr:`~flightsite.metadata.records.ValidationReport.expected_rows`). The
#: real figure is 619,770; this floor is deliberately less than half of it.
MIN_EXPECTED_ROWS: Final = 250_000

#: Where the routes live inside the archive. Anchored on the ``routes`` segment
#: rather than on the archive's top-level directory, whose name carries the
#: branch (``standing-data-main/``) and is upstream's to change.
ROUTE_MEMBER_PATTERN: Final = re.compile(r"(?:^|/)routes/schema-01/[A-Z0-9]/[^/]+\.csv$")

#: Header names this module reads. A missing one means upstream renamed or
#: dropped a column, which is a rejection rather than an import of nulls.
REQUIRED_COLUMNS: Final[tuple[str, ...]] = ("Callsign", "AirlineCode", "AirportCodes")

#: Files sampled during validation, and rows read from each. Bounded so the
#: cost of ``validate`` never scales with the archive.
VALIDATE_SAMPLE_FILES: Final = 8
VALIDATE_SAMPLE_ROWS: Final = 250

#: Fraction of sampled rows that must yield a usable record. Real snapshots are
#: 100 %; this leaves slack for an upstream oddity without masking a file this
#: module has stopped understanding.
MIN_SAMPLE_PASS_RATIO: Final = 0.99

ClientFactory = Callable[[], httpx.AsyncClient]


class StandingDataDownloadError(MetadataError):
    """The download stream misbehaved (oversized, or the transport failed)."""


def build_client(timeout_s: float = DEFAULT_TIMEOUT_S) -> httpx.AsyncClient:
    """Build the default HTTP client for downloading the artifact."""
    return httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)


def route_members(archive: zipfile.ZipFile) -> list[str]:
    """Every ``routes/schema-01`` CSV member, in a stable order.

    Read from the zip's central directory, so this costs one seek rather than
    a decompression of anything. Sorted so two imports of the same archive
    stage rows in the same order, which is what lets a test assert on a
    duplicate callsign resolving to the same row twice.
    """
    return sorted(
        info.filename
        for info in archive.infolist()
        if not info.is_dir() and ROUTE_MEMBER_PATTERN.search(info.filename)
    )


def _rows(archive: zipfile.ZipFile, member: str) -> Iterator[dict[str, str | None]]:
    """One member's rows, header-keyed.

    ``utf-8-sig`` because upstream writes a BOM on some files, and a BOM left
    on the first header name would make ``Callsign`` unfindable in exactly the
    files that carry one. Members are a few kilobytes each, so each is read
    whole rather than streamed.
    """
    text = archive.read(member).decode("utf-8-sig")
    yield from csv.DictReader(io.StringIO(text))


def _to_record(row: Mapping[str, str | None]) -> RouteDirectoryRecord | None:
    """One CSV row as a normalized record, ``None`` if it is not imported.

    Two different failures, deliberately reported differently — the same
    distinction :mod:`flightsite.airports.ourairports` draws between an
    excluded airport type and an unparseable one:

    * ``None`` means **deliberately skipped**: the callsign is not in the ICAO
      flight-identification form, so no lookup could ever ask for it. 58 of the
      measured snapshot's 619,828 rows are these, and counting them as rejected
      would make a perfectly healthy snapshot look like it was failing its own
      tolerance.
    * A record with an empty callsign is a row that *should* have imported and
      could not — a missing or malformed path — and is yielded so the
      pipeline's own boundary rejects and *counts* it, exactly as it counts a
      bad row from any other source.
    """
    callsign = (row.get("Callsign") or "").strip()
    try:
        return normalize_route(
            callsign=callsign,
            airport_codes=row.get("AirportCodes"),
            airline_code=row.get("AirlineCode"),
        )
    except RouteRecordError:
        if _looks_like_a_flight(callsign):
            return RouteDirectoryRecord(callsign="", airport_codes="")
        return None


def _looks_like_a_flight(callsign: str) -> bool:
    """Whether a row was *meant* to be importable, for reject accounting.

    Deliberately looser than the eligibility rule
    :func:`~flightsite.enrichment.directory.normalize_route` applies: this only
    asks "is the callsign the shape of an airline flight?", so that a row this
    build skips on purpose is not counted against the reject tolerance while a
    row with a good callsign and a broken path still is.
    """
    return len(callsign) >= 4 and callsign[:3].isalpha() and callsign[3:].isalnum()


async def _fetch(client: httpx.AsyncClient, url: str) -> bytes:
    """GET ``url``, streamed and capped at :data:`MAX_ARTIFACT_BYTES`."""
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise StandingDataDownloadError(
                    f"standing data archive exceeds {MAX_ARTIFACT_BYTES} bytes"
                )
            chunks.append(chunk)
    return b"".join(chunks)


class VrsRoutesProvider:
    """:class:`~flightsite.metadata.provider.DatasetProvider` over the VRS
    standing-data route CSVs.

    Registered as the source ``routes`` with
    :class:`~flightsite.enrichment.directory.RouteDirectoryImportSink`, so
    slice 025's "Update Aircraft Metadata" action imports and reports it beside
    the aircraft sources and the airport dataset, and a failure in one leaves
    the others untouched (SPEC §27). It is excluded from the airframe
    precedence model for the reason
    :meth:`flightsite.metadata.registry.SourceRegistry.precedence` gives: it
    carries a sink of its own and writes no ``aircraft_metadata`` row, so it
    has no claim about an airframe to rank.

    Args:
        artifact_url: overrides :data:`DEFAULT_ARTIFACT_URL`, for tests.
        client_factory: builds the HTTP client used by :meth:`download`;
            replaced in tests with one wired to a mock transport. The same seam
            :mod:`flightsite.metadata.sources.mictronics` and
            :mod:`flightsite.airports.ourairports` carry.
    """

    __slots__ = ("_artifact_url", "_client_factory")

    def __init__(
        self,
        *,
        artifact_url: str = DEFAULT_ARTIFACT_URL,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._artifact_url = artifact_url
        self._client_factory = client_factory if client_factory is not None else build_client

    async def download(self, workdir: Path) -> SourceArtifact:
        """Fetch the archive into ``workdir``.

        ``version`` and ``content_hash`` are both a SHA-256 of the downloaded
        bytes, the choice :class:`~flightsite.airports.ourairports.
        OurAirportsProvider` makes and for the same reason: upstream publishes
        no release tag reachable from the artifact alone — the repository is a
        moving branch — so the content hash is what ties a set of rows back to
        the bytes that produced them, and it doubles as the version so a day
        when nothing changed re-imports as a visible no-op in
        ``metadata_sources.dataset_version``.
        """
        client = self._client_factory()
        try:
            raw = await _fetch(client, self._artifact_url)
        finally:
            await client.aclose()

        path = workdir / ARTIFACT_FILENAME
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        return SourceArtifact(
            path=path,
            version=f"sha256:{digest[:16]}",
            content_hash=f"sha256:{digest}",
            size_bytes=len(raw),
        )

    def validate(self, artifact: SourceArtifact) -> ValidationReport:
        """Judge the archive without inflating all of it.

        Five checks, cheapest first: a size floor standing in for a row count,
        the bytes being a readable zip at all, the member index carrying enough
        ``routes/schema-01`` files, a bounded sample of those files having the
        header this module reads and rows it can normalize, and — carried
        forward as ``expected_rows`` for the pipeline to enforce after the
        transform — a floor on how many routes a real snapshot yields. The last
        is what catches an archive that opened and parsed cleanly but held one
        airline.
        """
        if artifact.size_bytes < MIN_ARTIFACT_BYTES:
            return ValidationReport.rejected(
                f"downloaded artifact is only {artifact.size_bytes} bytes, below the "
                f"{MIN_ARTIFACT_BYTES}-byte floor for a genuine snapshot"
            )
        try:
            with zipfile.ZipFile(artifact.path) as archive:
                members = route_members(archive)
                if len(members) < MIN_ROUTE_FILES:
                    return ValidationReport.rejected(
                        f"downloaded archive holds {len(members)} route files, below the "
                        f"{MIN_ROUTE_FILES} a genuine snapshot carries"
                    )
                return self._sample(archive, members)
        except zipfile.BadZipFile as exc:
            return ValidationReport.rejected(f"downloaded artifact is not a zip archive: {exc}")
        except OSError as exc:
            return ValidationReport.rejected(f"could not read downloaded artifact: {exc}")

    def _sample(self, archive: zipfile.ZipFile, members: list[str]) -> ValidationReport:
        """Read the front of a few members and judge what comes back."""
        sampled = 0
        usable = 0
        for member in members[:VALIDATE_SAMPLE_FILES]:
            try:
                reader = _rows(archive, member)
                header_checked = False
                for row in reader:
                    if not header_checked:
                        missing = [name for name in REQUIRED_COLUMNS if name not in row]
                        if missing:
                            return ValidationReport.rejected(
                                f"{member} is missing required column(s): {', '.join(missing)}"
                            )
                        header_checked = True
                    sampled += 1
                    record = _to_record(row)
                    if record is not None and record.callsign:
                        usable += 1
                    if sampled >= VALIDATE_SAMPLE_ROWS * VALIDATE_SAMPLE_FILES:
                        break
            except (UnicodeDecodeError, csv.Error) as exc:
                return ValidationReport.rejected(f"{member} is not valid CSV: {exc}")

        if sampled == 0:
            return ValidationReport.rejected("downloaded archive contains no route rows")
        ratio = usable / sampled
        if ratio < MIN_SAMPLE_PASS_RATIO:
            return ValidationReport.rejected(
                f"only {ratio:.0%} of sampled route rows carry a usable callsign and path"
            )
        return ValidationReport.accepted(expected_rows=MIN_EXPECTED_ROWS)

    def transform(self, artifact: SourceArtifact) -> Iterator[RouteDirectoryRecord]:
        """Stream every route in the archive as a normalized record.

        Members are inflated one at a time and dropped, so peak memory is one
        CSV file — a few tens of kilobytes — rather than the 19 MB the route
        tree occupies uncompressed, let alone the 138 MB the parsed corpus
        occupies as Python objects.
        """
        with zipfile.ZipFile(artifact.path) as archive:
            for member in route_members(archive):
                for row in _rows(archive, member):
                    record = _to_record(row)
                    if record is not None:
                        yield record


__all__ = [
    "ARTIFACT_FILENAME",
    "DEFAULT_ARTIFACT_URL",
    "DEFAULT_TIMEOUT_S",
    "MAX_ARTIFACT_BYTES",
    "MIN_ARTIFACT_BYTES",
    "MIN_EXPECTED_ROWS",
    "MIN_ROUTE_FILES",
    "MIN_SAMPLE_PASS_RATIO",
    "REQUIRED_COLUMNS",
    "ROUTE_MEMBER_PATTERN",
    "VALIDATE_SAMPLE_FILES",
    "VALIDATE_SAMPLE_ROWS",
    "ClientFactory",
    "StandingDataDownloadError",
    "VrsRoutesProvider",
    "build_client",
    "route_members",
]
