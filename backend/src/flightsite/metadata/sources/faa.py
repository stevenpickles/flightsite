"""The FAA Releasable Aircraft Database as a :class:`MetadataProvider` (SPEC §26).

The FAA Civil Aviation Registry publishes a daily snapshot of every U.S.
civil aircraft registration at
``https://registry.faa.gov/database/ReleasableAircraft.zip``: a zip archive
of fixed-column, comma-delimited text files, refreshed in place (no release
tags, no history — today's download simply replaces yesterday's). Two
members matter here:

``MASTER.txt``
    ~300,000 rows, one per N-number: registration, registrant, manufacture
    year, and (where the FAA has recorded one) the aircraft's Mode S code in
    both octal and hex. The hex form is the ICAO 24-bit address every other
    part of FlightSite keys on, which makes it the join key into this
    provider's output — a MASTER row with no hex code describes an airframe
    FlightSite has no live-tracking use for, so it contributes nothing.
``ACFTREF.txt``
    A few thousand rows, one per manufacturer/model code: free-text make and
    model. MASTER references a row here by ``MFR MDL CODE`` rather than
    spelling out the make/model on every registration, so a normalized
    record's ``model`` text comes from joining the two.

Per ``flightsite.metadata.precedence.DEFAULT_FIELD_PRIORITIES``, this source
leads on ``manufacture_year`` and ``owner`` — the two things a national
registry actually holds and Mictronics mostly leaves blank — and only
supplements ``registration`` and ``model``. It deliberately does not touch
``type_code`` or ``operator_name``: ``MFR MDL CODE`` is an FAA-internal code,
not an ICAO type designator, and ``NAME`` is the registrant of record, not an
operator. Claiming either would be fighting the precedence model rather than
supplementing it.

**Owner privacy.** SPEC §26 is explicit: "If owner information is
unavailable or withheld, ``Unknown`` is preferable to speculation." Two
different things can make ``NAME`` unusable here, and this module treats both
the same way — as *no claim* (``owner=None``), never as a guess:

* the field is genuinely blank, which happens for aircraft mid-transaction
  or otherwise not yet fully on file; and
* the field holds one of the FAA's own status placeholders — literal text
  such as ``"SALE REPORTED"`` or ``"REGISTRATION PENDING"`` written into the
  *name* column itself when ``STATUS CODE`` says the registration is "in
  question" — which is a workflow note, not a registrant name.

(The FAA's separate LADD program filters *live* position feeds for
participating owners; it does not blank this bulk download's ``NAME``
column, but a withheld or placeholder name is handled identically here
regardless of *why* the FAA left it that way — this module never tries to
distinguish the reasons, only recognizes when there is no usable name.)
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import httpx
import structlog

from flightsite.metadata.records import (
    NormalizedAircraftRecord,
    RecordError,
    SourceArtifact,
    ValidationReport,
    normalize_record,
)

logger = structlog.get_logger(__name__)

#: The FAA's own download URL. Overridable per instance (a mirror, a fixture
#: server in a test) rather than only via a module constant, since the
#: pipeline builds one provider instance per process.
DEFAULT_URL: Final = "https://registry.faa.gov/database/ReleasableAircraft.zip"

#: Members this provider actually reads. ``ENGINE.txt`` is also in the
#: archive but nothing FlightSite normalizes comes from it.
MASTER_MEMBER: Final = "MASTER.txt"
ACFTREF_MEMBER: Final = "ACFTREF.txt"

#: The archive is tens of megabytes; the FAA server is not always fast.
DEFAULT_TIMEOUT_S: Final = 120.0

#: A floor ``validate()`` holds ``MASTER.txt`` to. The real file has run
#: ~290,000-300,000+ rows for years; this is set well below that so ordinary
#: year-to-year growth or a de-registration wave never trips it, while a
#: truncated or empty download — a captive portal's HTML saved with a `.zip`
#: extension, a connection that died mid-transfer — reliably does.
MIN_MASTER_ROWS: Final = 100_000

#: NAME values that are FAA workflow placeholders, not registrant names.
#: Written into the name column itself when ``STATUS CODE`` marks a
#: registration "in question" pending a sale or a new registration.
_STATUS_PLACEHOLDER_NAMES: Final = frozenset({"SALE REPORTED", "REGISTRATION PENDING"})

#: A plausible Mode S hex code: exactly six hex digits. Checked before
#: :func:`~flightsite.metadata.records.normalize_record` ever sees the value,
#: so a MASTER row with no assigned code (most of them predate ADS-B, or are
#: gliders/balloons with no transponder) is skipped quietly here rather than
#: raising out of the transform and failing the whole source — that would
#: turn an entirely ordinary registry row into a fatal error.
_HEX_PATTERN: Final = re.compile(r"^[0-9a-fA-F]{6}$")

ClientFactory = Callable[[], httpx.AsyncClient]


def build_client(timeout_s: float = DEFAULT_TIMEOUT_S) -> httpx.AsyncClient:
    """Build the default HTTP client for the FAA download."""
    return httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)


class FaaRegistryProvider:
    """Downloads, validates, and normalizes the FAA releasable registry.

    Implements :class:`~flightsite.metadata.provider.MetadataProvider`.

    Args:
        url: where to fetch the archive from. Defaults to the FAA's own
            endpoint; overridable for a mirror or, in tests, a mocked
            transport pointed at the same URL.
        client_factory: builds the HTTP client :meth:`download` uses.
            Defaults to the module-level :func:`build_client`, referenced by
            name (not bound at construction) so a test can monkeypatch
            ``flightsite.metadata.sources.faa.build_client`` and have it
            take effect for a provider built after the patch — the same
            pattern :mod:`flightsite.ingest.readsb` uses for the decoder
            client.
        min_master_rows: the floor :meth:`validate` holds ``MASTER.txt`` to.
            Overridable so tests can validate a small fixture without either
            inflating it to production size or disabling the check entirely.
    """

    __slots__ = ("_client_factory", "_min_master_rows", "_url")

    def __init__(
        self,
        *,
        url: str = DEFAULT_URL,
        client_factory: ClientFactory | None = None,
        min_master_rows: int = MIN_MASTER_ROWS,
    ) -> None:
        self._url = url
        self._client_factory = client_factory if client_factory is not None else build_client
        self._min_master_rows = min_master_rows

    async def download(self, workdir: Path) -> SourceArtifact:
        """Fetch the archive into ``workdir``, hashing it as it streams by.

        Raises whatever httpx raises — a connection failure, a timeout, or
        (via ``raise_for_status``) a non-2xx response — which the import
        pipeline records as this source's failure and nothing else's.
        """
        path = workdir / "ReleasableAircraft.zip"
        hasher = hashlib.sha256()
        size = 0
        client = self._client_factory()
        try:
            async with client.stream("GET", self._url, timeout=DEFAULT_TIMEOUT_S) as response:
                response.raise_for_status()
                with path.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
                        hasher.update(chunk)
                        size += len(chunk)
                version = _version_from(response)
        finally:
            await client.aclose()

        logger.info("faa_download_complete", size_bytes=size, version=version)
        return SourceArtifact(
            path=path,
            version=version,
            content_hash=f"sha256:{hasher.hexdigest()}",
            size_bytes=size,
        )

    def validate(self, artifact: SourceArtifact) -> ValidationReport:
        """Confirm the archive is intact and holds what a real snapshot does.

        Checked, in order: the file is a valid zip, ``testzip()`` finds no
        corrupt member, both expected members are present, and ``MASTER.txt``
        clears the row-count floor. ``expected_rows`` is deliberately left
        unset on the accepted report: most ``MASTER.txt`` rows have no Mode S
        hex code at all (older or non-transponder-equipped airframes), so the
        raw row count is not a lower bound on what :meth:`transform` yields —
        unlike a source where every row keys the join, staging fewer rows
        than this file contains is completely normal, not a sign of a
        truncated transform.
        """
        try:
            with zipfile.ZipFile(artifact.path) as archive:
                corrupt = archive.testzip()
                if corrupt is not None:
                    return ValidationReport.rejected(f"corrupt member in archive: {corrupt}")
                missing = {MASTER_MEMBER, ACFTREF_MEMBER} - set(archive.namelist())
                if missing:
                    return ValidationReport.rejected(
                        "archive is missing expected member(s): " + ", ".join(sorted(missing))
                    )
                row_count = _count_data_rows(archive, MASTER_MEMBER)
        except zipfile.BadZipFile as exc:
            return ValidationReport.rejected(f"not a valid zip archive: {exc}")

        if row_count < self._min_master_rows:
            return ValidationReport.rejected(
                f"MASTER.txt has {row_count} data rows, below the "
                f"{self._min_master_rows} floor expected of a genuine snapshot"
            )
        return ValidationReport.accepted()

    def transform(self, artifact: SourceArtifact) -> Iterator[NormalizedAircraftRecord]:
        """Stream ``MASTER.txt`` joined against ``ACFTREF.txt``.

        ``ACFTREF.txt`` is small (a few thousand rows) and loaded whole into
        a dict before the first record is yielded; ``MASTER.txt`` — the
        ~300,000-row file — is read one line at a time through a
        :class:`csv.DictReader` over a text-wrapped zip member, so peak
        memory is one row plus the small reference table rather than the
        whole dataset.
        """
        with zipfile.ZipFile(artifact.path) as archive:
            acftref = _load_acftref(archive)
            with archive.open(MASTER_MEMBER) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1", newline=""))
                _clean_fieldnames(reader)
                for row in reader:
                    record = _transform_row(row, acftref)
                    if record is not None:
                        yield record


def _version_from(response: httpx.Response) -> str:
    """A snapshot label from whatever the server tells us.

    The FAA publishes no release tag for this file — it is simply overwritten
    in place daily — so ``Last-Modified`` is the closest thing to a version
    when the live endpoint sends one; ``Date`` is the fallback most mocked
    transports set; the download's own timestamp is the last resort so a
    version is never empty.
    """
    header: str | None = response.headers.get("last-modified") or response.headers.get("date")
    if header:
        return header
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_fieldnames(reader: csv.DictReader[str]) -> None:
    """Strip whitespace from header names.

    A defensive match for the field *values*' own padding — real FAA files
    pad every field with trailing spaces to a fixed width, headers included
    in some published copies.
    """
    if reader.fieldnames is not None:
        reader.fieldnames = [name.strip() for name in reader.fieldnames]


def _count_data_rows(archive: zipfile.ZipFile, member: str) -> int:
    """Count data rows in ``member`` (total lines minus the header)."""
    with archive.open(member) as raw:
        total = sum(1 for _ in io.TextIOWrapper(raw, encoding="latin-1", newline=""))
    return max(total - 1, 0)


def _load_acftref(archive: zipfile.ZipFile) -> dict[str, str]:
    """``MFR MDL CODE`` -> ``"<manufacturer> <model>"``, loaded in full."""
    result: dict[str, str] = {}
    with archive.open(ACFTREF_MEMBER) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1", newline=""))
        _clean_fieldnames(reader)
        for row in reader:
            code = (row.get("CODE") or "").strip()
            if not code:
                continue
            mfr = (row.get("MFR") or "").strip()
            model = (row.get("MODEL") or "").strip()
            text = " ".join(part for part in (mfr, model) if part)
            if text:
                result[code] = text
    return result


def _transform_row(
    row: Mapping[str, str], acftref: Mapping[str, str]
) -> NormalizedAircraftRecord | None:
    """One ``MASTER.txt`` row (joined against ``acftref``) as a record, or ``None``.

    ``None`` covers both a row this provider has nothing to key on (blank or
    unparsable Mode S hex) and one whose address turns out to be unusable
    after all despite looking plausible — the latter re-raises as
    :class:`~flightsite.metadata.records.RecordError` from
    :func:`~flightsite.metadata.records.normalize_record`, caught here so one
    bad row cannot abort the whole streamed transform.
    """
    hex_code = (row.get("MODE S CODE HEX") or "").strip()
    if not _HEX_PATTERN.match(hex_code):
        return None

    n_number = (row.get("N-NUMBER") or "").strip()
    registration = f"N{n_number}" if n_number else None

    name = (row.get("NAME") or "").strip()
    owner = None if not name or name.upper() in _STATUS_PLACEHOLDER_NAMES else name

    model = acftref.get((row.get("MFR MDL CODE") or "").strip())

    try:
        return normalize_record(
            icao24=hex_code,
            registration=registration,
            manufacture_year=row.get("YEAR MFR"),
            owner=owner,
            model=model,
        )
    except RecordError:
        return None


__all__ = [
    "ACFTREF_MEMBER",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_URL",
    "MASTER_MEMBER",
    "MIN_MASTER_ROWS",
    "ClientFactory",
    "FaaRegistryProvider",
    "build_client",
]
