"""Every SQL statement the metadata subsystem issues.

Split out from the pipeline so the pipeline reads as the sequence
``docs/DATA_MODEL.md`` §3.2 describes — stage, validate, swap — and so the
session discipline of ADR-0001/ADR-0008 is enforced in exactly one place.

Two rules shape this module:

**Short writer transactions.** The process has one writer session and it is
shared with sighting persistence, so an import must never hold it for the
length of a download-sized write. Staging is loaded in batches, each its own
short transaction; the writer lock is released between them. Only the promotion
— a handful of set-based statements plus the resolved rebuild — runs as one
transaction, because only it has to be atomic.

**Atomicity where it is load-bearing.** :meth:`MetadataRepository.promote` does
the whole visible swap inside one transaction: the source's old rows go, the
staged rows land, staging is cleared, ``aircraft_metadata_resolved`` is rebuilt
and the status row is updated. Any exception rolls all of it back, which is what
makes SPEC §27's *"preserves the previous working dataset if an import fails"*
a property of the storage layer rather than a hope about error handling.

The resolved rebuild streams rather than loading the table: a snapshot runs to
hundreds of thousands of airframes, and keyset pagination over ``icao24`` keeps
peak memory at one chunk (``docs/ARCHITECTURE.md`` §6, "streamed imports").
Rows for one airframe are contiguous under the ``(icao24, source)`` primary key,
so a chunk boundary is the only thing that could split an airframe's claims —
and :meth:`MetadataRepository._claim_groups` never emits a group it has not seen
the end of.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Final

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.db import Database
from flightsite.db.models import (
    Aircraft,
    AircraftMetadata,
    AircraftMetadataResolved,
    AircraftMetadataStaging,
    MetadataSource,
    Operator,
)
from flightsite.metadata.precedence import (
    PrecedenceModel,
    ResolvedMetadata,
    SourceClaim,
)
from flightsite.metadata.records import NormalizedAircraftRecord
from flightsite.metadata.registry import SourceStatus, SourceStatusRecord

#: Columns shared by ``aircraft_metadata`` and its staging table, in the order
#: the promotion's ``INSERT ... SELECT`` pairs them up.
METADATA_COLUMNS: Final[tuple[str, ...]] = (
    "icao24",
    "source",
    "registration",
    "type_code",
    "model",
    "manufacture_year",
    "operator_name",
    "owner",
    "military_flag",
    "flags_json",
    "updated_ms",
)

#: Rows per ``INSERT`` statement while loading staging. Large enough that
#: per-statement overhead disappears, small enough that one statement's bound
#: parameters stay well inside SQLite's limits.
STAGE_BATCH_ROWS: Final = 1_000

#: Rows read per page while rebuilding the resolved table. At two sources per
#: airframe this is a few thousand airframes per round trip.
REBUILD_PAGE_ROWS: Final = 4_000

#: Addresses bound into one lookup. SQLite's default host-parameter limit is
#: 999; staying under it keeps a whole-live-set read working without
#: depending on a build-time setting.
IN_CLAUSE_CHUNK: Final = 500

#: Cap on a stored error message. Status is a summary a user reads, not a log:
#: a provider that raises a megabyte-long string must not turn the status row
#: into one.
MAX_ERROR_CHARS: Final = 500


class MetadataRepository:
    """Reads and writes the metadata tables through the database's sessions."""

    __slots__ = ("_database",)

    def __init__(self, database: Database) -> None:
        self._database = database

    # ------------------------------------------------------------- status

    async def ensure_source(self, source: str) -> None:
        """Create ``source``'s status row if it does not exist yet.

        ``aircraft_metadata.source`` references this table, so the row has to
        exist before any of that source's data can land. Never overwrites: a
        source that has run before keeps its history.
        """
        statement = (
            sqlite_insert(MetadataSource)
            .values(source=source, status=SourceStatus.NEVER_RUN.value)
            .on_conflict_do_nothing(index_elements=[MetadataSource.source])
        )
        async with self._database.writer_session() as session:
            await session.execute(statement)

    async def read_status(self, source: str) -> SourceStatusRecord | None:
        """The stored status of ``source``, or ``None`` if it has no row."""
        async with self._database.read_session() as session:
            row = await session.get(MetadataSource, source)
            return None if row is None else _to_status(row)

    async def read_statuses(self) -> tuple[SourceStatusRecord, ...]:
        """Every stored source status, sorted by source name."""
        async with self._database.read_session() as session:
            rows = (
                await session.scalars(select(MetadataSource).order_by(MetadataSource.source))
            ).all()
            return tuple(_to_status(row) for row in rows)

    async def mark_attempt(self, source: str, *, at_ms: int) -> None:
        """Record that an import of ``source`` has begun.

        Only ``last_attempt_ms`` moves. The status, last success, version and
        row count still describe the dataset that is actually installed, and
        they must keep describing it for as long as it is the one in use —
        including for the whole duration of a run that is about to fail.
        """
        await self._update_source(source, last_attempt_ms=at_ms)

    async def mark_failure(self, source: str, *, at_ms: int, error: str) -> None:
        """Record a failed import of ``source``, preserving its dataset facts.

        Runs in its own transaction, after the failed run's transaction has
        rolled back — the status write must survive the rollback that protects
        the data, or a user would see a stale ``ok`` beside data that did not
        change.
        """
        await self._update_source(
            source,
            last_attempt_ms=at_ms,
            status=SourceStatus.FAILED.value,
            last_error=error[:MAX_ERROR_CHARS],
        )

    async def _update_source(self, source: str, **values: object) -> None:
        async with self._database.writer_session() as session:
            await self._update_source_in(session, source, **values)

    @staticmethod
    async def _update_source_in(session: AsyncSession, source: str, **values: object) -> None:
        await session.execute(
            update(MetadataSource).where(MetadataSource.source == source).values(**values)
        )

    # ------------------------------------------------------------- staging

    async def clear_staging(self, source: str) -> None:
        """Delete ``source``'s staged rows.

        Called before a run loads new ones, which is also what makes a crashed
        run harmless: leftover staging rows are scratch, are never read by
        anything but their own run's promotion, and are cleared before the next
        run of the same source can use them.
        """
        async with self._database.writer_session() as session:
            await session.execute(
                delete(AircraftMetadataStaging).where(AircraftMetadataStaging.source == source)
            )

    async def stage_batch(
        self,
        source: str,
        records: Sequence[NormalizedAircraftRecord],
        *,
        updated_ms: int,
    ) -> int:
        """Insert one batch of ``source``'s records into staging.

        Later duplicates of an ``icao24`` within a snapshot overwrite earlier
        ones rather than failing the import: upstream files do contain repeated
        addresses, and the last row is the conventional reading. Returns the
        number of records written.
        """
        if not records:
            return 0
        rows = [_staging_row(source, record, updated_ms) for record in records]
        async with self._database.writer_session() as session:
            for start in range(0, len(rows), STAGE_BATCH_ROWS):
                chunk = rows[start : start + STAGE_BATCH_ROWS]
                await session.execute(
                    sqlite_insert(AircraftMetadataStaging)
                    .values(chunk)
                    .on_conflict_do_update(
                        index_elements=[
                            AircraftMetadataStaging.icao24,
                            AircraftMetadataStaging.source,
                        ],
                        set_={
                            name: getattr(sqlite_insert(AircraftMetadataStaging).excluded, name)
                            for name in METADATA_COLUMNS
                            if name not in ("icao24", "source")
                        },
                    )
                )
        return len(rows)

    async def count_staged(self, source: str) -> int:
        """How many rows ``source`` currently has in staging."""
        async with self._database.read_session() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(AircraftMetadataStaging)
                .where(AircraftMetadataStaging.source == source)
            )
            return int(total or 0)

    async def count_live(self, source: str) -> int:
        """How many live ``aircraft_metadata`` rows ``source`` currently owns."""
        async with self._database.read_session() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(AircraftMetadata)
                .where(AircraftMetadata.source == source)
            )
            return int(total or 0)

    # ------------------------------------------------------------- promotion

    async def promote(
        self,
        source: str,
        *,
        precedence: PrecedenceModel,
        at_ms: int,
        dataset_version: str,
        row_count: int,
    ) -> None:
        """Swap ``source``'s staged rows in and rebuild resolution. Atomic.

        One transaction covers the entire visible change: the source's previous
        rows are replaced, staging is emptied, every resolved row is rebuilt
        from the new picture, and the status row records the success. A failure
        anywhere inside rolls the lot back, leaving the previous dataset — and
        the previous resolved table — exactly as they were.
        """
        async with self._database.writer_session() as session:
            await session.execute(delete(AircraftMetadata).where(AircraftMetadata.source == source))
            columns = [getattr(AircraftMetadataStaging, name) for name in METADATA_COLUMNS]
            await session.execute(
                insert(AircraftMetadata).from_select(
                    list(METADATA_COLUMNS),
                    select(*columns).where(AircraftMetadataStaging.source == source),
                )
            )
            await session.execute(
                delete(AircraftMetadataStaging).where(AircraftMetadataStaging.source == source)
            )
            await self.rebuild_resolved(session, precedence=precedence, at_ms=at_ms)
            await self._update_source_in(
                session,
                source,
                status=SourceStatus.OK.value,
                last_attempt_ms=at_ms,
                last_success_ms=at_ms,
                dataset_version=dataset_version,
                row_count=row_count,
                last_error=None,
            )

    async def rebuild_resolved(
        self,
        session: AsyncSession,
        *,
        precedence: PrecedenceModel,
        at_ms: int,
    ) -> int:
        """Rebuild ``aircraft_metadata_resolved`` from the per-source rows.

        Runs inside the caller's transaction — normally the promotion's — so
        the resolved table is never observable in a half-rebuilt state. Returns
        the number of resolved rows written.

        Airframes for which no source supplies a single resolvable field are
        omitted rather than written as an all-``NULL`` row: absence is the
        honest representation of "nothing is known", and it is what the lookup
        cache reports either way.
        """
        groups = await self._operator_groups(session)
        await session.execute(delete(AircraftMetadataResolved))

        written = 0
        pending: list[dict[str, str | int | None]] = []
        async for icao24, claims in self._claim_groups(session):
            resolved = precedence.resolve(icao24, claims, updated_ms=at_ms)
            if resolved.is_empty:
                continue
            pending.append(_with_group(resolved, groups).as_row())
            if len(pending) >= STAGE_BATCH_ROWS:
                await session.execute(insert(AircraftMetadataResolved), pending)
                written += len(pending)
                pending = []
        if pending:
            await session.execute(insert(AircraftMetadataResolved), pending)
            written += len(pending)
        return written

    async def _operator_groups(self, session: AsyncSession) -> Mapping[str, int]:
        """Exact operator string to curated group id.

        Empty until slice 024 populates ``operators``; loaded whole because it
        is curated data measured in thousands of rows, not a scan of anything
        that grows with traffic.
        """
        rows = (await session.execute(select(Operator.name, Operator.group_id))).all()
        return {str(name): int(group_id) for name, group_id in rows}

    async def _claim_groups(
        self, session: AsyncSession
    ) -> AsyncIterator[tuple[str, list[SourceClaim]]]:
        """Yield ``(icao24, claims)`` for every airframe, in ``icao24`` order.

        Keyset pagination rather than a held cursor: the same transaction is
        writing to ``aircraft_metadata_resolved`` between pages, and paging by
        the primary key keeps reads and writes from sharing a cursor. A page is
        cut back to its last complete airframe, so an airframe's claims are
        never split across two groups.
        """
        after = ""
        while True:
            rows = (
                (
                    await session.execute(
                        select(AircraftMetadata)
                        .where(AircraftMetadata.icao24 > after)
                        .order_by(AircraftMetadata.icao24, AircraftMetadata.source)
                        .limit(REBUILD_PAGE_ROWS)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return

            complete = list(rows)
            if len(rows) == REBUILD_PAGE_ROWS:
                # The final airframe on a full page may continue onto the next
                # one; leave it for the next round rather than resolving half
                # of its claims.
                last = rows[-1].icao24
                complete = [row for row in rows if row.icao24 != last]
                if not complete:  # pragma: no cover - see below
                    # One airframe filling an entire page would need
                    # REBUILD_PAGE_ROWS sources, so this cannot happen — but
                    # if it ever did, resolving it from a full page beats
                    # looping forever on a cursor that never advances.
                    complete = list(rows)
            after = complete[-1].icao24

            current: list[SourceClaim] = []
            current_icao = complete[0].icao24
            for row in complete:
                if row.icao24 != current_icao:
                    yield current_icao, current
                    current_icao, current = row.icao24, []
                current.append(_to_claim(row))
            yield current_icao, current

    # ------------------------------------------------------------- lookups

    async def load_live_view(
        self, icaos: Sequence[str]
    ) -> dict[str, tuple[ResolvedMetadata | None, int | None]]:
        """Resolved metadata *and* rarity counter for ``icaos``, in one query.

        The cache's read, and its only one. Splitting it into a metadata
        query and a rarity query would be tidier to read and twice as slow:
        each aiosqlite round trip is a thread hand-off, and on an appear
        that arrives alone the second one is pure added latency against the
        slice's per-event budget. One query is also the honest shape of the
        question — *everything the cache holds about these aircraft*.

        An address may have a resolved row, an ``aircraft`` row, both, or
        neither, so the addresses themselves are the driving table — a join in
        either direction would silently drop one of those cases. SQLite has no
        portable full outer join at the version floor FlightSite targets, hence
        the ``VALUES`` list and the two ``LEFT JOIN``s spelled out here rather
        than composed in Core.

        Every requested address appears in the result, with ``None`` for
        whichever half is missing; that is what lets the cache distinguish
        "nobody knows" from "not looked up yet".
        """
        if not icaos:
            return {}
        found: dict[str, tuple[ResolvedMetadata | None, int | None]] = {}
        async with self._database.read_session() as session:
            for chunk in _chunks(icaos, IN_CLAUSE_CHUNK):
                params = {f"i{index}": icao for index, icao in enumerate(chunk)}
                values = ", ".join(f"(:{name})" for name in params)
                rows = (
                    (await session.execute(text(_LIVE_VIEW_SQL.format(values=values)), params))
                    .mappings()
                    .all()
                )
                for mapping in rows:
                    icao24 = str(mapping["icao24"])
                    count = mapping["sighting_count"]
                    found[icao24] = (
                        _resolved_from_mapping(icao24, mapping),
                        None if count is None else int(count),
                    )
        return found

    async def load_type_counts(self) -> dict[str, int]:
        """Unique airframes ever recorded, per resolved ICAO type designator.

        ``docs/DATA_MODEL.md`` §6.5 gives this figure a table of its own
        (``type_stats``) — but that table lands with the analytics rollups in
        slice 031, so until then the same number is computed from ``aircraft``
        joined to the resolved types. One row per airframe in ``aircraft``
        makes the count a unique-airframe count by construction.
        """
        async with self._database.read_session() as session:
            rows = (
                await session.execute(
                    select(AircraftMetadataResolved.type_code, func.count())
                    .join(Aircraft, Aircraft.icao24 == AircraftMetadataResolved.icao24)
                    .where(AircraftMetadataResolved.type_code.is_not(None))
                    .group_by(AircraftMetadataResolved.type_code)
                )
            ).all()
            return {str(type_code): int(count) for type_code, count in rows}


#: The cache's single read (see :meth:`MetadataRepository.load_live_view`).
#: ``{values}`` is filled with one ``(:param)`` per requested address.
_LIVE_VIEW_SQL: Final = """
WITH wanted(icao24) AS (VALUES {values})
SELECT w.icao24,
       a.sighting_count,
       r.registration, r.registration_src,
       r.type_code, r.type_code_src,
       r.model, r.model_src,
       r.manufacture_year, r.year_src,
       r.operator_name, r.operator_src,
       r.operator_group_id,
       r.owner, r.owner_src,
       r.updated_ms
FROM wanted AS w
LEFT JOIN aircraft AS a ON a.icao24 = w.icao24
LEFT JOIN aircraft_metadata_resolved AS r ON r.icao24 = w.icao24
"""


def _resolved_from_mapping(icao24: str, mapping: RowMapping) -> ResolvedMetadata | None:
    """Build a resolved record from a joined row, or ``None`` if there was none."""
    if mapping["updated_ms"] is None:
        return None
    year = mapping["manufacture_year"]
    group_id = mapping["operator_group_id"]
    return ResolvedMetadata(
        icao24=icao24,
        updated_ms=int(mapping["updated_ms"]),
        registration=mapping["registration"],
        registration_src=mapping["registration_src"],
        type_code=mapping["type_code"],
        type_code_src=mapping["type_code_src"],
        model=mapping["model"],
        model_src=mapping["model_src"],
        manufacture_year=None if year is None else int(year),
        year_src=mapping["year_src"],
        operator_name=mapping["operator_name"],
        operator_src=mapping["operator_src"],
        operator_group_id=None if group_id is None else int(group_id),
        owner=mapping["owner"],
        owner_src=mapping["owner_src"],
    )


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _staging_row(
    source: str, record: NormalizedAircraftRecord, updated_ms: int
) -> dict[str, str | int | None]:
    return {
        "icao24": record.icao24,
        "source": source,
        "registration": record.registration,
        "type_code": record.type_code,
        "model": record.model,
        "manufacture_year": record.manufacture_year,
        "operator_name": record.operator_name,
        "owner": record.owner,
        "military_flag": None if record.military_flag is None else int(record.military_flag),
        "flags_json": record.flags_json(),
        "updated_ms": updated_ms,
    }


def _to_claim(row: AircraftMetadata) -> SourceClaim:
    return SourceClaim(
        source=row.source,
        record=NormalizedAircraftRecord(
            icao24=row.icao24,
            registration=row.registration,
            type_code=row.type_code,
            model=row.model,
            manufacture_year=row.manufacture_year,
            operator_name=row.operator_name,
            owner=row.owner,
            military_flag=None if row.military_flag is None else bool(row.military_flag),
        ),
    )


def _with_group(resolved: ResolvedMetadata, groups: Mapping[str, int]) -> ResolvedMetadata:
    """Attach the curated operator group for the resolved operator, if any.

    A miss is the normal case until slice 024 lands: the exact operator string
    stays on the row either way, which is what SPEC §38 means by grouping being
    additive.
    """
    if resolved.operator_name is None:
        return resolved
    group_id = groups.get(resolved.operator_name)
    if group_id is None:
        return resolved
    return replace(resolved, operator_group_id=group_id)


def _to_status(row: MetadataSource) -> SourceStatusRecord:
    return SourceStatusRecord(
        source=row.source,
        status=SourceStatus(row.status),
        last_attempt_ms=row.last_attempt_ms,
        last_success_ms=row.last_success_ms,
        dataset_version=row.dataset_version,
        row_count=row.row_count,
        last_error=row.last_error,
    )


__all__ = [
    "IN_CLAUSE_CHUNK",
    "MAX_ERROR_CHARS",
    "METADATA_COLUMNS",
    "REBUILD_PAGE_ROWS",
    "STAGE_BATCH_ROWS",
    "MetadataRepository",
]
