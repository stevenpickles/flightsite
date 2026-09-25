"""Every SQL statement the metadata subsystem issues.

Split out from the pipeline so the pipeline reads as the sequence
``docs/DATA_MODEL.md`` §3.2 describes — stage, validate, swap — and so the
session discipline of ADR-0001/ADR-0008 is enforced in exactly one place.

Two rules shape this module:

**Short writer transactions.** The process has one writer session and it is
shared with sighting persistence, so an import must never hold it for the
length of a download-sized write. Staging is loaded in batches, each its own
short transaction; the writer lock is released between them. So is the
resolution a promotion installs: it is *built* first, a page at a time, and
only the swap itself — a handful of set-based statements — runs as one
transaction, because only it has to be atomic.

**Atomicity where it is load-bearing.** :meth:`MetadataRepository.promote`
does the whole visible swap inside one transaction: the source's old rows go,
the staged rows land, staging is cleared, ``aircraft_metadata_resolved``, the
curated operator tables and ``aircraft_classification`` are replaced from the
resolution built beforehand, and the status row is updated. Any exception
rolls all of it back, which is what makes SPEC §27's *"preserves the previous
working dataset if an import fails"* a property of the storage layer rather
than a hope about error handling — and what keeps an airframe's metadata and
its classification describing the same dataset at every instant a reader could
look.

Promotion in two phases (slice 075, issue #185)
-----------------------------------------------

Resolution and classification are Python work over *every* airframe in the
database, not just the imported source's: precedence merges each airframe's
per-source claims, and the classifier reads the merged result. Until slice 075
that pass ran inside the promotion transaction, on the event loop, holding the
single writer for as long as it took — minutes, at the owner's ~900k
airframes. The persistence worker and the alert engine take the same lock to
drain their bounded queues, so they stopped draining, overflowed, and resynced.

So the pass moved out of the transaction, ahead of it:

1. :meth:`MetadataRepository.build_resolution` pages the **post-swap claim
   view** — every other source's live rows plus this source's *staged* rows,
   which is exactly what ``aircraft_metadata`` will hold once the swap
   happens — through a fresh read session per page, resolves and classifies
   each page in a worker thread (``docs/ARCHITECTURE.md`` §3.3), and writes
   the results to ``aircraft_metadata_resolved_staging`` and
   ``aircraft_classification_staging`` in one short writer transaction per
   page. Nothing it touches is visible to a reader: all three tables it writes
   are scratch, so a failure here leaves the installed dataset untouched and
   the next run clears what it left behind.
2. :meth:`MetadataRepository.promote` then swaps: metadata rows, resolved
   rows, classification rows and the curated operator tables, all with
   set-based statements over tables that are already in their final shape.

The two phases are sequential within one promotion and a promotion is the only
writer of these scratch tables; imports run one source at a time, so no second
build can be in flight while a swap runs.

The claim view is paged rather than loaded: a snapshot runs to hundreds of
thousands of airframes, and keyset pagination over ``icao24`` keeps peak
memory at one page (``docs/ARCHITECTURE.md`` §6, "streamed imports"). Rows for
one airframe are contiguous under the ``(icao24, source)`` primary key, so a
page boundary is the only thing that could split an airframe's claims — and
:meth:`MetadataRepository._claim_pages` never emits a page it has not seen the
end of.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.classification.engine import classify
from flightsite.classification.model import Evidence
from flightsite.classification.operators import OperatorDirectory, default_directory
from flightsite.classification.store import (
    add_operators,
    clear_classifications,
    sync_operator_directory,
)
from flightsite.db import Database
from flightsite.db.models import (
    Aircraft,
    AircraftClassification,
    AircraftClassificationStaging,
    AircraftMetadata,
    AircraftMetadataResolved,
    AircraftMetadataResolvedStaging,
    AircraftMetadataStaging,
    MetadataSource,
    Operator,
    OperatorGroup,
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

#: Columns of ``aircraft_metadata_resolved`` and of
#: ``aircraft_classification``, each shared with its staging table. Read off
#: the models rather than listed: the two shapes come from one declarative
#: mixin apiece (``_ResolvedColumns``, ``_ClassificationColumns``), so there is
#: one definition and the swap's ``INSERT ... SELECT`` cannot drift from it.
RESOLVED_COLUMNS: Final[tuple[str, ...]] = tuple(AircraftMetadataResolved.__table__.columns.keys())
CLASSIFICATION_COLUMNS: Final[tuple[str, ...]] = tuple(
    AircraftClassification.__table__.columns.keys()
)

#: Rows per ``INSERT`` statement while loading staging. Large enough that
#: per-statement overhead disappears, small enough that one statement's bound
#: parameters stay well inside SQLite's limits.
STAGE_BATCH_ROWS: Final = 1_000

#: Claim rows read per page while building a resolution. At two sources per
#: airframe this is a few thousand airframes per round trip — and per worker
#: thread hop, and per short writer transaction.
REBUILD_PAGE_ROWS: Final = 4_000

#: Addresses bound into one lookup. SQLite's default host-parameter limit is
#: 999; staying under it keeps a whole-live-set read working without
#: depending on a build-time setting.
IN_CLAUSE_CHUNK: Final = 500

#: Cap on a stored error message. Status is a summary a user reads, not a log:
#: a provider that raises a megabyte-long string must not turn the status row
#: into one.
MAX_ERROR_CHARS: Final = 500


@dataclass(frozen=True, slots=True)
class AircraftLookup:
    """Everything one read of the metadata tables knows about one airframe.

    A record rather than a tuple because it grew a fourth and fifth member in
    slice 024 and would have grown a sixth in 026: naming the parts is what
    keeps the cache's population loop readable.

    ``military_flag_source`` names the source whose military bit is set, and is
    ``None`` when none is — which covers both "nobody has heard of it" and "a
    source says it is civilian", neither of which is a reason to say military.
    It is read here rather than off ``aircraft_metadata_resolved`` because
    ``docs/DATA_MODEL.md`` §3.3 gives that table no military column: the bit is
    evidence for a classification, not a resolved field of its own.
    """

    metadata: ResolvedMetadata | None = None
    sighting_count: int | None = None
    military_flag_source: str | None = None
    #: Display name of the curated operator group (``docs/API.md`` §3.3's
    #: ``operator_group``), or ``None`` when the operator matched no group.
    operator_group: str | None = None

    def evidence(self, icao24: str, *, callsign: str | None = None) -> Evidence:
        """The classification engine's inputs for this airframe."""
        metadata = self.metadata
        return Evidence(
            icao24=icao24,
            military_flag=self.military_flag_source is not None,
            military_flag_source=self.military_flag_source,
            operator_name=None if metadata is None else metadata.operator_name,
            type_code=None if metadata is None else metadata.type_code,
            registration=None if metadata is None else metadata.registration,
            callsign=callsign,
        )


