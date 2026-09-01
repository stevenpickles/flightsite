"""The transactional metadata import pipeline (SPEC §27).

One run per source, four stages, and one guarantee that shapes all of them:
**a failed import leaves the previous dataset fully intact.** Not "usually",
not "unless it fails late" — at every stage, including the last.

```text
download ──► validate ──► stage ──► promote
   │            │           │          │
   │            │           │          └─ one transaction: replace this
   │            │           │             source's rows, empty staging,
   │            │           │             rebuild resolution, record success
   │            │           └─ writes only to aircraft_metadata_staging
   │            └─ reads the artifact; touches no table
   └─ writes only inside the run's working directory
```

Nothing before ``promote`` writes a byte the rest of FlightSite can see. The
first three stages touch the working directory and the staging table, both of
which are scratch, and ``promote`` is a single transaction. So a failure at any
stage leaves ``aircraft_metadata`` and ``aircraft_metadata_resolved`` byte for
byte as they were, which is the property the fault-injection tests assert stage
by stage.

**Independence.** Sources are imported one at a time and each records its own
outcome (SPEC §27: *"reports status separately for each source"*). One source
failing neither aborts the run nor touches another source's rows or status —
the pipeline catches per source, records the failure, and moves on.

**Where the work happens.** ``transform`` is synchronous and can be
CPU-expensive over a large snapshot, so it runs in a worker thread and hands
batches back to the event loop (``docs/ARCHITECTURE.md`` §3.3: "blocking or
CPU-heavy work runs via ``asyncio.to_thread``"). Staging is loaded in short
writer transactions between which the writer lock is free, so sighting
persistence keeps flushing throughout an import.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import structlog

from flightsite.db import Database, utc_now_ms
from flightsite.metadata.provider import MetadataProvider
from flightsite.metadata.records import (
    MetadataError,
    NormalizedAircraftRecord,
    RecordError,
    SourceArtifact,
    ValidationReport,
    normalize_record,
)
from flightsite.metadata.registry import ImportPhase, SourceRegistry
from flightsite.metadata.repository import MetadataRepository

logger = structlog.get_logger(__name__)

#: A source of UTC epoch milliseconds; ``utc_now_ms`` in production.
ClockFn = Callable[[], int]

#: Working directory for downloads, under the data directory rather than the
#: system temp: a snapshot can be hundreds of megabytes and ``/tmp`` on a Pi is
#: often a RAM disk. Created per run and deleted when the run ends, so it never
#: becomes persistent state (``docs/ARCHITECTURE.md`` §2.1).
WORK_DIRNAME: Final = "metadata-work"

#: Records buffered before a staging write. Bounds peak memory during a
#: streamed import to one batch of records rather than one dataset.
TRANSFORM_BATCH: Final = 5_000

#: Rejected-row ratio above which a transform is treated as broken rather than
#: merely imperfect. Real snapshots contain a handful of unusable rows; a
#: majority of unusable rows means the parser and the file disagree, and
#: importing the remainder would quietly replace good data with a fragment.
MAX_REJECT_RATIO: Final = 0.10


class ImportFailure(MetadataError):
    """An import stage failed. Carries the phase for status reporting."""

    def __init__(self, phase: ImportPhase, message: str) -> None:
        super().__init__(message)
        self.phase = phase


@dataclass(frozen=True, slots=True)
class SourceImportResult:
    """The outcome of importing one source."""

    source: str
    ok: bool
    #: The phase reached: the one that failed, or ``DONE``.
    phase: ImportPhase
    rows_imported: int = 0
    rows_rejected: int = 0
    dataset_version: str | None = None
    error: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportRun:
    """The outcome of one "Update Aircraft Metadata" action across sources."""

    results: tuple[SourceImportResult, ...] = ()
    started_ms: int = 0
    finished_ms: int = 0

    @property
    def succeeded(self) -> tuple[str, ...]:
        """Sources whose data was replaced by this run."""
        return tuple(result.source for result in self.results if result.ok)

    @property
    def failed(self) -> tuple[str, ...]:
        """Sources that failed, leaving their previous data in place."""
        return tuple(result.source for result in self.results if not result.ok)

    @property
    def changed_data(self) -> bool:
        """True when at least one source promoted new rows.

        The metadata cache repopulates on exactly this condition: a run where
        every source failed changed nothing, so invalidating a warm cache would
        cost a repopulation for no new data.
        """
        return bool(self.succeeded)


class MetadataImporter:
    """Runs the import pipeline for registered sources.

    Args:
        database: the application database.
        registry: the registered sources and their in-flight run state.
        data_dir: parent of the per-run working directory.
        clock: UTC epoch-millisecond source, injected for tests.
    """

    __slots__ = ("_clock", "_data_dir", "_registry", "_repository")

    def __init__(
        self,
        *,
        database: Database,
        registry: SourceRegistry,
        data_dir: Path,
        clock: ClockFn = utc_now_ms,
    ) -> None:
        self._repository = MetadataRepository(database)
        self._registry = registry
        self._data_dir = Path(data_dir)
        self._clock = clock

    @property
    def repository(self) -> MetadataRepository:
        """The repository this importer writes through."""
        return self._repository

    async def run(self, sources: Sequence[str] | None = None) -> ImportRun:
        """Import ``sources`` (default: every registered source).

        This is the entrypoint slice 025's ``POST /api/internal/metadata/update``
        calls. It never raises for a source failure — a failure is a result, not
        an exception, because the user needs to see which sources worked.

        Raises:
            KeyError: if a name in ``sources`` is not registered. That is a
                programming error, not a run outcome.
        """
        names = tuple(sources) if sources is not None else self._registry.names
        for name in names:
            self._registry.get(name)

        started_ms = self._clock()
        results: list[SourceImportResult] = []
        for name in names:
            results.append(await self._run_source(name))
        finished_ms = self._clock()

        logger.info(
            "metadata_import_run_finished",
            sources=len(results),
            succeeded=[result.source for result in results if result.ok],
            failed=[result.source for result in results if not result.ok],
            duration_ms=finished_ms - started_ms,
        )
        return ImportRun(results=tuple(results), started_ms=started_ms, finished_ms=finished_ms)

    async def _run_source(self, name: str) -> SourceImportResult:
        source = self._registry.get(name)
        at_ms = self._clock()
        await self._repository.ensure_source(name)
        await self._repository.mark_attempt(name, at_ms=at_ms)

        workdir = self._data_dir / WORK_DIRNAME / name
        try:
            return await self._import_source(source.name, source.provider, workdir, at_ms)
        except ImportFailure as failure:
            return await self._record_failure(name, failure.phase, str(failure))
        except Exception as exc:
            # A provider may raise anything at all; whatever it is, it is this
            # source's failure and nothing else's.
            phase = self._registry.run_state(name).phase or ImportPhase.DOWNLOAD
            return await self._record_failure(name, phase, f"{type(exc).__name__}: {exc}")
        finally:
            self._registry.mark_finished(name)
            await asyncio.to_thread(_remove_tree, workdir)

    async def _import_source(
        self,
        name: str,
        provider: MetadataProvider,
        workdir: Path,
        at_ms: int,
    ) -> SourceImportResult:
        self._registry.mark_phase(name, ImportPhase.DOWNLOAD)
        await asyncio.to_thread(_prepare_workdir, workdir)
        artifact = await provider.download(workdir)

        self._registry.mark_phase(name, ImportPhase.VALIDATE)
        report = provider.validate(artifact)
        if not report.ok:
            raise ImportFailure(ImportPhase.VALIDATE, report.reason())

        self._registry.mark_phase(name, ImportPhase.STAGING)
        staged, rejected = await self._stage(name, provider, artifact, report, at_ms)

        self._registry.mark_phase(name, ImportPhase.SWAP, staged_rows=staged)
        await self._repository.promote(
            name,
            precedence=self._registry.precedence(),
            at_ms=at_ms,
            dataset_version=artifact.version,
            row_count=staged,
        )
        self._registry.mark_phase(name, ImportPhase.DONE, staged_rows=staged)

        logger.info(
            "metadata_import_succeeded",
            source=name,
            version=artifact.version,
            rows=staged,
            rejected=rejected,
        )
        return SourceImportResult(
            source=name,
            ok=True,
            phase=ImportPhase.DONE,
            rows_imported=staged,
            rows_rejected=rejected,
            dataset_version=artifact.version,
            warnings=report.warnings,
        )

    async def _stage(
        self,
        name: str,
        provider: MetadataProvider,
        artifact: SourceArtifact,
        report: ValidationReport,
        at_ms: int,
    ) -> tuple[int, int]:
        """Stream the provider's records into staging. Returns (staged, rejected)."""
        await self._repository.clear_staging(name)

        collector = _TransformCollector(provider, artifact)
        staged = 0
        while True:
            batch = await collector.next_batch()
            if not batch:
                break
            staged += await self._repository.stage_batch(name, batch, updated_ms=at_ms)
            self._registry.mark_phase(name, ImportPhase.STAGING, staged_rows=staged)

        # `staged` counts distinct addresses after conflict resolution, so it
        # can trail the records yielded; both are reported honestly.
        staged = await self._repository.count_staged(name)
        rejected = collector.rejected
        total = staged + rejected

        if staged == 0:
            raise ImportFailure(
                ImportPhase.STAGING,
                f"{name} produced no usable rows from {artifact.describe()}",
            )
        if total and rejected / total > MAX_REJECT_RATIO:
            raise ImportFailure(
                ImportPhase.STAGING,
                f"{name} rejected {rejected} of {total} rows, above the "
                f"{MAX_REJECT_RATIO:.0%} tolerance",
            )
        if report.expected_rows is not None and staged < report.expected_rows:
            raise ImportFailure(
                ImportPhase.STAGING,
                f"{name} staged {staged} rows but validation expected {report.expected_rows}",
            )
        return staged, rejected

    async def _record_failure(
        self, name: str, phase: ImportPhase, error: str
    ) -> SourceImportResult:
        """Record a failed run, then leave everything else alone.

        Staging is cleared so the next run of this source starts from an empty
        landing area; the live rows are untouched because nothing outside
        ``promote`` ever writes them.
        """
        await self._repository.clear_staging(name)
        await self._repository.mark_failure(name, at_ms=self._clock(), error=error)
        logger.warning("metadata_import_failed", source=name, phase=phase.value, error=error)
        return SourceImportResult(source=name, ok=False, phase=phase, error=error)


