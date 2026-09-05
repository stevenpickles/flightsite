"""The offline route directory: records, storage, and the import destination.

SPEC §28 as amended on 2026-09-05 admits *"an offline, periodically imported
route directory … as the primary source, with AeroDataBox consulted only for
callsigns the directory does not know"*. This module is the FlightSite half of
that: what a directory row **is**, where it lives, and how an import replaces
it. The upstream half — what the Virtual Radar Server publishes and how it is
parsed — is :mod:`flightsite.metadata.sources.routes`, and the ADR-0006 line
between the two runs through :class:`RouteDirectoryRecord`.

Why a directory at all
----------------------

Slice 070 measured what a purely online route source costs on the owner's
receiver: 2,200-2,650 distinct airline callsigns a day at ~190 lookups an hour,
against an AeroDataBox allowance a feeder earns slowly. Every instrument that
slice built — a week-long TTL, learned schedules, a daily budget, priority
ordering — spends effort deciding *which* of those callsigns to buy. A local
table of 619,770 callsigns answers most of them for free, and the credits then
go where they are actually needed: the callsigns nobody has filed a schedule
for. ADR-0016 records the decision and the alternatives.

Where it is read, and where it is not
-------------------------------------

:meth:`RouteDirectoryRepository.lookup` is one indexed primary-key read, and it
is made **only** from the enrichment worker's own task
(:class:`~flightsite.enrichment.service.EnrichmentService`), behind the same
bounded subscription every other consumer sits behind. Nothing in
:mod:`flightsite.live`, :mod:`flightsite.ingest` or the API serializers reaches
this module, so ``docs/ARCHITECTURE.md`` §3.1's rule — *no live request or
decoder poll ever waits on SQLite* — holds unchanged. The read is deliberately
not cached in a second in-memory structure either: the worker already holds a
bounded answer cache in front of ``route_cache``, and a directory hit is
written into ``route_cache`` the moment it is used, so the same callsign costs
one read per TTL rather than one per observation.

Why the import stages in a table
--------------------------------

:class:`~flightsite.airports.sink.AirportImportSink` buffers its whole dataset
in memory, and says why: 71,190 narrow rows is a few tens of megabytes and one
``DELETE``/``INSERT`` transaction is plainer than a staging table. The route
dataset is a different size. Slice 071 measured the parsed snapshot — 619,828
rows as three-string records keyed by callsign — at **138 MB** of Python
objects, which is not a thing to hold on a Pi beside a live aircraft store and
a metadata cache. So this sink stages into ``route_directory_staging`` in short
writer transactions and promotes with one ``DELETE`` + ``INSERT … SELECT``,
which is exactly what :class:`~flightsite.metadata.sink.AircraftMetadataSink`
does with a snapshot of the same magnitude, and for the same reason. Peak
memory during an import is one batch.

The promotion is still one transaction, so the sink contract is unchanged: a
failure at any stage leaves the previous directory byte for byte as it was.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import structlog
from sqlalchemy import delete, func, insert, literal, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from flightsite.db import (
    Database,
    MetadataSource,
    RouteDirectory,
    RouteDirectoryStaging,
)
from flightsite.enrichment.model import ROUTE_SOURCE_VRS, RouteInfo
from flightsite.enrichment.policy import cache_key, eligible_callsign
from flightsite.metadata.records import MetadataError
from flightsite.metadata.registry import SourceStatus

logger = structlog.get_logger(__name__)

#: The registered source name. Short, lowercase and stable, because it is a
#: primary key in ``metadata_sources`` and appears verbatim in the slice-025
#: status payload (``docs/API.md`` §4.2).
ROUTES_SOURCE: Final = "routes"

#: The success value written to ``metadata_sources.status``, read from the
#: registry's own enum rather than spelled again — the same borrowing
#: :mod:`flightsite.airports.repository` does, for the same reason.
SOURCE_STATUS_OK: Final = SourceStatus.OK.value

#: What separates one airport code from the next in ``airport_codes``.
#: Upstream's own spelling, kept rather than re-encoded: the column reads as
#: the route does, and a reader that wants the ends takes the first and the
#: last.
PATH_SEPARATOR: Final = "-"

#: Fewest codes a usable path carries. One code is not a route — it names a
#: field without saying whether the flight is going there or coming from it —
#: and the honest storage of that is no row at all.
MIN_PATH_CODES: Final = 2

#: Most codes a path may carry. The measured snapshot tops out at twelve legs;
#: this is a sanity bound against a malformed row, not a limit on aviation.
MAX_PATH_CODES: Final = 16

#: An airport code as upstream files it: three or four upper-case
#: alphanumerics. 1,279,062 of the 1,279,075 codes in the measured snapshot are
#: four-character ICAO idents and thirteen are three-character; nothing else
#: appears, and anything else is a row this module does not understand.
AIRPORT_CODE_PATTERN: Final = re.compile(r"^[A-Z0-9]{3,4}$")

#: An ICAO airline designator, two or three characters upstream. Only the
#: three-character form can ever appear in an eligible callsign, so the shorter
#: one survives here only as a diagnostic label on a row that got in some other
#: way — which, given the callsign filter, it cannot.
AIRLINE_CODE_PATTERN: Final = re.compile(r"^[A-Z0-9]{2,3}$")

#: Rows per ``INSERT`` when staging. Three columns at a thousand rows is three
#: thousand parameters, comfortably inside SQLite's modern limit while keeping
#: the statement's own parameter list off the memory story.
STAGE_CHUNK_ROWS: Final = 1_000


class RouteRecordError(ValueError):
    """A directory row could not be normalized into a usable record.

    The sibling of :class:`~flightsite.metadata.records.RecordError`, and it
    means the same thing to the pipeline: the row is counted as rejected and
    the import carries on. A tolerance on the ratio is what turns *a lot* of
    these into a failed import.
    """


class RouteDirectoryError(MetadataError):
    """The route directory could not be replaced."""


@dataclass(frozen=True, slots=True)
class RouteDirectoryRecord:
    """One callsign's route as the directory holds it.

    The ADR-0006 boundary for this dataset: everything upstream of it —
    upstream's column names, its file layout, its CSV quirks — is
    :mod:`flightsite.metadata.sources.routes`' private problem, and everything
    on this side deals only in this.

    Built through :func:`normalize_route`, which rejects rather than repairs.
    A record constructed directly is not validated, which is exactly how the
    provider yields a deliberately unusable row for the pipeline to count.
    """

    #: The normalized callsign, spelled as
    #: :func:`flightsite.enrichment.policy.cache_key` spells it.
    callsign: str
    #: Hyphen-separated ICAO idents, origin first and destination last.
    airport_codes: str
    #: Upstream's airline designator, kept for diagnostics.
    airline_code: str | None = None

    @property
    def path(self) -> tuple[str, ...]:
        """Every airport on the route, in order."""
        return tuple(self.airport_codes.split(PATH_SEPARATOR))

    @property
    def origin_ident(self) -> str:
        """Where the flight starts: the first code on the path."""
        return self.path[0]

    @property
    def destination_ident(self) -> str:
        """Where the flight ends: the last code on the path."""
        return self.path[-1]

    def route_info(self) -> RouteInfo:
        """This row in the vocabulary the enrichment worker speaks.

        The ends become the route; the whole path rides along in ``extras`` for
        a multi-leg row, and only for a multi-leg row — a two-code path in
        ``extras`` would restate the two idents beside it, and
        ``route_cache.payload_json`` is a diagnostic convenience rather than a
        second copy of the answer.
        """
        path = self.path
        extras = {"path": self.airport_codes} if len(path) > MIN_PATH_CODES else {}
        return RouteInfo(
            origin_ident=path[0],
            destination_ident=path[-1],
            extras=extras,
            source=ROUTE_SOURCE_VRS,
        )


def normalize_route(
    *,
    callsign: str | None,
    airport_codes: str | None,
    airline_code: str | None = None,
) -> RouteDirectoryRecord:
    """One upstream row as a storable record, or raise.

    Normalization is enforced here rather than trusted to the provider, for
    :mod:`flightsite.metadata.records`' reason: SQLite compares text byte for
    byte, and a callsign that reached the table as ``"dal1234 "`` would be a
    row no lookup could ever find. The callsign is held to the *same* rule the
    enrichment worker's eligibility policy applies
    (:func:`~flightsite.enrichment.policy.eligible_callsign`), so every row in
    the table is a row a lookup could ask for — which drops 58 of the measured
    snapshot's 619,828 rows, all of them two-letter-designator or
    registration-shaped callsigns the worker would never look up anyway.

    Raises:
        RouteRecordError: if the callsign is not one that can be looked up, or
            the path is not two-to-sixteen well-formed airport codes.
    """
    normalized = eligible_callsign(callsign)
    if normalized is None:
        raise RouteRecordError(f"not a callsign a route can be filed against: {callsign!r}")

    raw_path = (airport_codes or "").strip().upper()
    codes = tuple(part for part in raw_path.split(PATH_SEPARATOR) if part)
    if not (MIN_PATH_CODES <= len(codes) <= MAX_PATH_CODES):
        raise RouteRecordError(
            f"{normalized}: a route path must name {MIN_PATH_CODES}-{MAX_PATH_CODES} "
            f"airports, got {len(codes)} from {airport_codes!r}"
        )
    for code in codes:
        if AIRPORT_CODE_PATTERN.match(code) is None:
            raise RouteRecordError(f"{normalized}: {code!r} is not an airport code")

    airline = (airline_code or "").strip().upper()
    if airline and AIRLINE_CODE_PATTERN.match(airline) is None:
        # A malformed designator is dropped rather than rejecting the row: it
        # is a diagnostic label, and the route is what the row is for.
        airline = ""

    return RouteDirectoryRecord(
        callsign=cache_key(normalized),
        airport_codes=PATH_SEPARATOR.join(codes),
        airline_code=airline or None,
    )


@dataclass(frozen=True, slots=True)
class RouteDirectoryRepository:
    """Point lookups and whole-dataset replacement over ``route_directory``.

    Everything here is off the hot path. :meth:`lookup` runs on the enrichment
    worker's task, once per callsign per cache TTL; the rest runs when a user
    asks for a metadata update.
    """

    database: Database

    async def lookup(self, callsign: str) -> RouteDirectoryRecord | None:
        """The directory's route for ``callsign``, or ``None``.

        One primary-key read on a ``WITHOUT ROWID`` table, which is a single
        B-tree descent — deliberately the whole of the directory's read
        surface, because anything richer would invite a caller onto a path this
        module promises to keep off SQLite.
        """
        async with self.database.read_session() as session:
            row = await session.get(RouteDirectory, cache_key(callsign))
        if row is None:
            return None
        return RouteDirectoryRecord(
            callsign=row.callsign,
            airport_codes=row.airport_codes,
            airline_code=row.airline_code,
        )

    async def count(self) -> int:
        """How many routes the directory currently holds."""
        async with self.database.read_session() as session:
            total = await session.scalar(select(func.count()).select_from(RouteDirectory))
            return int(total or 0)

    async def dataset_version(self) -> str | None:
        """The version every row was imported from, or ``None`` when empty.

        One row's version is every row's version: the table is replaced whole,
        so the value is a property of the dataset rather than of a row.
        """
        async with self.database.read_session() as session:
            found = await session.scalar(select(RouteDirectory.dataset_version).limit(1))
        return str(found) if found is not None else None

    async def clear_all(self) -> int:
        """Delete every route. Returns how many went (SPEC §73, slice 045).

        The same "delete what an import would recreate" logic
        :meth:`flightsite.airports.repository.AirportRepository.clear_all`
        applies: the rows are a cache of somebody else's dataset, and the next
        update rebuilds them.
        """
        async with self.database.writer_session() as session:
            total = await session.scalar(select(func.count()).select_from(RouteDirectory))
            await session.execute(delete(RouteDirectory))
            return int(total or 0)

    async def clear_staging(self) -> None:
        """Discard whatever a previous or failed run left staged."""
        async with self.database.writer_session() as session:
            await session.execute(delete(RouteDirectoryStaging))

    async def stage_batch(self, records: Sequence[RouteDirectoryRecord]) -> int:
        """Insert one batch into staging. Returns how many rows it wrote.

        Later duplicates of a callsign overwrite earlier ones rather than
        failing the import on the primary key — the conventional reading of a
        repeated key, and the rule the aircraft staging table already applies
        to a repeated address. Upstream files one row per callsign, so this
        costs nothing in practice and cannot make a re-keyed upstream fail an
        import.
        """
        if not records:
            return 0
        rows = [
            {
                "callsign": record.callsign,
                "airline_code": record.airline_code,
                "airport_codes": record.airport_codes,
            }
            for record in records
        ]
        async with self.database.writer_session() as session:
            for start in range(0, len(rows), STAGE_CHUNK_ROWS):
                statement = sqlite_insert(RouteDirectoryStaging).values(
                    rows[start : start + STAGE_CHUNK_ROWS]
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[RouteDirectoryStaging.callsign],
                        set_={
                            "airline_code": statement.excluded.airline_code,
                            "airport_codes": statement.excluded.airport_codes,
                        },
                    )
                )
        return len(rows)

    async def count_staged(self) -> int:
        """How many distinct callsigns are staged right now."""
        async with self.database.read_session() as session:
            total = await session.scalar(select(func.count()).select_from(RouteDirectoryStaging))
            return int(total or 0)

    async def promote(self, *, source: str, at_ms: int, dataset_version: str) -> int:
        """Make the staged rows the directory, and record the run. Atomic.

        One transaction covers the whole visible change: the previous routes
        go, the staged ones land carrying ``dataset_version``, staging is
        emptied, and the ``metadata_sources`` row records the success. A
        failure anywhere inside rolls all four back, which is the sink contract
        (:mod:`flightsite.metadata.sink`) and the reason the status row is
        written here rather than by the caller afterwards.

        The copy is ``INSERT … SELECT``, so 619,770 rows never exist in Python
        at once. Returns how many rows the directory now holds.
        """
        async with self.database.writer_session() as session:
            staged = int(
                await session.scalar(select(func.count()).select_from(RouteDirectoryStaging)) or 0
            )
            if staged == 0:
                raise RouteDirectoryError("refusing to replace the route directory with nothing")
            await session.execute(delete(RouteDirectory))
            await session.execute(
                insert(RouteDirectory).from_select(
                    ["callsign", "airline_code", "airport_codes", "dataset_version"],
                    select(
                        RouteDirectoryStaging.callsign,
                        RouteDirectoryStaging.airline_code,
                        RouteDirectoryStaging.airport_codes,
                        # A bound literal rather than a column: the version
                        # belongs to the artifact and is known only once it has
                        # validated, so staging never carried it.
                        literal(dataset_version).label("dataset_version"),
                    ),
                )
            )
            await session.execute(delete(RouteDirectoryStaging))
            await session.execute(
                update(MetadataSource)
                .where(MetadataSource.source == source)
                .values(
                    status=SOURCE_STATUS_OK,
                    last_attempt_ms=at_ms,
                    last_success_ms=at_ms,
                    dataset_version=dataset_version,
                    row_count=staged,
                    last_error=None,
                )
            )
        return staged


class RouteDirectoryImportSink:
    """The ``routes`` destination for the metadata import pipeline.

    An :class:`~flightsite.metadata.sink.ImportSink` over
    :class:`RouteDirectoryRepository`, so the route dataset rides the pipeline
    every other dataset rides: same download, same validation gate, same
    reject-ratio tolerance, same independent ``metadata_sources`` row that
    slice 025's update action reports (SPEC §27).

    Every method takes the source name because the contract is per-source. Only
    ``routes`` writes here, so the name is checked rather than partitioned on —
    a second route source would need a ``source`` column in the staging table
    before this class could honestly ignore the difference.
    """

    __slots__ = ("_repository",)

    def __init__(self, repository: RouteDirectoryRepository) -> None:
        self._repository = repository

    def canonical(self, record: Any) -> RouteDirectoryRecord | None:
        """Re-normalize a provider's record, or ``None`` if it is unusable.

        The ADR-0006 boundary enforced rather than trusted, exactly as the
        aircraft and airport sinks enforce it: a callsign that reached the
        table lower-cased or padded would be a row the worker's lookup — which
        spells the key its own way — could never find, and no schema constraint
        would catch it. Rows that come back ``None`` are counted as rejected,
        and the pipeline enforces a tolerance on the ratio.
        """
        try:
            return normalize_route(
                callsign=record.callsign,
                airport_codes=record.airport_codes,
                airline_code=record.airline_code,
            )
        except (AttributeError, RouteRecordError):
            return None

    async def clear_staging(self, source: str) -> None:
        """Drop anything staged for ``source``."""
        del source
        await self._repository.clear_staging()

    async def stage_batch(self, source: str, records: Sequence[Any], *, updated_ms: int) -> int:
        """Stage one batch. Returns how many rows it wrote.

        ``updated_ms`` is part of the sink contract and unused here: the
        directory carries no per-row timestamp, because it is replaced whole
        and ``metadata_sources.last_success_ms`` already records when. A
        per-row copy of one instant would say nothing extra.
        """
        del source, updated_ms
        return await self._repository.stage_batch(records)

    async def count_staged(self, source: str) -> int:
        """How many distinct callsigns are staged."""
        del source
        return await self._repository.count_staged()

    async def promote(
        self, source: str, *, at_ms: int, dataset_version: str, row_count: int
    ) -> None:
        """Replace the directory with what is staged. Atomic.

        ``row_count`` is the pipeline's count of what it staged; the repository
        writes its own, taken inside the promoting transaction, into
        ``metadata_sources.row_count``. The two agree in every real run — the
        staging table is keyed by callsign, and so is the pipeline's count —
        and where they could not, the number a user reads should be the number
        of rows the table actually holds.
        """
        del row_count
        written = await self._repository.promote(
            source=source, at_ms=at_ms, dataset_version=dataset_version
        )
        logger.info("route_directory_replaced", source=source, rows=written)


__all__ = [
    "AIRLINE_CODE_PATTERN",
    "AIRPORT_CODE_PATTERN",
    "MAX_PATH_CODES",
    "MIN_PATH_CODES",
    "PATH_SEPARATOR",
    "ROUTES_SOURCE",
    "STAGE_CHUNK_ROWS",
    "RouteDirectoryError",
    "RouteDirectoryImportSink",
    "RouteDirectoryRecord",
    "RouteDirectoryRepository",
    "RouteRecordError",
    "normalize_route",
]