@dataclass(frozen=True, slots=True)
class MetadataClearCounts:
    """Rows removed by :meth:`MetadataRepository.clear_all` (SPEC §73)."""

    aircraft_metadata_rows: int
    staging_rows: int
    resolved_rows: int
    classification_rows: int
    operator_rows: int
    operator_group_rows: int
    sources_reset: int


@dataclass(frozen=True, slots=True)
class ResolutionBuild:
    """What :meth:`MetadataRepository.build_resolution` left in the scratch tables.

    The rows themselves stayed in the database — that is the whole point of
    building them there — so this carries only what the swap cannot read back
    out of them: how many resolved rows there are, and the operator names the
    dataset turned out to use that a curated *phrase* claimed. The latter has
    no table to live in until the swap replaces the curated ones, so it is
    accumulated in memory across pages, one entry per distinct name rather
    than one per airframe.
    """

    written: int
    discovered: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class _ResolvedPage:
    """One page of claims, resolved and classified — the worker thread's output."""

    resolved: list[dict[str, str | int | None]]
    classifications: list[dict[str, str | int | float | None]]
    discovered: dict[str, int]


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
        """Swap ``source``'s staged rows in, with a resolution built first.

        Two phases, and only the second is a transaction.

        :meth:`build_resolution` runs first and writes nothing a reader can
        see: it resolves and classifies the picture the swap is *about* to
        install, into the two scratch tables, off the writer lock. Then one
        transaction covers the entire visible change — the source's previous
        rows are replaced, staging is emptied, the resolved and classification
        tables are replaced from their scratch tables, and the status row
        records the success. A failure anywhere inside rolls the lot back,
        leaving the previous dataset exactly as it was; a failure in the first
        phase never reached it at all.
        """
        resolver = default_directory()
        build = await self.build_resolution(
            source, precedence=precedence, at_ms=at_ms, directory=resolver
        )
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
            await self._install_resolution(session, build=build, resolver=resolver)
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

    async def build_resolution(
        self,
        source: str | None = None,
        *,
        precedence: PrecedenceModel,
        at_ms: int,
        directory: OperatorDirectory | None = None,
    ) -> ResolutionBuild:
        """Resolve and classify every airframe into the two scratch tables.

        Phase one of a promotion, and the reason a promotion no longer holds
        the writer for minutes (slice 075, issue #185). **Touches only scratch
        tables** — ``aircraft_metadata_resolved_staging`` and
        ``aircraft_classification_staging`` — so it is safe to fail: the
        installed dataset is not involved, and the next build clears whatever
        this one left behind.

        ``source`` names the source whose *staged* rows stand in for its live
        ones, which is what makes this the post-swap picture rather than the
        current one. ``None`` resolves the live table as it is, which is what
        :meth:`rebuild_resolved` wants.

        One pass, three outputs, because they all read the same thing: an
        airframe's per-source claims. Splitting classification into a second
        pass would re-read every claim for evidence this one already has in
        hand, and would have to read the military bit from a resolved table
        that (by design, ``docs/DATA_MODEL.md`` §3.3) does not carry it.

        Per page: one read session, one worker thread, one short writer
        transaction — in that order, one page at a time. The thread is where
        ``PrecedenceModel.resolve`` and :func:`classify` run, which is what
        keeps hundreds of thousands of airframes' worth of Python off the
        event loop (``docs/ARCHITECTURE.md`` §3.3); one page is in flight at a
        time because the work is CPU-bound and the point is to yield the
        writer lock between pages, not to race for it.

        Airframes for which no source supplies a single resolvable field are
        omitted from the resolved rows rather than written as an all-``NULL``
        row: absence is the honest representation of "nothing is known". They
        can still earn a classification row — an airframe known only by a
        military bit has nothing to resolve and something to say — and an
        airframe whose classification asserts nothing is likewise left out
        rather than stored as a row of negatives.
        """
        resolver = directory if directory is not None else default_directory()
        async with self._database.writer_session() as session:
            await self._delete_resolution_staging(session)

        written = 0
        # Operator strings the *dataset* uses that a curated phrase claims.
        # Curated exact names are written by the directory sync; these are the
        # ones only an import can discover, and they are collected rather than
        # inserted per row so one name seen on a thousand airframes is written
        # once — by the swap, which is the transaction that owns that table.
        discovered: dict[str, int] = {}

        async for claims in self._claim_pages(source):
            page = await asyncio.to_thread(
                _resolve_claims, claims, precedence=precedence, resolver=resolver, at_ms=at_ms
            )
            discovered.update(page.discovered)
            written += len(page.resolved)
            async with self._database.writer_session() as session:
                await _insert_rows(session, AircraftMetadataResolvedStaging, page.resolved)
                await _insert_rows(session, AircraftClassificationStaging, page.classifications)

        return ResolutionBuild(written=written, discovered=discovered)

    async def rebuild_resolved(
        self,
        *,
        precedence: PrecedenceModel,
        at_ms: int,
        directory: OperatorDirectory | None = None,
    ) -> int:
        """Rebuild resolution, operator grouping and classification from the live rows.

        :meth:`promote` without the metadata swap: the same two phases over
        ``aircraft_metadata`` as it already stands. Returns the number of
        resolved rows written. Used when the inputs to resolution changed but
        the data did not — a different curated directory, a source that is no
        longer registered.
        """
        resolver = directory if directory is not None else default_directory()
        build = await self.build_resolution(precedence=precedence, at_ms=at_ms, directory=resolver)
        async with self._database.writer_session() as session:
            await self._install_resolution(session, build=build, resolver=resolver)
        return build.written

    async def _install_resolution(
        self,
        session: AsyncSession,
        *,
        build: ResolutionBuild,
        resolver: OperatorDirectory,
    ) -> None:
        """Move a built resolution into the live tables, in the caller's transaction.

        Every statement here is a ``DELETE`` or an ``INSERT ... SELECT`` over a
        whole table: no row is examined in Python, which is the property that
        bounds how long the writer lock is held.

        The order is fixed by ``foreign_keys=ON`` (ADR-0001): resolved rows
        reference ``operator_groups``, so they are cleared *before* the curated
        group rows are replaced and inserted *after* — which is also why the
        scratch table carries no such reference, since the group ids in it
        belong to a directory that is not installed yet.
        """
        await session.execute(delete(AircraftMetadataResolved))
        await clear_classifications(session)
        await sync_operator_directory(session, resolver)
        await _install_from_staging(
            session, AircraftMetadataResolved, AircraftMetadataResolvedStaging, RESOLVED_COLUMNS
        )
        await _install_from_staging(
            session, AircraftClassification, AircraftClassificationStaging, CLASSIFICATION_COLUMNS
        )
        await self._delete_resolution_staging(session)
        await self._add_discovered_operators(session, dict(build.discovered))

    @staticmethod
    async def _delete_resolution_staging(session: AsyncSession) -> None:
        """Empty both resolution scratch tables on the caller's session."""
        await session.execute(delete(AircraftMetadataResolvedStaging))
        await session.execute(delete(AircraftClassificationStaging))

    @staticmethod
    async def _add_discovered_operators(session: AsyncSession, discovered: dict[str, int]) -> None:
        """Record dataset operator strings that a curated *phrase* claimed.

        Written after the curated names so a name that is both curated and
        present in the dataset is not inserted twice; sorted so a re-import over
        the same snapshot produces the same rows in the same order.

        The existence check is chunked because there is no bound on how many
        distinct names a phrase can claim — every county sheriff's office in a
        national registry is a separate string — and SQLite's host-parameter
        limit is not generous.
        """
        names = sorted(discovered)
        curated: set[str] = set()
        for chunk in _chunks(names, IN_CLAUSE_CHUNK):
            found = await session.execute(select(Operator.name).where(Operator.name.in_(chunk)))
            curated.update(str(name) for name in found.scalars().all())
        rows: list[Mapping[str, str | int]] = [
            {"name": name, "group_id": discovered[name]} for name in names if name not in curated
        ]
        await add_operators(session, rows)

    async def _claim_pages(self, source: str | None) -> AsyncIterator[Sequence[RowMapping]]:
        """Yield the claim view a page at a time, in ``(icao24, source)`` order.

        Keyset pagination on a **fresh read session per page**, rather than one
        cursor held open: a build runs for minutes over a million airframes,
        and a read transaction held for its duration would pin a WAL snapshot
        that the writes landing behind it then pile up on. Paging by the
        primary key costs one index seek per page and holds nothing between
        them.

        A page is cut back to its last complete airframe, so an airframe's
        claims are never split across two pages and each page can be resolved
        on its own.
        """
        sql = _LIVE_CLAIM_PAGE_SQL if source is None else _STAGED_CLAIM_PAGE_SQL
        after = ""
        while True:
            params: dict[str, Any] = {"after": after, "limit": REBUILD_PAGE_ROWS}
            if source is not None:
                params["source"] = source
            async with self._database.read_session() as session:
                rows = (await session.execute(text(sql), params)).mappings().all()
            if not rows:
                return

            complete: Sequence[RowMapping] = rows
            if len(rows) == REBUILD_PAGE_ROWS:
                # The final airframe on a full page may continue onto the next
                # one; leave it for the next round rather than resolving half
                # of its claims.
                last = rows[-1]["icao24"]
                complete = [row for row in rows if row["icao24"] != last]
                if not complete:  # pragma: no cover - see below
                    # One airframe filling an entire page would need
                    # REBUILD_PAGE_ROWS sources, so this cannot happen — but
                    # if it ever did, resolving it from a full page beats
                    # looping forever on a cursor that never advances.
                    complete = rows
            after = str(complete[-1]["icao24"])
            yield complete

    # ------------------------------------------------------------- lookups

    async def load_live_view(self, icaos: Sequence[str]) -> dict[str, AircraftLookup]:
        """Resolved metadata, rarity, grouping and military bit, in one query.

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
        whichever part is missing; that is what lets the cache distinguish
        "nobody knows" from "not looked up yet".

        Slice 024 added two columns to the same query rather than a second one.
        The operator group's *name* comes from a join (the resolved row stores
        only its id, and the API publishes prose), and the military bit from a
        correlated lookup on ``aircraft_metadata``'s primary key — an index seek
        per address, cheap enough to keep the cache's read a single round trip,
        which is what its per-appear latency budget is built on.
        """
        if not icaos:
            return {}
        found: dict[str, AircraftLookup] = {}
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
                    group = mapping["operator_group"]
                    military_src = mapping["military_src"]
                    found[icao24] = AircraftLookup(
                        metadata=_resolved_from_mapping(icao24, mapping),
                        sighting_count=None if count is None else int(count),
                        military_flag_source=None if military_src is None else str(military_src),
                        operator_group=None if group is None else str(group),
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

    # ------------------------------------------------------------- reset

    async def clear_all(self) -> MetadataClearCounts:
        """Delete every imported and derived metadata row (SPEC §73, slice 045).

        Behind Settings' "Clear Metadata Cache" action. Everything deleted
        here is either a per-source import product (``aircraft_metadata``, its
        staging table), scratch a promotion builds and consumes (the two
        resolution staging tables), or something the next successful import
        recreates wholesale (``aircraft_metadata_resolved``,
        ``aircraft_classification``, ``operators``, ``operator_groups``) — so
        clearing it loses nothing an "Update Aircraft Metadata" run would not
        already replace.

        Per-source status rows are *reset*, not deleted:
        ``aircraft_metadata.source`` is a foreign key into
        ``metadata_sources.source`` (and, for the ``airports`` source,
        :meth:`flightsite.airports.repository.AirportRepository.clear_all`
        depends on the row surviving too), and leaving a stale ``ok`` status
        beside a dataset that no longer exists would misreport what
        :meth:`~flightsite.metadata.service.MetadataService.statuses` shows a
        user. ``last_attempt_ms`` is left alone — it is a historical fact
        about when a run last happened, not a claim about what is installed.

        ``aircraft``, ``sightings`` and everything derived from sighting
        history are untouched: nothing in this table set holds a foreign key
        into them, and nothing here reads or writes
        ``aircraft.sighting_count``.

        One writer transaction. A failure partway must not leave one table
        cleared and another still describing the old dataset.
        """
        async with self._database.writer_session() as session:
            aircraft_metadata_rows = await _table_count(session, AircraftMetadata)
            staging_rows = await _table_count(session, AircraftMetadataStaging)
            resolved_rows = await _table_count(session, AircraftMetadataResolved)
            classification_rows = await _table_count(session, AircraftClassification)
            operator_rows = await _table_count(session, Operator)
            operator_group_rows = await _table_count(session, OperatorGroup)

            # Same order _install_resolution uses on the way out
            # (foreign_keys=ON, ADR-0001): resolved rows reference
            # operator_groups, so they are cleared before the curated group
            # rows go.
            await session.execute(delete(AircraftMetadataResolved))
            await clear_classifications(session)
            await session.execute(delete(Operator))
            await session.execute(delete(OperatorGroup))
            await self._delete_resolution_staging(session)
            await session.execute(delete(AircraftMetadataStaging))
            await session.execute(delete(AircraftMetadata))
            reset = await session.execute(
                update(MetadataSource)
                .values(
                    status=SourceStatus.NEVER_RUN.value,
                    last_success_ms=None,
                    dataset_version=None,
                    row_count=None,
                    last_error=None,
                )
                .returning(MetadataSource.source)
            )
            sources_reset = len(reset.scalars().all())

        return MetadataClearCounts(
            aircraft_metadata_rows=aircraft_metadata_rows,
            staging_rows=staging_rows,
            resolved_rows=resolved_rows,
            classification_rows=classification_rows,
            operator_rows=operator_rows,
            operator_group_rows=operator_group_rows,
            sources_reset=sources_reset,
        )


async def _table_count(session: AsyncSession, model: type[Any]) -> int:
    """Row count of ``model``'s table, read on the caller's own session."""
    total = await session.scalar(select(func.count()).select_from(model))
    return int(total or 0)


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
       r.updated_ms,
       g.name AS operator_group,
       (SELECT m.source FROM aircraft_metadata AS m
         WHERE m.icao24 = w.icao24 AND m.military_flag = 1
         ORDER BY m.source LIMIT 1) AS military_src
FROM wanted AS w
LEFT JOIN aircraft AS a ON a.icao24 = w.icao24
LEFT JOIN aircraft_metadata_resolved AS r ON r.icao24 = w.icao24
LEFT JOIN operator_groups AS g ON g.id = r.operator_group_id
"""


#: Columns of the claim view: everything a :class:`SourceClaim` is made of.
#: ``flags_json`` and ``updated_ms`` are deliberately not read — precedence
#: stamps its own ``updated_ms`` and nothing in resolution reads the opaque
#: flags — so a page carries only what it uses.
_CLAIM_COLUMNS: Final = (
    "icao24, source, registration, type_code, model, manufacture_year, "
    "operator_name, owner, military_flag"
)

#: One page of the **post-swap** claim view: every other source's live rows
#: plus ``:source``'s staged ones, which is what ``aircraft_metadata`` will
#: hold once the swap runs.
#:
#: Each branch is limited and ordered in a subquery of its own, because SQLite
#: applies a trailing ``ORDER BY``/``LIMIT`` to the compound as a whole — and a
#: compound that had to sort both tables end to end to produce one page would
#: turn the keyset pagination into a full sort per page. Limiting each branch
#: first is exact, not an approximation: the globally first ``:limit`` rows are
#: always contained in the union of each branch's first ``:limit``.
_STAGED_CLAIM_PAGE_SQL: Final = f"""
SELECT {_CLAIM_COLUMNS} FROM (
    SELECT {_CLAIM_COLUMNS} FROM aircraft_metadata
     WHERE icao24 > :after AND source <> :source
     ORDER BY icao24, source
     LIMIT :limit
)
UNION ALL
SELECT {_CLAIM_COLUMNS} FROM (
    SELECT {_CLAIM_COLUMNS} FROM aircraft_metadata_staging
     WHERE icao24 > :after AND source = :source
     ORDER BY icao24, source
     LIMIT :limit
)
ORDER BY icao24, source
LIMIT :limit
"""

#: One page of the claim view as the live table already stands — the rebuild
#: that resolves what is installed rather than what is about to be.
_LIVE_CLAIM_PAGE_SQL: Final = f"""
SELECT {_CLAIM_COLUMNS} FROM aircraft_metadata
 WHERE icao24 > :after
 ORDER BY icao24, source
 LIMIT :limit
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


def _to_claim(mapping: RowMapping) -> SourceClaim:
    """One claim row of the claim view, as the precedence model wants it."""
    military = mapping["military_flag"]
    return SourceClaim(
        source=str(mapping["source"]),
        record=NormalizedAircraftRecord(
            icao24=str(mapping["icao24"]),
            registration=mapping["registration"],
            type_code=mapping["type_code"],
            model=mapping["model"],
            manufacture_year=mapping["manufacture_year"],
            operator_name=mapping["operator_name"],
            owner=mapping["owner"],
            military_flag=None if military is None else bool(military),
        ),
    )


def _resolve_claims(
    rows: Sequence[RowMapping],
    *,
    precedence: PrecedenceModel,
    resolver: OperatorDirectory,
    at_ms: int,
) -> _ResolvedPage:
    """Resolve and classify one page of claims. Pure, and therefore threadable.

    Runs on a worker thread (:meth:`MetadataRepository.build_resolution`), so
    it touches no session and no repository state: it takes rows already read
    and returns rows not yet written. ``rows`` arrive in ``(icao24, source)``
    order and end on a complete airframe, so grouping is a single pass.
    """
    page = _ResolvedPage(resolved=[], classifications=[], discovered={})
    claims: list[SourceClaim] = []
    current = ""
    for row in rows:
        icao24 = str(row["icao24"])
        if icao24 != current:
            if claims:
                _resolve_airframe(page, current, claims, precedence, resolver, at_ms)
            current, claims = icao24, []
        claims.append(_to_claim(row))
    if claims:
        _resolve_airframe(page, current, claims, precedence, resolver, at_ms)
    return page


def _resolve_airframe(
    page: _ResolvedPage,
    icao24: str,
    claims: Sequence[SourceClaim],
    precedence: PrecedenceModel,
    resolver: OperatorDirectory,
    at_ms: int,
) -> None:
    """Add one airframe's resolved row, classification row and operator name."""
    resolved = precedence.resolve(icao24, claims, updated_ms=at_ms)
    operator_name = resolved.operator_name
    match = resolver.match(operator_name)
    if match is not None and operator_name is not None:
        resolved = replace(resolved, operator_group_id=match.group_id)
        page.discovered[operator_name] = match.group_id
    if not resolved.is_empty:
        page.resolved.append(resolved.as_row())

    classification = classify(_evidence(icao24, resolved, claims), directory=resolver)
    if not classification.is_unknown:
        page.classifications.append(classification.as_row(icao24, updated_ms=at_ms))


async def _insert_rows(
    session: AsyncSession, model: type[Any], rows: Sequence[Mapping[str, Any]]
) -> None:
    """Insert ``rows`` into ``model``'s table in statement-sized batches."""
    for start in range(0, len(rows), STAGE_BATCH_ROWS):
        chunk = rows[start : start + STAGE_BATCH_ROWS]
        await session.execute(insert(model), list(chunk))


async def _install_from_staging(
    session: AsyncSession,
    model: type[Any],
    staging: type[Any],
    columns: Sequence[str],
) -> None:
    """Move every row of ``staging`` into ``model``'s (already empty) table.

    One ``INSERT ... SELECT``: the rows never enter the process, which is what
    makes the swap's cost a function of the database rather than of Python.
    """
    await session.execute(
        insert(model).from_select(
            list(columns), select(*[getattr(staging, name) for name in columns])
        )
    )


def _evidence(icao24: str, resolved: ResolvedMetadata, claims: Sequence[SourceClaim]) -> Evidence:
    """Assemble the classification engine's inputs for one airframe.

    The identity fields come from the *resolved* row so classification agrees
    with what the API publishes. The military bit comes from the raw claims,
    because ``docs/DATA_MODEL.md`` §3.3 does not resolve it into a column: it
    is evidence, not a field.

    A source claiming military wins outright — any positive assertion is taken,
    and a source's silence or explicit ``False`` is not a counter-claim. That is
    the same rule precedence uses for values ("silence never wins"), applied to
    a bit whose only interesting state is set. Ties go to the alphabetically
    first source so a re-import writes the same provenance every time.
    """
    asserting = sorted(claim.source for claim in claims if claim.record.military_flag)
    return Evidence(
        icao24=icao24,
        military_flag=bool(asserting),
        military_flag_source=asserting[0] if asserting else None,
        operator_name=resolved.operator_name,
        type_code=resolved.type_code,
        registration=resolved.registration,
    )


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
    "CLASSIFICATION_COLUMNS",
    "IN_CLAUSE_CHUNK",
    "MAX_ERROR_CHARS",
    "METADATA_COLUMNS",
    "REBUILD_PAGE_ROWS",
    "RESOLVED_COLUMNS",
    "STAGE_BATCH_ROWS",
    "AircraftLookup",
    "MetadataClearCounts",
    "MetadataRepository",
    "ResolutionBuild",
]
