"""The OurAirports dataset adapter (SPEC §41, roadmap slice 027).

**This module is the only place in FlightSite that knows OurAirports' column
names or its conventions.** Everything it produces crosses the ADR-0006
boundary as :class:`~flightsite.airports.records.AirportRecord`.

Choice of artifact
------------------

OurAirports publishes its database as CSV in two places: the project site's own
download page, and a GitHub Pages mirror
(``davidmegginson.github.io/ourairports-data/``) that the project's README
names as the canonical machine-readable endpoint and that regenerates daily
from the same database. This module downloads ``airports.csv`` from the mirror:
one HTTP request, one file, a stable URL with no session or scraping, and the
same artifact any other consumer of this dataset fetches. The URL is
:data:`DEFAULT_ARTIFACT_URL`; :class:`OurAirportsProvider` accepts an override
for tests.

The file is plain CSV rather than compressed — about 13 MB at the time of
writing, roughly 86 000 rows — so unlike the aircraft snapshot it is stored
uncompressed in the run's working directory and read twice: once for
validation's bounded sample, once streamed for the transform.

CSV format
----------

A single header row, then RFC 4180 rows with quoted text fields. Nineteen
columns; this module reads eight of them and ignores the rest:

===================== ======================================================
Column                Meaning
===================== ======================================================
``id``                OurAirports' own row id. Stable across releases, kept
                      as the surrogate primary key.
``ident``             ICAO code where one exists, local/GPS code otherwise
                      (``KSEA``, ``EGLL``, ``00AK``). The key everything
                      joins on, and ``UNIQUE`` in FlightSite's table.
``type``              Size class — see
                      :data:`~flightsite.airports.records.IMPORTED_AIRPORT_TYPES`
                      for which values are imported and why.
``name``              Field name as displayed.
``latitude_deg``      Decimal degrees, WGS-84.
``longitude_deg``     Decimal degrees, WGS-84.
``elevation_ft``      Field elevation. Empty for ~16% of rows.
``iso_country``       ISO 3166-1 alpha-2. Empty for a handful.
``iata_code``         Three-letter IATA code. Present on ~1 row in 8.
===================== ======================================================

The eleven unread columns (``continent``, ``iso_region``, ``municipality``,
``scheduled_service``, ``icao_code``, ``gps_code``, ``local_code``,
``home_link``, ``wikipedia_link``, ``keywords``) carry nothing
nearest-airport context needs, and ``docs/DATA_MODEL.md`` §3.6 stores none of
them. ``icao_code`` in particular is *not* preferred over ``ident``: it is
populated only where an official ICAO code exists, while ``ident`` is populated
for every row, and a key that is sometimes empty is not a key.

Columns are located **by header name**, not by position. Upstream has added
columns before (``icao_code`` postdates the original schema) and a positional
reader would silently start reading the wrong field the next time it does.

License and attribution
-----------------------

OurAirports places its data in the **public domain** — the project's own data
page states the database is public domain and asks only for a courtesy credit,
with no attribution *requirement*. That is the most permissive footing of any
dataset FlightSite touches, and it is why this one could in principle be
bundled. It still is not: the file changes daily, a bundled copy would be stale
the week it shipped, and fetch-on-demand keeps the posture uniform with every
other dataset in ``docs/LICENSES.md``. This provider downloads into the running
deployment's own working directory when a user runs "Update Aircraft Metadata",
and FlightSite redistributes nothing.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Final

import httpx

from flightsite.airports.records import (
    IMPORTED_AIRPORT_TYPES,
    AirportRecord,
    AirportRecordError,
    normalize_airport,
)
from flightsite.metadata.records import MetadataError, SourceArtifact, ValidationReport

#: The artifact this provider downloads — see the module docstring's "Choice of
#: artifact" for why this endpoint rather than the project's download page.
DEFAULT_ARTIFACT_URL: Final = "https://davidmegginson.github.io/ourairports-data/airports.csv"

#: Filename the downloaded bytes are written under in the run's working
#: directory.
ARTIFACT_FILENAME: Final = "airports.csv"

#: Request timeout for the download. Generous relative to the decoder-polling
#: timeout elsewhere: this is a ~13 MB file fetched once per update action, not
#: a per-second poll.
DEFAULT_TIMEOUT_S: Final = 30.0

#: Hard ceiling on the downloaded artifact. A real snapshot is ~13 MB; this is
#: generous headroom against upstream growth while still bounding memory on a
#: homelab Pi against a misbehaving or compromised endpoint.
MAX_ARTIFACT_BYTES: Final = 100 * 1024 * 1024

#: Floor on the downloaded size, standing in for a row-count floor without
#: parsing the file. ``validate`` runs synchronously on the event loop (never
#: off-threaded, unlike ``transform``), so it must stay cheap; a captive-portal
#: page, an HTTP error body or a transfer that died partway all land far below
#: this.
MIN_ARTIFACT_BYTES: Final = 2_000_000

#: Fewest importable airports a genuine snapshot yields, checked by the
#: pipeline against what the transform actually produced
#: (:attr:`~flightsite.metadata.records.ValidationReport.expected_rows`). The
#: real figure is ~71 000; this floor is deliberately less than half of it, so
#: it catches a truncated file or a filter that stopped matching without
#: failing an import the week upstream reorganizes a category.
MIN_EXPECTED_ROWS: Final = 30_000

#: Rows read from the front of the file to sanity-check structure. Bounded so
#: the cost of ``validate`` never scales with file size.
VALIDATE_SAMPLE_ROWS: Final = 2_000

#: Fraction of sampled rows that must carry a usable ident and a parseable
#: coordinate pair. Real snapshots are effectively 100%; this leaves slack for
#: upstream oddities without masking a genuinely wrong file format.
MIN_SAMPLE_PASS_RATIO: Final = 0.99

#: Header names this module reads. A missing one means upstream renamed or
#: dropped a column, which is a rejection rather than an import of nulls — the
#: failure the whole validate stage exists to catch.
REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "ident",
    "type",
    "name",
    "latitude_deg",
    "longitude_deg",
)

#: Header names read when present and tolerated when absent. Each maps to a
#: record field that is legitimately ``None``, so losing one upstream degrades
#: the dataset rather than invalidating it.
OPTIONAL_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "iata_code",
    "elevation_ft",
    "iso_country",
)

ClientFactory = Callable[[], httpx.AsyncClient]


class OurAirportsDownloadError(MetadataError):
    """The download stream misbehaved (oversized, or the transport failed)."""


def build_client(timeout_s: float = DEFAULT_TIMEOUT_S) -> httpx.AsyncClient:
    """Build the default HTTP client for downloading the artifact."""
    return httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)


def _to_record(row: Mapping[str, str | None]) -> AirportRecord | None:
    """One CSV row to a normalized record, or ``None`` if it is not imported.

    ``None`` means *deliberately skipped* — a type outside
    :data:`~flightsite.airports.records.IMPORTED_AIRPORT_TYPES`, which is about
    a fifth of the file. Those are not malformed and counting them as rejected
    would make a perfectly healthy snapshot look like it was failing its own
    reject-ratio tolerance.

    A row of the right type that cannot be normalized is a different thing, and
    is yielded with an unusable ident so the pipeline's own boundary rejects
    and *counts* it, the same as any other bad row from any other source.
    """
    if (row.get("type") or "").strip() not in IMPORTED_AIRPORT_TYPES:
        return None
    try:
        return normalize_airport(
            ident=row.get("ident"),
            name=row.get("name"),
            type=row["type"] or "",
            lat=row.get("latitude_deg"),
            lon=row.get("longitude_deg"),
            iata=row.get("iata_code"),
            elevation_ft=row.get("elevation_ft"),
            iso_country=row.get("iso_country"),
            upstream_id=row.get("id"),
        )
    except AirportRecordError:
        return AirportRecord(ident="", name="", type="", lat=0.0, lon=0.0)


def _open_csv(path: Path) -> Iterator[dict[str, str | None]]:
    """Stream ``path`` as header-keyed CSV rows."""
    with path.open("rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def _header(path: Path) -> list[str]:
    """The file's header row, reading no further than it."""
    with path.open("rt", encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle), [])


