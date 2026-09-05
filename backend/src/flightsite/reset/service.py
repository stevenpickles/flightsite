"""Clear Metadata Cache (SPEC §73): the non-destructive-to-history reset action.

Deletes every row a metadata import, an airport-dataset import or a
route-directory import produces,
then invalidates the two in-memory caches built from them — the live metadata
& rarity cache (:class:`~flightsite.metadata.cache.MetadataCache`) and the
nearest-airport index (:class:`~flightsite.airports.service.AirportContextService`)
— so a live aircraft reflects the clear on its very next appearance rather
than serving stale entries until it next leaves and re-enters the live set.

History is untouched by construction. Nothing this module deletes is
referenced by, or holds a reference into, ``aircraft``, ``sightings`` or
anything derived from sighting history (analytics rollups, receiver metrics,
lifetime counters). An "Update Aircraft Metadata" run recreates every table
this clears from scratch on its next successful import — see
:meth:`flightsite.metadata.repository.MetadataRepository.clear_all` for why
that makes clearing them lossless.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from flightsite.airports.repository import AirportRepository
from flightsite.airports.service import AirportContextService
from flightsite.db.engine import Database
from flightsite.enrichment.cache import RouteCacheRepository
from flightsite.enrichment.directory import RouteDirectoryRepository
from flightsite.metadata.repository import MetadataRepository
from flightsite.metadata.service import MetadataService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClearMetadataResult:
    """What :func:`clear_metadata_cache` deleted, for logging and the API response."""

    aircraft_metadata_rows: int
    staging_rows: int
    resolved_rows: int
    classification_rows: int
    operator_rows: int
    operator_group_rows: int
    route_cache_rows: int
    route_directory_rows: int
    airport_rows: int
    sources_reset: int

    def as_dict(self) -> dict[str, int]:
        """The counts as a flat mapping — the shape both the log line and the
        JSON response use."""
        return {
            "aircraft_metadata_rows": self.aircraft_metadata_rows,
            "staging_rows": self.staging_rows,
            "resolved_rows": self.resolved_rows,
            "classification_rows": self.classification_rows,
            "operator_rows": self.operator_rows,
            "operator_group_rows": self.operator_group_rows,
            "route_cache_rows": self.route_cache_rows,
            "route_directory_rows": self.route_directory_rows,
            "airport_rows": self.airport_rows,
            "sources_reset": self.sources_reset,
        }


async def clear_metadata_cache(
    *,
    database: Database,
    metadata: MetadataService,
    airports: AirportContextService,
) -> ClearMetadataResult:
    """Delete imported metadata, the route cache and airports; invalidate caches.

    Four independent deletions run through the writer — the metadata tables
    (:meth:`~flightsite.metadata.repository.MetadataRepository.clear_all`),
    ``route_cache`` (:meth:`~flightsite.enrichment.cache.RouteCacheRepository.clear_all`),
    ``route_directory``
    (:meth:`~flightsite.enrichment.directory.RouteDirectoryRepository.clear_all`)
    and ``airports`` (:meth:`~flightsite.airports.repository.AirportRepository.clear_all`)
    — followed by invalidating the live metadata cache and rebuilding the
    nearest-airport index from the now-empty table, in that order, so neither
    in-memory structure is left holding an entry for a row that no longer
    exists.

    Idempotent: every table is already empty and every source's status is
    already reset on a second call, so it repeats cleanly and reports zero
    rows removed.
    """
    metadata_counts = await MetadataRepository(database).clear_all()
    route_cache_rows = await RouteCacheRepository(database).clear_all()
    route_directory_rows = await RouteDirectoryRepository(database).clear_all()
    airport_rows = await AirportRepository(database).clear_all()

    await metadata.cache.invalidate()
    await airports.reload()

    result = ClearMetadataResult(
        aircraft_metadata_rows=metadata_counts.aircraft_metadata_rows,
        staging_rows=metadata_counts.staging_rows,
        resolved_rows=metadata_counts.resolved_rows,
        classification_rows=metadata_counts.classification_rows,
        operator_rows=metadata_counts.operator_rows,
        operator_group_rows=metadata_counts.operator_group_rows,
        route_cache_rows=route_cache_rows,
        route_directory_rows=route_directory_rows,
        airport_rows=airport_rows,
        sources_reset=metadata_counts.sources_reset,
    )
    logger.warning("metadata_cache_cleared", **result.as_dict())
    return result


__all__ = ["ClearMetadataResult", "clear_metadata_cache"]
