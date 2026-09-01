"""Where an imported dataset lands, and how it is promoted.

:mod:`flightsite.metadata.importer` runs one pipeline — download, validate,
stage, promote — and until slice 027 that pipeline knew exactly one
destination: ``aircraft_metadata`` via
:class:`~flightsite.metadata.repository.MetadataRepository`. The airport dataset
(``docs/DATA_MODEL.md`` §3.6) needs the same pipeline and a different
destination, so the destination becomes a seam.

An :class:`ImportSink` is bound to a source at registration, beside its
provider and its precedence, for the reason the registry gives for binding
precedence there: *what a source's data means to FlightSite is FlightSite's
decision, not the provider's.* Where the rows go is the same kind of decision.

The contract has one guarantee, and it is the pipeline's own: **nothing a sink
does before ``promote`` may be visible to the rest of FlightSite, and
``promote`` must be atomic.** A failed import at any stage leaves the previous
dataset byte for byte as it was. How a sink reaches that — a staging table and
a swap, as the aircraft sink does, or a buffered run and one transaction, as
the airport sink does — is its own business.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from flightsite.metadata.precedence import PrecedenceModel
from flightsite.metadata.records import (
    NormalizedAircraftRecord,
    RecordError,
    normalize_record,
)
from flightsite.metadata.repository import MetadataRepository


@runtime_checkable
class ImportSink(Protocol):
    """The destination half of an import run.

    Every method takes the source name: one sink instance serves every source
    that shares a destination (both aircraft-metadata providers share one), and
    an import touches only its own source's rows.
    """

    def canonical(self, record: Any) -> Any | None:
        """``record`` in storable form, or ``None`` if it cannot be stored.

        Called on every row a provider yields, on the transform's worker
        thread. This is the ADR-0006 boundary made real: a provider that forgot
        to strip a trailing space or upper-case an identifier would otherwise
        split one entity into two, and no schema constraint would catch it.
        Rows that come back ``None`` are counted as rejected, and the pipeline
        enforces a tolerance on the ratio.
        """
        ...

    async def clear_staging(self, source: str) -> None:
        """Discard anything a previous or failed run left staged for ``source``."""
        ...

    async def stage_batch(self, source: str, records: Sequence[Any], *, updated_ms: int) -> int:
        """Accept one batch of ``source``'s rows. Returns how many were taken."""
        ...

    async def count_staged(self, source: str) -> int:
        """How many distinct rows ``source`` currently has staged."""
        ...

    async def promote(
        self, source: str, *, at_ms: int, dataset_version: str, row_count: int
    ) -> None:
        """Make ``source``'s staged rows the live dataset. Atomic."""
        ...


class AircraftMetadataSink:
    """The ``aircraft_metadata`` destination — slices 021 through 023.

    The behaviour the import pipeline had before the seam existed, moved behind
    it unchanged: rows are staged in ``aircraft_metadata_staging`` in short
    writer transactions (so sighting persistence keeps flushing throughout an
    import) and promoted in one transaction that also rebuilds
    ``aircraft_metadata_resolved``.

    Args:
        repository: the metadata repository owning both tables.
        precedence: called at promotion time rather than held, because the
            registry builds the model from *currently registered* sources and
            the answer must be the one true at promotion, not at construction.
    """

    __slots__ = ("_precedence", "_repository")

    def __init__(
        self,
        repository: MetadataRepository,
        *,
        precedence: Callable[[], PrecedenceModel],
    ) -> None:
        self._repository = repository
        self._precedence = precedence

    def canonical(self, record: Any) -> NormalizedAircraftRecord | None:
        """Re-normalize a provider's record, or ``None`` if it is unusable."""
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
        except (AttributeError, RecordError):
            return None

    async def clear_staging(self, source: str) -> None:
        await self._repository.clear_staging(source)

    async def stage_batch(self, source: str, records: Sequence[Any], *, updated_ms: int) -> int:
        return await self._repository.stage_batch(source, records, updated_ms=updated_ms)

    async def count_staged(self, source: str) -> int:
        return await self._repository.count_staged(source)

    async def promote(
        self, source: str, *, at_ms: int, dataset_version: str, row_count: int
    ) -> None:
        await self._repository.promote(
            source,
            precedence=self._precedence(),
            at_ms=at_ms,
            dataset_version=dataset_version,
            row_count=row_count,
        )


__all__ = ["AircraftMetadataSink", "ImportSink"]