def _sample_rows(path: Path, limit: int) -> list[dict[str, str | None]]:
    """The first ``limit`` rows of ``path``, reading no more of the file."""
    rows: list[dict[str, str | None]] = []
    for row in _open_csv(path):
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _plausible(row: Mapping[str, str | None]) -> bool:
    """Whether a sampled row looks like an airport, for validation only."""
    ident = (row.get("ident") or "").strip()
    if not ident:
        return False
    try:
        float(row.get("latitude_deg") or "")
        float(row.get("longitude_deg") or "")
    except ValueError:
        return False
    return True


async def _fetch(client: httpx.AsyncClient, url: str) -> bytes:
    """GET ``url``, streamed and capped at :data:`MAX_ARTIFACT_BYTES`."""
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise OurAirportsDownloadError(
                    f"airport dataset exceeds {MAX_ARTIFACT_BYTES} bytes"
                )
            chunks.append(chunk)
    return b"".join(chunks)


class OurAirportsProvider:
    """:class:`~flightsite.metadata.provider.DatasetProvider` over
    OurAirports' ``airports.csv``.

    Registered as the source ``airports`` with
    :class:`~flightsite.airports.sink.AirportImportSink`, so slice 025's
    "Update Aircraft Metadata" action imports and reports it beside the
    aircraft sources and a failure in one leaves the other untouched
    (SPEC §27).

    Args:
        artifact_url: overrides :data:`DEFAULT_ARTIFACT_URL`, for tests.
        client_factory: builds the HTTP client used by :meth:`download`;
            replaced in tests with one wired to a mock transport. Mirrors
            :mod:`flightsite.metadata.sources.mictronics`' seam of the same
            name.
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
        """Fetch the artifact into ``workdir``.

        ``version`` and ``content_hash`` are both a SHA-256 of the downloaded
        bytes. Upstream publishes no release tag reachable from the artifact
        alone — the mirror regenerates daily — so the content hash is what ties
        a set of rows back to the bytes that produced them, and it doubles as
        the version so a day when nothing changed re-imports as a visible no-op
        in ``metadata_sources.dataset_version``.
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
        """Judge the downloaded artifact without reading all of it.

        Four checks, cheapest first: a size floor standing in for a row count,
        the header carrying every column this module reads, a bounded sample
        from the front of the file being structurally sound, and — carried
        forward as ``expected_rows`` for the pipeline to enforce after the
        transform — a floor on how many importable airports a real snapshot
        yields. The last is what catches a file that downloaded and parsed
        cleanly but was truncated at three megabytes.
        """
        if artifact.size_bytes < MIN_ARTIFACT_BYTES:
            return ValidationReport.rejected(
                f"downloaded artifact is only {artifact.size_bytes} bytes, below the "
                f"{MIN_ARTIFACT_BYTES}-byte floor for a genuine snapshot"
            )
        try:
            header = _header(artifact.path)
            missing = [name for name in REQUIRED_COLUMNS if name not in header]
            if missing:
                return ValidationReport.rejected(
                    f"downloaded artifact is missing required column(s): {', '.join(missing)}"
                )
            sample = _sample_rows(artifact.path, VALIDATE_SAMPLE_ROWS)
        except OSError as exc:
            return ValidationReport.rejected(f"could not read downloaded artifact: {exc}")
        except (UnicodeDecodeError, csv.Error) as exc:
            return ValidationReport.rejected(f"downloaded artifact is not valid CSV: {exc}")

        if not sample:
            return ValidationReport.rejected("downloaded artifact contains no rows")

        plausible = sum(1 for row in sample if _plausible(row))
        ratio = plausible / len(sample)
        if ratio < MIN_SAMPLE_PASS_RATIO:
            return ValidationReport.rejected(
                f"only {ratio:.0%} of sampled rows have a usable ident and coordinates"
            )

        warnings = [
            f"upstream dropped the optional column {name!r}; "
            f"the field it fills will be empty for every airport"
            for name in OPTIONAL_COLUMNS
            if name not in header
        ]
        return ValidationReport.accepted(expected_rows=MIN_EXPECTED_ROWS, warnings=warnings)

    def transform(self, artifact: SourceArtifact) -> Iterator[AirportRecord]:
        """Stream the importable rows as normalized airport records.

        Rows of an excluded type are skipped silently rather than yielded and
        rejected — they are not malformed data, just not airports FlightSite
        reasons about. See
        :data:`~flightsite.airports.records.IMPORTED_AIRPORT_TYPES`.
        """
        for row in _open_csv(artifact.path):
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
    "MIN_SAMPLE_PASS_RATIO",
    "OPTIONAL_COLUMNS",
    "REQUIRED_COLUMNS",
    "VALIDATE_SAMPLE_ROWS",
    "ClientFactory",
    "OurAirportsDownloadError",
    "OurAirportsProvider",
    "build_client",
]
