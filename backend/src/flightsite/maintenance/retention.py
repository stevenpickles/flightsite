"""The retention-pruning executor, and where its authority stops.

``docs/DATA_MODEL.md`` §9 is the whole retention model, and most of it says
*indefinite*: SPEC §65 keeps sightings, tracks, events, milestones, activity,
rollups and lifetime records until the user deliberately resets them. Only four
rows of that table describe something that is ever deleted, and each already has
an owner:

============================== ============================================
``receiver_metrics_raw``       :class:`~flightsite.receiver_metrics.service.ReceiverMetricsService`
``sighting_track_checkpoints`` :mod:`flightsite.sightings.recovery` and the
                               persistence worker's close path
``route_cache``                **here** — :class:`RouteCachePruner`
``aircraft_metadata*``         replaced wholesale by each import, never pruned
============================== ============================================

Why the first two are *not* driven from here
--------------------------------------------

Both are already correct, and both are correct for reasons a generic scheduler
cannot know.

The receiver metrics prune their raw tier on their own cadence, and they do it
strictly *after* recomputing the summaries that supersede the rows they are
about to drop — the one ordering ADR-0009 forbids reversing. That ordering, the
recompute margin protecting the bucket at the prune boundary, and the watermark
that makes a failed pass retry its own range all live inside one method
(:meth:`~flightsite.receiver_metrics.service.ReceiverMetricsService.run_maintenance`).
Calling it again from here would not add safety; it would add a second caller
racing the first for the same watermark, and a second prune of rows the first
already removed. So the boundary is drawn where the invariant is: that service
owns its tier, and this one does not touch it.

Track checkpoints are the same argument in a different shape. They are deleted
transactionally at the instant a sighting closes, and the leftovers an unclean
shutdown strands are swept by :mod:`flightsite.sightings.recovery` at startup —
which can tell a stranded checkpoint from a live one because it knows which
sightings are open. A time-based pruner here could not, and would eventually
delete the checkpoints of a long-lived sighting still in progress.

What is left is ``route_cache``, and it genuinely had no executor: expiry was
decided on read and expired rows were simply not returned
(:mod:`flightsite.enrichment.cache`), so the dead rows accumulated forever. The
repository has always had a :meth:`~flightsite.enrichment.cache.RouteCacheRepository.prune`
"for when maintenance asks it to"; this is maintenance asking.

Adding a prunable later
-----------------------

Implement :class:`RetentionTask` and pass it to the service. The executor runs
each task independently — one raising does not stop the others — so a new task
can never take the retention job down with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from flightsite.enrichment.cache import RouteCacheRepository

#: Task name of the ``route_cache`` pruner, as it appears in diagnostics.
ROUTE_CACHE_TASK: Final = "route_cache"


@runtime_checkable
class RetentionTask(Protocol):
    """One prunable table, reduced to "delete what has expired by now"."""

    @property
    def name(self) -> str:
        """Stable identifier for logs and the maintenance report."""

    async def prune(self, *, now_ms: int) -> int:
        """Delete rows that have expired as of ``now_ms``; return how many."""


@dataclass(frozen=True, slots=True)
class RouteCachePruner:
    """Deletes ``route_cache`` rows whose TTL has passed (DATA_MODEL §7).

    A thin adapter, deliberately: the deletion, its ``RETURNING`` count and its
    writer transaction are the enrichment repository's, so pruning and reading
    can never disagree about what "expired" means. Both compare the same
    ``expires_ms`` column against the same instant.
    """

    repository: RouteCacheRepository

    @property
    def name(self) -> str:
        """See :attr:`RetentionTask.name`."""
        return ROUTE_CACHE_TASK

    async def prune(self, *, now_ms: int) -> int:
        """Delete every expired cache row; returns how many went."""
        return await self.repository.prune(now_ms=now_ms)


__all__ = ["ROUTE_CACHE_TASK", "RetentionTask", "RouteCachePruner"]
