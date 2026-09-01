"""The ``airports`` destination for the metadata import pipeline.

An :class:`~flightsite.metadata.sink.ImportSink` over
:class:`~flightsite.airports.repository.AirportRepository`, so the airport
dataset rides the same pipeline as the aircraft sources: same download, same
validation gate, same reject-ratio tolerance, same independent
``metadata_sources`` row that slice 025's update action reports.

Why no staging table
--------------------

The aircraft sources stage into ``aircraft_metadata_staging`` and swap, because
a snapshot there is half a million wide rows and holding one in memory on a Pi
would be unreasonable. The airport dataset is ~70k narrow rows — call it twenty
megabytes of Python objects — so this sink stages **in memory** and replaces the
table in one transaction instead.

Three things that buys, and one it costs:

* ``docs/DATA_MODEL.md`` §3.6 stays exactly what the schema is. No table exists
  that the data model does not document.
* The atomicity guarantee is unchanged and arguably plainer: one
  ``DELETE`` + ``INSERT`` transaction, so a failure at any stage — including
  inside the promotion — leaves the previous dataset and the index built from
  it byte for byte as they were.
* Nothing is written at all until the whole dataset has parsed, so a transform
  that dies halfway has touched no table.
* The cost is a writer transaction held for the length of ~70k inserts rather
  than for a swap. That is a fraction of a second, it happens only when a user
  asks for an update, and the comparable aircraft promotion already rebuilds
  every resolved row inside its own single transaction.

Peak memory is still bounded by the pipeline in the way that matters: the
provider's transform is streamed, so the ~13 MB CSV is never materialized —
only the filtered, normalized records are held.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import structlog

from flightsite.airports.records import AirportRecord, AirportRecordError, normalize_airport
from flightsite.airports.repository import AirportRepository

logger = structlog.get_logger(__name__)


class AirportImportSink:
    """Buffers a run's airport records and replaces the table in one transaction.

    Args:
        repository: the ``airports`` repository.

    The buffer is keyed by source name even though only one source ever writes
    airports: the :class:`~flightsite.metadata.sink.ImportSink` contract is
    per-source because sinks are shared, and honouring it here means a second
    airport source — a national AIP extract, say — needs no change to this
    class beyond the table it writes.
    """

    __slots__ = ("_repository", "_staged")

    def __init__(self, repository: AirportRepository) -> None:
        self._repository = repository
        #: Records buffered for the current run, keyed by ident so a snapshot
        #: that repeats an ident collapses to its last row rather than failing
        #: the promotion's ``UNIQUE`` constraint.
        self._staged: dict[str, dict[str, AirportRecord]] = {}

    def canonical(self, record: Any) -> AirportRecord | None:
        """Re-normalize a provider's record, or ``None`` if it is unusable.

        The ADR-0006 boundary, enforced rather than trusted: an ident that
        reached the table with a trailing space or in lower case would make one
        airport two, and the index would then answer with whichever it loaded
        second. A row that cannot be normalized is counted as rejected by the
        pipeline, which enforces a tolerance on the ratio.
        """
        try:
            return normalize_airport(
                ident=record.ident,
                name=record.name,
                type=record.type,
                lat=record.lat,
                lon=record.lon,
                iata=record.iata,
                elevation_ft=record.elevation_ft,
                iso_country=record.iso_country,
                upstream_id=record.upstream_id,
            )
        except (AttributeError, AirportRecordError):
            return None

    async def clear_staging(self, source: str) -> None:
        """Drop anything buffered for ``source``.

        Called before a run loads new records and again after a failed one, so
        a run that died partway cannot contribute a fragment to the next.
        """
        self._staged.pop(source, None)

    async def stage_batch(self, source: str, records: Sequence[Any], *, updated_ms: int) -> int:
        """Buffer one batch. Returns how many records it held.

        ``updated_ms`` is part of the sink contract and unused here: the
        ``airports`` table carries no per-row timestamp, because the dataset is
        replaced whole and ``metadata_sources.last_success_ms`` already records
        when. A per-row copy of one instant would say nothing extra.
        """
        del updated_ms
        staged = self._staged.setdefault(source, {})
        for record in records:
            staged[record.ident] = record
        return len(records)

    async def count_staged(self, source: str) -> int:
        """How many distinct idents ``source`` has buffered."""
        return len(self._staged.get(source, ()))

    async def promote(
        self, source: str, *, at_ms: int, dataset_version: str, row_count: int
    ) -> None:
        """Replace the table with ``source``'s buffered records. Atomic.

        ``row_count`` is the pipeline's count of what it staged; the repository
        writes its own, taken after de-duplication by ident, into
        ``metadata_sources.row_count``. The two agree in every real run — the
        buffer is already keyed by ident — and where they could not, the number
        a user reads should be the number of rows the table actually holds.
        """
        del row_count
        staged = self._staged.get(source)
        if not staged:  # pragma: no cover - the pipeline's row floor precedes this
            raise ValueError(f"{source} has nothing staged to promote")
        written = await self._repository.replace_all(
            list(staged.values()),
            source=source,
            at_ms=at_ms,
            dataset_version=dataset_version,
        )
        self._staged.pop(source, None)
        logger.info("airport_dataset_replaced", source=source, rows=written)


__all__ = ["AirportImportSink"]
