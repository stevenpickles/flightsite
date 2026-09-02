"""The OpenSky Network aircraft database adapter (ADR-0013, roadmap slice 059).

**This module is the only place in FlightSite that knows this upstream's column
names, its date formats, or its placeholder conventions.** Everything it
produces crosses the ADR-0006 boundary as
:class:`~flightsite.metadata.records.NormalizedAircraftRecord`.

Opt-in, and off by default
--------------------------

Unlike :mod:`~flightsite.metadata.sources.mictronics` and
:mod:`~flightsite.metadata.sources.faa`, this source does not participate in
"Update Aircraft Metadata" unless the user turns it on
(``metadata.opensky_enabled``, default ``false``). The gate lives at *provider
construction* in :func:`flightsite.app._build_metadata_registry`, not inside
this module: when the setting is off no :class:`OpenSkyProvider` is built and
nothing is registered, so the source cannot be reached, reported, or fetched.
"Off" means absent rather than skipped.

That is a licensing decision, not a technical one, and ADR-0013 records it in
full. The short version: OpenSky's General Terms of Use license their data
"solely for the purpose of non-profit research and non-profit education" and
require a written license for any for-profit or commercial use, while the
aircraft database's own page (``https://opensky-network.org/data/aircraft``)
states under "Citation and Use" that "[t]he aircraft database is unlicensed and
does not fall under our terms of use. We do not provide support or guarantees of
any kind — it is offered 'as is'." Those two statements disagree, and
"unlicensed" is the absence of a grant rather than a grant. FlightSite therefore
treats this the way ``docs/LICENSES.md`` already treats the ambiguous Mictronics
row — **fetch-on-demand only, never bundled or redistributed** — and adds
default-off on top, so contacting OpenSky at all is a deliberate act by the
operator rather than something a stock install does on their behalf.

CSV format
----------

One HTTP request for ``aircraftDatabase.csv``: a single comma-delimited,
fully-quoted CSV **with** a header row, served as ``text/csv`` from
``opensky-network.org`` behind a 302 to the project's S3 bucket (hence
``follow_redirects``). Roughly 94 MB, uncompressed — see "Download shape" below.

The header, verified against the live artifact while writing this module, is 27
columns::

    icao24,registration,manufacturericao,manufacturername,model,typecode,
    serialnumber,linenumber,icaoaircrafttype,operator,operatorcallsign,
    operatoricao,operatoriata,owner,testreg,registered,reguntil,status,built,
    firstflightdate,seatconfiguration,engines,modes,adsb,acars,notes,
    categoryDescription

Only the six in :data:`REQUIRED_COLUMNS` are read; the rest are ignored rather
than rejected, so an upstream that adds a column does not break the import.
Reading by *name* through :class:`csv.DictReader` rather than by position is
deliberate for the same reason — this file has 27 columns and a positional
parser would silently mis-map every field after any upstream insertion.

Two structural quirks a real snapshot contains:

* **Addressless rows.** The very first data row of a real snapshot carries no
  data at all — except that it is not literally empty: the three boolean
  columns hold ``"false"``, so a "every column is blank" test does *not* catch
  it. The property that actually distinguishes these rows is an empty
  ``icao24``, which is what both :func:`_to_record` and :func:`_sample_rows`
  test. They are not malformed data, so they are skipped silently rather than
  counted against the importer's reject-ratio tolerance.
* **Dates where a year belongs.** ``built`` is an ISO date (``"1998-01-01"``),
  not a bare year, so :func:`_year_from_built` takes the leading four digits
  before handing off to
  :func:`~flightsite.metadata.records.normalize_year`. Passing the raw value
  through would yield ``None`` for every row in the file.

What this source contributes, and what it deliberately does not
---------------------------------------------------------------

Four fields only: ``operator_name``, ``owner``, ``model`` and
``manufacture_year``. Those are precisely where this upstream adds something the
two higher-precedence sources lack — free-text operator and owner strings, and a
build year, for non-US airframes that Mictronics leaves blank and that the FAA
registry (US registrations only) never covers.

``registration`` and ``type_code`` are returned as ``None`` on every record,
even though this upstream supplies both. Type code is the field FlightSite
*groups* by — rarity, type statistics, the icon hierarchy — and a crowdsourced
designator disagreeing with Mictronics' ICAO Doc 8643 value would silently
fragment those counts. Withholding them here means the guarantee holds at the
record level and not only at the precedence level: even a future misconfiguration
of :data:`~flightsite.metadata.precedence.DEFAULT_FIELD_PRIORITIES` could not
make this source influence a type designator, because it never makes a claim
about one.

Within its four fields it is ranked *below* both existing sources
(:data:`~flightsite.metadata.precedence.DEFAULT_FIELD_PRIORITIES`), so an
OpenSky value can only ever land where both left ``NULL``. Combined with the
precedence model's "silence never wins" rule, that is fill-gaps-only by
construction: this source cannot overwrite anything.

``model`` is assembled as ``"<manufacturername> <model>"``
(:func:`_join_manufacturer_model`), matching what
:mod:`~flightsite.metadata.sources.faa` already writes into the same field from
its own ``ACFTREF`` make/model pair — so the resolved column holds one kind of
string regardless of which source won it.

Placeholder names
-----------------

``owner`` and ``operator`` carry workflow placeholders rather than names on many
rows — ``"Private"`` is common, and ``"Unknown"`` occurs. These are dropped to
``None`` (:data:`_PLACEHOLDER_PARTY_NAMES`), for the same reason
:mod:`~flightsite.metadata.sources.faa` drops the FAA's own ``"SALE REPORTED"``
and ``"REGISTRATION PENDING"``: SPEC §26 prefers "Unknown" to speculation, and
because this source is the lowest-precedence one, a retained placeholder would
land in a column the better sources had deliberately left empty — actively worse
than the null it replaced.

Download shape
--------------

This module streams the download to disk with a rolling hash, the way
:mod:`~flightsite.metadata.sources.faa` fetches its archive — *not* the way
:mod:`~flightsite.metadata.sources.mictronics` does. Mictronics accumulates the
whole artifact in memory and ``b"".join``s it, which is fine for its ~8 MB gzip
but would peak near 190 MB here. OpenSky serves plain CSV: there is no ``.gz``
variant (both ``aircraftDatabase.csv.gz`` and ``.tar.gz`` are 404) and the
endpoint does not honour ``Accept-Encoding: gzip``, so ~94 MB is genuinely what
crosses the wire. The divergence between the two sibling adapters is therefore
deliberate — each uses the shape that suits its artifact's size.

Staleness
---------

The published snapshot's ``Last-Modified`` is November 2024, and the dataset
page carries an "Important note" that it "is not up to date" and that the
crowdsourced database "may be made available again at a further date". This
source's value will decay and its URL may eventually 404. Both are survivable
precisely because it is opt-in and gap-filling: a failed download leaves the
previous import fully intact (``docs/SECURITY.md`` §4, enforced by
:mod:`flightsite.metadata.importer`), and a stale owner name filling a column
that would otherwise be empty is still better than nothing. It is, however, a
standing reason not to promote this source's precedence later.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Final

import httpx
import structlog

from flightsite import __version__
from flightsite.metadata.records import (
    MetadataError,
    NormalizedAircraftRecord,
    SourceArtifact,
    ValidationReport,
    normalize_text,
    normalize_year,
)

logger = structlog.get_logger(__name__)

#: The documented download URL. Redirects (302) to the project's S3 bucket, so
#: the client must follow redirects; the documented address is kept here rather
#: than the bucket it currently resolves to, which is an implementation detail
#: OpenSky may change.
DEFAULT_ARTIFACT_URL: Final = "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"

#: Sent on the download. A real, identifying User-Agent naming the project and
#: version is basic courtesy to a donation-funded non-profit serving a ~94 MB
#: file, and it gives OpenSky someone to contact if FlightSite ever misbehaves.
USER_AGENT: Final = f"FlightSite/{__version__} (+https://github.com/stevenpickles/flightsite)"

#: Filename the downloaded bytes are written under in the run's working
#: directory. Stored as received — see the module docstring's "Download shape".
ARTIFACT_FILENAME: Final = "aircraftDatabase.csv"

#: Request timeout. Generous: this is a large one-off download over a link
#: FlightSite does not control, not a poll.
DEFAULT_TIMEOUT_S: Final = 120.0

#: Hard ceiling on the download. A real snapshot is ~94 MB; this is headroom
#: against upstream growth while still bounding a misbehaving or compromised
#: endpoint. Enforced while streaming, so an oversized response is abandoned
#: rather than written out in full.
MAX_ARTIFACT_BYTES: Final = 400 * 1024 * 1024

#: Floor on the download size. A real snapshot is ~94 MB; a captive-portal
#: page, an HTTP error body, or a transfer that died early lands far below this.
MIN_ARTIFACT_BYTES: Final = 5 * 1024 * 1024

#: Rows read from the front of the file to sanity-check structure and address
#: plausibility. Bounded so ``validate``'s cost never scales with file size —
#: it is called directly on the event loop by
#: :class:`~flightsite.metadata.importer.MetadataImporter`, never off-threaded.
VALIDATE_SAMPLE_ROWS: Final = 5_000

#: Fraction of sampled non-blank rows that must carry a plausible ICAO address.
MIN_SAMPLE_PASS_RATIO: Final = 0.99

#: The columns :func:`_to_record` actually reads. Validation requires exactly
#: these in the header and ignores the other 21, so an upstream that adds or
#: reorders columns keeps importing.
REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"icao24", "registration", "manufacturername", "model", "operator", "owner", "built"}
)

#: A plausible ICAO 24-bit address as this upstream spells it: six hex digits.
#: Real rows are already lowercase, which is FlightSite's canonical spelling,
#: but the check stays case-insensitive — it judges upstream plausibility during
#: validation, not canonical form, which
#: :func:`~flightsite.metadata.records.normalize_icao24` enforces at the
#: ADR-0006 boundary.
_ICAO_PATTERN: Final = re.compile(r"^[0-9A-Fa-f]{6}$")

#: Leading four digits of an ISO-ish date. ``built`` is ``"1998-01-01"`` in a
#: real snapshot, but a bare ``"1998"`` also occurs.
_YEAR_PATTERN: Final = re.compile(r"^\s*(\d{4})")

#: Owner/operator values that are workflow placeholders rather than names — see
#: the module docstring. Compared upper-cased, after whitespace normalization.
_PLACEHOLDER_PARTY_NAMES: Final[frozenset[str]] = frozenset(
    {"PRIVATE", "PRIVATE OWNER", "UNKNOWN", "UNKNOWN OWNER", "N/A", "NA", "-", "--", "NONE"}
)

ClientFactory = Callable[[], httpx.AsyncClient]


class OpenSkyDownloadError(MetadataError):
    """The download stream misbehaved (oversized, or the transport failed)."""


def build_client(timeout_s: float = DEFAULT_TIMEOUT_S) -> httpx.AsyncClient:
    """Build the default HTTP client for downloading the artifact."""
    return httpx.AsyncClient(
        timeout=timeout_s,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def _clean_party(raw: object) -> str | None:
    """An owner/operator name, or ``None`` when it is a placeholder.

    See :data:`_PLACEHOLDER_PARTY_NAMES` and the module docstring: a placeholder
    retained here would fill a column the higher-precedence sources left empty
    on purpose.
    """
    text = normalize_text(raw)
    if text is None or text.upper() in _PLACEHOLDER_PARTY_NAMES:
        return None
    return text


def _year_from_built(raw: object) -> int | None:
    """Manufacture year from this upstream's ``built`` column.

    ``built`` is an ISO date (``"1998-01-01"``), so the leading four digits are
    taken before :func:`~flightsite.metadata.records.normalize_year` applies its
    plausibility floor. Never raises: a garbled date is not a reason to discard
    an otherwise usable row.
    """
    text = normalize_text(raw)
    if text is None:
        return None
    match = _YEAR_PATTERN.match(text)
    return normalize_year(match.group(1)) if match is not None else None


def _join_manufacturer_model(manufacturer: object, model: object) -> str | None:
    """``"<manufacturer> <model>"``, matching what ``faa.py`` writes.

    Either half alone is used when only one is present. When the model already
    leads with the manufacturer's name — ``manufacturername="Boeing"`` with
    ``model="Boeing 737-800"`` occurs upstream — it is returned unchanged rather
    than doubled.
    """
    made_by = normalize_text(manufacturer)
    named = normalize_text(model)
    if made_by is None:
        return named
    if named is None:
        return made_by
    if named.upper().startswith(made_by.upper()):
        return named
    return f"{made_by} {named}"


def _cell(row: Mapping[str, object], column: str) -> str:
    """One column's raw text, tolerating :class:`csv.DictReader`'s ragged rows.

    A row with *more* fields than the header puts the surplus in a **list**
    under the reader's ``restkey``; a row with fewer leaves columns at
    ``restval``. Neither is necessarily a string, and a corrupt or hostile
    artifact produces both, so every column read goes through here instead of
    trusting the mapping's value type. Anything that is not a string reads as
    absent — which is what it is.
    """
    value = row.get(column)
    return value if isinstance(value, str) else ""


def _to_record(row: Mapping[str, object]) -> NormalizedAircraftRecord | None:
    """One CSV row to a normalized record, or ``None`` if it claims nothing.

    Returns ``None`` — silently skipped, not counted as rejected — in two cases,
    neither of which is malformed data:

    * **No address.** Real snapshots contain all-empty rows (the first data row
      of the current one is entirely blank). A row with no ``icao24`` names no
      airframe.
    * **Nothing this source contributes.** A row whose operator, owner,
      manufacturer/model and build year are all empty has nothing to offer:
      this source withholds ``registration`` and ``type_code`` by design (see
      the module docstring), so such a record would be an empty claim that
      staged a row and won nothing.

    Rows that *are* malformed — a bad address on a row that does carry data —
    are yielded and rejected at the ADR-0006 boundary, counted like any other
    source's unparseable row.
    """
    icao24 = _cell(row, "icao24").strip()
    if not icao24:
        return None

    operator_name = _clean_party(_cell(row, "operator"))
    owner = _clean_party(_cell(row, "owner"))
    model = _join_manufacturer_model(_cell(row, "manufacturername"), _cell(row, "model"))
    manufacture_year = _year_from_built(_cell(row, "built"))
    if operator_name is None and owner is None and model is None and manufacture_year is None:
        return None

    return NormalizedAircraftRecord(
        icao24=icao24,
        # Withheld deliberately, though this upstream supplies both — see the
        # module docstring's "What this source contributes".
        registration=None,
        type_code=None,
        model=model,
        manufacture_year=manufacture_year,
        operator_name=operator_name,
        owner=owner,
        military_flag=None,
    )


def _open_csv(path: Path) -> Iterator[Mapping[str, object]]:
    """Stream ``path`` as CSV dict rows keyed by the header's column names.

    ``errors="replace"`` rather than strict: one undecodable byte in a 94 MB
    file is a mangled name in one row, not a reason to abandon the import.
    """
    with path.open("rt", encoding="utf-8", errors="replace", newline="") as handle:
        yield from csv.DictReader(handle, restval="")


def _sample_rows(path: Path, limit: int) -> tuple[list[str], list[Mapping[str, object]]]:
    """The header and the first ``limit`` rows that name an airframe.

    Rows with no ``icao24`` are skipped rather than sampled, matching
    :func:`_to_record`'s own first test. A real snapshot contains them — its
    very first data row is blank apart from literal ``false`` in the three
    boolean columns, so "every column is empty" would *not* have caught it —
    and counting them against the address-plausibility ratio would penalize a
    healthy file. A file in which *no* row has an address samples empty, which
    :meth:`OpenSkyProvider.validate` rejects.
    """
    rows: list[Mapping[str, object]] = []
    with path.open("rt", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, restval="")
        header = list(reader.fieldnames or ())
        for row in reader:
            if not _cell(row, "icao24").strip():
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
    return header, rows


async def _download(client: httpx.AsyncClient, url: str, path: Path) -> tuple[str, int]:
    """Stream ``url`` into ``path``, hashing as it goes.

    Streamed rather than buffered because this artifact is ~94 MB — see the
    module docstring's "Download shape". Returns ``(hex digest, size)``.
    """
    hasher = hashlib.sha256()
    size = 0
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_ARTIFACT_BYTES:
                    raise OpenSkyDownloadError(
                        f"aircraft database exceeds {MAX_ARTIFACT_BYTES} bytes"
                    )
                handle.write(chunk)
                hasher.update(chunk)
    return hasher.hexdigest(), size


class OpenSkyProvider:
    """:class:`~flightsite.metadata.provider.MetadataProvider` over OpenSky's
    ``aircraftDatabase.csv``.

    Constructed **only** when ``metadata.opensky_enabled`` is set — see the
    module docstring and ADR-0013. Constructing it still opens nothing; it
    downloads only when an import actually runs.

    Args:
        artifact_url: overrides :data:`DEFAULT_ARTIFACT_URL`, for tests.
        client_factory: builds the HTTP client used by :meth:`download`;
            replaced in tests with one wired to a mock transport, mirroring the
            seam :mod:`~flightsite.metadata.sources.mictronics` uses.
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
        """Fetch the artifact into ``workdir``, hashing it as it streams by.

        ``version`` and ``content_hash`` are both a SHA-256 of the downloaded
        bytes. This upstream publishes no release tag or date stamp reachable
        from the artifact itself, and its ``Last-Modified`` has been frozen
        since November 2024 (see the module docstring's "Staleness"), which
        would make a header-derived version — the approach
        :mod:`~flightsite.metadata.sources.faa` takes — constant across genuinely
        different downloads. The content hash is honest about what was imported
        and makes an unchanged snapshot re-import as a visible no-op in
        ``metadata_sources.dataset_version``.

        Raises whatever httpx raises — a connection failure, a timeout, or (via
        ``raise_for_status``) a non-2xx response — which the import pipeline
        records as this source's failure and nothing else's.
        """
        path = workdir / ARTIFACT_FILENAME
        client = self._client_factory()
        try:
            digest, size = await _download(client, self._artifact_url, path)
        finally:
            await client.aclose()

        logger.info("opensky_download_complete", size_bytes=size)
        return SourceArtifact(
            path=path,
            version=f"sha256:{digest[:16]}",
            content_hash=f"sha256:{digest}",
            size_bytes=size,
        )

    def validate(self, artifact: SourceArtifact) -> ValidationReport:
        """Judge the downloaded artifact without reading all of it.

        Bounded deliberately: :class:`~flightsite.metadata.importer.MetadataImporter`
        calls this synchronously on the event loop, never in a worker thread
        (unlike ``transform``). What it checks: the file is at least as large as
        a genuine snapshot could be, its header carries every column
        :func:`_to_record` reads, and a bounded sample from the front of the
        file has plausible ICAO addresses.

        ``expected_rows`` is deliberately left unset on an accepted report.
        Many rows contribute nothing this source supplies and are skipped by
        design (see :func:`_to_record`), so the file's row count is not a lower
        bound on what :meth:`transform` yields — the same reasoning
        :mod:`~flightsite.metadata.sources.faa` records for its own file.
        """
        if artifact.size_bytes < MIN_ARTIFACT_BYTES:
            return ValidationReport.rejected(
                f"downloaded artifact is only {artifact.size_bytes} bytes, below the "
                f"{MIN_ARTIFACT_BYTES}-byte floor for a genuine snapshot"
            )
        try:
            header, sample = _sample_rows(artifact.path, VALIDATE_SAMPLE_ROWS)
        except OSError as exc:
            return ValidationReport.rejected(f"could not read downloaded artifact: {exc}")
        except (UnicodeDecodeError, csv.Error) as exc:
            return ValidationReport.rejected(f"downloaded artifact is not valid CSV: {exc}")

        missing = REQUIRED_COLUMNS.difference(header)
        if missing:
            return ValidationReport.rejected(
                f"downloaded artifact is missing expected column(s): {', '.join(sorted(missing))}"
            )
        if not sample:
            return ValidationReport.rejected("downloaded artifact contains no rows")

        plausible = sum(1 for row in sample if _ICAO_PATTERN.match(_cell(row, "icao24").strip()))
        ratio = plausible / len(sample)
        if ratio < MIN_SAMPLE_PASS_RATIO:
            return ValidationReport.rejected(
                f"only {ratio:.0%} of sampled rows have a plausible ICAO 24-bit address"
            )
        return ValidationReport.accepted()

    def transform(self, artifact: SourceArtifact) -> Iterator[NormalizedAircraftRecord]:
        """Stream every contributing row as a normalized record.

        Rows this source has nothing to say about are skipped rather than
        yielded and rejected — they are not malformed, just silent. See
        :func:`_to_record`.
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
    "MIN_SAMPLE_PASS_RATIO",
    "REQUIRED_COLUMNS",
    "USER_AGENT",
    "VALIDATE_SAMPLE_ROWS",
    "ClientFactory",
    "OpenSkyDownloadError",
    "OpenSkyProvider",
    "build_client",
]