class _TransformCollector:
    """Pulls batches out of a provider's synchronous transform, off the loop.

    ``transform`` is an ordinary generator that may parse megabytes between
    yields. Draining it on the event loop would block every other task —
    ingestion included — for the length of the parse, so each batch is drained
    in a worker thread. The generator stays on one thread at a time: only one
    ``to_thread`` call is ever in flight.

    Every yielded record is re-normalized here rather than trusted. That is the
    ADR-0006 boundary made real: a provider that forgot to strip a trailing
    space or upper-case a type designator would otherwise split one airframe or
    one type into two in the resolved table, and no schema constraint would
    catch it. Records that cannot be normalized at all are counted and dropped;
    the caller enforces a tolerance on the ratio, so a handful of bad rows in a
    real snapshot is survivable while a parser that disagrees with its file is
    not.
    """

    __slots__ = ("_exhausted", "_records", "_rejected")

    def __init__(self, provider: MetadataProvider, artifact: SourceArtifact) -> None:
        self._records = provider.transform(artifact)
        self._rejected = 0
        self._exhausted = False

    @property
    def rejected(self) -> int:
        """Rows the provider yielded that could not be normalized."""
        return self._rejected

    async def next_batch(self) -> list[NormalizedAircraftRecord]:
        """The next batch of records, or an empty list when exhausted."""
        if self._exhausted:
            return []
        batch, rejected, exhausted = await asyncio.to_thread(self._drain)
        self._rejected += rejected
        self._exhausted = exhausted
        return batch

    def _drain(self) -> tuple[list[NormalizedAircraftRecord], int, bool]:
        batch: list[NormalizedAircraftRecord] = []
        rejected = 0
        while len(batch) < TRANSFORM_BATCH:
            try:
                record = next(self._records)
            except StopIteration:
                return batch, rejected, True
            canonical = _canonical(record)
            if canonical is None:
                rejected += 1
            else:
                batch.append(canonical)
        return batch, rejected, False


