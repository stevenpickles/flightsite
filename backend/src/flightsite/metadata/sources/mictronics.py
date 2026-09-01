"""The Mictronics/tar1090 aircraft database adapter (SPEC §25, roadmap slice 022).

**This module is the only place in FlightSite that knows this upstream's field
names, its bit-packed flags, or its ICAO-block bookkeeping rows.** Everything
it produces crosses the ADR-0006 boundary as
:class:`~flightsite.metadata.records.NormalizedAircraftRecord`.

Choice of artifact
-------------------

Upstream research (this slice) found three ways to obtain this database:

1. The Mictronics ``readsb`` webapp's own per-block JSON shards
   (``webapp/src/db/*.js`` in ``github.com/Mictronics/readsb``) — the format
   the browser IndexedDB loader consumes, split across roughly 150 files by
   address prefix.
2. The Mictronics ``readsb`` webapp's flat source files
   (``webapp/src/db/aircrafts.json``, ``operators.json``, ``types.json``) —
   one ~28 MB JSON blob plus two smaller lookup tables, rebuilt from the
   author's own export tool.
3. ``wiedehopf/tar1090-db``'s ``csv`` branch, which repacks (1) into a single
   semicolon-delimited ``aircraft.csv``, gzip-compressed to about 8 MB, and is
   the format ``readsb``/``tar1090`` themselves load via ``--db-file``
   (``https://github.com/wiedehopf/tar1090-db``, README: *"Database repo for
   tar1090 using the database maintained by
   https://github.com/Mictronics/readsb"*).

This module downloads (3): one HTTP request, one file, no shard enumeration,
and it is the same artifact a real readsb/tar1090 install already refreshes
itself with — a homelab-practical choice the roadmap calls for explicitly
("single compressed CSV preferred over thousands of shards"). The download
URL is :data:`DEFAULT_ARTIFACT_URL`; :class:`MictronicsProvider` accepts an
override for tests.

CSV format
----------

No header row. Each line is 7 or 8 semicolon-delimited fields (the CSV writer
that produces it always emits a trailing empty field from a trailing ``;``),
written with :func:`csv.writer` under ``delimiter=";"``,
``escapechar="\\\\"``, ``quoting=QUOTE_NONE`` — so a literal ``;`` inside a
field would appear backslash-escaped, though it does not occur anywhere in a
real snapshot at the time of writing::

    3B9BFB;;E2;10;Grumman E-2C Hawkeye 2000;;;
    A1BCCA;N21065;P28A;00;PIPER PA-28-140/150/160/180;1978;OMNI MANAGEMENT LLC;

===== ============== ==========================================================
Index Field          Meaning
===== ============== ==========================================================
0     address        ICAO 24-bit address, 6 uppercase hex digits.
1     registration   Tail number. Often blank.
2     type code      ICAO aircraft type designator. Often blank.
3     flags          A *bit string*, not a decimal number — see below.
4     long type      Free-text manufacturer/model description.
5     year            Manufacture year. Sparse outside US-registered airframes.
6     ownop          Free-text operator or, for some rows, an individual
                      owner's name — this upstream does not distinguish them.
7     (trailing)     Always empty; an artifact of the writer's trailing ``;``.
===== ============== ==========================================================

The flags field (index 3) is decoded **character by character**, matching
``readsb``'s own C parser (``aircraft.c``): position 0 is the military bit,
position 1 "interesting", position 2 PIA (Privacy ICAO Address), position 3
LADD (Limiting Aircraft Data Displayed); a position past the end of the string
is simply unset. So ``"10"`` means military only, ``"0010"`` means PIA only,
and ``"11000"`` (seen on at least one real row) means military *and*
"interesting" with a spare trailing bit upstream does not currently define.
:func:`_parse_db_flags` implements exactly this. Military status lands on
:attr:`~flightsite.metadata.records.NormalizedAircraftRecord.military_flag`;
the other three are source-specific extras this upstream is uniquely
positioned to supply, so they ride in
:attr:`~flightsite.metadata.records.NormalizedAircraftRecord.flags` for slice
024 to mine rather than crowding the normalized schema.

**ICAO-block bookkeeping rows.** Roughly 8% of lines in a real snapshot have
*both* registration and type code blank — these are not aircraft. They are
range markers readsb uses internally for country/military-block lookups when
no exact address match exists (``"000001;;;10;;;Miscode - VARIOUS;"``,
``"3E8057;;;10;;;;"``). A row with *either* field populated is a real
airframe claim and is kept, even when unusual (a type code with no
registration, e.g. block-level military-type entries, is common and genuine).
:func:`_to_record` is the boundary that drops the former and keeps the
latter — see its docstring for exactly where that line falls.

``owner`` is never populated here: this upstream's one free-text field
(``ownop``) is mapped to ``operator_name``, matching
:mod:`flightsite.metadata.precedence`'s own accounting of what each v1 source
actually supplies (Mictronics: identity and type; FAA, slice 023: year and
owner).

License and attribution
------------------------

Verified against the upstream repositories directly (no separate LICENSE
covers the data specifically):

* ``github.com/Mictronics/readsb`` — the repository whose ``webapp/src/db``
  directory is the origin of this data — is licensed **GPL v3, or any later
  version** (its ``LICENSE`` file), incorporating GPL v2+ and BSD-licensed
  ``dump1090`` code. Its ``webapp/src/db/README`` states the underlying
  sources: operator/callsign decode from **FAA JO7340.2**, aircraft type data
  from **ICAO Doc 8643**, updated from
  ``https://www.mictronics.de/aircraft-database/export.php``.
* ``github.com/wiedehopf/tar1090-db`` (the ``csv`` branch this module
  downloads) carries no LICENSE file of its own; its README credits Mictronics
  as the maintained source and adds no separate terms.

No file in either repository grants an explicit data license distinct from
the GPL covering the *readsb* software itself, and the data blends multiple
upstream sources (Mictronics' own curation, FAA JO7340.2 operator/callsign
tables, ICAO Doc 8643 type data) with no per-row provenance to attribute
individually. FlightSite therefore treats this as **fetch-on-demand only**:
this provider downloads the artifact into the running deployment's own working
directory at the user's request (an "Update Aircraft Metadata" action) and
never bundles, ships, or redistributes it in FlightSite's source tree or
container images — the same posture already taken for OpenStreetMap-derived
tiles in ``docs/LICENSES.md``. In-app and documentation attribution names
Mictronics and the upstream data sources it credits; see the register in
``docs/LICENSES.md`` for the exact text and the compatibility reasoning.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import re
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Final

import httpx

from flightsite.metadata.records import (
    MetadataError,
    NormalizedAircraftRecord,
    SourceArtifact,
    ValidationReport,
    normalize_text,
    normalize_year,
)

#: The single artifact this provider downloads — see the module docstring's
#: "Choice of artifact" for why this one, of the three upstream offers.
DEFAULT_ARTIFACT_URL: Final = (
    "https://raw.githubusercontent.com/wiedehopf/tar1090-db/csv/aircraft.csv.gz"
)

#: Filename the downloaded bytes are written under in the run's working
#: directory. Kept compressed on disk — :func:`_open_csv` decompresses on
#: read, once for validation's bounded sample and once, streamed, for the
#: transform — rather than materializing an ~30 MB decompressed copy that
#: nothing but those two reads would ever use.
ARTIFACT_FILENAME: Final = "aircraft.csv.gz"

#: Request timeout for the download. Generous relative to the decoder-polling
#: timeout elsewhere in the codebase: this is an ~8 MB file fetched once per
#: "Update Aircraft Metadata" action, not a per-second poll.
DEFAULT_TIMEOUT_S: Final = 30.0

#: Hard ceiling on the downloaded artifact. A real snapshot is a few MB; this
#: is generous headroom against upstream growth while still bounding memory
#: for a homelab Pi against a misbehaving or compromised endpoint.
MAX_ARTIFACT_BYTES: Final = 200 * 1024 * 1024

#: gzip's two-byte magic number, checked before attempting to decompress.
GZIP_MAGIC: Final = b"\x1f\x8b"

#: Floor on the *compressed* download size, standing in for a row-count floor
#: without decompressing the whole file. ``validate`` is called directly on
#: the event loop by :class:`~flightsite.metadata.importer.MetadataImporter`
#: (never off-threaded, unlike ``transform``), so it must stay cheap; a real
#: snapshot is roughly 8 MB, and a captive-portal page, an HTTP error body, or
#: a connection that died partway through a multi-megabyte transfer all land
#: far below this well before a byte of it needs decompressing.
MIN_ARTIFACT_BYTES: Final = 1_000_000

#: Rows read from the front of the file to sanity-check structure and address
#: plausibility. Bounded so the cost of ``validate`` never scales with file
#: size — reading stops the moment this many rows have been seen, regardless
#: of how much of the file that represents.
VALIDATE_SAMPLE_ROWS: Final = 5_000

#: Fraction of the sampled rows that must be well-formed / have a plausible
#: ICAO address for the artifact to pass. Real snapshots are effectively
#: 100%; this leaves slack for a handful of upstream oddities without masking
#: a genuinely wrong file format.
MIN_SAMPLE_PASS_RATIO: Final = 0.99

#: Fewest semicolon-delimited fields a well-formed data line has (the 8th,
#: always-empty trailing field may be absent without the line being broken).
MIN_CSV_FIELDS: Final = 7

# Column indices within one CSV row — see the module docstring's field table.
_COL_ICAO: Final = 0
_COL_REGISTRATION: Final = 1
_COL_TYPE_CODE: Final = 2
_COL_DB_FLAGS: Final = 3
_COL_MODEL: Final = 4
_COL_YEAR: Final = 5
_COL_OWNOP: Final = 6

#: A plausible ICAO 24-bit address as this upstream spells it: six hex
#: digits, case-insensitive (real rows are uppercase). Deliberately looser
#: than :data:`flightsite.metadata.records.ICAO24_PATTERN`, which is the
#: framework's canonical *lowercase-only* spelling checked at the ADR-0006
#: boundary — this one only judges upstream plausibility during validation.
_ICAO_PATTERN: Final = re.compile(r"^[0-9A-Fa-f]{6}$")

ClientFactory = Callable[[], httpx.AsyncClient]


class MictronicsDownloadError(MetadataError):
    """The download stream misbehaved (oversized, or the transport failed)."""


def build_client(timeout_s: float = DEFAULT_TIMEOUT_S) -> httpx.AsyncClient:
    """Build the default HTTP client for downloading the artifact."""
    return httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)


def _parse_db_flags(raw: str) -> tuple[bool, bool, bool, bool]:
    """Decode the flags field's bit string into (military, interesting, pia, ladd).

    Character-by-character, matching ``readsb``'s own parser: position *i*
    means bit *i* is set only when the string has a character there and it is
    ``"1"``. A short or empty string simply leaves the missing positions
    unset — this upstream's structural convention for "no", not "unknown"
    (see the module docstring).
    """

    def bit(index: int) -> bool:
        return index < len(raw) and raw[index] == "1"

    return bit(0), bit(1), bit(2), bit(3)


def _to_record(fields: Sequence[str]) -> NormalizedAircraftRecord | None:
    """One CSV row to a normalized record, or ``None`` if it names no aircraft.

    Two things make a row not worth yielding:

    * **Too short to parse.** A line with fewer than :data:`MIN_CSV_FIELDS`
      fields is malformed, not merely sparse — real rows always have at least
      this many. Rather than silently dropping it, it is turned into a record
      with an unusable address (``icao24=""``), so the ADR-0006 boundary's own
      re-normalization in
      :class:`~flightsite.metadata.importer.MetadataImporter` rejects and
      *counts* it, the same as any other unparseable row from any source.
    * **An ICAO-block bookkeeping row**, not an aircraft: both registration
      and type code are blank (see the module docstring). These are silently
      skipped — they are not malformed, so counting them as rejected would
      make a perfectly healthy snapshot look like it was failing its own
      reject-ratio tolerance.
    """
    if len(fields) < MIN_CSV_FIELDS:
        return NormalizedAircraftRecord(icao24="")

    registration = normalize_text(fields[_COL_REGISTRATION])
    type_code_raw = normalize_text(fields[_COL_TYPE_CODE])
    type_code = type_code_raw.upper() if type_code_raw is not None else None
    if registration is None and type_code is None:
        return None

    military, interesting, pia, ladd = _parse_db_flags(fields[_COL_DB_FLAGS])
    return NormalizedAircraftRecord(
        icao24=fields[_COL_ICAO],
        registration=registration,
        type_code=type_code,
        model=normalize_text(fields[_COL_MODEL]),
        manufacture_year=normalize_year(fields[_COL_YEAR]),
        operator_name=normalize_text(fields[_COL_OWNOP]),
        owner=None,
        military_flag=military,
        flags={"interesting": interesting, "pia": pia, "ladd": ladd},
    )


def _open_csv(path: Path) -> Iterator[list[str]]:
    """Stream ``path`` (gzip-compressed) as CSV rows, skipping blank lines."""
    with gzip.open(path, mode="rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=";", escapechar="\\", quoting=csv.QUOTE_NONE)
        for row in reader:
            if row:
                yield row


def _sample_rows(path: Path, limit: int) -> list[list[str]]:
    """The first ``limit`` non-blank rows of ``path``, decompressing no more
    of the file than that requires.
    """
    rows: list[list[str]] = []
    for row in _open_csv(path):
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


async def _fetch(client: httpx.AsyncClient, url: str) -> bytes:
    """GET ``url``, streamed and capped at :data:`MAX_ARTIFACT_BYTES`."""
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise MictronicsDownloadError(
                    f"aircraft database exceeds {MAX_ARTIFACT_BYTES} bytes"
                )
            chunks.append(chunk)
    return b"".join(chunks)


class MictronicsProvider:
    """:class:`~flightsite.metadata.provider.MetadataProvider` over this
    upstream's ``aircraft.csv.gz``.

    Args:
        artifact_url: overrides :data:`DEFAULT_ARTIFACT_URL`, for tests.
        client_factory: builds the HTTP client used by :meth:`download`;
            replaced in tests with one wired to a mock transport. Mirrors
            :mod:`flightsite.ingest.readsb`'s ``client_factory`` seam.
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
        """Fetch the artifact into ``workdir``, kept gzip-compressed on disk.

        ``version`` and ``content_hash`` are both a SHA-256 of the downloaded
        bytes: this upstream publishes no release tag or date stamp reachable
        from the artifact alone, so the content hash is, per
        :class:`~flightsite.metadata.records.SourceArtifact`, "the only thing
        tying a set of resolved rows back to the bytes that produced them" —
        and it doubles as the version, so an unchanged snapshot re-imports as
        a visible no-op in ``metadata_sources.dataset_version``.
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
        """Judge the downloaded artifact without decompressing all of it.

        Bounded deliberately: :class:`~flightsite.metadata.importer.MetadataImporter`
        calls this synchronously, directly on the event loop, never in a
        worker thread (unlike ``transform``) — see
        :data:`MIN_ARTIFACT_BYTES`. What this checks: the file is at least as
        large as a genuine snapshot could plausibly compress to (standing in
        for a row-count floor without a full scan), it starts with the gzip
        magic number, and a bounded sample from the front of the file is
        structurally well-formed CSV with plausible ICAO addresses.
        """
        if artifact.size_bytes < MIN_ARTIFACT_BYTES:
            return ValidationReport.rejected(
                f"downloaded artifact is only {artifact.size_bytes} bytes, below the "
                f"{MIN_ARTIFACT_BYTES}-byte floor for a genuine snapshot"
            )
        try:
            with artifact.path.open("rb") as raw_header:
                magic = raw_header.read(len(GZIP_MAGIC))
            if magic != GZIP_MAGIC:
                return ValidationReport.rejected("downloaded artifact is not gzip-compressed")
            sample = _sample_rows(artifact.path, VALIDATE_SAMPLE_ROWS)
        except OSError as exc:
            return ValidationReport.rejected(f"could not read downloaded artifact: {exc}")
        except (EOFError, UnicodeDecodeError, csv.Error) as exc:
            return ValidationReport.rejected(f"downloaded artifact is not a valid gzip CSV: {exc}")

        if not sample:
            return ValidationReport.rejected("downloaded artifact contains no rows")

        well_formed = [row for row in sample if len(row) >= MIN_CSV_FIELDS]
        if len(well_formed) / len(sample) < MIN_SAMPLE_PASS_RATIO:
            return ValidationReport.rejected(
                f"only {len(well_formed)} of {len(sample)} sampled rows have the expected "
                f"{MIN_CSV_FIELDS}+ semicolon-delimited fields"
            )
        plausible = sum(1 for row in well_formed if _ICAO_PATTERN.match(row[_COL_ICAO]))
        ratio = plausible / len(well_formed)
        if ratio < MIN_SAMPLE_PASS_RATIO:
            return ValidationReport.rejected(
                f"only {ratio:.0%} of sampled rows have a plausible ICAO 24-bit address"
            )
        return ValidationReport.accepted()

    def transform(self, artifact: SourceArtifact) -> Iterator[NormalizedAircraftRecord]:
        """Stream every row as a normalized record.

        Real ICAO-block bookkeeping rows (see the module docstring) are
        silently skipped rather than yielded and rejected — they are not
        malformed data, just not aircraft.
        """
        for fields in _open_csv(artifact.path):
            record = _to_record(fields)
            if record is not None:
                yield record


__all__ = [
    "ARTIFACT_FILENAME",
    "DEFAULT_ARTIFACT_URL",
    "DEFAULT_TIMEOUT_S",
    "MAX_ARTIFACT_BYTES",
    "MIN_ARTIFACT_BYTES",
    "MIN_CSV_FIELDS",
    "MIN_SAMPLE_PASS_RATIO",
    "VALIDATE_SAMPLE_ROWS",
    "ClientFactory",
    "MictronicsDownloadError",
    "MictronicsProvider",
    "build_client",
]