def _canonical(record: NormalizedAircraftRecord) -> NormalizedAircraftRecord | None:
    """``record`` in canonical form, or ``None`` if it cannot be stored."""
    try:
        return normalize_record(
            icao24=record.icao24,
            registration=record.registration,
            type_code=record.type_code,
            model=record.model,
            manufacture_year=record.manufacture_year,
            operator_name=record.operator_name,
            owner=record.owner,
            military_flag=record.military_flag,
            flags=record.flags,
        )
    except RecordError:
        return None


def _remove_tree(path: Path) -> None:
    """Delete ``path`` and everything under it, ignoring absence.

    Called through :func:`asyncio.to_thread`: deleting a tree holding an
    unpacked snapshot is filesystem work, and on a Pi's SD card it is not
    always fast.
    """
    shutil.rmtree(path, ignore_errors=True)


def _prepare_workdir(path: Path) -> None:
    """Give the run an empty working directory, discarding any earlier one."""
    _remove_tree(path)
    path.mkdir(parents=True, exist_ok=True)


__all__ = [
    "MAX_REJECT_RATIO",
    "TRANSFORM_BATCH",
    "WORK_DIRNAME",
    "ClockFn",
    "ImportFailure",
    "ImportRun",
    "MetadataImporter",
    "SourceImportResult",
]
